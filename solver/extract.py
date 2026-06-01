"""LLM-output -> Lean-tactic-body extractor.

Lifted out of solver/solver.py to keep that module under the size cap.
Defends against three observed failure modes in marathon hard2 emits:
(1) `### Step N` markdown CoT inside the JSON `proof` field; (2) full-file
re-emit with `import JudgeProblem` + `def submission : Goal := by`;
(3) `intro G _ h x y z w` shape where the model duplicates the wrapper's
`intro G _ h` prefix but with additional downstream binders we want to
preserve.
"""

import json
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
_TACTIC_ANYWHERE_RE = re.compile(
    r"(?:^|[^a-zA-Z_])(?:" + r"|".join(_TACTIC_HEAD_KW) + r")(?:$|[^a-zA-Z_])"
)
# Lines marking prose / markdown / re-emit shapes never legal as tactics.
_PROSE_HEAD_RE = re.compile(
    r"^\s*(?:#{1,6}\s|>\s|\*\*|Verdict\b|Proof\b|Step\b|Attempted\b|"
    r"We\b|Let\b|Note\b|Here\b|First\b|Now\b|Since\b|Therefore\b|Thus\b|"
    r"This\b|That\b|The\b|It\b|So\b|import\b|open\b|namespace\b|section\b|"
    r"def\s+\w|theorem\s+\w|lemma\s+\w|example\s)"
)


def _strip_leading_prose(body: str) -> str:
    """Drop every line until we hit one that begins with a Lean tactic
    verb. If no such line exists we return empty - the caller's sentinel
    converts that to "sorry" and l4/l5 can take another swing. This is
    strict by design: hard2 emits prose (numbered lists, markdown
    headings, bare equations, Cayley tables) that look nothing like
    a tactic; keeping any of it produces unparseable submissions."""
    lines = body.split("\n")
    out, dropping = [], True
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


def extract_body(text: str) -> str:
    """Pull a Lean tactic body out of raw LLM output.

    Accepts fenced ```lean blocks, raw tactics, or the upstream JSON
    `{verdict, proof}` shape. Returns a body suitable for the wrapper
    (no imports, no theorem/def header). Falls back to "sorry" when the
    head of the body has no recognizable Lean tactic keyword."""
    s = text.strip()
    s = re.sub(r"<think>[\s\S]*?</think>", "", s).strip()
    m = re.search(r"\{[\s\S]*\}", s)
    if m:
        try:
            obj = json.loads(m.group())
            if isinstance(obj, dict) and "proof" in obj:
                s = str(obj["proof"])
        except (json.JSONDecodeError, ValueError):
            pass
    fm = re.search(r"```(?:lean4?|Lean4?)?\s*\n?(.*?)```", s, re.DOTALL)
    if fm:
        s = fm.group(1)
    s = re.sub(r"^\s*(?:import\s+\S+\n)+", "", s)
    s = re.sub(
        r"^\s*(?:def\s+submission|theorem\s+\w+|lemma\s+\w+|example)\b"
        r"[\s\S]*?:=\s*by\b\s*\n?",
        "",
        s,
        count=1,
    )
    s = re.sub(
        r"^\s*intro\s+G\s+\S+\s+h(?=\s|$)",
        "intro",
        s,
        count=1,
        flags=re.MULTILINE,
    )
    s = re.sub(r"^\s*intro\s*$\n?", "", s, count=1, flags=re.MULTILINE)
    s = _strip_leading_prose(s)
    if not _TACTIC_ANYWHERE_RE.search(s.lstrip()[:400]):
        return "sorry"
    return s.strip() or "sorry"
