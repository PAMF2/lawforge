"""Distill Kaggle-harvested Kimina candidates into solver/cheatsheet.md.

Pipeline:
  1. Read /kaggle/working/harvested.jsonl produced by the harvest notebook
     (one row per problem, each row has up to K candidate tactic bodies).
  2. For each candidate, judge True via lean.judge.judge_or_score against
     the problem's (eq1, eq2) - reuse the eval harness's judge so this is
     identical to the SAIR scoring rule.
  3. Group accepted candidates by 3-token tactic skeleton (same definition
     as scripts.mine_etp_patterns.skeleton).
  4. For each skeleton, pick the shortest accepted exemplar.
  5. Print PATTERN block candidates for skeletons NOT already covered by
     the current cheatsheet. Curation stays manual to respect the 10KB
     hard cap.

Usage:
    python3 -m scripts.distill_harvested --in /kaggle/working/harvested.jsonl
    python3 -m scripts.distill_harvested --in harvested.jsonl --min-count 2
"""

import argparse
import json
import multiprocessing as mp
import os
import re
import sys
from collections import Counter
from pathlib import Path

from lean.judge import judge_or_score
from scripts.mine_etp_patterns import covered_in_cheatsheet, skeleton
from solver.extract import extract_body
from solver.solver import _wrap_true_submission

_TACTIC_LINE = re.compile(
    r"^\s*(intro|have|rw|apply|exact|simp|aesop|calc|refine|symm|cases|"
    r"nth_rewrite|repeat|rfl|decide|assumption|fun|trivial|conv|let|show)\b"
)

# Mathlib-only identifiers that the SAIR sandbox cannot resolve. A body that
# references any of these typechecks against Kimina's training environment
# (Mathlib + Aesop) but will fail when the SAIR judge wraps it inside
# `import JudgeProblem; def submission : Goal := by ...`.
_MATHLIB_LEAK = re.compile(
    r"\b("
    r"Nat\.|Int\.|Real\.|Rat\.|Complex\.|Finset\.|List\.|Set\.|"
    r"Mathlib\.|BigOperators|Topology|Order\.|Group\.|Ring\.|Field\.|"
    r"Module\.|LinearMap|Polynomial|MeasureTheory|Continuous|"
    r"omega|positivity|polyrith|linarith|nlinarith|norm_num|ring|ring_nf|"
    r"field_simp|abel|gcongr"
    r")\b"
)


def _is_plausible_body(body: str) -> bool:
    if not body or body.strip() == "sorry":
        return False
    if _MATHLIB_LEAK.search(body):
        return False
    return any(_TACTIC_LINE.match(ln) for ln in body.splitlines())


def judge_candidate(cand: str, eq1: str, eq2: str, problem: dict) -> str | None:
    body = extract_body(cand)
    if not _is_plausible_body(body):
        return None
    wrapped = _wrap_true_submission(body)
    v = judge_or_score(
        wrapped,
        expected_verdict="true",
        eq1=eq1,
        eq2=eq2,
        use_llm_fallback=False,
        problem=problem,
    )
    return body if v.accepted else None


def _judge_one_row(args: tuple) -> tuple[dict, str | None]:
    row, max_cands, allow_mock = args
    if allow_mock:
        os.environ["LAWFORGE_ALLOW_MOCK"] = "1"
    eq1 = row["eq1"]
    eq2 = row["eq2"]
    problem = {
        "id": row["id"],
        "equation1": eq1,
        "equation2": eq2,
        "hypothesis": eq1,
        "goal": eq2,
    }
    for cand in row["candidates"][:max_cands]:
        body = judge_candidate(cand, eq1, eq2, problem)
        if body:
            return row, body
    return row, None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_path", default="/kaggle/working/harvested.jsonl")
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--min-count", type=int, default=2)
    ap.add_argument(
        "--max-cands-per-problem",
        type=int,
        default=8,
        help="Cap candidates judged per problem (saves time).",
    )
    ap.add_argument(
        "--workers",
        type=int,
        default=max(1, (os.cpu_count() or 4) - 1),
        help="Parallel judge workers (each spawns a Lean subprocess).",
    )
    ap.add_argument(
        "--allow-mock",
        action="store_true",
        help="Permit heuristic mock judge when upstream Lean missing. "
        "Mock has false positives; use only for quick iteration.",
    )
    args = ap.parse_args()

    rows: list[dict] = []
    with Path(args.in_path).open() as f:
        for line in f:
            rows.append(json.loads(line))

    accepted: list[tuple[dict, str]] = []
    problems_seen = 0
    problems_with_accept = 0
    pool_args = [(row, args.max_cands_per_problem, args.allow_mock) for row in rows]
    with mp.Pool(processes=args.workers) as pool:
        for row, body in pool.imap_unordered(_judge_one_row, pool_args, chunksize=4):
            problems_seen += 1
            if body:
                accepted.append((row, body))
                problems_with_accept += 1
            if problems_seen % 50 == 0:
                sys.stderr.write(
                    f"[distill] {problems_seen}/{len(rows)} judged, "
                    f"{problems_with_accept} accepted so far\n"
                )

    sys.stderr.write(
        f"[distill] DONE judged={problems_seen} accepted={problems_with_accept} "
        f"({100 * problems_with_accept / max(1, problems_seen):.1f}%)\n"
    )

    skels: Counter[tuple[str, ...]] = Counter()
    examples: dict[tuple[str, ...], str] = {}
    for _row, body in accepted:
        skel = skeleton(body)
        if not skel:
            continue
        skels[skel] += 1
        if skel not in examples or len(body) < len(examples[skel]):
            examples[skel] = body

    novel = []
    for skel, count in skels.most_common():
        if count < args.min_count:
            break
        if covered_in_cheatsheet(skel):
            continue
        novel.append((skel, count, examples[skel]))
        if len(novel) >= args.top:
            break

    print(
        f"# {problems_with_accept}/{problems_seen} problems with at least "
        f"one accepted candidate"
    )
    print(
        f"# {len(skels)} unique skeletons, {len(novel)} novel "
        f"(>= {args.min_count} hits, not covered)\n"
    )
    for skel, count, ex in novel:
        print(f"## skeleton: {' '.join(skel)}  ({count} hits)")
        print(f"```lean\n{ex.strip()[:300]}\n```\n")


if __name__ == "__main__":
    main()
