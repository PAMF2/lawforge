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


def _is_plausible_body(body: str) -> bool:
    if not body or body.strip() == "sorry":
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
    args = ap.parse_args()

    accepted: list[tuple[dict, str]] = []
    problems_seen = 0
    problems_with_accept = 0
    with Path(args.in_path).open() as f:
        for line in f:
            row = json.loads(line)
            problems_seen += 1
            eq1 = row["eq1"]
            eq2 = row["eq2"]
            problem = {
                "id": row["id"],
                "equation1": eq1,
                "equation2": eq2,
                "hypothesis": eq1,
                "goal": eq2,
            }
            got = False
            for cand in row["candidates"][: args.max_cands_per_problem]:
                body = judge_candidate(cand, eq1, eq2, problem)
                if body:
                    accepted.append((row, body))
                    got = True
                    break
            if got:
                problems_with_accept += 1
            if problems_seen % 50 == 0:
                sys.stderr.write(
                    f"[distill] {problems_seen} judged, "
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
