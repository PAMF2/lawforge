from lean.judge import Verdict, _mock_judge, reward


def test_mock_accepts_rfl_proof():
    # Pin directly to _mock_judge: production `judge()` raises when real Lean
    # is missing (no silent fallback). Mock heuristics are exercised here.
    code = "theorem t : True := by rfl"
    v = _mock_judge(code)
    assert v.status == "accepted"


def test_mock_flags_sorry_as_incomplete():
    # Pin to _mock_judge: the heuristic flags `sorry` regardless of real judge.
    assert _mock_judge("theorem t : True := by sorry").status == "incomplete_proof"


def test_mock_flags_empty_as_malformed():
    assert _mock_judge("").status == "malformed"


def test_reward_binary():
    assert reward(Verdict(status="accepted")) == 1.0
    assert reward(Verdict(status="incorrect")) == 0.0


def test_reward_shaped():
    assert reward(Verdict(status="accepted"), shaping=True) == 1.0
    assert reward(Verdict(status="incorrect"), shaping=True) == 0.10
    assert reward(Verdict(status="incomplete_proof"), shaping=True) == 0.05
    assert reward(Verdict(status="malformed"), shaping=True) == 0.02
    assert reward(Verdict(status="unparsed"), shaping=True) == 0.0
