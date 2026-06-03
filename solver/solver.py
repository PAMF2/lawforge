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
from solver.proxy_client import call_llm_context, call_local, submit_judge

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


_MARATHON_RE = re.compile(r"\{(problem|solver|history)\.[a-zA-Z_]+\}")


def _marathon_fill_prompt(problem: dict) -> str:
    eq1 = problem.get("equation1", "")
    eq2 = problem.get("equation2", "")
    eq1_name = f"Equation{problem.get('eq1_id', '')}"
    eq2_name = f"Equation{problem.get('eq2_id', '')}"
    vars_ = {
        "problem.id": str(problem.get("id", "")),
        "problem.eq1_id": str(problem.get("eq1_id", "")),
        "problem.eq2_id": str(problem.get("eq2_id", "")),
        "problem.equation1": eq1,
        "problem.equation2": eq2,
        "problem.equation1_id": eq1_name,
        "problem.equation2_id": eq2_name,
        "history.attempts": "(no prior attempts)",
        "history.round": "0",
        "history.last_error": "",
        "history.last_status": "",
        "solver.round": "0",
        "solver.stage": "marathon",
        "solver.ce_hint": "",
    }
    out = PROMPT
    for k, v in vars_.items():
        out = out.replace("{" + k + "}", v)
    return _MARATHON_RE.sub("", out)


def _marathon_counterex_pass(
    problems: list, out, deadline: float, solved_ids: set
) -> None:
    for p in problems:
        if time.time() >= deadline:
            break
        pid = p.get("id", "")
        eq1 = p.get("equation1", "")
        eq2 = p.get("equation2", "")
        ce = search_counterex(eq1, eq2, max_order=MAX_ORDER)
        if ce is None:
            continue
        code = emit_lean_counterex(ce, eq1, eq2)
        out.write(json.dumps({"id": pid, "verdict": "false", "code": code}) + "\n")
        out.flush()
        solved_ids.add(pid)


def _marathon_emit(out, pid: str, code: str, solved_ids: set) -> None:
    out.write(json.dumps({"id": pid, "verdict": "true", "code": code}) + "\n")
    out.flush()
    solved_ids.add(pid)


def _marathon_llm_phase(remaining: list, out, deadline: float, solved_ids: set) -> None:
    total = len(remaining)
    for i, p in enumerate(remaining, start=1):
        if time.time() >= deadline:
            break
        pid = p.get("id", "")
        eq1 = p.get("equation1", "")
        eq2 = p.get("equation2", "")
        t0 = time.time()
        l1 = l1_syntactic(eq1, eq2)
        if l1:
            _marathon_emit(out, pid, l1, solved_ids)
            sys.stderr.write(
                f"[marathon] [{i}/{total}] {pid} l1 emit {time.time() - t0:.1f}s\n"
            )
            sys.stderr.flush()
            continue
        r = call_local(_marathon_fill_prompt(p), LLM_MAX_TOKENS, TEMPERATURE)
        dt = time.time() - t0
        if r.text.startswith("# LLM "):
            sys.stderr.write(
                f"[marathon] [{i}/{total}] {pid} llm-skip {r.text[:40]} ({dt:.1f}s)\n"
            )
            sys.stderr.flush()
            continue
        body = _extract_body(r.text)
        code = _wrap_true_submission(body)
        _marathon_emit(out, pid, code, solved_ids)
        sys.stderr.write(
            f"[marathon] [{i}/{total}] {pid} llm emit {len(code)}b {dt:.1f}s\n"
        )
        if body == "sorry" and os.environ.get("LAWFORGE_DEBUG_RAW", "0") == "1":
            head = r.text[:400].replace("\n", "\\n")
            tail = r.text[-400:].replace("\n", "\\n")
            sys.stderr.write(
                f"[marathon] [{i}/{total}] {pid} RAW len={len(r.text)} "
                f"head={head!r} tail={tail!r}\n"
            )
        sys.stderr.flush()


def _marathon_main() -> None:
    """Marathon track: read manifest, attempt each problem under a global
    budget, append accepted answers to JUDGE_MARATHON_OUTPUT as JSONL."""
    manifest_path = Path(os.environ["JUDGE_MARATHON_MANIFEST"])
    output_path = Path(os.environ["JUDGE_MARATHON_OUTPUT"])
    budget_s = float(os.environ.get("JUDGE_MARATHON_BUDGET_SECONDS", "30000"))
    deadline = time.time() + budget_s

    problems = []
    with manifest_path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                problems.append(json.loads(line))

    sys.stderr.write(f"[marathon] {len(problems)} problems, budget={budget_s:.0f}s\n")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    solved_ids: set[str] = set()
    with output_path.open("a") as out:
        _marathon_counterex_pass(problems, out, deadline, solved_ids)
        sys.stderr.write(
            f"[marathon] counterex pass: {len(solved_ids)}/{len(problems)} FALSE\n"
        )
        remaining = [p for p in problems if p.get("id") not in solved_ids]
        if remaining and time.time() < deadline:
            per_problem_s = max(30.0, (deadline - time.time()) / len(remaining))
            sys.stderr.write(
                f"[marathon] LLM phase: {len(remaining)} remaining, "
                f"~{per_problem_s:.0f}s each\n"
            )
            _marathon_llm_phase(remaining, out, deadline, solved_ids)
    sys.stderr.write(
        f"[marathon] done: {len(solved_ids)}/{len(problems)} solved "
        f"in {time.time() - (deadline - budget_s):.0f}s\n"
    )


def main() -> None:
    if "JUDGE_MARATHON_MANIFEST" in os.environ:
        _marathon_main()
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
