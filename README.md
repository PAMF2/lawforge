# eqt-trm

TRM-style solver for SAIR Mathematics Distillation Challenge — Equational Theories Stage 2.

## Idea

Tiny Recursive Model (Jolicoeur-Martineau 2025, arXiv:2510.04871):
- 7M params, beats LLM on ARC via recursive latent reasoning.
- Input: question + answer draft + latent state. Recurse n steps, refine latent. Emit answer.

Apply to (Eq1, Eq2) → Lean 4 certificate:
- Encode equation pair as token seq.
- Latent state z carries proof sketch.
- Recurse: z_{t+1} = f(z_t, eq_pair, draft_t); draft_{t+1} = g(z_{t+1}).
- Decode draft as Lean proof OR finite magma counterexample.
- Judge verdict (`accepted` / `incorrect` / `incomplete_proof`) = training signal.

## Structure

```
data/      raw equational_theories problems (normal, hard1-3)
model/     TRM architecture (PyTorch)
solver/    solver.py entry (Solo + Marathon tracks)
lean/      Lean 4 toolchain, deps, judge harness
scripts/   training, eval, data prep
notes/     research log
proofs/    cached accepted proofs (training data)
```

## Tracks

- **Solo**: stdin/stdout JSON, 3600s/problem, 65536 tokens/call, 100KB Lean code.
- **Marathon**: N=100 problems/run, ratio=0.5 → 50h + ~3.3M tokens shared budget.

## Dates

- Pre-reg: 2026-04-23
- Start: 2026-05-01
- Deadline: **2026-08-31 23:59 AoE**
- Now: 2026-05-21 → ~102 days

## Refs

- TRM paper: https://arxiv.org/abs/2510.04871
- Cheatsheet distillation: https://arxiv.org/abs/2509.20820
- Equational Theories Project: https://teorth.github.io/equational_theories/
- Stage 2 repo: https://github.com/SAIRcompetition/equational-theories-lean-stage2
- HF dataset: https://huggingface.co/datasets/SAIRfoundation/equational-theories-selected-problems
