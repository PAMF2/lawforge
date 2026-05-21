"""Lean judge wrapper.

Calls the upstream Stage 2 judge subprocess (the deterministic Lean verifier
shipped in github.com/SAIRcompetition/equational-theories-lean-stage2) and
parses its verdict.

Status enum from competition spec:
  accepted | unparsed | malformed | incomplete_proof | incorrect

Stub: tries upstream/scripts/judge.sh first, falls back to a mock if absent
(so unit tests pass without Lean installed).
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UPSTREAM_JUDGE = ROOT / "upstream" / "scripts" / "judge.sh"


@dataclass
class Verdict:
    status: str           # accepted | unparsed | malformed | incomplete_proof | incorrect
    message: str = ""

    @property
    def accepted(self) -> bool:
        return self.status == "accepted"


def judge(lean_code: str, expected_verdict: str = "true", problem_id: str = "") -> Verdict:
    """Run the upstream Lean judge on a candidate proof.

    expected_verdict: "true" (proof of implication) or "false" (counterexample).
    """
    if not UPSTREAM_JUDGE.exists():
        return _mock_judge(lean_code)

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({
            "call": "judge",
            "verdict": expected_verdict,
            "code": lean_code,
            "problem_id": problem_id,
        }, f)
        payload_path = f.name

    try:
        r = subprocess.run(
            ["bash", str(UPSTREAM_JUDGE), payload_path],
            capture_output=True, text=True, timeout=300,
        )
        out = r.stdout.strip().splitlines()
        if not out:
            return Verdict(status="unparsed", message=r.stderr[:500])
        last = out[-1]
        try:
            data = json.loads(last)
            return Verdict(status=data.get("status", "unparsed"), message=data.get("message", ""))
        except json.JSONDecodeError:
            return Verdict(status="unparsed", message=last[:500])
    except subprocess.TimeoutExpired:
        return Verdict(status="incorrect", message="judge timeout")
    finally:
        os.unlink(payload_path)


def _mock_judge(lean_code: str) -> Verdict:
    """Heuristic mock for offline / CI testing without Lean installed."""
    if "sorry" in lean_code or "admit" in lean_code:
        return Verdict(status="incomplete_proof")
    if "theorem" not in lean_code and "example" not in lean_code:
        return Verdict(status="malformed")
    for tac in ("rfl", "decide", "trivial", "aesop"):
        if tac in lean_code:
            return Verdict(status="accepted", message=f"mock accepted on {tac}")
    return Verdict(status="incorrect", message="mock: no obvious tactic")


def reward(verdict: Verdict, shaping: bool = False) -> float:
    """Convert verdict to RL reward.

    Default: binary (1.0 accepted, 0.0 else) = pure RLVR signal.
    Shaping: small partial credit for proof-that-compiles-but-wrong (incorrect)
    vs total garbage (unparsed). Use with caution; can reward-hack.
    """
    if verdict.accepted:
        return 1.0
    if not shaping:
        return 0.0
    return {
        "incorrect": 0.10,
        "incomplete_proof": 0.05,
        "malformed": 0.02,
        "unparsed": 0.0,
    }.get(verdict.status, 0.0)
