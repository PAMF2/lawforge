"""End-to-end judge diagnostic. Runs in ~30s, no LLM, no Karpathy loop.

For one TRUE problem and one FALSE problem from the dev split, this script:
  1. Builds an upstream-canonical Lean submission *by hand* (no model in the
     loop) - exact bytes match equational-theories-lean-stage2/examples/solo/
     demos/baseline/solver.py:make_true_code / make_false_code.
  2. Builds the same submission via our wrappers (_wrap_true_submission /
     emit_lean_counterex) and our _normalize_lean_code / _to_diamond path.
  3. Calls lean.judge.judge() against each and prints the verdict status +
     message verbatim.

Reading the output answers, in order:
  - Is the judge itself healthy?  (hand-crafted TRUE/FALSE on a known easy
    problem should be `accepted`. If not, judge env or imports are broken.)
  - Does our wrapper match upstream byte-for-byte? (diff the two TRUE codes;
    diff the two FALSE codes.)
  - If the judge rejects ours but accepts the hand-crafted, the failure mode
    is localized to our wrapping / extraction layer.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lean.judge import (  # noqa: E402
    _ALLOW_MOCK,
    _JUDGE_AVAILABLE,
    _build_upstream_problem,
    _normalize_lean_code,
    _to_diamond,
    judge,
)
from solver.counterex import emit_lean_counterex, search_counterex  # noqa: E402
from solver.solver import _wrap_true_submission  # noqa: E402


def _baseline_true(proof_body: str) -> str:
    """Exact upstream baseline make_true_code shape."""
    lines = proof_body.strip().split("\n")
    indented = "\n".join("  " + ln if ln.strip() else "" for ln in lines)
    return (
        "import JudgeProblem\n\n"
        "def submission : Goal := by\n"
        "  intro G _ h\n"
        f"{indented}\n"
    )


def _baseline_false(n: int, table: list[list[int]]) -> str:
    """Exact upstream baseline make_false_code shape."""
    table_str = json.dumps(table)
    return (
        "import JudgeProblem\n"
        "import JudgeDecide.DecideBang\n"
        "import JudgeFinOp.MemoFinOp\n"
        "open MemoFinOp\n\n"
        "def submission : Goal := by\n"
        f"  let m : Magma (Fin {n}) := {{\n"
        f'    op := finOpTable "{table_str}"\n'
        f"  }}\n"
        f"  refine ⟨Fin {n}, m, ?_⟩\n"
        f"  decideFin!\n"
    )


def _load_one(split: str, label: str) -> dict | None:
    p = ROOT / "data" / f"{split}_split.jsonl"
    if not p.exists():
        return None
    with p.open() as f:
        for line in f:
            r = json.loads(line)
            if r.get("label") == label:
                return r
    return None


def _print_section(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def _run(label: str, expected: str, candidate: str, problem: dict) -> None:
    norm = _normalize_lean_code(candidate)
    print(f"--- candidate Lean ({label}, {len(candidate)} bytes) ---")
    print(norm)
    print("--- upstream problem dict ---")
    print(
        json.dumps(
            _build_upstream_problem(problem, expected), ensure_ascii=False, indent=2
        )
    )
    v = judge(candidate, expected_verdict=expected, problem=problem)
    print(f"--- judge verdict: status={v.status} ---")
    print(f"message: {v.message[:1500]}")


def main() -> None:
    print(f"_JUDGE_AVAILABLE={_JUDGE_AVAILABLE} _ALLOW_MOCK={_ALLOW_MOCK}")
    if not _JUDGE_AVAILABLE:
        print("ABORT: upstream judge missing. run `bash upstream/scripts/setup.sh`.")
        sys.exit(2)

    true_p = _load_one("dev", "true")
    false_p = _load_one("dev", "false")
    if not true_p or not false_p:
        print("ABORT: dev_split missing TRUE or FALSE example")
        sys.exit(2)

    _print_section(f"TRUE PROBLEM: id={true_p['id']}")
    print(f"hypothesis: {true_p['hypothesis']}")
    print(f"goal:       {true_p['goal']}")
    print(f"diamond(hyp): {_to_diamond(true_p['hypothesis'])}")
    print(f"diamond(gol): {_to_diamond(true_p['goal'])}")

    # A. hand-crafted upstream-baseline TRUE with trivial `assumption` body
    _print_section("A) hand-crafted upstream baseline (TRUE, body=`assumption`)")
    _run("baseline-true", "true", _baseline_true("assumption"), true_p)

    # B. our wrapper TRUE with same body
    _print_section("B) our _wrap_true_submission (TRUE, body=`assumption`)")
    _run("ours-true", "true", _wrap_true_submission("assumption"), true_p)

    # C. our wrapper TRUE with `exact h _ _ _` style (filler)
    _print_section("C) our wrapper (TRUE, body=`intro x; exact h x`)")
    _run("ours-true-2", "true", _wrap_true_submission("intro x\nexact h x"), true_p)

    _print_section(f"FALSE PROBLEM: id={false_p['id']}")
    print(f"hypothesis: {false_p['hypothesis']}")
    print(f"goal:       {false_p['goal']}")

    # D. search counterex then submit with our emitter
    ce = search_counterex(false_p["hypothesis"], false_p["goal"], max_order=4)
    if ce is None:
        print("could not find counterexample at order <= 4")
        # Still test hand-crafted FALSE with a trivial 2x2 table
        _print_section("D) hand-crafted baseline (FALSE, n=2, table=[[0,0],[1,1]])")
        _run("baseline-false", "false", _baseline_false(2, [[0, 0], [1, 1]]), false_p)
    else:
        print(f"counterex order={ce.order} table={ce.table}")
        _print_section("D) our emit_lean_counterex (FALSE)")
        _run(
            "ours-false",
            "false",
            emit_lean_counterex(ce, false_p["hypothesis"], false_p["goal"]),
            false_p,
        )
        _print_section("E) hand-crafted baseline (FALSE, same table)")
        _run("baseline-false", "false", _baseline_false(ce.order, ce.table), false_p)

    print("\n" + "=" * 78)
    print("DONE. Compare ours vs baseline outputs above. Any pair that differs")
    print("in verdict pinpoints the wrapping bug.")
    print("=" * 78)


if __name__ == "__main__":
    main()
