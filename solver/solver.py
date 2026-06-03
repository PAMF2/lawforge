# aislop-ignore-file ai-slop/hallucinated-import
"""lawforge solver - Stage 2 Solo track.

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
from solver.extract import extract_body as _extract_body
from solver.proxy_client import call_llm_context, submit_judge

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
VARIANT_K = (
    int((HERE / "VARIANT_K").read_text().strip())
    if (HERE / "VARIANT_K").exists()
    else int(os.environ.get("LAWFORGE_VARIANT_K", "0"))
)
VARIANT_TEMP = (
    float((HERE / "VARIANT_TEMP").read_text().strip())
    if (HERE / "VARIANT_TEMP").exists()
    else float(os.environ.get("LAWFORGE_VARIANT_TEMP", "0.6"))
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


def _llm_text(context: dict) -> str:
    """Production Solo: solver sends a context dict; proxy fills PROMPT and
    calls LLM. eval_harness mirrors the production proxy locally so this
    single path covers both the upstream judge and our in-repo dev harness.

    We attach max_tokens/temperature/cheatsheet_on as `solver.*` context keys.
    The dev eval_harness reads them to parameterize call_local; the upstream
    judge proxy ignores unknown keys, so the production contract is preserved.
    """
    context = dict(context)
    context.setdefault("max_tokens", LLM_MAX_TOKENS)
    context.setdefault("temperature", TEMPERATURE)
    context.setdefault("cheatsheet_on", int(bool(USE_CHEATSHEET)))
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


def l3_variant(
    eq1: str,
    eq2: str,
    round_: int,
    ce_hint: str,
    variant_idx: int,
    temperature: float,
) -> str:
    """One diverse tactic candidate at elevated temperature.

    AlphaProof / Kimina-RL evidence: pass@1 -> pass@32 gives the largest
    gain per token spent. variant_idx is surfaced to the proxy as a
    diversification hint so the template can perturb the prompt header.
    """
    text = _llm_text(
        {
            "eq1": eq1,
            "eq2": eq2,
            "stage": "first",
            "round": round_,
            "ce_hint": ce_hint or "not searched yet",
            "variant_idx": variant_idx,
            "temperature": temperature,
            "extra": (
                f"# Candidate {variant_idx} of K. Try a structurally "
                "different tactic plan than other candidates. Emit only "
                "the Lean 4 tactic body."
            ),
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


def _strip_submission_wrapper(code: str) -> str:
    """Return only the tactic body of a wrapped submission.

    Tolerant of varied whitespace / extra `intros` and of bodies that
    were emitted without the wrapper (returns input unchanged).
    """
    out = re.sub(r"^\s*(?:import\s+\S+\s*\n)+", "", code, count=1, flags=re.MULTILINE)
    out = re.sub(r"^\s*def\s+submission\s*:\s*Goal\s*:=\s*by\s*\n", "", out, count=1)
    out = re.sub(r"^\s*intro\s+G\s+_\s+h\s*\n", "", out, count=1)
    return out


def l5_refine(
    eq1: str,
    eq2: str,
    prior_code: str,
    error_msg: str,
    round_: int = 2,
) -> str:
    """Layer 5: structured self-correction (Goedel-V2 idiom).

    Feeds previous tactic body and verbatim Lean error back to the LLM in
    tagged form so the model can target the failing tactic instead of
    rewriting the whole proof.
    """
    body_only = _strip_submission_wrapper(prior_code).strip()[:1000]
    err = error_msg.strip()[:1200]
    extra = (
        "Your previous Lean 4 tactic body did NOT close the goal.\n\n"
        f"<previous_attempt>\n{body_only}\n</previous_attempt>\n\n"
        f"<lean_error>\n{err}\n</lean_error>\n\n"
        "Read the error. Identify the failing tactic. Replace ONLY the "
        "failing line(s) with a corrected sequence. Keep the rest intact "
        "when possible. Emit ONLY the Lean 4 tactic body (no `import`, no "
        "`def submission`, no `theorem`, no markdown fences). Continue "
        "from where `intro G _ h` left off."
    )
    text = _llm_text(
        {
            "eq1": eq1,
            "eq2": eq2,
            "stage": "refine",
            "round": round_,
            "ce_hint": "",
            "prior_code": prior_code[:1500],
            "last_error": err,
            "extra": extra,
        }
    )
    return _wrap_true_submission(_extract_body(text))


def solve(problem: dict) -> dict:
    eq1 = (
        problem.get("equation1") or problem.get("hypothesis") or problem.get("eq1", "")
    )
    eq2 = problem.get("equation2") or problem.get("goal") or problem.get("eq2", "")
    rnd = 0
    ce_hint = ""

    def _accept(verdict: str, code: str, v: dict) -> dict:
        return {**v, "verdict": verdict, "code": code}

    code = l1_syntactic(eq1, eq2)
    if code:
        v = submit_judge("true", code)
        if v.get("status") == "accepted":
            return _accept("true", code, v)

    if USE_MACE4_FIRST:
        ce_code = l2_counterex(eq1, eq2, max_order=MAX_ORDER)
        if ce_code:
            v = submit_judge("false", ce_code)
            if v.get("status") == "accepted":
                return _accept("false", ce_code, v)
        else:
            ce_hint = f"no counterex on Fin 2..{MAX_ORDER}"

    code = l3_tactic_ladder(eq1, eq2, round_=rnd, ce_hint=ce_hint)
    rnd += 1
    v = submit_judge("true", code)
    if v.get("status") == "accepted":
        return _accept("true", code, v)
    last_err = v.get("message", "")
    llm_dead = code.startswith("# LLM timeout") or code.startswith("# LLM error")

    if not llm_dead:
        for vi in range(1, VARIANT_K + 1):
            cand = l3_variant(eq1, eq2, rnd, ce_hint, vi, VARIANT_TEMP)
            rnd += 1
            if cand.startswith("# LLM"):
                llm_dead = True
                break
            v = submit_judge("true", cand)
            if v.get("status") == "accepted":
                return _accept("true", cand, v)
            last_err = v.get("message", last_err)

    code4 = code
    if not llm_dead:
        code4 = l4_subgoal_decomp(eq1, eq2, round_=rnd, ce_hint=ce_hint)
        rnd += 1
        v = submit_judge("true", code4)
        if v.get("status") == "accepted":
            return _accept("true", code4, v)
        last_err = v.get("message", last_err)

        for _ in range(VERIFIER_REFINE_K):
            code4 = l5_refine(eq1, eq2, code4, last_err, round_=rnd)
            rnd += 1
            v = submit_judge("true", code4)
            if v.get("status") == "accepted":
                return _accept("true", code4, v)
            last_err = v.get("message", last_err)

    ce_code = l2_counterex(eq1, eq2, max_order=MAX_ORDER)
    if ce_code:
        v = submit_judge("false", ce_code)
        if v.get("status") == "accepted":
            return _accept("false", ce_code, v)

    return {"status": "incorrect"}


def main() -> None:
    if "JUDGE_MARATHON_MANIFEST" in os.environ:
        from solver.marathon import run_marathon

        run_marathon()
        return

    line = sys.stdin.readline().strip()
    if not line:
        return
    msg = json.loads(line)
    problem = msg.get("problem", msg) if isinstance(msg, dict) else msg
    t0 = time.time()
    result = solve(problem)
    sys.stderr.write(
        f"[solver] solved={result.get('status') == 'accepted'} "
        f"t={time.time() - t0:.1f}s\n"
    )


if __name__ == "__main__":
    main()
