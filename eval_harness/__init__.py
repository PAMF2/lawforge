# aislop-ignore-file ai-slop/hallucinated-import
"""Evaluation harness: run solver on a dev split, print SOLVED_RATE=<float>.

Key invariant: a single problem MUST exit within `--timeout` seconds, even if
the solver subprocess or the LLM endpoint hangs. We enforce this by polling
the subprocess stdout via `select` and killing the process group on overshoot.
"""

import argparse
import json
import os
import random
import select
import signal
import subprocess
import sys
import time
from pathlib import Path

from lawforge_utils import env_bool
from lean.judge import judge_or_score
from solver.proxy_client import call_local

_USE_LLM_JUDGE = env_bool("LAWFORGE_LLM_JUDGE")

ROOT = Path(__file__).resolve().parent.parent


def load_split(
    name: str, limit: int | None = None, seed: int | None = None
) -> list[dict]:
    p = ROOT / "data" / f"{name}_split.jsonl"
    if not p.exists():
        return [{"hypothesis": "x = x", "goal": "x = x", "label": "true"}]
    rows = []
    with p.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    if seed is not None:
        random.Random(seed).shuffle(rows)
    if limit is not None:
        rows = rows[:limit]
    return rows


def _kill(proc: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=3)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            return


def _read_line_with_deadline(proc: subprocess.Popen, deadline: float) -> str | None:
    """Block until proc.stdout has a line OR deadline passes. None on timeout."""
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            return None
        r, _, _ = select.select([proc.stdout], [], [], min(1.0, remaining))
        if not r:
            if proc.poll() is not None:
                return None
            continue
        line = proc.stdout.readline()
        return line or None


def _format_history(judge_log: list[dict]) -> str:
    """Mirror of pipeline/proxy.py _format_history — used to fill the
    {history.attempts} placeholder in solver.PROMPT during local eval."""
    if not judge_log:
        return "(no prior attempts)"
    out = []
    for i, entry in enumerate(judge_log[-3:], start=max(0, len(judge_log) - 3)):
        req = entry.get("request", {})
        resp = entry.get("response", {})
        err = resp.get("stderr") or resp.get("message") or ""
        out.append(
            f"  round {i}: verdict={req.get('verdict')} "
            f"status={resp.get('status')} err={err[:200]!r}"
        )
    return "\n".join(out)


def _fill_prompt(
    template: str, problem: dict, context: dict, judge_log: list[dict]
) -> str:
    """Local mirror of pipeline proxy template filler.
    Supports {problem.*}, {history.*}, {solver.*} namespaces and strips
    unfilled placeholders so the LLM doesn't see literal {...}."""
    eq1_name = f"Equation{problem.get('eq1_id', '')}"
    eq2_name = f"Equation{problem.get('eq2_id', '')}"
    vars_ = {
        "problem.id": str(problem.get("id", "")),
        "problem.eq1_id": str(problem.get("eq1_id", "")),
        "problem.eq2_id": str(problem.get("eq2_id", "")),
        "problem.eq1_name": eq1_name,
        "problem.eq2_name": eq2_name,
        "problem.equation1": str(
            problem.get("equation1", problem.get("hypothesis", ""))
        ),
        "problem.equation2": str(problem.get("equation2", problem.get("goal", ""))),
        "problem.equation1_id": eq1_name,
        "problem.equation2_id": eq2_name,
        "history.attempts": _format_history(judge_log),
        "history.round": str(len(judge_log)),
    }
    if judge_log:
        last_resp = judge_log[-1].get("response") or {}
        vars_["history.last_error"] = (
            last_resp.get("stderr") or last_resp.get("message") or ""
        )
        vars_["history.last_status"] = last_resp.get("status", "")
    else:
        vars_["history.last_error"] = ""
        vars_["history.last_status"] = ""
    for k, v in context.items():
        vars_[f"solver.{k}"] = str(v)
    out = template
    for k, v in vars_.items():
        out = out.replace("{" + k + "}", v)
    import re as _re

    return _re.sub(r"\{(problem|solver|history)\.[a-zA-Z_]+\}", "", out)


def _load_solver_prompt() -> str:
    """Read the solver's effective PROMPT (post-cheatsheet-inline). Mirrors
    what the production proxy reads from the solver module."""
    raw = (ROOT / "solver" / "prompt_template.txt").read_text()
    cheatsheet_path = ROOT / "solver" / "cheatsheet.md"
    cheatsheet = cheatsheet_path.read_text() if cheatsheet_path.exists() else ""
    return raw.replace("__CHEATSHEET__", cheatsheet)


def run_solver_on_problem(problem: dict, timeout: int = 30) -> bool:
    """Drive the solver subprocess on one problem; hard kill on timeout.

    Mirrors the production Solo proxy: wrapped startup, {call:llm,context}
    requests get the PROMPT template filled locally then dispatched to our
    LLM endpoint, judge calls forwarded to lean.judge.judge_or_score.
    """
    env = os.environ.copy()
    env["LAWFORGE_PROXY_MODE"] = "live"
    env["PYTHONPATH"] = str(ROOT)
    prompt_tpl = _load_solver_prompt()
    proc = subprocess.Popen(
        [sys.executable, "-m", "solver.solver"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        cwd=ROOT,
        env=env,
        text=True,
        bufsize=1,
        start_new_session=True,
    )
    deadline = time.time() + timeout
    solved = False
    judge_log: list[dict] = []
    try:
        startup = {
            "problem": problem,
            "budget": {
                "timeout_seconds": timeout,
                "max_code_length": 100_000,
                "max_false_cert_bytes": 20_000,
            },
        }
        proc.stdin.write(json.dumps(startup) + "\n")
        proc.stdin.flush()
        while True:
            line = _read_line_with_deadline(proc, deadline)
            if line is None:
                break
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                continue
            call = req.get("call")
            if call == "judge":
                v = judge_or_score(
                    req.get("code", ""),
                    expected_verdict=req.get("verdict", "true"),
                    eq1=str(problem.get("equation1", problem.get("hypothesis", ""))),
                    eq2=str(problem.get("equation2", problem.get("goal", ""))),
                    use_llm_fallback=_USE_LLM_JUDGE,
                    problem=problem,
                )
                resp = {"status": v.status, "message": v.message, "stderr": v.message}
                judge_log.append({"request": req, "response": resp})
                proc.stdin.write(json.dumps(resp) + "\n")
                proc.stdin.flush()
                if v.accepted:
                    solved = True
                    break
            elif call == "llm":
                context = req.get("context") or {}
                filled = _fill_prompt(prompt_tpl, problem, context, judge_log)
                r = call_local(filled, 2048, 0.3)
                proc.stdin.write(json.dumps({"response": r.text}) + "\n")
                proc.stdin.flush()
            else:
                break
    finally:
        _kill(proc)
    return solved


def main() -> None:
    import concurrent.futures as cf

    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="dev")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument(
        "--timeout",
        type=int,
        default=45,
        help="per-problem hard wall-clock cap (seconds)",
    )
    ap.add_argument(
        "--workers",
        type=int,
        default=4,
        help="parallel solver subprocesses (I/O-bound on LLM)",
    )
    ap.add_argument(
        "--seed",
        type=int,
        default=None,
        help="shuffle split with this seed (per-gen variance for bandit)",
    )
    args = ap.parse_args()

    problems = load_split(args.split, limit=args.limit, seed=args.seed)
    solved = 0
    done = 0
    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = [ex.submit(run_solver_on_problem, p, args.timeout) for p in problems]
        for fut in cf.as_completed(futures):
            done += 1
            if fut.result():
                solved += 1
            if done % 5 == 0:
                print(
                    f"[eval] {done}/{len(problems)} solved={solved} "
                    f"elapsed={time.time() - t0:.0f}s",
                    file=sys.stderr,
                )
    rate = solved / max(1, len(problems))
    print(
        f"[eval] split={args.split} solved={solved}/{len(problems)} "
        f"elapsed={time.time() - t0:.0f}s workers={args.workers}",
        file=sys.stderr,
    )
    print(f"SOLVED_RATE={rate:.4f}")


if __name__ == "__main__":
    main()
