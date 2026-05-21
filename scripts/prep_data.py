"""Download SAIR equational-theories problem sets from HuggingFace,
split into train/dev, write JSONL to data/.

Layout produced:
  data/train_split.jsonl  (80% of normal+hard1)
  data/dev_split.jsonl    (20% balanced TRUE/FALSE)
  data/hard2_test.jsonl   (held-out for late-stage eval)
  data/hard3_test.jsonl   (held-out)
"""
from __future__ import annotations

import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
HF_REPO = "SAIRfoundation/equational-theories-selected-problems"


def normalize(row: dict) -> dict:
    """Canonicalize HF row -> lawforge solver schema."""
    return {
        "id": row.get("id", ""),
        "difficulty": row.get("difficulty", ""),
        "hypothesis": row.get("equation1", row.get("hypothesis", "")),
        "goal": row.get("equation2", row.get("goal", "")),
        "label": "true" if row.get("answer") is True else
                 "false" if row.get("answer") is False else row.get("label", ""),
    }


def main(seed: int = 7) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    from datasets import load_dataset  # type: ignore

    splits = {
        "normal": load_dataset(HF_REPO, "normal", split="train"),
        "hard1": load_dataset(HF_REPO, "hard1", split="train"),
        "hard2": load_dataset(HF_REPO, "hard2", split="train"),
        "hard3": load_dataset(HF_REPO, "hard3", split="train"),
    }

    pool = ([normalize(dict(r)) for r in splits["normal"]]
            + [normalize(dict(r)) for r in splits["hard1"]])
    random.Random(seed).shuffle(pool)
    cut = int(0.8 * len(pool))
    train, dev = pool[:cut], pool[cut:]

    write(DATA / "train_split.jsonl", train)
    write(DATA / "dev_split.jsonl", dev)
    write(DATA / "hard2_test.jsonl", [normalize(dict(r)) for r in splits["hard2"]])
    write(DATA / "hard3_test.jsonl", [normalize(dict(r)) for r in splits["hard3"]])
    print(f"train={len(train)} dev={len(dev)} "
          f"hard2={len(splits['hard2'])} hard3={len(splits['hard3'])}")


def write(path: Path, rows: list[dict]) -> None:
    with path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


if __name__ == "__main__":
    main()
