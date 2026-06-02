"""Extract teorth/equational_theories proven implications as training pairs.

Walks the Generated/*/theorems/*.lean files for `theorem Equation{X}_implies_
Equation{Y} ... := <body>` declarations. Pairs each with the human-readable
equation strings from data/equations.txt so the resulting JSONL can be used
as a fine-tune corpus.

Output JSONL row shape:
  {"eq1_id": int, "eq2_id": int,
   "eq1_str": str, "eq2_str": str,
   "lean_proof": str,
   "source_file": str}
"""

import argparse
import json
import re
import sys
from pathlib import Path

THEOREM_RE = re.compile(
    r"theorem\s+Equation(\d+)_implies_Equation(\d+)\b"
    r"(.*?:=\s*)(.*?)(?=\n\s*@\[|\n\s*theorem\s+|\Z)",
    re.DOTALL,
)


def _load_equations(equations_path: Path) -> dict[int, str]:
    eqs: dict[int, str] = {}
    with equations_path.open() as f:
        for i, line in enumerate(f, start=1):
            line = line.strip()
            if line:
                eqs[i] = line
    return eqs


def _extract_from_file(path: Path, eqs: dict[int, str]) -> list[dict]:
    rows: list[dict] = []
    text = path.read_text()
    for m in THEOREM_RE.finditer(text):
        eq1_id = int(m.group(1))
        eq2_id = int(m.group(2))
        proof = m.group(4).strip()
        # drop the trailing newline + whitespace; keep through `:= <body>`
        proof = proof.rstrip("\n").rstrip()
        if not proof:
            continue
        if eq1_id not in eqs or eq2_id not in eqs:
            continue
        rows.append(
            {
                "eq1_id": eq1_id,
                "eq2_id": eq2_id,
                "eq1_str": eqs[eq1_id],
                "eq2_str": eqs[eq2_id],
                "lean_proof": proof,
                "source_file": str(path.name),
            }
        )
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--etp-root",
        default="/home/pedroafonso/Desktop/equational_theories",
        help="root of cloned teorth/equational_theories repo",
    )
    ap.add_argument(
        "--out",
        default="/home/pedroafonso/Desktop/lawforge/data/etp_proofs.jsonl",
        help="output JSONL path",
    )
    args = ap.parse_args()

    root = Path(args.etp_root)
    equations_path = root / "data" / "equations.txt"
    if not equations_path.exists():
        sys.stderr.write(f"missing {equations_path}\n")
        sys.exit(1)
    eqs = _load_equations(equations_path)
    sys.stderr.write(f"loaded {len(eqs)} equations\n")

    theorem_dirs = list((root / "equational_theories" / "Generated").glob("*/theorems"))
    sys.stderr.write(f"scanning {len(theorem_dirs)} theorem dirs\n")

    all_rows: list[dict] = []
    for d in theorem_dirs:
        for lean_file in d.glob("*.lean"):
            file_rows = _extract_from_file(lean_file, eqs)
            all_rows.extend(file_rows)
            if file_rows:
                sys.stderr.write(f"  {lean_file.relative_to(root)}: {len(file_rows)}\n")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        for r in all_rows:
            f.write(json.dumps(r) + "\n")
    sys.stderr.write(f"wrote {len(all_rows)} rows to {out_path}\n")


if __name__ == "__main__":
    main()
