"""Distill accepted Lean proofs into the shipped cheatsheet (Honda 2025 pattern).

Inputs:  proofs/accepted/*.lean   (mined by train_grpo or by the Karpathy loop)
Output:  solver/cheatsheet.md     (overwritten — gets re-emitted with pattern blocks)

Strategy (single-pass, deterministic):
  1. Group accepted proofs by their dominant tactic chain (rfl / decide / aesop / calc / refine).
  2. For each group, pick the K=3 shortest exemplars (favor compact, transferable).
  3. Emit one PATTERN block per group with the exemplars inline.
  4. Cap total bytes at MAX_CHEATSHEET (default 8 KB so it fits comfortably in
     the 100 KB Lean-code-per-call limit even with prompt + cheatsheet).

A more sophisticated distill (Honda-style learned compression) would use an
LLM to summarize each group. That requires another LLM call per group; we
defer it. Current approach: pick-and-package, no LLM needed.
"""

import argparse
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ACCEPTED = ROOT / "proofs" / "accepted"
OUT = ROOT / "solver" / "cheatsheet.md"

TACTIC_KEYS = [
    "rfl",
    "decide",
    "trivial",
    "aesop",
    "calc",
    "simp",
    "polyrith",
    "nlinarith",
    "ring",
    "refine",
    "constructor",
    "exact",
]
_TACTIC_RE = re.compile(r"\b(" + "|".join(TACTIC_KEYS) + r")\b")


def _dominant_tactic(code: str) -> str:
    counts: dict[str, int] = {}
    for match in _TACTIC_RE.finditer(code):
        tac = match.group(1)
        counts[tac] = counts.get(tac, 0) + 1
    return max(counts, key=lambda k: counts[k]) if counts else "other"


_LEAN_FENCE_RE = re.compile(r"```(?:lean4?|Lean4?)\s*\n(.*?)```", re.DOTALL)
_THEOREM_BLOCK_RE = re.compile(
    r"(theorem\s+\w[\w\s\S]*?:=\s*by[\s\S]*?(?=\n(?:theorem|example|def|--|\Z))"
    r"|example[\s\S]*?:=\s*by[\s\S]*?(?=\n(?:theorem|example|def|--|\Z)))",
)
_LEAN_VALID_RE = re.compile(r"\b(theorem|example|def|instance|lemma|:=\s*by)\b")


def _looks_like_lean(block: str) -> bool:
    """Reject prose that happens to be inside ```lean fences (mined bench
    runs are prose like 'VERDICT: FALSE\\nREASONING: ...'). Real Lean has
    at least one of theorem/example/def/instance/lemma or `:= by`."""
    return bool(_LEAN_VALID_RE.search(block))


def _extract_lean(text: str) -> list[str]:
    """Pull Lean code blocks out of a free-form LLM response. Tries fenced
    code blocks first; falls back to theorem/example patterns. Drops blocks
    that contain no Lean keywords (prose contamination)."""
    blocks = [m.group(1).strip() for m in _LEAN_FENCE_RE.finditer(text)]
    if not blocks:
        blocks = [m.group(0).strip() for m in _THEOREM_BLOCK_RE.finditer(text)]
    return [b for b in blocks if _looks_like_lean(b)]


def _load_accepted(path: Path) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    if not path.exists():
        return dict(groups)
    for f in sorted(path.glob("*.lean")):
        for blk in _extract_lean(f.read_text()):
            if blk.strip():
                groups[_dominant_tactic(blk)].append(blk)
    return dict(groups)


def _shortest_k(items: list[str], k: int) -> list[str]:
    return sorted(items, key=len)[:k]


def distill(
    accepted_dir: Path, out: Path, k_per_group: int = 3, max_bytes: int = 8192
) -> None:
    groups = _load_accepted(accepted_dir)
    n_proofs = sum(len(v) for v in groups.values())
    if n_proofs == 0:
        print(
            f"[distill] no valid Lean blocks in {accepted_dir} — preserving seed {out}"
        )
        return
    lines = ["# Lawforge Cheatsheet (distilled from accepted proofs)\n"]
    total = len(lines[0])
    for tac, items in sorted(groups.items(), key=lambda x: -len(x[1])):
        header = f"\n## PATTERN: {tac}-chain ({len(items)} accepted)\n\n"
        block = ""
        for ex in _shortest_k(items, k_per_group):
            block += f"```lean\n{ex.strip()}\n```\n\n"
        if total + len(header) + len(block) > max_bytes:
            break
        lines.append(header + block)
        total += len(header) + len(block)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Overwrite warning: the seed cheatsheet's hand-written semantic patterns
    # (identity-reflexive, etc.) and any aesop_prelude arm injections will be
    # replaced by these tactic-grouped patterns. Re-apply arms after distill.
    out.write_text("".join(lines))
    print(f"[distill] groups={len(groups)} proofs={n_proofs} bytes={total} -> {out}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-dir", default=str(ACCEPTED))
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--max-bytes", type=int, default=8192)
    args = ap.parse_args()
    distill(Path(args.from_dir), Path(args.out), args.k, args.max_bytes)


if __name__ == "__main__":
    main()
