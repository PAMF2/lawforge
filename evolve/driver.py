"""Single-generation driver: arm select -> apply -> commit -> train -> eval -> keep|reset.

Run via: python -m evolve.driver --gen N --smoke-sec 300
"""

import argparse
import json
import os
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
TRAIN_HARD_CAP_S = 900  # 15 min, double the configured budget-sec
EVAL_HARD_CAP_S = 2700  # 45 min, covers 20 problems x 90s x 1/4 workers worst case


def _run_with_pg_kill(
    argv: list[str], timeout_s: int
) -> subprocess.CompletedProcess | None:
    """Like subprocess.run with timeout, but kills the full process group on
    timeout (not just the parent). Without this, child threads/subprocesses
    can keep running past the deadline (observed: Lean judge subprocesses
    holding open file descriptors after eval.py timed out)."""
    import signal as _signal

    proc = subprocess.Popen(
        argv,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    try:
        out, _ = proc.communicate(timeout=timeout_s)
        return subprocess.CompletedProcess(argv, proc.returncode, stdout=out, stderr="")
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), _signal.SIGTERM)
            proc.wait(timeout=5)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(os.getpgid(proc.pid), _signal.SIGKILL)
            except ProcessLookupError:
                return None
        return None


def run_smoke(budget_sec: int) -> None:
    r = _run_with_pg_kill(
        ["python3", "-m", "train_smoke", "--smoke", "--budget-sec", str(budget_sec)],
        TRAIN_HARD_CAP_S,
    )
    if r is None:
        print(
            f"[driver] train.py exceeded {TRAIN_HARD_CAP_S}s — killed pg",
            file=sys.stderr,
        )


def run_eval(gen: int = 0) -> float:
    workers = os.environ.get("LAWFORGE_EVAL_WORKERS", "2")
    limit = os.environ.get("LAWFORGE_EVAL_LIMIT", "20")
    timeout = os.environ.get("LAWFORGE_EVAL_TIMEOUT", "45")
    split = os.environ.get("LAWFORGE_EVAL_SPLIT", "dev")
    argv = [
        "python3",
        "-m",
        "eval_harness",
        "--split",
        split,
        "--limit",
        limit,
        "--workers",
        workers,
        "--timeout",
        timeout,
    ]
    if os.environ.get("LAWFORGE_EVAL_SHUFFLE", "1") == "1":
        argv += ["--seed", str(gen)]
    r = _run_with_pg_kill(argv, EVAL_HARD_CAP_S)
    if r is None:
        print(
            f"[driver] eval.py exceeded {EVAL_HARD_CAP_S}s — killed pg, using 0.0",
            file=sys.stderr,
        )
        return 0.0
    for line in r.stdout.splitlines()[::-1]:
        if line.startswith("SOLVED_RATE="):
            return float(line.split("=", 1)[1])
    if os.environ.get("LAWFORGE_EVAL_VERBOSE", "0") == "1":
        print(
            "[driver] eval produced no SOLVED_RATE — last 60 lines of stdout:",
            file=sys.stderr,
        )
        for line in r.stdout.splitlines()[-60:]:
            print(f"  {line}", file=sys.stderr)
    return 0.0


def load_last_metric() -> float:
    if LAST_METRIC.exists():
        return json.loads(LAST_METRIC.read_text()).get("val_solved_rate", 0.0)
    return 0.0


def save_metric(val: float) -> None:
    LAST_METRIC.write_text(json.dumps({"val_solved_rate": val}))


def log_row(
    gen: int, arm: Arm, before: float, after: float, kept: int, commit_sha: str
) -> None:
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

    pre_sha = git("rev-parse", "HEAD")

    if os.environ.get("LAWFORGE_PRE_ARM_BASELINE", "1") == "1":
        before = run_eval(gen=args.gen)
        print(f"[gen {args.gen}] pre-arm baseline={before:.4f} @ seed={args.gen}")
    else:
        before = load_last_metric()
        print(f"[gen {args.gen}] using stale last_metric={before:.4f} (no pre-arm)")

    arm.apply(ROOT)
    subprocess.run(["git", "add", "-A"], cwd=ROOT, check=False)
    subprocess.run(
        ["git", "commit", "-m", f"gen{args.gen}: try arm={arm.name}"],
        cwd=ROOT,
        check=False,
    )
    trial_sha = git("rev-parse", "HEAD")

    t0 = time.time()
    run_smoke(args.smoke_sec)
    print(f"[gen {args.gen}] smoke train took {time.time() - t0:.0f}s")

    after = run_eval(gen=args.gen)
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
