"""Sanity tests for arm library: each apply() must complete without error
and leave the repo in a parseable state."""
from pathlib import Path

import pytest

from evolve.arms import CORE_ARMS, build_arm_library


@pytest.mark.parametrize("name,apply_fn", CORE_ARMS)
def test_arm_applies_cleanly(tmp_path: Path, name: str, apply_fn):
    # mirror minimal repo state
    (tmp_path / "solver").mkdir()
    (tmp_path / "solver" / "prompt_template.txt").write_text("placeholder\n")
    (tmp_path / "solver" / "cheatsheet.md").write_text("# stub\n")
    (tmp_path / "train.py").write_text(
        "MAX_ORDER = 4\nTEMPERATURE = 0.3\nLLM_MAX_TOKENS = 4096\n"
        "CHEATSHEET_K = 8\nREFINE_ROUNDS = 3\n"
    )
    apply_fn(tmp_path)
    # train.py should still be parseable
    compile((tmp_path / "train.py").read_text(), "train.py", "exec")


def test_build_arm_library(tmp_path: Path):
    arms = build_arm_library(tmp_path)
    names = {a.name for a in arms}
    assert "prompt_kimina" in names
    assert "max_order_5" in names
    assert "mace4_first" in names
    assert len(arms) >= 20
