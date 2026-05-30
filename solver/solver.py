# aislop-ignore-file ai-slop/hallucinated-import
"""lawforge solver — Stage 2 Solo track.

I/O protocol (per Stage 2 spec):
  - Read one problem JSON from stdin.
  - Communicate with the organizer's proxy via {"call": "llm"|"judge", ...}
    written to stdout; read response line from stdin.
  - Final answer is whatever the judge `accepted` on.

Strategy ladder (L1 -> L5). Each layer is cheap-to-expensive in token cost.
Bandit-edited components (cheatsheet, prompt, thresholds) are loaded from
files so the Karpathy outer loop can mutate them without touching this file.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

from solver.counterex import emit_lean_counterex, search_counterex
from solver.proxy_client import call_llm, call_llm_context, submit_judge

HERE = Path(__file__).resolve().parent
_RAW_PROMPT_TPL = (HERE / "prompt_template.txt").read_text()
CHEATSHEET = (HERE / "cheatsheet.md").read_text()
PROMPT = _RAW_PROMPT_TPL.replace("__CHEATSHEET__", CHEATSHEET)
PROMPT_TPL = PROMPT

USE_MACE4_FIRST = (HERE / "USE_MACE4_FIRST").exists()
USE_CHEATSHEET = (
    int((HERE / "USE_CHEATSHEET").read_text().strip())
    if (HERE / "USE_CHEATSHEET").exists()
    else 0
)
VERIFIER_REFINE_K = (
    int((HERE / "VERIFIER_REFINE_K").read_text().strip())
    if (HERE / "VERIFIER_REFINE_K").exists()
    else 0
)
LLM_MAX_TOKENS = (
    int((HERE / "LLM_MAX_TOKENS").read_text().strip())
    if (HERE / "LLM_MAX_TOKENS").exists()
    else int(os.environ.get("LAWFORGE_LLM_MAX_TOKENS", "1024"))
)

TEMPERATURE = (
    float((HERE / "TEMPERATURE").read_text().strip())
    if (HERE / "TEMPERATURE").exists()
    else 0.3
)
MAX_ORDER = (
    int((HERE / "MAX_ORDER").read_text().strip())
    if (HERE / "MAX_ORDER").exists()
    else 5
)


def _wrap_true_submission(proof_body: str) -> str:
    """Wrap a tactic body as TRUE submission matching upstream contract.

    Mirror of equational-theories-lean-stage2/examples/solo/demos/baseline/
    solver.py:make_true_code. Goal expands to
      ∀ (G : Type) [Magma G], EquationLHS G → EquationRHS G
    so we `intro G _ h` and let the body close the implication.
    """
    body = proof_body.strip()
    body = re.sub(r"^:?=?\s*by\s+", "", body)
    body = re.sub(r"^\s*import\s+.*\n?", "", body, flags=re.MULTILINE)
    lines = body.split("\n")
    # Strip the common leading indent so the wrapper's 2-space prefix yields
    # a uniformly-indented tactic block (Lean is whitespace-sensitive).
    non_empty = [ln for ln in lines if ln.strip()]
    if non_empty:
        min_indent = min(len(ln) - len(ln.lstrip()) for ln in non_empty)
        lines = [ln[min_indent:] if len(ln) > min_indent else ln for ln in lines]
    indented = "\n".join("  " + ln if ln.strip() else "" for ln in lines)
    return (
        "import JudgeProblem\n\n"
        "def submission : Goal := by\n"
        "  intro G _ h\n"
        f"{indented}\n"
    )


def l1_syntactic(eq1: str, eq2: str) -> str | None:
    """Layer 1: free. Eq1 ≡ Eq2 syntactically -> hypothesis IS the goal."""
    if eq1.replace(" ", "") == eq2.replace(" ", ""):
        return _wrap_true_submission("exact h")
    return None


def l2_counterex(eq1: str, eq2: str, max_order: int = 4) -> str | None:
    """Layer 2: brute force finite-magma counterexample. Free, deterministic."""
    ce = search_counterex(eq1, eq2, max_order=max_order)
    return emit_lean_counterex(ce, eq1, eq2) if ce else None


_LLM_USE_LEGACY = os.environ.get("LAWFORGE_LLM_LEGACY", "0") == "1"


def _llm_text(context: dict) -> str:
    """Production Solo: solver sends a context dict; proxy fills PROMPT and
    calls LLM. LAWFORGE_LLM_LEGACY=1 falls back to the local call_llm path
    used by the in-repo eval harness during development."""
    if _LLM_USE_LEGACY:
        prompt = PROMPT.format(
            eq1=context.get("eq1", ""),
            eq2=context.get("eq2", ""),
            cheatsheet=CHEATSHEET if USE_CHEATSHEET else "(none)",
            ce_hint=context.get("ce_hint", "not searched yet"),
        )
        extra = context.get("extra")
        if extra:
            prompt = prompt + "\n\n" + str(extra)
        resp = call_llm(prompt, max_tokens=LLM_MAX_TOKENS, temperature=TEMPERATURE)
        return resp.text
    return call_llm_context(context)


def l3_tactic_ladder(eq1: str, eq2: str, round_: int = 0, ce_hint: str = "") -> str:
    """Layer 3: ask LLM for a tactic body, wrap as submission."""
    text = _llm_text(
        {
            "eq1": eq1,
            "eq2": eq2,
            "stage": "first",
            "round": round_,
            "ce_hint": ce_hint or "not searched yet",
        }
    )
    return _wrap_true_submission(_extract_body(text))


def l4_subgoal_decomp(eq1: str, eq2: str, round_: int = 1, ce_hint: str = "") -> str:
    """Layer 4: ask LLM to decompose before composing."""
    text = _llm_text(
        {
            "eq1": eq1,
            "eq2": eq2,
            "stage": "subgoal",
            "round": round_,
            "ce_hint": ce_hint or "not searched yet",
            "extra": "Decompose into 2-3 subgoals (Lean lemma signatures) "
            "before proving the main implication. Emit only the final tactic body.",
        }
    )
    return _wrap_true_submission(_extract_body(text))


def l5_refine(
    eq1: str,
    eq2: str,
    prior_code: str,
    error_msg: str,
    round_: int = 2,
) -> str:
    """Layer 5: feed Lean error back to LLM, ask for fix."""
    text = _llm_text(
        {
            "eq1": eq1,
            "eq2": eq2,
            "stage": "refine",
            "round": round_,
            "ce_hint": "",
            "prior_code": prior_code[:1500],
            "last_error": error_msg[:1500],
            "extra": (
                f"The previous attempt failed with:\n{error_msg[:800]}\n\n"
                "Emit a corrected Lean 4 tactic body only "
                "(no imports, no theorem header)."
            ),
        }
    )
    return _wrap_true_submission(_extract_body(text))


def _extract_body(text: str) -> str:
    """Pull tactic body from LLM output. Accepts fenced ```lean blocks, raw,
    or upstream-style JSON {verdict, proof}. Returns body suitable for
    _wrap_true_submission (no imports, no theorem/def header)."""
    s = text.strip()
    s = re.sub(r"<think>[\s\S]*?</think>", "", s).strip()
    # try JSON first (upstream PROMPT contract)
    m = re.search(r"\{[\s\S]*\}", s)
    if m:
        try:
            obj = json.loads(m.group())
            if isinstance(obj, dict) and "proof" in obj:
                s = str(obj["proof"])
        except (json.JSONDecodeError, ValueError):
            pass
    # strip fences if any
    fm = re.search(r"```(?:lean4?|Lean4?)?\s*\n?(.*?)```", s, re.DOTALL)
    if fm:
        s = fm.group(1)
    # drop a leading `def submission` / `theorem` wrapper if the model emitted one
    s = re.sub(r"^\s*(?:import\s+\S+\n)+", "", s)
    s = re.sub(
        r"^\s*(?:def\s+submission|theorem\s+\w+|example)\b[^\n]*?:=\s*by\b", "", s
    )
    # If the LLM also emitted `intro G _ h` (or its variants), strip — the
    # wrapper adds this exact line and a second intro would error
    # "no introducible binders left".
    s = re.sub(r"^\s*intro\s+G\s+\S+\s+h\s*$", "", s, count=1, flags=re.MULTILINE)
    return s.strip() or "sorry"


def solve(problem: dict) -> dict:
    eq1 = (
        problem.get("equation1") or problem.get("hypothesis") or problem.get("eq1", "")
    )
    eq2 = problem.get("equation2") or problem.get("goal") or problem.get("eq2", "")
    rnd = 0
    ce_hint = ""

    code = l1_syntactic(eq1, eq2)
    if code:
        v = submit_judge("true", code)
        if v.get("status") == "accepted":
            return v

    if USE_MACE4_FIRST:
        ce_code = l2_counterex(eq1, eq2, max_order=MAX_ORDER)
        if ce_code:
            v = submit_judge("false", ce_code)
            if v.get("status") == "accepted":
                return v
        else:
            ce_hint = f"no counterex on Fin 2..{MAX_ORDER}"

    code = l3_tactic_ladder(eq1, eq2, round_=rnd, ce_hint=ce_hint)
    rnd += 1
    v = submit_judge("true", code)
    if v.get("status") == "accepted":
        return v
    last_err = v.get("message", "")
    llm_dead = code.startswith("# LLM timeout") or code.startswith("# LLM error")

    code4 = code
    if not llm_dead:
        code4 = l4_subgoal_decomp(eq1, eq2, round_=rnd, ce_hint=ce_hint)
        rnd += 1
        v = submit_judge("true", code4)
        if v.get("status") == "accepted":
            return v
        last_err = v.get("message", last_err)

        for _ in range(VERIFIER_REFINE_K):
            code4 = l5_refine(eq1, eq2, code4, last_err, round_=rnd)
            rnd += 1
            v = submit_judge("true", code4)
            if v.get("status") == "accepted":
                return v
            last_err = v.get("message", last_err)

    ce_code = l2_counterex(eq1, eq2, max_order=MAX_ORDER)
    if ce_code:
        v = submit_judge("false", ce_code)
        if v.get("status") == "accepted":
            return v

    return {"status": "incorrect"}


def main() -> None:
    line = sys.stdin.readline().strip()
    if not line:
        return
    msg = json.loads(line)
    # Production Solo: startup is {"problem": {...}, "budget": {...}}.
    # Legacy local eval may still send raw problem dict.
    problem = msg.get("problem", msg) if isinstance(msg, dict) else msg
    t0 = time.time()
    result = solve(problem)
    sys.stderr.write(
        f"[solver] solved={result.get('status') == 'accepted'} "
        f"t={time.time() - t0:.1f}s\n"
    )


if __name__ == "__main__":
    main()
