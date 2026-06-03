# lawforge

Self-evolving Lean 4 prover for the SAIR Mathematics Distillation Challenge - Equational Theories, Stage 2.

Forge proofs of equational laws on magmas. Karpathy Loop outer driver + Agent57 bandit meta-controller + autoresearch arXiv scanner = open-ended evolution targeting `solved_rate` on the held-out hard split.

## Stack

- **Base LLM:** `unsloth/gpt-oss-20b` MXFP4 (free T4 Colab) → optional `google/gemma-4-31B` on Pro A100.
- **Training:** Unsloth + TRL `GRPOTrainer`. Reward = Lean judge `accepted` (1.0) else 0.0 (binary RLVR).
- **Judge:** upstream `equational-theories-lean-stage2` deterministic Lean verifier. Mock fallback for CI.
- **Meta-controller:** UCB1-tuned + windowed mean (w=8) + novelty bonus. Picks one hypothesis per generation.
- **Autoresearch:** arXiv API scanner, scores abstracts by technique vocabulary, emits arm proposals.

## Architecture

```
outer:  Karpathy Loop
        ├── read program.md + results.tsv + train.py
        ├── Agent57.select() → arm
        ├── arm.apply() mutates train.py / prompt / agent.py
        ├── git commit
        ├── smoke train (5 min)
        ├── eval on dev_split → val_solved_rate
        ├── improved? keep : git reset --hard
        └── Agent57.update(arm, reward=delta)

inner:  GRPO RLVR
        ├── rollout K=8 samples per problem
        ├── Lean judge each → reward ∈ {0.0, 1.0}
        ├── group-relative advantage
        └── policy update
```

## Layout

```
program.md          spec, stop criteria, hypothesis library
train.py            Unsloth + TRL GRPO (mutable hyperparams)
eval.py             solver harness, prints SOLVED_RATE=
evolve/
  loop.sh           Karpathy outer driver
  driver.py         one-generation runner
  agent57.py        UCB1-tuned bandit + novelty
  arms.py           hypothesis library (13 arms + dynamic)
  autoresearch.py   arXiv scanner → proposals.jsonl
solver/
  solver.py         Stage 2 Solo-track stdin/stdout entry
  prompt_template.txt
lean/
  judge.py          subprocess wrapper + mock
tests/              pytest
scripts/
  setup.sh          clone upstream + Lean toolchain
  prep_data.py      HF download + train/dev split
data/               (gitignored) HF cache, splits
proofs/             (gitignored) accepted proof cache
```

## Hypothesis library (initial 13 arms)

prompt: `base` / `kimina` (`<think>` blocks) / `subgoal` (DeepSeek-Prover-V2 style)
hyperparam: `lora_r ∈ {8,32,64}` · `temp ∈ {0.3,1.0}` · `grpo_K ∈ {4,16}`
structural: `mace4_first` · `cheatsheet_inject` · `verifier_in_loop`

Autoresearch adds new arms dynamically when arXiv abstracts score above threshold on technique vocab.

## Quickstart

```bash
git clone https://github.com/PAMF2/lawforge
cd lawforge
bash scripts/setup.sh
python scripts/prep_data.py
bash evolve/loop.sh smoke      # one generation
bash evolve/loop.sh infinite   # run until deadline / plateau
```

## Tests

```bash
pytest -q tests/
```

## Constraints (Stage 2 official)

- Solver = single `solver.py` ≤ **500 KB**.
- Lean axioms allowed: `propext`, `Quot.sound`, `Classical.choice`.
- Solver runs in isolated subprocess. LLM access only via organizer proxy.
- Solo budget: 3600s wall / 65536 tokens / 100KB Lean per call.
- Marathon budget: `0.5 × N × Solo` shared global.

Strategy: lawforge optimizes the **cheatsheet + prompt + tactic library** to ship inside `solver.py`, not the LoRA weights (which exceed 500KB).

## Dates

- Pre-reg: 2026-04-23
- Start: 2026-05-01, 12:00 UTC
- Deadline: **2026-08-31, 23:59 AoE**

## References

- DeepSeek-Prover-V2 (arXiv:2504.21801) - subgoal decomposition + RL
- Kimina-Prover Preview (arXiv:2504.11354) - `<think>` blocks + GRPO + Lean server
- Leanabell-Prover-V2 (arXiv:2507.08649) - verifier-integrated reasoning
- ETP (arXiv:2512.07087) - 22M magma implications, Lean formalization
- Honda+ "Cheat-sheet ICL" (arXiv:2509.20820) - Stage 2 inspiration
- Agent57 (arXiv:2003.13350) - meta-controller bandit
- Karpathy Loop - minimal automated-research outer driver

## License

MIT
