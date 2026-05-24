"""Per-generation LLM autoresearch: inspect recent results + ask local LLM
for ONE concrete patch to prompt_template or cheatsheet. Persist as a
dynamic arm JSON the bandit can sample on the next gen.

Inputs read:
  - evolve/results.tsv (last 5 rows)
  - solver/prompt_template.txt
  - solver/cheatsheet.md (head)
  - proofs/grpo_log.jsonl (tail, if exists)

Output written:
  evolve/dynamic_arms/g<gen>.json
    {"name": "...", "file": "solver/prompt_template.txt|solver/cheatsheet.md",
     "op": "append|prepend|replace", "payload": "..."}
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "evolve" / "results.tsv"
PROMPT = ROOT / "solver" / "prompt_template.txt"
CHEATSHEET = ROOT / "solver" / "cheatsheet.md"
GRPO_LOG = ROOT / "proofs" / "grpo_log.jsonl"
DYN_DIR = ROOT / "evolve" / "dynamic_arms"
LLM_URL = os.environ.get("LAWFORGE_LLM_URL", "http://127.0.0.1:8000/v1/chat/completions")
LLM_MODEL = os.environ.get("LAWFORGE_LLM_MODEL", "deepseek-ai/DeepSeek-Prover-V2-7B")
LLM_KEY = os.environ.get("LAWFORGE_LLM_KEY", "no-key")
TIMEOUT = int(os.environ.get("LAWFORGE_LLM_TIMEOUT", "60"))

ALLOWED_FILES = {"solver/prompt_template.txt", "solver/cheatsheet.md"}
ALLOWED_OPS = {"append", "prepend", "replace"}
MAX_PAYLOAD = 2000


def _tail(path: Path, n: int = 5) -> list[str]:
    if not path.exists():
        return []
    return path.read_text().splitlines()[-n:]


def _head(path: Path, n_chars: int = 1500) -> str:
    return path.read_text()[:n_chars] if path.exists() else ""


def _build_prompt(gen: int) -> str:
    recent = "\n".join(_tail(RESULTS, 5)) or "(no prior gens)"
    grpo_tail = "\n".join(_tail(GRPO_LOG, 5)) or "(no grpo log)"
    return f"""You are a code-mutation agent for a Lean 4 proof loop.

Goal: increase `solved_rate` on the SAIR Stage 2 dev set. The solver emits
a tactic body that the harness wraps as `def submission : Goal := by
intro G _ h\\n  <body>`. The upstream judge compiles and checks it.

Magma operator is `◇` (NOT `*`). Allowed axioms only: propext, Quot.sound,
Classical.choice. Forbidden: sorry, admit, import, theorem, def submission.

Recent generations (gen,arm,before,after,kept,sha):
{recent}

Recent rollout stats:
{grpo_tail}

Current solver/prompt_template.txt:
---
{_head(PROMPT, 1200)}
---

Current solver/cheatsheet.md (head):
---
{_head(CHEATSHEET, 1500)}
---

Propose ONE concrete mutation. Output strict JSON only, no commentary:

{{"name": "<short_kebab_id>",
  "file": "solver/prompt_template.txt" | "solver/cheatsheet.md",
  "op": "append" | "prepend" | "replace",
  "payload": "<Lean-only snippet or prompt-rule text; <= {MAX_PAYLOAD} chars>"}}

Constraints:
- file in {sorted(ALLOWED_FILES)}.
- op in {sorted(ALLOWED_OPS)}; replace only if current content clearly broken.
- payload: if file=cheatsheet.md, ONE Lean tactic-body snippet inside a ```lean
  fence (NO `theorem`, NO `import`, NO `def submission` header — just the body).
  if file=prompt_template.txt, terse English rules (no Lean code).
- prefer append. Be minimal. One mutation.
"""


def _call_llm(prompt: str) -> str:
    body = json.dumps({
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 600,
        "temperature": 0.7,
    }).encode()
    req = urllib.request.Request(
        LLM_URL, data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {LLM_KEY}"},
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        data = json.loads(r.read())
    return data["choices"][0]["message"]["content"]


def _extract_json(text: str) -> dict | None:
    """First top-level {...} block. Tolerates fences and trailing prose."""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i, c in enumerate(text[start:], start):
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _validate(proposal: dict) -> tuple[bool, str]:
    if not isinstance(proposal, dict):
        return False, "not a dict"
    for k in ("name", "file", "op", "payload"):
        if k not in proposal:
            return False, f"missing key: {k}"
    if proposal["file"] not in ALLOWED_FILES:
        return False, f"file not allowed: {proposal['file']}"
    if proposal["op"] not in ALLOWED_OPS:
        return False, f"op not allowed: {proposal['op']}"
    payload = proposal["payload"]
    if not isinstance(payload, str) or not payload.strip():
        return False, "empty payload"
    if len(payload) > MAX_PAYLOAD:
        return False, f"payload too long ({len(payload)} > {MAX_PAYLOAD})"
    name = proposal["name"]
    if not isinstance(name, str) or not name.strip():
        return False, "missing name"
    return True, ""


def run(gen: int) -> int:
    DYN_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DYN_DIR / f"g{gen:04d}.json"
    if out_path.exists():
        print(f"[autoresearch_llm] gen{gen} already proposed -> {out_path.name}",
              file=sys.stderr)
        return 0
    try:
        raw = _call_llm(_build_prompt(gen))
    except Exception as e:
        print(f"[autoresearch_llm] LLM call failed: {e}", file=sys.stderr)
        return 1
    proposal = _extract_json(raw)
    if proposal is None:
        print(f"[autoresearch_llm] no JSON in response: {raw[:300]!r}", file=sys.stderr)
        return 1
    ok, why = _validate(proposal)
    if not ok:
        print(f"[autoresearch_llm] invalid proposal ({why}): {proposal}", file=sys.stderr)
        return 1
    proposal["gen"] = gen
    out_path.write_text(json.dumps(proposal, indent=2))
    print(f"[autoresearch_llm] gen{gen} arm={proposal['name']} "
          f"file={proposal['file']} op={proposal['op']} "
          f"payload_len={len(proposal['payload'])}",
          file=sys.stderr)
    return 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gen", type=int, required=True)
    args = ap.parse_args()
    sys.exit(run(args.gen))


if __name__ == "__main__":
    main()
