"""Unit tests for solver.marathon prompt filler."""

import re

from solver.marathon import _fill_prompt


def test_fill_prompt_substitutes_known_keys():
    problem = {
        "id": "p001",
        "eq1_id": 42,
        "eq2_id": 7,
        "equation1": "x = y",
        "equation2": "y = x",
    }
    out = _fill_prompt(problem)
    assert "Equation42" in out
    assert "Equation7" in out
    assert "x = y" in out
    assert "y = x" in out


def test_fill_prompt_strips_unfilled_placeholders():
    out = _fill_prompt(
        {"id": "x", "equation1": "a = b", "equation2": "b = a", "eq1_id": 1, "eq2_id": 2}
    )
    assert not re.search(r"\{(problem|solver|history)\.[a-zA-Z_]+\}", out)


def test_fill_prompt_handles_missing_fields():
    out = _fill_prompt({})
    assert isinstance(out, str)
    assert len(out) > 0
