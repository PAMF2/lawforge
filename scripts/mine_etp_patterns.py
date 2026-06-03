"""P3 path-B: mine ETP Generated proofs for tactic skeletons.

Reads data/etp_proofs.jsonl produced by extract_etp_corpus.py and counts
top-level tactic skeletons. Picks the most frequent skeletons whose
canonical-form prefix is NOT already represented in solver/cheatsheet.md
and prints them as PATTERN block candidates for manual paste-in (we don't
overwrite the cheatsheet automatically because curation is cheap and
mistakes are expensive in a 10KB budget).

Skeleton = ordered list of top-level tactic names with arity stubs. We
strip helper-lemma identifiers (e.g. `RewriteHypothesis.EquationN...`)
since those resolve to ETP-internal lemmas not shipped in the SAIR
runtime. What survives is the orchestration shape (intro / have / rw /
apply / nth_rewrite / simp / aesop / calc / exact / refine / repeat).
"""

import argparse
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CORPUS = ROOT / "data" / "etp_proofs.jsonl"
CHEATSHEET = ROOT / "solver" / "cheatsheet.md"

TACTIC_TOKEN = re.compile(
    r"\b(intro|intros|have|apply|exact|rw|nth_rewrite|conv|simp|simp_all|"
    r"aesop|calc|refine|symm|cases|induction|repeat|rfl|decide|assumption|"
    r"trivial|constructor|show|let)\b"
)


def skeleton(proof: str) -> tuple[str, ...]:
    body = proof.split(":=", 1)[-1]
    body = body.replace("by", " ", 1)
    tokens = TACTIC_TOKEN.findall(body)
    out: list[str] = []
    for t in tokens:
        if not out or out[-1] != t:
            out.append(t)
    return tuple(out[:6])


def covered_in_cheatsheet(skel: tuple[str, ...]) -> bool:
    if not skel:
        return True
    text = re.sub(r"\s+", " ", CHEATSHEET.read_text().lower())
    prefix = " ".join(skel[:3])
    return prefix in text


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--min-count", type=int, default=10)
    args = ap.parse_args()

    skels: Counter[tuple[str, ...]] = Counter()
    examples: dict[tuple[str, ...], str] = {}
    with Path(args.corpus).open() as f:
        for line in f:
            row = json.loads(line)
            proof = row.get("lean_proof", "")
            skel = skeleton(proof)
            if not skel:
                continue
            skels[skel] += 1
            if skel not in examples and len(proof) < 400:
                examples[skel] = proof

    novel = []
    for skel, count in skels.most_common():
        if count < args.min_count:
            break
        if covered_in_cheatsheet(skel):
            continue
        novel.append((skel, count, examples.get(skel, "")))
        if len(novel) >= args.top:
            break

    print(f"# Mined {sum(skels.values())} proofs, {len(skels)} unique skeletons")
    print(f"# Showing top {len(novel)} novel skeletons (>= {args.min_count} hits)\n")
    for skel, count, ex in novel:
        print(f"## skeleton: {' '.join(skel)}  ({count} hits)")
        print(f"```lean\n{ex.strip()[:300]}\n```\n")


if __name__ == "__main__":
    main()
