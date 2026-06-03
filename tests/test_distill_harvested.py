"""Unit tests for scripts.distill_harvested filters."""

from scripts.distill_harvested import _is_plausible_body


def test_accepts_simple_body():
    assert _is_plausible_body("intro x y\nrw [h]")


def test_rejects_empty():
    assert not _is_plausible_body("")


def test_rejects_sorry():
    assert not _is_plausible_body("sorry")


def test_rejects_mathlib_namespace_ref():
    assert not _is_plausible_body("intro x\nrw [Mathlib.Tactic.foo]")
    assert not _is_plausible_body("intro x\napply Nat.succ_eq_succ_iff")
    assert not _is_plausible_body("intro x\nexact Real.exp_pos x")


def test_rejects_mathlib_tactic():
    assert not _is_plausible_body("intro x y z\nlinarith")
    assert not _is_plausible_body("intro x\nnorm_num")
    assert not _is_plausible_body("intro x\nring")
    assert not _is_plausible_body("intro x\npolyrith")


def test_accepts_basic_tactic_chain():
    assert _is_plausible_body("intro x y z\nhave h1 := h x y z\nrw [h1]")
    assert _is_plausible_body("repeat intro\napply h")
    assert _is_plausible_body("aesop")


def test_rejects_no_tactic_keyword():
    assert not _is_plausible_body("just some text")
    assert not _is_plausible_body("// comment only")
