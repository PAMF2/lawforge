"""Evaluation harness: run current solver on a split, return solved_rate.

Prints last line `SOLVED_RATE=<float>` for driver.py to parse.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_split(name: str) -> list[dict]:
    path = Path(f"data/{name}_split.json")
    if not path.exists():
        # smoke fallback: 1 dummy problem
        return [{"hypothesis": "x = x", "goal": "x = x", "label": "true"}]
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def solve_one(problem: dict) -> bool:
    """Run solver on a problem, return True if judge accepts."""
    # TODO: subprocess to solver/solver.py with stdin=problem, parse output,
    # subprocess Lean judge, return accepted bool.
    return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="dev")
    args = ap.parse_args()
    problems = load_split(args.split)
    solved = sum(1 for p in problems if solve_one(p))
    rate = solved / max(1, len(problems))
    print(f"[eval] split={args.split} solved={solved}/{len(problems)}")
    print(f"SOLVED_RATE={rate:.4f}")


if __name__ == "__main__":
    main()
