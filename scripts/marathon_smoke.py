"""Smoke test for the marathon entry point.

Build a 5-problem manifest from the dev split, run solver.py as a subprocess
with JUDGE_MARATHON_MANIFEST / JUDGE_MARATHON_OUTPUT set, then read back the
output JSONL and verify shape + counterex coverage.

Counterex pass is pure Python (no Lean / no LLM needed), so this smoke can
run on any machine. The LLM phase is bypassed by giving a tiny budget.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dev(limit: int) -> list[dict]:
    p = ROOT / "data" / "dev_split.jsonl"
    if not p.exists():
        sys.stderr.write(f"missing {p} — run scripts/prep_data.py first\n")
        sys.exit(1)
    rows = []
    with p.open() as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
            if len(rows) >= limit:
                break
    return rows


def _to_manifest_row(p: dict) -> dict:
    return {
        "id": p.get("id", ""),
        "eq1_id": p.get("eq1_id", 0),
        "eq2_id": p.get("eq2_id", 0),
        "equation1": p.get("equation1", p.get("hypothesis", "")),
        "equation2": p.get("equation2", p.get("goal", "")),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--budget", type=float, default=8.0)
    args = ap.parse_args()

    rows = _load_dev(args.limit)
    with tempfile.TemporaryDirectory() as td:
        manifest = Path(td) / "manifest.jsonl"
        with manifest.open("w") as f:
            for p in rows:
                f.write(json.dumps(_to_manifest_row(p)) + "\n")
        output = Path(td) / "answers.jsonl"

        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT)
        env["JUDGE_MARATHON_MANIFEST"] = str(manifest)
        env["JUDGE_MARATHON_OUTPUT"] = str(output)
        env["JUDGE_MARATHON_BUDGET_SECONDS"] = str(args.budget)

        r = subprocess.run(
            [sys.executable, "-m", "solver.solver"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        sys.stderr.write(r.stderr)
        if r.returncode != 0:
            sys.stderr.write(f"solver exited rc={r.returncode}\n")
            sys.exit(1)

        if not output.exists():
            sys.stderr.write("no output file written\n")
            sys.exit(1)

        answers = []
        with output.open() as f:
            for line in f:
                line = line.strip()
                if line:
                    answers.append(json.loads(line))

        false_n = sum(1 for a in answers if a.get("verdict") == "false")
        true_n = sum(1 for a in answers if a.get("verdict") == "true")
        print(
            f"manifest={len(rows)} answers={len(answers)} false={false_n} true={true_n}"
        )
        for a in answers:
            code_len = len(a.get("code", ""))
            print(f"  {a.get('id')} verdict={a.get('verdict')} code_bytes={code_len}")

        if false_n == 0:
            sys.stderr.write("WARN: zero FALSE answers — counterex pass empty\n")


if __name__ == "__main__":
    main()
