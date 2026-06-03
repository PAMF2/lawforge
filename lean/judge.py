"""Lean judge wrapper.

Calls the upstream Stage 2 judge (`judge.verify.verify_answer`) shipped in
github.com/SAIRcompetition/equational-theories-lean-stage2. Activated when
`upstream/.env.judge` and `upstream/judge/verify.py` exist (after running
`bash upstream/scripts/setup.sh` which installs Lean toolchain + mathlib +
builds judge modules).

Mock policy: the heuristic mock is for unit tests ONLY and never fires in
production paths. judge() / judge_or_score() raise RuntimeError when the
upstream judge is unavailable. To opt in for offline runs (CI, dev box
without Lean), set LAWFORGE_ALLOW_MOCK=1.

Status enum from competition spec:
  accepted | unparsed | malformed | incomplete_proof | incorrect
"""

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

_log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
UPSTREAM = ROOT / "upstream"
UPSTREAM_JUDGE = UPSTREAM / "scripts" / "judge.sh"  # legacy probe (not used)
UPSTREAM_ENV = UPSTREAM / ".env.judge"
_JUDGE_AVAILABLE = UPSTREAM_ENV.exists() and (UPSTREAM / "judge" / "verify.py").exists()
_ALLOW_MOCK = os.environ.get("LAWFORGE_ALLOW_MOCK", "0") == "1"


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


_VERIFY_FN = None
_JUDGE_CONFIG = None
_JUDGE_LOAD_TRIED = False


def _load_real_judge() -> bool:
    """Import upstream judge.verify lazily; cache config. Idempotent."""
    global _VERIFY_FN, _JUDGE_CONFIG, _JUDGE_LOAD_TRIED
    if _VERIFY_FN is not None:
        return True
    if _JUDGE_LOAD_TRIED:
        return False
    _JUDGE_LOAD_TRIED = True
    import sys as _sys

    if str(UPSTREAM) not in _sys.path:
        _sys.path.insert(0, str(UPSTREAM))
    try:
        import importlib

        verify_mod = importlib.import_module("judge.verify")
        _JUDGE_CONFIG = verify_mod._resolve_config(None)
        _VERIFY_FN = verify_mod.verify_answer
        return True
    except Exception as e:
        _log.warning("failed to load upstream verify: %s", e)
        return False


def _to_diamond(text: str) -> str:
    """Convert magma operator `*` -> `◇` (U+25C7).

    The HF SAIRfoundation/equational-theories-selected-problems dataset ships
    equations with `*`. The upstream Stage 2 judge's regex
    `^[\\sa-zA-Z0-9◇=()]+$` REJECTS `*` outright with JudgeConfigurationError.
    Single source of conversion to avoid drift across solver/eval/judge paths.
    """
    return text.replace("*", "◇") if text else text


_STAGE2_ALLOWED_AXIOMS = ("propext", "Quot.sound", "Classical.choice")


def _build_upstream_problem(p: dict | None, expected_verdict: str) -> dict:
    """Translate our internal problem dict to upstream PROBLEM_KEYS shape.

    Converts `*` -> `◇` in equations so the judge regex doesn't reject them.

    Attaches a Stage 2 default proof_policy allowing the three canonical
    axioms (propext, Quot.sound, Classical.choice). Without this, judge
    defaults to allowed_axioms=() and every `decide`/`simp`/`aesop`-derived
    proof gets rejected as `incomplete_proof: proof uses disallowed axioms`.
    """
    p = p or {}
    return {
        "id": p.get("id", p.get("problem_id", "lawforge_x")),
        "eq1_id": int(p.get("eq1_id", 0)),
        "eq2_id": int(p.get("eq2_id", 0)),
        "equation1": _to_diamond(p.get("equation1", p.get("hypothesis", ""))),
        "equation2": _to_diamond(p.get("equation2", p.get("goal", ""))),
        "answer": expected_verdict == TRUE,
        "proof_policy": {
            "allowed_axioms": list(_STAGE2_ALLOWED_AXIOMS),
        },
    }


def _normalize_lean_code(code: str) -> str:
    """Replace `*` magma operator with `◇` in submitted Lean code so it
    matches the Magma class infix notation built by the judge. Safe to apply
    repeatedly (idempotent on `◇`)."""
    return code.replace("*", "◇") if code else code


def judge(
    lean_code: str, expected_verdict: str = TRUE, problem: dict | None = None
) -> Verdict:
    """Run upstream Lean judge.verify on a candidate proof.

    `problem` should include equation1/equation2/eq1_id/eq2_id/id (HF schema).
    Raises RuntimeError when the upstream judge is unavailable, unless
    LAWFORGE_ALLOW_MOCK=1 (CI/dev escape hatch).
    """
    if not _JUDGE_AVAILABLE or not _load_real_judge():
        if _ALLOW_MOCK:
            return _mock_judge(lean_code)
        raise RuntimeError(
            "Lean judge unavailable: run `bash upstream/scripts/setup.sh` "
            f"(missing {UPSTREAM_ENV} or upstream/judge/verify.py). Set "
            "LAWFORGE_ALLOW_MOCK=1 only for offline tests."
        )

    upstream_problem = _build_upstream_problem(problem, expected_verdict)
    raw_answer = json.dumps(
        {
            "verdict": expected_verdict,
            "code": _normalize_lean_code(lean_code),
        }
    )
    try:
        result = _VERIFY_FN(upstream_problem, raw_answer, config=_JUDGE_CONFIG)
        return Verdict(
            status=result.get("status", UNPARSED),
            message=(result.get("message") or result.get("error_code") or "")[:500],
        )
    except Exception as e:
        _log.warning("verify_answer raised %s: %s", type(e).__name__, e)
        return Verdict(
            status=INCORRECT, message=f"judge error: {type(e).__name__}: {e}"
        )


def _mock_judge(lean_code: str) -> Verdict:
    """Heuristic mock - TESTS ONLY. Never called from production paths
    (judge / judge_or_score raise instead). Kept for unit-test fixtures
    that explicitly import _mock_judge."""
    if "sorry" in lean_code or "admit" in lean_code:
        return Verdict(status=INCOMPLETE_PROOF)
    has_decl = (
        "theorem" in lean_code
        or "example" in lean_code
        or "def submission" in lean_code
    )
    if not has_decl:
        return Verdict(status=MALFORMED)
    for tac in ("rfl", "decide", "trivial", "aesop", "decideFin!"):
        if tac in lean_code:
            return Verdict(status=ACCEPTED, message=f"mock accepted on {tac}")
    return Verdict(status=INCORRECT, message="mock: no obvious tactic")


ACCEPT_THRESHOLD = float(os.environ.get("LAWFORGE_JUDGE_ACCEPT", "0.85"))
MALFORMED_THRESHOLD = float(os.environ.get("LAWFORGE_JUDGE_MALFORMED", "0.1"))


def llm_judge_score(
    lean_code: str, eq1: str = "", eq2: str = "", expected_verdict: str = TRUE
) -> float:
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


def judge_or_score(
    lean_code: str,
    expected_verdict: str = TRUE,
    eq1: str = "",
    eq2: str = "",
    use_llm_fallback: bool = True,
    problem: dict | None = None,
) -> Verdict:
    """Cascaded reward: real Lean -> LLM-as-judge (RULER). No mock in
    production: when neither Lean nor `use_llm_fallback` is available, raises
    unless LAWFORGE_ALLOW_MOCK=1."""
    if _JUDGE_AVAILABLE:
        return judge(lean_code, expected_verdict, problem=problem)
    if use_llm_fallback:
        score = llm_judge_score(lean_code, eq1, eq2, expected_verdict)
        if score >= ACCEPT_THRESHOLD:
            status = ACCEPTED
        elif score < MALFORMED_THRESHOLD:
            status = MALFORMED
        else:
            status = INCORRECT
        return Verdict(status=status, message=f"llm-judge score={score:.3f}")
    if _ALLOW_MOCK:
        return _mock_judge(lean_code)
    raise RuntimeError(
        "judge_or_score: Lean unavailable and use_llm_fallback=False. "
        "Run `bash upstream/scripts/setup.sh` or set LAWFORGE_ALLOW_MOCK=1."
    )


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
