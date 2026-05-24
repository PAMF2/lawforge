"""GRPO trainer with cascaded reward stack (Lean judge -> RULER -> mock).

Three-layer cascade defined in `lean.judge.judge_or_score`. This file just
drives K rollouts per problem and saves accepted ones.

Outputs
=======
- proofs/accepted/<hash>.lean — accepted candidate proofs (cheatsheet corpus).
- proofs/grpo_log.jsonl       — per-step training log.
"""
from __future__ import annotations

import argparse
import concurrent.futures as _cf
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from lawforge_utils import problem_hash, render_prompt  # noqa: E402

GRPO_GROUP = 4
MAX_RESPONSE_LEN = 1024
MAX_CANDIDATE_CHARS = 1200  # cap per-candidate text in RULER prompt
ROLLOUT_TEMP = 0.7
JUDGE_MAX_TOKENS = 512
ACCEPT_REWARD = 0.85       # mirror lean.judge.ACCEPT_THRESHOLD
JUDGE_FALLBACK_SCORE = 0.5

MODEL_ID = os.environ.get("LAWFORGE_LLM_MODEL", "deepseek-ai/DeepSeek-Prover-V2-7B")
ACCEPTED_DIR = ROOT / "proofs" / "accepted"
GRPO_LOG = ROOT / "proofs" / "grpo_log.jsonl"
ACCEPTED_DIR.mkdir(parents=True, exist_ok=True)
GRPO_LOG.parent.mkdir(parents=True, exist_ok=True)


def _score_group(prompt: str, responses: list[str], expected: list[str]) -> list[float]:
    """Score K rollouts. Cascade: real Lean (per-response) -> RULER (group)."""
    from lean.judge import _JUDGE_AVAILABLE, judge_or_score, reward as r2reward

    if _JUDGE_AVAILABLE:
        return [r2reward(judge_or_score(r, expected_verdict=exp, use_llm_fallback=False))
                for r, exp in zip(responses, expected)]
    return ruler_score(prompt, responses, expected[0])


def ruler_score(prompt: str, responses: list[str], expected_verdict: str) -> list[float]:
    """LLM-as-judge group ranking. Returns one 0..1 score per response."""
    from lawforge_utils import extract_json
    from solver.proxy_client import call_local

    block = "\n\n".join(
        f"=== Candidate {i+1} ===\n{r[:MAX_CANDIDATE_CHARS]}"
        for i, r in enumerate(responses)
    )
    judge_prompt = (
        "You are scoring Lean 4 proof candidates relatively against each other.\n"
        "Higher score = more likely to be accepted by the Lean type-checker.\n"
        f"Expected verdict: {expected_verdict}\n"
        f"Original problem prompt:\n{prompt[:2000]}\n\n"
        f"Candidates:\n{block}\n\n"
        "Output JSON only, no commentary:\n"
        '{"scores": [{"id": 1, "score": <0..1>}, ...]}'
    )
    resp = call_local(judge_prompt, max_tokens=JUDGE_MAX_TOKENS, temperature=0.0)
    data = extract_json(resp.text)
    if not data:
        print(f"[ruler_score] no JSON in judge output: {resp.text[:200]!r}", file=sys.stderr)
        return [JUDGE_FALLBACK_SCORE] * len(responses)
    scores = [0.0] * len(responses)
    for item in data.get("scores", []):
        try:
            i = int(item["id"]) - 1
            if 0 <= i < len(scores):
                scores[i] = max(0.0, min(1.0, float(item["score"])))
        except (KeyError, ValueError, TypeError):
            continue
    return scores


def _save_accepted(problem: dict, lean_code: str) -> None:
    (ACCEPTED_DIR / f"{problem_hash(problem)}.lean").write_text(lean_code)


def _log_step(step: int, mean_reward: float, accepted_in_step: int) -> None:
    with GRPO_LOG.open("a") as f:
        f.write(json.dumps({
            "ts": time.time(), "step": step,
            "mean_reward": mean_reward, "accepted": accepted_in_step,
        }) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true",
                    help="single-problem mining pass, no GRPO weight update")
    ap.add_argument("--problem-idx", type=int, default=-1,
                    help="when --smoke, pick this problem index (-1 = round-robin)")
    args = ap.parse_args()

    print(f"[grpo] MODEL={MODEL_ID} group={GRPO_GROUP} smoke={args.smoke}",
          file=sys.stderr)

    from eval import load_split
    problems = load_split("train")

    if not args.smoke:
        # Full GRPO requires ART; gate by import availability.
        try:
            import openpipe_art  # noqa: F401
        except ImportError:
            print("[grpo] openpipe-art not installed; full training unavailable.\n"
                  "  pip install openpipe-art unsloth trl peft", file=sys.stderr)
            return
        print("[grpo] full GRPO training loop is TODO; use --smoke for mining",
              file=sys.stderr)
        return

    from solver.proxy_client import call_local

    if args.problem_idx < 0:
        n_existing = len(list(ACCEPTED_DIR.glob("*.lean")))
        idx = n_existing % len(problems)
    else:
        idx = args.problem_idx % len(problems)
    p = problems[idx]
    prompt = render_prompt(p.get("hypothesis", p.get("equation1", "")),
                           p.get("goal", p.get("equation2", "")))
    print(f"[grpo-smoke] problem={p.get('id', '?')}", file=sys.stderr)

    with _cf.ThreadPoolExecutor(max_workers=GRPO_GROUP) as ex:
        futs = [ex.submit(call_local, prompt, MAX_RESPONSE_LEN, ROLLOUT_TEMP)
                for _ in range(GRPO_GROUP)]
        rollouts = [f.result() for f in futs]
    responses = [r.text for r in rollouts]
    expected = [str(p.get("label", "true")).lower()] * GRPO_GROUP
    rewards = _score_group(prompt, responses, expected)

    accepted = 0
    for i, (r, rew) in enumerate(zip(responses, rewards)):
        print(f"  [{i}] reward={rew:.3f} excerpt={r[:120]!r}", file=sys.stderr)
        if rew >= ACCEPT_REWARD:
            _save_accepted(p, r)
            accepted += 1
    _log_step(0, sum(rewards) / len(rewards), accepted)


if __name__ == "__main__":
    main()
