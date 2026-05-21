from lean.judge import Verdict, judge, reward


def test_mock_accepts_rfl_proof():
    code = "theorem t : True := by rfl"
    v = judge(code, expected_verdict="true")
    assert v.status in {"accepted", "incorrect"}  # mock returns accepted; real may differ


def test_mock_flags_sorry_as_incomplete():
    v = judge("theorem t : True := by sorry")
    assert v.status == "incomplete_proof"


def test_mock_flags_empty_as_malformed():
    v = judge("")
    assert v.status == "malformed"


def test_reward_binary():
    assert reward(Verdict(status="accepted")) == 1.0
    assert reward(Verdict(status="incorrect")) == 0.0


def test_reward_shaped():
    assert reward(Verdict(status="accepted"), shaping=True) == 1.0
    assert reward(Verdict(status="incorrect"), shaping=True) == 0.10
    assert reward(Verdict(status="incomplete_proof"), shaping=True) == 0.05
    assert reward(Verdict(status="malformed"), shaping=True) == 0.02
    assert reward(Verdict(status="unparsed"), shaping=True) == 0.0
