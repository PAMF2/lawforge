"""Hypothesis arm library.

Each Arm.apply(repo_root) mutates one or more files in-place. The Karpathy
outer loop commits the change, smoke-trains (= calibrate), evals on dev, and
decides keep/reset.

Arms operate on:
  * solver/prompt_template.txt    -- the Lean-prompt format
  * solver/cheatsheet.md          -- worked patterns shipped to the LLM
  * solver/USE_MACE4_FIRST        -- toggle flag
  * solver/USE_CHEATSHEET         -- K examples to inject
  * solver/VERIFIER_REFINE_K      -- L5 refinement rounds
  * train.py top-level constants  -- MAX_ORDER, TEMPERATURE, etc.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from evolve.agent57 import Arm


PROMPT_BASE = """You are a Lean 4 expert in equational theories of magmas.
Decide if Equation 1 implies Equation 2. Emit a Lean certificate.
Eq1: {eq1}
Eq2: {eq2}
Cheatsheet:
{cheatsheet}
CE hint: {ce_hint}
"""

PROMPT_KIMINA = """You are a Lean 4 formal-reasoning expert.

<think>
Plan the proof. Consider both directions:
  - TRUE: find a Lean tactic chain (rfl, simp, decide, aesop, polyrith).
  - FALSE: find a small finite magma where Eq1 holds and Eq2 fails.
</think>

Eq1: {eq1}
Eq2: {eq2}

Cheatsheet:
{cheatsheet}
CE hint: {ce_hint}

Emit only the Lean 4 code.
"""

PROMPT_SUBGOAL = """You are a Lean 4 expert. To prove Eq1 implies Eq2:
1. List 3 candidate subgoals (Lean lemma signatures).
2. Prove each subgoal.
3. Compose into the final certificate.

Eq1: {eq1}
Eq2: {eq2}

Cheatsheet:
{cheatsheet}
CE hint: {ce_hint}

Emit only the Lean 4 code.
"""


def _patch_prompt(root: Path, new: str) -> None:
    (root / "solver" / "prompt_template.txt").write_text(new)


def arm_prompt_base(root: Path) -> None: _patch_prompt(root, PROMPT_BASE)
def arm_prompt_kimina(root: Path) -> None: _patch_prompt(root, PROMPT_KIMINA)
def arm_prompt_subgoal(root: Path) -> None: _patch_prompt(root, PROMPT_SUBGOAL)


def _set_hparam(root: Path, key: str, value) -> None:
    p = root / "train.py"
    src = p.read_text()
    src = re.sub(rf"^{key}\s*=\s*[^\n]+", f"{key} = {value!r}", src, count=1, flags=re.M)
    p.write_text(src)


def arm_max_order_3(root: Path) -> None: _set_hparam(root, "MAX_ORDER", 3)
def arm_max_order_5(root: Path) -> None: _set_hparam(root, "MAX_ORDER", 5)
def arm_temp_low(root: Path) -> None: _set_hparam(root, "TEMPERATURE", 0.1)
def arm_temp_med(root: Path) -> None: _set_hparam(root, "TEMPERATURE", 0.3)
def arm_temp_high(root: Path) -> None: _set_hparam(root, "TEMPERATURE", 0.8)
def arm_tokens_2k(root: Path) -> None: _set_hparam(root, "LLM_MAX_TOKENS", 2048)
def arm_tokens_8k(root: Path) -> None: _set_hparam(root, "LLM_MAX_TOKENS", 8192)
def arm_refine_1(root: Path) -> None: _set_hparam(root, "REFINE_ROUNDS", 1)
def arm_refine_5(root: Path) -> None: _set_hparam(root, "REFINE_ROUNDS", 5)


def arm_mace4_first(root: Path) -> None:
    (root / "solver" / "USE_MACE4_FIRST").write_text("1")


def arm_no_mace4_first(root: Path) -> None:
    f = root / "solver" / "USE_MACE4_FIRST"
    if f.exists():
        f.unlink()


def arm_cheatsheet_8(root: Path) -> None:
    (root / "solver" / "USE_CHEATSHEET").write_text("8")


def arm_cheatsheet_16(root: Path) -> None:
    (root / "solver" / "USE_CHEATSHEET").write_text("16")


def arm_cheatsheet_off(root: Path) -> None:
    (root / "solver" / "USE_CHEATSHEET").write_text("0")


def arm_aesop_prelude(root: Path) -> None:
    """Always prefix L3 with `intros; aesop?` attempt."""
    cs = root / "solver" / "cheatsheet.md"
    src = cs.read_text()
    block = ("\n## PATTERN: always-try-aesop-first\n\n"
             "Every TRUE proof should start with `intros; try aesop;`. If that\n"
             "fails, fall through to specific tactics.\n")
    if "always-try-aesop-first" not in src:
        cs.write_text(src + block)


# Removed arms: curriculum_easy/hard, reward_shaping_on/off — the flag files
# (CURRICULUM_TAG, REWARD_SHAPING) were written but never read, so pulling
# these arms gave zero-signal reward and poisoned the bandit.
#
# Removed: _load_autoresearch_proposals — the proposals.jsonl arms only
# appended to applied.log without mutating any pipeline file, so pulling them
# was also zero-signal. Re-add once a real code-edit agent translates
# proposals into actual patches.


CORE_ARMS = [
    ("prompt_base", arm_prompt_base),
    ("prompt_kimina", arm_prompt_kimina),
    ("prompt_subgoal", arm_prompt_subgoal),
    ("max_order_3", arm_max_order_3),
    ("max_order_5", arm_max_order_5),
    ("temp_low", arm_temp_low),
    ("temp_med", arm_temp_med),
    ("temp_high", arm_temp_high),
    ("tokens_2k", arm_tokens_2k),
    ("tokens_8k", arm_tokens_8k),
    ("refine_1", arm_refine_1),
    ("refine_5", arm_refine_5),
    ("mace4_first", arm_mace4_first),
    ("no_mace4_first", arm_no_mace4_first),
    ("cheatsheet_8", arm_cheatsheet_8),
    ("cheatsheet_16", arm_cheatsheet_16),
    ("cheatsheet_off", arm_cheatsheet_off),
    ("aesop_prelude", arm_aesop_prelude),
]


def build_arm_library(root: Path) -> list[Arm]:
    return [Arm(name=n, apply=f) for n, f in CORE_ARMS]
