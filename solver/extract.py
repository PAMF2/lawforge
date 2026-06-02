"""LLM-output -> Lean-tactic-body extractor.

Tuned for Goedel-Prover-V2-8B output shape:
chain-of-thought "proof plan" prose, then a fenced ```lean4 ... ``` block
containing the FULL wrapped Lean code (imports + `def submission : Goal := by`
+ `intro G _ h` + tactics). We want just the inner tactic body so
solver._wrap_true_submission can re-wrap it with the canonical header.

Strategy:
(1) find the LAST ```lean4 / ```Lean4 / ```lean fence and take its body;
(2) strip imports, the `def submission ... := by` header, and the
    `intro G _ h` line the model copied from the prompt; any additional
    `intro x y z` the model emitted downstream is preserved verbatim;
(3) if no fence is found, fall back to prose-stripping the raw text via the
    legacy _TACTIC_HEAD_RE / _PROSE_HEAD_RE machinery;
(4) if nothing tactic-shaped survives, return "sorry" so the wrapper still
    produces a syntactically valid (if false) submission.
"""

import re

_TACTIC_HEAD_KW = (
    "intro", "intros", "apply", "exact", "refine", "rw", "rewrite",
    "simp", "simp_all", "have", "show", "obtain", "rcases", "cases",
    "induction", "subst", "constructor", "use", "calc", "trivial", "rfl",
    "decide", "aesop", "omega", "linarith", "nlinarith", "ring", "ring_nf",
    "norm_num", "tauto", "assumption", "contradiction", "by_contra",
    "by_cases", "specialize", "funext", "ext", "convert", "first",
    "all_goals", "any_goals", "repeat", "try", "done", "let", "set",
)
_TACTIC_HEAD_RE = re.compile(
    r"^\s*(?:" + r"|".join(_TACTIC_HEAD_KW) + r")\b|^\s*(?:·|<;>|\(|\{|\[)"
)
# Lines marking prose / markdown / re-emit shapes never legal as tactics.
_PROSE_HEAD_RE = re.compile(
    r"^\s*(?:#{1,6}\s|>\s|\*\*|Verdict\b|Proof\b|Step\b|Attempted\b|"
    r"We\b|Let\b|Note\b|Here\b|First\b|Now\b|Since\b|Therefore\b|Thus\b|"
    r"This\b|That\b|The\b|It\b|So\b|import\b|open\b|namespace\b|section\b|"
    r"def\s+\w|theorem\s+\w|lemma\s+\w|example\s)"
)
# Find ```lean4 / ```Lean4 / ```lean fences; case-insensitive on the tag.
# Use a non-greedy body and re.DOTALL so newlines are captured. We will
# pick the LAST match — Goedel emits a CoT scratch block first sometimes,
# the final fence is the one that holds the real submission.
_FENCE_RE = re.compile(
    r"```(?:lean4?|Lean4?)\s*\n?(.*?)```",
    re.DOTALL | re.IGNORECASE,
)
# Strip the wrapped header the model copied from the prompt. We tolerate
# arbitrary whitespace and any `intro G _ h` variant (the underscore may be
# a real name like `inst`).
_HEADER_RE = re.compile(
    r"^\s*(?:def|theorem|lemma|example)\s+[\s\S]*?:=\s*by\s*\n?",
    re.MULTILINE,
)
_INTRO_GMH_RE = re.compile(
    r"^\s*intro\s+G\s+\S+\s+h\s*(?:\n|$)",
    re.MULTILINE,
)
_IMPORT_RE = re.compile(r"^\s*import\s+\S.*\n?", re.MULTILINE)
_CLASS_RE = re.compile(
    r"^\s*(?:class|instance|infixl|infixr|infix|open|namespace|variable)\b[^\n]*\n?",
    re.MULTILINE,
)


def _strip_leading_prose(body: str) -> str:
    """Drop every line until we hit one that begins with a Lean tactic
    verb. Returns "" if no tactic-shaped line is found; the caller's
    sentinel turns that into "sorry"."""
    lines = body.split("\n")
    out: list[str] = []
    dropping = True
    for ln in lines:
        if dropping:
            if not ln.strip() or _PROSE_HEAD_RE.match(ln):
                continue
            if _TACTIC_HEAD_RE.match(ln):
                dropping = False
                out.append(ln)
                continue
            continue
        out.append(ln)
    return "\n".join(out).strip()


def _strip_goedel_wrapper(body: str) -> str:
    """Remove the prompt wrapper Goedel re-emits inside the fence:
    `import`/`class`/`infixl`/`open`/`namespace`/`variable` headers,
    the `def|theorem|lemma|example ... := by` declaration line, and the
    matching `intro G _ h` if the model copied it. Any downstream
    `intro x y z` the model added is preserved verbatim."""
    body = _IMPORT_RE.sub("", body)
    body = _CLASS_RE.sub("", body)
    body = _HEADER_RE.sub("", body, count=1)
    body = _INTRO_GMH_RE.sub("", body, count=1)
    return body


def extract_body(text: str) -> str:
    """Pull a Lean tactic body out of raw Goedel-Prover-V2-8B output.

    Contract: returns a string suitable for solver._wrap_true_submission,
    which prepends `import JudgeProblem\\n\\ndef submission : Goal := by\\n
    intro G _ h\\n` and then indents each line by two spaces. We therefore
    return the INNER tactic body only, no imports, no def header, no
    `intro G _ h`. Returns "sorry" on any failure so the wrapper still
    yields a syntactically valid file.
    """
    if not isinstance(text, str) or not text.strip():
        return "sorry"
    s = text.strip()
    # Drop any <think>...</think> scratchpad some checkpoints emit.
    s = re.sub(r"<think>[\s\S]*?</think>", "", s).strip()

    fences = _FENCE_RE.findall(s)
    if fences:
        # LAST fence wins — earlier ones are usually CoT scratch.
        body = fences[-1]
        body = _strip_goedel_wrapper(body)
        body = _strip_leading_prose(body)
        return body.strip() or "sorry"

    # No fence — fall back to raw-text prose stripping. Still try to strip
    # the wrapper in case the model emitted it without a fence.
    body = _strip_goedel_wrapper(s)
    body = _strip_leading_prose(body)
    return body.strip() or "sorry"
