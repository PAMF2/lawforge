"""Single-generation driver: arm select -> apply -> commit -> train -> eval -> keep|reset.

Run via: python -m evolve.driver --gen N --smoke-sec 300
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from evolve.agent57 import Agent57Meta, Arm
from evolve.arms import build_arm_library

ROOT = Path(__file__).resolve().parent.parent
META_PATH = ROOT / "evolve" / "meta_state.json"
RESULTS_TSV = ROOT / "evolve" / "results.tsv"
LAST_METRIC = ROOT / "evolve" / "last_metric.json"


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


# Hard wall-clock caps so no single generation can stall the loop.
TRAIN_HARD_CAP_S = 900   # 15 min, double the configured budget-sec
EVAL_HARD_CAP_S = 1500   # 25 min, covers 20 problems x 45s x 1/4 workers worst case


def run_smoke(budget_sec: int) -> None:
    try:
        subprocess.run(
            ["python3", "-m", "train", "--smoke", "--budget-sec", str(budget_sec)],
            cwd=ROOT, check=False, timeout=TRAIN_HARD_CAP_S,
        )
    except subprocess.TimeoutExpired:
        print(f"[driver] train.py exceeded {TRAIN_HARD_CAP_S}s — killed", file=sys.stderr)


def run_eval() -> float:
    try:
        out = subprocess.check_output(
            ["python3", "-m", "eval", "--split", "dev"], cwd=ROOT, text=True,
            timeout=EVAL_HARD_CAP_S,
        )
    except subprocess.TimeoutExpired:
        print(f"[driver] eval.py exceeded {EVAL_HARD_CAP_S}s — using 0.0", file=sys.stderr)
        return 0.0
    for line in out.splitlines()[::-1]:
        if line.startswith("SOLVED_RATE="):
            return float(line.split("=", 1)[1])
    return 0.0


def load_last_metric() -> float:
    if LAST_METRIC.exists():
        return json.loads(LAST_METRIC.read_text()).get("val_solved_rate", 0.0)
    return 0.0


def save_metric(val: float) -> None:
    LAST_METRIC.write_text(json.dumps({"val_solved_rate": val}))


def log_row(gen: int, arm: Arm, before: float, after: float, kept: int, commit_sha: str) -> None:
    row = [str(gen), arm.name, f"{before:.4f}", f"{after:.4f}", str(kept), commit_sha]
    if not RESULTS_TSV.exists():
        RESULTS_TSV.write_text("gen\tarm\tbefore\tafter\tkept\tcommit\n")
    with RESULTS_TSV.open("a") as f:
        f.write("\t".join(row) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", type=int, required=True)
    ap.add_argument("--smoke-sec", type=int, default=300)
    args = ap.parse_args()

    arms = build_arm_library(ROOT)
    meta = Agent57Meta(arms)
    meta.load(META_PATH)

    arm = meta.select()
    print(f"[gen {args.gen}] selected arm: {arm.name}")
    arm.apply(ROOT)

    pre_sha = git("rev-parse", "HEAD")
    subprocess.run(["git", "add", "-A"], cwd=ROOT, check=False)
    subprocess.run(
        ["git", "commit", "-m", f"gen{args.gen}: try arm={arm.name}"],
        cwd=ROOT, check=False,
    )
    trial_sha = git("rev-parse", "HEAD")

    before = load_last_metric()
    t0 = time.time()
    run_smoke(args.smoke_sec)
    print(f"[gen {args.gen}] smoke train took {time.time()-t0:.0f}s")

    after = run_eval()
    delta = after - before
    print(f"[gen {args.gen}] before={before:.4f} after={after:.4f} delta={delta:+.4f}")

    kept = 1 if delta >= 0.005 else 0
    if not kept:
        subprocess.run(["git", "reset", "--hard", pre_sha], cwd=ROOT, check=False)
        print(f"[gen {args.gen}] REVERTED to {pre_sha[:8]}")
    else:
        save_metric(after)
        print(f"[gen {args.gen}] KEPT at {trial_sha[:8]}")

    meta.update(arm, reward=delta if kept else 0.0)
    meta.save(META_PATH)
    log_row(args.gen, arm, before, after, kept, trial_sha[:8])


if __name__ == "__main__":
    main()
