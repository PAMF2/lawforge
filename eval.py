"""Evaluation harness: run lawforge solver on a split, return solved rate.

For the Karpathy outer loop. We run the solver in a single in-process pass
against a mocked proxy (so we don't have to spin up an LLM server per
generation). The mocked proxy:
  - judge: calls lean.judge.judge() (real Lean if available, mock otherwise).
  - llm:   calls solver.proxy_client._call_local() against the configured
           LAWFORGE_LLM_URL endpoint (e.g. Colab gpt-oss-20b via vLLM, or
           OpenRouter).

Final line printed: SOLVED_RATE=<float>  (parsed by evolve/driver.py).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_split(name: str) -> list[dict]:
    path = ROOT / "data" / f"{name}_split.jsonl"
    if not path.exists():
        return [{"hypothesis": "x = x", "goal": "x = x", "label": "true"}]
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def run_solver_on_problem(problem: dict, timeout: int = 60) -> bool:
    """Drive the solver subprocess on a single problem. Returns True if solved.

    We wrap stdin/stdout to play both 'proxy' and 'judge' roles: every line
    the solver writes is parsed, dispatched to either lean.judge or local LLM,
    and the response written back to its stdin.
    """
    from lean.judge import judge as run_judge
    from solver.proxy_client import _call_local

    env = os.environ.copy()
    env["LAWFORGE_PROXY_MODE"] = "live"
    env["PYTHONPATH"] = str(ROOT)
    proc = subprocess.Popen(
        [sys.executable, "-m", "solver.solver"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=ROOT, env=env, text=True, bufsize=1,
    )
    proc.stdin.write(json.dumps(problem) + "\n")
    proc.stdin.flush()

    solved = False
    try:
        while True:
            line = proc.stdout.readline()
            if not line:
                break
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                continue
            call = req.get("call")
            if call == "judge":
                v = run_judge(req.get("code", ""), expected_verdict=req.get("verdict", "true"))
                resp = {"status": v.status, "message": v.message}
                proc.stdin.write(json.dumps(resp) + "\n")
                proc.stdin.flush()
                if v.accepted:
                    solved = True
                    break
            elif call == "llm":
                r = _call_local(req["prompt"], req.get("max_tokens", 4096),
                                req.get("temperature", 0.3))
                resp = {"text": r.text, "tokens": r.tokens}
                proc.stdin.write(json.dumps(resp) + "\n")
                proc.stdin.flush()
            else:
                break
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    return solved


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="dev")
    ap.add_argument("--limit", type=int, default=50,
                    help="cap problems per smoke eval to keep latency bounded")
    ap.add_argument("--timeout", type=int, default=60)
    args = ap.parse_args()

    problems = load_split(args.split)[: args.limit]
    solved = sum(1 for p in problems if run_solver_on_problem(p, args.timeout))
    n = max(1, len(problems))
    rate = solved / n
    print(f"[eval] split={args.split} solved={solved}/{n}", file=sys.stderr)
    print(f"SOLVED_RATE={rate:.4f}")


if __name__ == "__main__":
    main()
