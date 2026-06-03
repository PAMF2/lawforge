"""Unit tests for solver.solver L3+ layers and helpers."""

import json
from unittest.mock import patch

from solver.solver import (
    _strip_submission_wrapper,
    _wrap_true_submission,
    l1_syntactic,
    l3_variant,
    l5_refine,
)


def test_strip_canonical_wrapper():
    code = (
        "import JudgeProblem\n\n"
        "def submission : Goal := by\n"
        "  intro G _ h\n"
        "  rw [h]\n"
        "  rfl\n"
    )
    out = _strip_submission_wrapper(code)
    assert "import" not in out
    assert "def submission" not in out
    assert "intro G _ h" not in out
    assert "rw [h]" in out
    assert "rfl" in out


def test_strip_multiple_imports():
    code = (
        "import JudgeProblem\n"
        "import Mathlib\n"
        "\n"
        "def submission : Goal := by\n"
        "  intro G _ h\n"
        "  aesop\n"
    )
    out = _strip_submission_wrapper(code)
    assert "import" not in out
    assert "aesop" in out


def test_strip_idempotent_on_body_only():
    body = "intro x y\nrw [h]\nrfl\n"
    out = _strip_submission_wrapper(body)
    assert out == body


def test_strip_whitespace_noise():
    code = (
        "import JudgeProblem\n\n"
        "def  submission  :  Goal  :=  by\n"
        "  intro G _ h\n"
        "  exact h\n"
    )
    out = _strip_submission_wrapper(code)
    assert "def" not in out
    assert "exact h" in out


def test_l1_syntactic_identity():
    out = l1_syntactic("x = y", "x = y")
    assert out is not None
    assert "exact h" in out
    assert "def submission" in out


def test_l1_syntactic_whitespace_insensitive():
    out = l1_syntactic("x = y", "x=y")
    assert out is not None


def test_l1_syntactic_returns_none_on_distinct():
    assert l1_syntactic("x = y", "y = x") is None


def test_wrap_true_submission_indents_body():
    out = _wrap_true_submission("rw [h]\nrfl")
    assert "import JudgeProblem" in out
    assert "def submission : Goal := by" in out
    assert "  intro G _ h" in out
    assert "  rw [h]" in out
    assert "  rfl" in out


def _fake_proxy_response(text: str):
    def fake_call(context: dict) -> str:
        fake_call.last_context = dict(context)
        return text

    fake_call.last_context = {}
    return fake_call


def test_l3_variant_sends_diversification_context():
    fake = _fake_proxy_response("rw [h]\nrfl")
    with patch("solver.solver.call_llm_context", side_effect=fake):
        out = l3_variant("x = y", "y = x", 3, "no ce", variant_idx=2, temperature=0.7)
    assert fake.last_context["variant_idx"] == 2
    assert fake.last_context["temperature"] == 0.7
    assert fake.last_context["stage"] == "first"
    assert fake.last_context["round"] == 3
    assert "Candidate 2 of K" in fake.last_context["extra"]
    assert "def submission" in out


def test_l5_refine_structured_error_context():
    fake = _fake_proxy_response("rw [h x y z]\nrfl")
    prior = (
        "import JudgeProblem\n\ndef submission : Goal := by\n  intro G _ h\n  rw [h]\n"
    )
    err = "Submission.lean:5:2: error: Tactic `rw` failed"
    with patch("solver.solver.call_llm_context", side_effect=fake):
        out = l5_refine("x = y", "y = x", prior, err, round_=2)
    extra = fake.last_context["extra"]
    assert "<previous_attempt>" in extra
    assert "<lean_error>" in extra
    assert err in extra
    body_section = extra.split("<previous_attempt>")[1].split("</previous_attempt>")[0]
    assert "rw [h]" in body_section
    # body strip removed wrapper, no import/def/intro G inside the tag section
    assert "import JudgeProblem" not in body_section
    assert "def submission" not in body_section
    assert "intro G _ h" not in body_section
    assert fake.last_context["last_error"] == err
    assert "def submission" in out


def test_l5_refine_clips_long_error():
    fake = _fake_proxy_response("aesop")
    long_err = "ERR " * 1000
    with patch("solver.solver.call_llm_context", side_effect=fake):
        l5_refine("a = b", "b = a", "intro x\nrfl", long_err, round_=1)
    assert len(fake.last_context["last_error"]) <= 1200


def test_solver_module_loadable_without_env():
    """Importing solver.solver must not require optional env files."""
    import importlib

    import solver.solver

    importlib.reload(solver.solver)
    assert solver.solver.VARIANT_K >= 0
    assert 0 < solver.solver.VARIANT_TEMP <= 2
