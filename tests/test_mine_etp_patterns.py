"""Unit tests for scripts.mine_etp_patterns."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "mine_etp_patterns", ROOT / "scripts" / "mine_etp_patterns.py"
)
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def test_skeleton_picks_top_tactics():
    proof = "by\n  intro x y\n  rw [h]\n  rfl\n"
    s = mod.skeleton(proof)
    assert s == ("intro", "rw", "rfl")


def test_skeleton_deduplicates_consecutive():
    proof = "by\n  intro x\n  intro y\n  intro z\n  rw [h]\n"
    s = mod.skeleton(proof)
    assert s == ("intro", "rw")


def test_skeleton_caps_at_six():
    proof = "by\n  intro\n  have\n  apply\n  rw\n  simp\n  aesop\n  rfl\n  exact\n"
    s = mod.skeleton(proof)
    assert len(s) == 6


def test_skeleton_empty_on_no_tactics():
    assert mod.skeleton("by\n  -- nothing here\n") == ()


def test_covered_in_cheatsheet_normalizes_whitespace(tmp_path, monkeypatch):
    fake_sheet = tmp_path / "sheet.md"
    fake_sheet.write_text("```lean\nrepeat intro\napply h\n```\n")
    monkeypatch.setattr(mod, "CHEATSHEET", fake_sheet)
    assert mod.covered_in_cheatsheet(("repeat", "intro", "apply"))


def test_covered_in_cheatsheet_false_when_absent(tmp_path, monkeypatch):
    fake_sheet = tmp_path / "sheet.md"
    fake_sheet.write_text("```lean\nrw [h]\n```\n")
    monkeypatch.setattr(mod, "CHEATSHEET", fake_sheet)
    assert not mod.covered_in_cheatsheet(("calc", "have", "rw"))
