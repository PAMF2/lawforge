"""Hypothesis arm library.

Each Arm.apply(repo_root) mutates one or more files in-place. The Karpathy
outer loop commits the change, smoke-trains, evals, and decides keep/reset.

Add new arms (or have autoresearch propose them via proposals.jsonl).
"""
from __future__ import annotations

import json
import random
import re
from pathlib import Path

from evolve.agent57 import Arm


# -------- prompt-template arms --------

def _patch_prompt(root: Path, new_prompt: str) -> None:
    p = root / "solver" / "prompt_template.txt"
    p.write_text(new_prompt)


PROMPT_BASE = """You are a Lean 4 expert in equational theories of magmas.
Decide if Equation 1 implies Equation 2. Emit a Lean certificate.
Eq1: {eq1}
Eq2: {eq2}
"""

PROMPT_KIMINA = """<think>
Plan the proof. Consider both true (find Lean tactic) and false (find finite magma counterexample).
</think>
You are a Lean 4 expert. Decide if Eq1 implies Eq2 and emit certificate.
Eq1: {eq1}
Eq2: {eq2}
"""

PROMPT_SUBGOAL = """You are a Lean 4 expert. Decide Eq1 -> Eq2 by:
1. List 3 candidate subgoals.
2. Prove each.
3. Compose into the final certificate.
Eq1: {eq1}
Eq2: {eq2}
"""


def arm_prompt_kimina(root: Path) -> None:
    _patch_prompt(root, PROMPT_KIMINA)


def arm_prompt_subgoal(root: Path) -> None:
    _patch_prompt(root, PROMPT_SUBGOAL)


def arm_prompt_base(root: Path) -> None:
    _patch_prompt(root, PROMPT_BASE)


# -------- hyperparam arms (edit train.py) --------

def _set_hparam(root: Path, key: str, value):
    p = root / "train.py"
    src = p.read_text()
    src = re.sub(rf"{key}\s*=\s*[^\n]+", f"{key} = {value!r}", src)
    p.write_text(src)


def arm_lora_r8(root: Path) -> None:
    _set_hparam(root, "LORA_R", 8)


def arm_lora_r32(root: Path) -> None:
    _set_hparam(root, "LORA_R", 32)


def arm_lora_r64(root: Path) -> None:
    _set_hparam(root, "LORA_R", 64)


def arm_temp_low(root: Path) -> None:
    _set_hparam(root, "TEMPERATURE", 0.3)


def arm_temp_high(root: Path) -> None:
    _set_hparam(root, "TEMPERATURE", 1.0)


def arm_rollouts_4(root: Path) -> None:
    _set_hparam(root, "GRPO_K", 4)


def arm_rollouts_16(root: Path) -> None:
    _set_hparam(root, "GRPO_K", 16)


# -------- structural arms --------

def arm_mace4_first(root: Path) -> None:
    """Try Mace4 finite-model search (orders 2-4) before LLM."""
    flag = root / "solver" / "USE_MACE4_FIRST"
    flag.write_text("1")


def arm_cheatsheet_inject(root: Path) -> None:
    """Prepend top-K accepted proofs as in-context examples."""
    flag = root / "solver" / "USE_CHEATSHEET"
    flag.write_text("8")  # K=8 examples


def arm_verifier_in_loop(root: Path) -> None:
    """Feed Lean error message back as extra context for K refinement rounds."""
    flag = root / "solver" / "VERIFIER_REFINE_K"
    flag.write_text("3")


# -------- autoresearch-proposed arms (loaded dynamically) --------

def _load_autoresearch_proposals(root: Path) -> list[Arm]:
    path = root / "evolve" / "autoresearch" / "proposals.jsonl"
    if not path.exists():
        return []
    arms = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        prop = json.loads(line)
        name = prop["suggested_arm_name"]
        # placeholder apply: just log; human inspects proposal and implements
        def make(prop=prop):
            def apply(root: Path) -> None:
                log = root / "evolve" / "autoresearch" / "applied.log"
                log.parent.mkdir(parents=True, exist_ok=True)
                with log.open("a") as f:
                    f.write(json.dumps(prop) + "\n")
                # NOTE: real implementation would translate prop -> code patch
                # via a more capable code-edit agent. For v0 this is a no-op
                # so the bandit treats it as a low-reward arm and prunes.
            return apply
        arms.append(Arm(name=name, apply=make()))
    return arms


# -------- assembly --------

CORE_ARMS = [
    ("prompt_base", arm_prompt_base),
    ("prompt_kimina", arm_prompt_kimina),
    ("prompt_subgoal", arm_prompt_subgoal),
    ("lora_r8", arm_lora_r8),
    ("lora_r32", arm_lora_r32),
    ("lora_r64", arm_lora_r64),
    ("temp_low", arm_temp_low),
    ("temp_high", arm_temp_high),
    ("rollouts_4", arm_rollouts_4),
    ("rollouts_16", arm_rollouts_16),
    ("mace4_first", arm_mace4_first),
    ("cheatsheet_inject", arm_cheatsheet_inject),
    ("verifier_in_loop", arm_verifier_in_loop),
]


def build_arm_library(root: Path) -> list[Arm]:
    arms = [Arm(name=n, apply=f) for n, f in CORE_ARMS]
    arms.extend(_load_autoresearch_proposals(root))
    return arms
