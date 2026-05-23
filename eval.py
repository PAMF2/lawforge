"""Evaluation harness: run solver on a dev split, print SOLVED_RATE=<float>.

Key invariant: a single problem MUST exit within `--timeout` seconds, even if
the solver subprocess or the LLM endpoint hangs. We enforce this by polling
the subprocess stdout via `select` and killing the process group on overshoot.
"""
from __future__ import annotations

import argparse
import json
import os
import select
import signal
import subprocess
import sys
import time
from pathlib import Path

from lean.judge import judge as run_judge
from solver.proxy_client import call_local

ROOT = Path(__file__).resolve().parent


def load_split(name: str, limit: int | None = None) -> list[dict]:
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
            if limit is not None and len(rows) >= limit:
                break
    return rows


def _kill(proc: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=3)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass


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


def run_solver_on_problem(problem: dict, timeout: int = 30) -> bool:
    """Drive the solver subprocess on one problem; hard kill on timeout."""
    env = os.environ.copy()
    env["LAWFORGE_PROXY_MODE"] = "live"
    env["PYTHONPATH"] = str(ROOT)
    proc = subprocess.Popen(
        [sys.executable, "-m", "solver.solver"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        cwd=ROOT, env=env, text=True, bufsize=1, start_new_session=True,
    )
    deadline = time.time() + timeout
    solved = False
    try:
        proc.stdin.write(json.dumps(problem) + "\n")
        proc.stdin.flush()
        while True:
            line = _read_line_with_deadline(proc, deadline)
            if line is None:
                break  # timeout or EOF
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                continue
            call = req.get("call")
            if call == "judge":
                v = run_judge(req.get("code", ""), expected_verdict=req.get("verdict", "true"))
                proc.stdin.write(json.dumps({"status": v.status, "message": v.message}) + "\n")
                proc.stdin.flush()
                if v.accepted:
                    solved = True
                    break
            elif call == "llm":
                r = call_local(req["prompt"], req.get("max_tokens", 2048),
                                req.get("temperature", 0.3))
                proc.stdin.write(json.dumps({"text": r.text, "tokens": r.tokens}) + "\n")
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
    ap.add_argument("--timeout", type=int, default=45,
                    help="per-problem hard wall-clock cap (seconds)")
    ap.add_argument("--workers", type=int, default=4,
                    help="parallel solver subprocesses (I/O-bound on LLM)")
    args = ap.parse_args()

    problems = load_split(args.split, limit=args.limit)
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
                print(f"[eval] {done}/{len(problems)} solved={solved} "
                      f"elapsed={time.time()-t0:.0f}s", file=sys.stderr)
    rate = solved / max(1, len(problems))
    print(f"[eval] split={args.split} solved={solved}/{len(problems)} "
          f"elapsed={time.time()-t0:.0f}s workers={args.workers}", file=sys.stderr)
    print(f"SOLVED_RATE={rate:.4f}")


if __name__ == "__main__":
    main()
