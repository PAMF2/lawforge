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
_JUDGE_AVAILABLE = UPSTREAM_JUDGE.exists()


# Stage 2 spec verdict strings — single source of truth, no typos.
ACCEPTED = "accepted"
UNPARSED = "unparsed"
MALFORMED = "malformed"
INCOMPLETE_PROOF = "incomplete_proof"
INCORRECT = "incorrect"

# Expected-verdict flags (what we're claiming Eq1 -> Eq2 status is).
TRUE = "true"
FALSE = "false"


@dataclass
class Verdict:
    status: str  # one of: accepted/unparsed/malformed/incomplete_proof/incorrect
    message: str = ""

    @property
    def accepted(self) -> bool:
        return self.status == ACCEPTED


def judge(lean_code: str, expected_verdict: str = "true", problem_id: str = "") -> Verdict:
    """Run the upstream Lean judge on a candidate proof.

    expected_verdict: "true" (proof of implication) or "false" (counterexample).
    """
    if not _JUDGE_AVAILABLE:
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
            return Verdict(status=data.get("status", UNPARSED), message=data.get("message", ""))
        except json.JSONDecodeError:
            return Verdict(status=UNPARSED, message=last[:500])
    except subprocess.TimeoutExpired:
        return Verdict(status=INCORRECT, message="judge timeout")
    finally:
        os.unlink(payload_path)


def _mock_judge(lean_code: str) -> Verdict:
    """Heuristic mock for offline / CI testing without Lean installed."""
    if "sorry" in lean_code or "admit" in lean_code:
        return Verdict(status=INCOMPLETE_PROOF)
    if "theorem" not in lean_code and "example" not in lean_code:
        return Verdict(status=MALFORMED)
    for tac in ("rfl", "decide", "trivial", "aesop"):
        if tac in lean_code:
            return Verdict(status=ACCEPTED, message=f"mock accepted on {tac}")
    return Verdict(status=INCORRECT, message="mock: no obvious tactic")


# LLM-judge calibration thresholds (used by judge_or_score). Tune via env.
ACCEPT_THRESHOLD = float(os.environ.get("LAWFORGE_JUDGE_ACCEPT", "0.85"))
MALFORMED_THRESHOLD = float(os.environ.get("LAWFORGE_JUDGE_MALFORMED", "0.1"))


def llm_judge_score(lean_code: str, eq1: str = "", eq2: str = "",
                    expected_verdict: str = TRUE) -> float:
    """RULER-style continuous reward 0..1 via LLM-as-judge.

    Returns 0.0 if the LLM call fails or returns malformed JSON.
    """
    from lawforge_utils import extract_json
    from solver.proxy_client import call_local
    prompt = (
        "You are scoring a Lean 4 proof candidate for the equational-implication task.\n"
        f"Eq1: {eq1}\nEq2: {eq2}\nExpected verdict: {expected_verdict}\n\n"
        f"Candidate proof:\n```lean\n{lean_code[:4000]}\n```\n\n"
        "Score 0..1 based on: syntactic validity, tactic correctness, "
        "type-correctness, and whether the goal is closed.\n"
        'Output ONLY JSON: {"score": <float 0..1>}'
    )
    resp = call_local(prompt, max_tokens=128, temperature=0.0)
    data = extract_json(resp.text)
    if not data:
        return 0.0
    try:
        return max(0.0, min(1.0, float(data["score"])))
    except (KeyError, ValueError, TypeError):
        return 0.0


def judge_or_score(lean_code: str, expected_verdict: str = TRUE,
                   eq1: str = "", eq2: str = "",
                   use_llm_fallback: bool = True) -> Verdict:
    """Cascaded reward: real Lean -> LLM-as-judge -> mock."""
    if _JUDGE_AVAILABLE:
        return judge(lean_code, expected_verdict)
    if not use_llm_fallback:
        return _mock_judge(lean_code)
    score = llm_judge_score(lean_code, eq1, eq2, expected_verdict)
    if score >= ACCEPT_THRESHOLD:
        status = ACCEPTED
    elif score < MALFORMED_THRESHOLD:
        status = MALFORMED
    else:
        status = INCORRECT
    return Verdict(status=status, message=f"llm-judge score={score:.3f}")


_SHAPED_REWARDS = {
    ACCEPTED: 1.0,
    INCORRECT: 0.10,
    INCOMPLETE_PROOF: 0.05,
    MALFORMED: 0.02,
    UNPARSED: 0.0,
}


def reward(verdict: Verdict, shaping: bool = False) -> float:
    """Convert verdict to RL reward. Binary by default; shaped if requested."""
    if verdict.accepted:
        return 1.0
    if not shaping:
        return 0.0
    return _SHAPED_REWARDS.get(verdict.status, 0.0)
