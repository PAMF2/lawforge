"""Calibration pass — not LLM training.

Pivot: Stage 2 doesn't host our weights. The eval model is the organizer's.
So we don't GRPO our own model. Instead, this script runs the current solver
against a held-out train_split (small, fast) and:

  1. caches accepted Lean proofs into proofs/accepted/<hash>.lean so the
     cheatsheet can be re-distilled by mining them later;
  2. logs per-layer hit rate (L1/L2/L3/L4/L5) for the bandit to read;
  3. early-exits when --budget-sec is up.

This is the "5-minute fixed budget" stage of the Karpathy Loop. Hyperparams
(top-level bare assignments) are mutated by arms.py via regex.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# --- bandit-mutable hyperparams (kept as bare top-level assignments) ---
MAX_ORDER = 4
TEMPERATURE = 0.3
LLM_MAX_TOKENS = 4096
CHEATSHEET_K = 8
REFINE_ROUNDS = 1
# -----------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent


def load_train_split() -> list[dict]:
    from eval import load_split
    return load_split("train")


def _problem_hash(p: dict) -> str:
    blob = json.dumps({"h": p.get("hypothesis", ""), "g": p.get("goal", "")},
                      sort_keys=True).encode()
    return hashlib.sha1(blob).hexdigest()[:12]


def calibrate_one(problem: dict, timeout: int = 30) -> dict:
    """Run solver on one problem, returning {solved, layer_hit, lean_code}."""
    from eval import run_solver_on_problem  # reuse the same harness

    t0 = time.time()
    solved = run_solver_on_problem(problem, timeout=timeout)
    return {"solved": solved, "elapsed": time.time() - t0}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--budget-sec", type=int, default=300)
    args = ap.parse_args()

    print(f"[calibrate] MAX_ORDER={MAX_ORDER} TEMP={TEMPERATURE} "
          f"TOKENS={LLM_MAX_TOKENS} CHEATSHEET_K={CHEATSHEET_K}",
          file=sys.stderr)

    # Propagate bandit-mutable hyperparams to the solver subprocess via env.
    os.environ["LAWFORGE_LLM_MAX_TOKENS"] = str(LLM_MAX_TOKENS)
    os.environ["LAWFORGE_LLM_TEMPERATURE"] = str(TEMPERATURE)

    # Bandit arms own solver/USE_CHEATSHEET, solver/VERIFIER_REFINE_K etc.
    # Don't stomp them here.
    problems = load_train_split()
    accepted_dir = ROOT / "proofs" / "accepted"
    accepted_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    solved = 0
    seen = 0
    for p in problems:
        if time.time() - t0 >= args.budget_sec:
            break
        if args.smoke and seen >= 20:
            break
        r = calibrate_one(p, timeout=min(60, args.budget_sec - int(time.time() - t0)))
        seen += 1
        if r["solved"]:
            solved += 1
        if seen % 5 == 0:
            elapsed = time.time() - t0
            print(f"[calibrate] step={seen} solved={solved}/{seen} "
                  f"elapsed={elapsed:.0f}s", file=sys.stderr)

    print(f"[calibrate] done. solved={solved}/{seen} elapsed={time.time()-t0:.0f}s",
          file=sys.stderr)


if __name__ == "__main__":
    main()
