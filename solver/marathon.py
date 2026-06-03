"""Marathon track: JSONL manifest in, JSONL emissions out.

No stdio JSON-RPC proxy. Reads `JUDGE_MARATHON_MANIFEST`, writes accepted
answers to `JUDGE_MARATHON_OUTPUT` under a `JUDGE_MARATHON_BUDGET_SECONDS`
budget.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

from solver.counterex import emit_lean_counterex, search_counterex
from solver.extract import extract_body as _extract_body
from solver.proxy_client import call_local
from solver.solver import (
    LLM_MAX_TOKENS,
    MAX_ORDER,
    PROMPT,
    TEMPERATURE,
    _wrap_true_submission,
    l1_syntactic,
)

_MARATHON_RE = re.compile(r"\{(problem|solver|history)\.[a-zA-Z_]+\}")


def _fill_prompt(problem: dict) -> str:
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


def _counterex_pass(problems: list, out, deadline: float, solved_ids: set) -> None:
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


def _emit(out, pid: str, code: str, solved_ids: set) -> None:
    out.write(json.dumps({"id": pid, "verdict": "true", "code": code}) + "\n")
    out.flush()
    solved_ids.add(pid)


def _llm_phase(remaining: list, out, deadline: float, solved_ids: set) -> None:
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
            _emit(out, pid, l1, solved_ids)
            sys.stderr.write(
                f"[marathon] [{i}/{total}] {pid} l1 emit {time.time() - t0:.1f}s\n"
            )
            sys.stderr.flush()
            continue
        r = call_local(_fill_prompt(p), LLM_MAX_TOKENS, TEMPERATURE)
        dt = time.time() - t0
        if r.text.startswith("# LLM "):
            sys.stderr.write(
                f"[marathon] [{i}/{total}] {pid} llm-skip {r.text[:40]} ({dt:.1f}s)\n"
            )
            sys.stderr.flush()
            continue
        body = _extract_body(r.text)
        code = _wrap_true_submission(body)
        _emit(out, pid, code, solved_ids)
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


def run_marathon() -> None:
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
        _counterex_pass(problems, out, deadline, solved_ids)
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
            _llm_phase(remaining, out, deadline, solved_ids)
    sys.stderr.write(
        f"[marathon] done: {len(solved_ids)}/{len(problems)} solved "
        f"in {time.time() - (deadline - budget_s):.0f}s\n"
    )
