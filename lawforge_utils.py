"""Shared helpers used across train, train_grpo, eval, scripts."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def problem_hash(p: dict) -> str:
    blob = json.dumps({"h": p.get("hypothesis", ""), "g": p.get("goal", "")},
                      sort_keys=True).encode()
    return hashlib.sha1(blob).hexdigest()[:12]


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, "1" if default else "0").lower() in {"1", "true", "yes", "on"}


_JSON_OBJ_RE = re.compile(r'\{(?:[^{}]|"(?:\\.|[^"\\])*")*\}', re.DOTALL)


def extract_json(s: str) -> dict | None:
    """Robustly pull the first {...} JSON object out of LLM output.
    Tolerates ```json fences, prose preambles, trailing chatter."""
    if not s:
        return None
    m = _JSON_OBJ_RE.search(s)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def render_prompt(eq1: str, eq2: str, *, ce_hint: str = "(unknown)") -> str:
    """Cache template + cheatsheet at module load; re-format per call."""
    return _PROMPT_TPL.format(eq1=eq1, eq2=eq2,
                              cheatsheet=_CHEATSHEET, ce_hint=ce_hint)


_PROMPT_TPL_PATH = ROOT / "solver" / "prompt_template.txt"
_CHEATSHEET_PATH = ROOT / "solver" / "cheatsheet.md"
_PROMPT_TPL = (_PROMPT_TPL_PATH.read_text()
               if _PROMPT_TPL_PATH.exists() else "Eq1: {eq1}\nEq2: {eq2}\n{cheatsheet}{ce_hint}")
_CHEATSHEET = (_CHEATSHEET_PATH.read_text() if _CHEATSHEET_PATH.exists() else "(none)")
