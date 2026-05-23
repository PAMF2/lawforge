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
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from solver.counterex import emit_lean_counterex, search_counterex, vars_of
from solver.proxy_client import call_llm, submit_judge

HERE = Path(__file__).resolve().parent
PROMPT_TPL = (HERE / "prompt_template.txt").read_text()
CHEATSHEET = (HERE / "cheatsheet.md").read_text()

USE_MACE4_FIRST = (HERE / "USE_MACE4_FIRST").exists()
USE_CHEATSHEET = int((HERE / "USE_CHEATSHEET").read_text().strip()) if (HERE / "USE_CHEATSHEET").exists() else 0
VERIFIER_REFINE_K = int((HERE / "VERIFIER_REFINE_K").read_text().strip()) if (HERE / "VERIFIER_REFINE_K").exists() else 0
LLM_MAX_TOKENS = int(os.environ.get("LAWFORGE_LLM_MAX_TOKENS", "1024"))


def l1_syntactic(eq1: str, eq2: str) -> str | None:
    """Layer 1: free. Identical-equation case."""
    if eq1.replace(" ", "") == eq2.replace(" ", ""):
        vars_ = vars_of(eq1, eq2)
        vs = " ".join(vars_) or "x"
        holes = " ".join("_" for _ in vars_) or "_"
        return (
            "-- L1: Eq1 ≡ Eq2 syntactically; hypothesis is the goal\n"
            "theorem implication {G : Type*} [Magma G]\n"
            f"    (h : ∀ {vs} : G, {eq1}) : ∀ {vs} : G, {eq2} := by\n"
            f"  intros; exact h {holes}\n"
        )
    return None


def l2_counterex(eq1: str, eq2: str, max_order: int = 4) -> str | None:
    """Layer 2: brute force finite-magma counterexample. Free, deterministic."""
    ce = search_counterex(eq1, eq2, max_order=max_order)
    return emit_lean_counterex(ce, eq1, eq2) if ce else None


def l3_tactic_ladder(eq1: str, eq2: str) -> str:
    """Layer 3: ask LLM for a one-shot tactic-driven proof."""
    prompt = PROMPT_TPL.format(eq1=eq1, eq2=eq2,
                                cheatsheet=CHEATSHEET if USE_CHEATSHEET else "(none)",
                                ce_hint="not searched yet")
    resp = call_llm(prompt, max_tokens=LLM_MAX_TOKENS, temperature=0.3)
    return _extract_code(resp.text)


def l4_subgoal_decomp(eq1: str, eq2: str) -> str:
    """Layer 4: DeepSeek-Prover-V2 style — single combined prompt (no planner)."""
    prompt = (
        PROMPT_TPL.format(eq1=eq1, eq2=eq2,
                          cheatsheet=CHEATSHEET if USE_CHEATSHEET else "(none)",
                          ce_hint="not searched yet")
        + "\n\nDecompose into 2-3 subgoals (as Lean lemma signatures) "
          "before proving the main implication. Emit only the final Lean code."
    )
    resp = call_llm(prompt, max_tokens=LLM_MAX_TOKENS, temperature=0.3)
    return _extract_code(resp.text)


def l5_refine(eq1: str, eq2: str, prior_code: str, error_msg: str) -> str:
    """Layer 5: feed Lean error back to LLM, ask for fix."""
    prompt = (
        f"The following Lean 4 proof attempt failed:\n```\n{prior_code}\n```\n"
        f"Judge feedback: {error_msg}\n\n"
        f"Eq1: {eq1}\nEq2: {eq2}\n\n"
        "Emit a corrected Lean 4 certificate. Output only the code."
    )
    resp = call_llm(prompt, max_tokens=LLM_MAX_TOKENS, temperature=0.5)
    return _extract_code(resp.text)


def _extract_code(text: str) -> str:
    """Pull Lean code from LLM output. Accepts fenced ```lean blocks or raw."""
    if "```lean" in text:
        a = text.index("```lean") + len("```lean")
        b = text.index("```", a)
        return text[a:b].strip()
    if "```" in text:
        a = text.index("```") + 3
        b = text.index("```", a)
        return text[a:b].strip()
    return text.strip()


def solve(problem: dict) -> dict:
    eq1 = problem.get("hypothesis", problem.get("eq1", ""))
    eq2 = problem.get("goal", problem.get("eq2", ""))

    code = l1_syntactic(eq1, eq2)
    if code:
        v = submit_judge("true", code)
        if v.get("status") == "accepted":
            return v

    if USE_MACE4_FIRST:
        ce_code = l2_counterex(eq1, eq2, max_order=3)
        if ce_code:
            v = submit_judge("false", ce_code)
            if v.get("status") == "accepted":
                return v

    code = l3_tactic_ladder(eq1, eq2)
    v = submit_judge("true", code)
    if v.get("status") == "accepted":
        return v
    last_err = v.get("message", "")
    llm_dead = code.startswith("# LLM timeout") or code.startswith("# LLM error")

    code4 = code
    if not llm_dead:
        code4 = l4_subgoal_decomp(eq1, eq2)
        v = submit_judge("true", code4)
        if v.get("status") == "accepted":
            return v
        last_err = v.get("message", last_err)

        for _ in range(VERIFIER_REFINE_K):
            code4 = l5_refine(eq1, eq2, code4, last_err)
            v = submit_judge("true", code4)
            if v.get("status") == "accepted":
                return v
            last_err = v.get("message", last_err)

    ce_code = l2_counterex(eq1, eq2, max_order=4)
    if ce_code:
        v = submit_judge("false", ce_code)
        if v.get("status") == "accepted":
            return v

    return {"status": "incorrect"}


def main() -> None:
    # Solo track: one problem per subprocess.
    line = sys.stdin.readline().strip()
    if not line:
        return
    problem = json.loads(line)
    t0 = time.time()
    result = solve(problem)
    sys.stderr.write(f"[solver] solved={result.get('status')=='accepted'} "
                     f"t={time.time()-t0:.1f}s\n")


if __name__ == "__main__":
    main()
