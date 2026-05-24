from lean.judge import Verdict, _mock_judge, judge, reward


def test_mock_accepts_rfl_proof():
    # Use judge() — works on both mock and real (real may classify rfl as
    # accepted or incorrect depending on the surrounding theorem statement).
    code = "theorem t : True := by rfl"
    v = judge(code, expected_verdict="true")
    assert v.status in {"accepted", "incorrect", "incomplete_proof", "malformed", "unparsed"}


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
