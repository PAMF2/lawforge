"""Inner-loop GRPO training stub. Unsloth gpt-oss-20b + Lean judge reward.

This is the file the Karpathy loop mutates. Keep top-level constants (LORA_R,
TEMPERATURE, GRPO_K, etc.) as bare assignments so arms.py can rewrite them
via regex.

Run: python -m train --smoke --budget-sec 300
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

# --- hyperparams (mutated by arms.py) ---
MODEL_ID = 'unsloth/gpt-oss-20b'
LORA_R = 32
LORA_ALPHA = 32
TEMPERATURE = 0.7
GRPO_K = 8
MAX_SEQ_LEN = 4096
LR = 2e-5
# ----------------------------------------


def build_model():
    from unsloth import FastLanguageModel  # type: ignore

    m, tok = FastLanguageModel.from_pretrained(
        MODEL_ID, max_seq_length=MAX_SEQ_LEN, load_in_4bit=True
    )
    m = FastLanguageModel.get_peft_model(
        m, r=LORA_R, lora_alpha=LORA_ALPHA,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
    )
    return m, tok


def judge_reward(lean_code: str, problem: dict) -> float:
    """Call local Lean judge subprocess. Return 1.0 if accepted else 0.0.

    Stub for now: real version pipes to `pipeline.runner` from upstream stage2.
    """
    # TODO: subprocess.run(["lean", "..."]) and parse verdict
    return 0.0


def grpo_step(model, tok, problem: dict) -> float:
    """One GRPO rollout group + reward + update.

    Stub: spec only. Real version follows Unsloth GRPO trainer recipe.
    """
    prompts = [render_prompt(problem)] * GRPO_K
    # outs = model.generate(... temperature=TEMPERATURE)
    # rewards = [judge_reward(o, problem) for o in outs]
    # advantages = rewards - mean(rewards)  # group-relative
    # backward(...)
    return 0.0


def render_prompt(problem: dict) -> str:
    tpl_path = Path("solver/prompt_template.txt")
    tpl = tpl_path.read_text() if tpl_path.exists() else "Eq1: {eq1}\nEq2: {eq2}\n"
    return tpl.format(eq1=problem["hypothesis"], eq2=problem["goal"])


def load_train_split() -> list[dict]:
    path = Path("data/train_split.json")
    if not path.exists():
        return [{"hypothesis": "x = x", "goal": "x = x"}]  # smoke stub
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--budget-sec", type=int, default=300)
    args = ap.parse_args()

    print(f"[train] MODEL_ID={MODEL_ID} LORA_R={LORA_R} TEMP={TEMPERATURE} K={GRPO_K}")
    t0 = time.time()
    step = 0
    # m, tok = build_model()  # uncomment when Unsloth env ready
    problems = load_train_split()
    while time.time() - t0 < args.budget_sec:
        prob = problems[step % len(problems)]
        # _ = grpo_step(m, tok, prob)
        step += 1
        if step % 10 == 0:
            print(f"[train] step={step} elapsed={time.time()-t0:.0f}s")
        if args.smoke and step >= 50:
            break
    print(f"[train] done. steps={step}")


if __name__ == "__main__":
    import json  # local; only needed in main
    main()
