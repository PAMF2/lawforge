# Plan

## Phase 0 - setup (week 1)

- Clone stage2 repo, build judge locally.
- Pull HF datasets (normal/hard1-3).
- Run baseline solver from `examples/solo/demos/baseline/`. Confirm judge accepts.
- Measure: % solved by deterministic baseline alone.

## Phase 1 - data (week 1-2)

- Mine accepted proofs from Stage 1 public submissions (if released).
- Generate synthetic Lean proofs via existing tactics (`decide`, `rfl`, `aesop`, `polyrith`).
- For FALSE pairs: brute-force finite magma counterexamples up to order 4-6.
- Build (eq_pair, lean_cert) corpus.

## Phase 2 - TRM (week 3-6)

- Tokenizer: byte-level + Lean-aware special tokens (`theorem`, `:=`, `by`, etc.).
- Arch: 2-layer transformer, ~7M params, recursive depth n=8-16.
- Train: cross-entropy on (input, latent_chain, output_cert). Reward = judge accept.
- Loss: token-level + outcome bonus (RLOO / GRPO style).

## Phase 3 - solver integration (week 7-8)

- Solo: solver subprocess loads TRM weights → emits cert → judge call.
- Marathon: triage easy problems with deterministic search first, hand hard ones to TRM.
- Cheatsheet: distill recurring proof patterns into in-file constants.

## Phase 4 - hardening (week 9-12)

- Local eval against hard1/hard2/hard3.
- Ablate recursion depth, latent dim.
- Submit weekly to leaderboard once it opens.

## Risk

- TRM never trained on formal proofs - may fail at Lean syntax. Mitigation: pretrain on mathlib4 corpus first.
- 500KB solver size limit - weights may not fit. Mitigation: quantize to int8 OR keep model server-side via proxy LLM call (use organizer LLM as backbone instead of own TRM).
- Marathon budget is global - need triage policy.

## Open questions

- Does proxy LLM allow custom model weights? (Re-read evaluation.md.) If not, TRM must run inside solver subprocess - quantize to fit 500KB.
- Judge timeout per call? Unknown.
- Allowed Lean axioms: propext, Quot.sound, Classical.choice only. Rules out heavy automation.
