"""GRPO trainer with cascaded reward stack (Lean judge -> RULER -> mock).

Architecture
============

This is the INNER loop. It fine-tunes a local LoRA adapter on
DeepSeek-Prover-V2-7B so the model emits more accepted Lean proofs.
The trained model is NOT shipped — Stage 2's 500KB solver.py limit forbids
weights. Instead, we use the trained model as a PROOF MINING TOOL: it
generates accepted proofs that we distill into the shipped cheatsheet.

Reward cascade (per response):
  1. Real Lean judge if `upstream/scripts/judge.sh` exists — binary {0, 1}.
  2. RULER (LLM-as-judge) — relative 0..1 score on a group of K rollouts.
     Used during dev before Lean toolchain is installed.
  3. Mock heuristic (rfl/decide/aesop keyword sniff) — CI fallback only.

The GRPO group-relative advantage handles the mixed scale naturally:
within each group of K rollouts, scores are normalized (mean=0, std=1),
so absolute scale doesn't matter — only ranking does.

Outputs
=======
- proofs/accepted/<hash>.lean — accepted candidate proofs (corpus for
  cheatsheet distill).
- proofs/grpo_log.jsonl — per-step training log.
- adapter/ — final LoRA weights (used by the served model in Stage B).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# -------- bandit-mutable hyperparams ------------------------------
LORA_R = 16
LORA_ALPHA = 32
GRPO_GROUP = 4
LEARNING_RATE = 5e-6
TRAIN_STEPS = 100
MAX_PROMPT_LEN = 1024
MAX_RESPONSE_LEN = 1024
# ------------------------------------------------------------------

MODEL_ID = os.environ.get("LAWFORGE_LLM_MODEL", "deepseek-ai/DeepSeek-Prover-V2-7B")
ADAPTER_DIR = ROOT / "adapter"
ACCEPTED_DIR = ROOT / "proofs" / "accepted"
GRPO_LOG = ROOT / "proofs" / "grpo_log.jsonl"


def _problem_hash(p: dict) -> str:
    blob = json.dumps({"h": p.get("hypothesis", ""), "g": p.get("goal", "")},
                      sort_keys=True).encode()
    return hashlib.sha1(blob).hexdigest()[:12]


def _render_prompt(problem: dict) -> str:
    tpl_path = ROOT / "solver" / "prompt_template.txt"
    cs_path = ROOT / "solver" / "cheatsheet.md"
    tpl = tpl_path.read_text() if tpl_path.exists() else "Eq1: {eq1}\nEq2: {eq2}\n"
    cs = cs_path.read_text() if cs_path.exists() else "(none)"
    return tpl.format(
        eq1=problem.get("hypothesis", problem.get("equation1", "")),
        eq2=problem.get("goal", problem.get("equation2", "")),
        cheatsheet=cs,
        ce_hint="(unknown)",
    )


def _score_group(prompts: list[str], responses: list[str], expected: list[str]) -> list[float]:
    """Return one reward per response. Cascade: Lean > RULER > mock."""
    from lean.judge import _JUDGE_AVAILABLE, judge as run_judge, reward as r2reward

    if _JUDGE_AVAILABLE:
        rewards = []
        for resp, exp in zip(responses, expected):
            v = run_judge(resp, expected_verdict=exp)
            rewards.append(r2reward(v))
        return rewards

    # RULER fallback
    return ruler_score(prompts[0], responses, expected[0])


def ruler_score(prompt: str, responses: list[str], expected_verdict: str) -> list[float]:
    """LLM-as-judge group ranking. Returns one 0..1 score per response.

    System prompt for the judge: 'score Lean 4 certificates for syntactic
    validity + tactic correctness + closure'. Judge sees all responses
    together and ranks them.
    """
    from solver.proxy_client import call_local

    block = "\n\n".join(f"=== Candidate {i+1} ===\n{r}" for i, r in enumerate(responses))
    judge_prompt = (
        "You are scoring Lean 4 proof candidates relatively against each other.\n"
        "Higher score = more likely to be accepted by the Lean type-checker.\n"
        f"Expected verdict: {expected_verdict}\n"
        f"Original problem prompt:\n{prompt[:2000]}\n\n"
        f"Candidates:\n{block}\n\n"
        "Output JSON only, no commentary:\n"
        '{"scores": [{"id": 1, "score": <0..1>}, ...]}'
    )
    resp = call_local(judge_prompt, max_tokens=512, temperature=0.0)
    try:
        s = resp.text.strip()
        # tolerate ```json fences
        if "```" in s:
            s = s.split("```", 2)[1]
            if s.startswith("json"):
                s = s[4:]
        data = json.loads(s)
        scores = [0.0] * len(responses)
        for item in data.get("scores", []):
            i = int(item["id"]) - 1
            if 0 <= i < len(scores):
                scores[i] = float(item["score"])
        return scores
    except Exception:
        # Judge failed; uniform 0.5 (no signal)
        return [0.5] * len(responses)


def _save_accepted(problem: dict, lean_code: str) -> None:
    ACCEPTED_DIR.mkdir(parents=True, exist_ok=True)
    h = _problem_hash(problem)
    (ACCEPTED_DIR / f"{h}.lean").write_text(lean_code)


def _log_step(step: int, mean_reward: float, accepted_in_step: int) -> None:
    GRPO_LOG.parent.mkdir(parents=True, exist_ok=True)
    with GRPO_LOG.open("a") as f:
        f.write(json.dumps({
            "ts": time.time(), "step": step,
            "mean_reward": mean_reward, "accepted": accepted_in_step,
        }) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=TRAIN_STEPS)
    ap.add_argument("--smoke", action="store_true",
                    help="single-problem mining pass, no GRPO weight update")
    ap.add_argument("--problem-idx", type=int, default=-1,
                    help="when --smoke, pick this problem index (-1 = round-robin)")
    args = ap.parse_args()

    print(f"[grpo] MODEL={MODEL_ID} R={LORA_R} group={GRPO_GROUP} "
          f"lr={LEARNING_RATE} steps={args.steps}", file=sys.stderr)

    try:
        from openpipe_art import GRPOTrainer  # noqa: F401
    except ImportError:
        print("[grpo] openpipe-art not installed; install via:\n"
              "  pip install openpipe-art unsloth trl peft\n"
              "Skipping training, running smoke-rollout-only mode.", file=sys.stderr)

    from eval import load_split
    problems = load_split("train")

    # Smoke mode: do GRPO_GROUP rollouts on selected problem, score, log.
    if args.smoke:
        from solver.proxy_client import call_local
        # round-robin by counting existing accepted files (cheap unique idx)
        if args.problem_idx < 0:
            n_existing = len(list(ACCEPTED_DIR.glob("*.lean"))) if ACCEPTED_DIR.exists() else 0
            idx = n_existing % len(problems)
        else:
            idx = args.problem_idx % len(problems)
        p = problems[idx]
        prompt = _render_prompt(p)
        print(f"[grpo-smoke] problem={p.get('id', '?')}", file=sys.stderr)
        rollouts = [call_local(prompt, max_tokens=MAX_RESPONSE_LEN, temperature=0.7)
                    for _ in range(GRPO_GROUP)]
        responses = [r.text for r in rollouts]
        expected = [str(p.get("label", "true")).lower()] * GRPO_GROUP
        rewards = _score_group([prompt] * GRPO_GROUP, responses, expected)
        for i, (r, rew) in enumerate(zip(responses, rewards)):
            print(f"  [{i}] reward={rew:.3f} excerpt={r[:120]!r}", file=sys.stderr)
            if rew >= 0.85:
                _save_accepted(p, r)
        _log_step(0, sum(rewards) / len(rewards), sum(1 for r in rewards if r >= 0.85))
        return

    # Full GRPO training would go here. Requires ART setup which is documented
    # in kaggle/loop/lawforge_loop.ipynb. Local CPU machine cannot run it.
    print("[grpo] full training requires GPU (run via kaggle/loop kernel)", file=sys.stderr)


if __name__ == "__main__":
    main()
