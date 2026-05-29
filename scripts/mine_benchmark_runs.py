"""Mine SAIRfoundation/equational-theories-benchmark for top-model accepted runs.

This dataset contains 90,000 actual model responses graded correct/incorrect
from 25 top models (Claude Opus 4.6, GPT-5.2, Gemini 3.1 Pro, DeepSeek, ...)
across multiple benchmarks. Filter to correct=True from top performers and
save each response as a candidate proof artifact for cheatsheet distill.

Usage:
  python scripts/mine_benchmark_runs.py --top-models 5 --max-rows 2000

Output:
  proofs/accepted/<hash>.lean  (one per mined response)
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lawforge_utils import problem_hash

REPO = "SAIRfoundation/equational-theories-benchmark"
ACCEPTED = ROOT / "proofs" / "accepted"


def _top_model_ids(leaderboard_rows, k: int) -> list[str]:
    """Pick the K best-performing model_ids by aggregate f1_score."""
    agg: dict[str, list[float]] = {}
    for r in leaderboard_rows:
        agg.setdefault(r["model_id"], []).append(float(r["f1_score"]))
    ranked = sorted(agg.items(), key=lambda kv: -sum(kv[1]) / len(kv[1]))
    return [mid for mid, _ in ranked[:k]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--top-models",
        type=int,
        default=5,
        help="number of best models to harvest from (by f1)",
    )
    ap.add_argument(
        "--max-rows", type=int, default=2000, help="cap total mined responses"
    )
    ap.add_argument(
        "--min-correct-streak",
        type=int,
        default=2,
        help="problem must be correct in >= N repeats across top models",
    )
    args = ap.parse_args()

    from datasets import load_dataset

    print(f"[mine-bench] loading leaderboard from {REPO}...", file=sys.stderr)
    lb = load_dataset(REPO, "leaderboard", split="train")
    top = _top_model_ids(list(lb), args.top_models)
    print(f"[mine-bench] top models: {top}", file=sys.stderr)

    print("[mine-bench] loading runs (90k rows)...", file=sys.stderr)
    runs = load_dataset(REPO, "runs", split="train")
    top_set = set(top)

    ACCEPTED.mkdir(parents=True, exist_ok=True)
    seen_problem: dict[str, int] = {}  # problem_id -> correct-count across top models
    saved = 0
    for row in runs:
        if row["model_id"] not in top_set:
            continue
        if not row.get("correct"):
            continue
        pid = row["problem_id"]
        seen_problem[pid] = seen_problem.get(pid, 0) + 1
        if seen_problem[pid] < args.min_correct_streak:
            continue
        # save once per problem (first qualifying response wins)
        problem = {"hypothesis": row["equation1"], "goal": row["equation2"]}
        out = ACCEPTED / f"{problem_hash(problem)}.lean"
        if out.exists():
            continue
        out.write_text(
            f"-- mined from {row['model_id']} on {row['problem_id']}\n"
            f"-- judge_reason: {row.get('judge_reason', '')}\n"
            f"{row['response']}\n"
        )
        saved += 1
        if saved >= args.max_rows:
            break
        if saved % 100 == 0:
            print(f"[mine-bench] saved {saved}", file=sys.stderr)
    print(
        f"[mine-bench] done. saved={saved} unique problems into {ACCEPTED}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
