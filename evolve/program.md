# eqt-trm self-prove-and-evolve program

## Goal

Maximize `solved_count / total` on held-out hard1+hard2 dev subset of SAIR Stage 2 equational theories problems. A problem counts as solved when the Lean judge returns `accepted` on the emitted certificate.

## Single metric

`val_solved_rate = solved / total` on `data/dev_split.json` (200 problems, balanced TRUE/FALSE).

Tiebreaker (when delta < 0.5pp): `val_tokens_per_solve` (lower is better).

## Inner loop (RLVR)

- Base model: `unsloth/gpt-oss-20b` MXFP4, QLoRA rank 32.
- For each problem: rollout K=8 with temperature 0.7, judge each, reward = 1.0 if accepted else 0.0.
- GRPO update on group advantage.
- One epoch = 256 problems.

## Outer loop (Karpathy)

- Each generation: agent reads this file + `results.tsv` + last `train.py` diff.
- Proposes ONE hypothesis (see library below).
- Modifies `train.py` (and/or `agent.py`, prompt template).
- Runs `loop.sh smoke` = 5 min of training on a 100-problem mini batch.
- Evaluates on dev_split (200 problems), 1 sample/problem, greedy.
- If `val_solved_rate` improves >= 0.5pp: `git commit`, advance.
- Else: `git reset --hard HEAD`, log failed hypothesis.

## Hypothesis library (autoresearch can pick from these or invent new)

1. **Prompt template** — change Lean preamble, add hints, switch to Kimina-style `<think>` blocks.
2. **Subgoal decomposition** — DeepSeek-Prover-V2-style: ask model to list subgoals first, then prove each.
3. **Counterexample search budget** — split LLM time: 50% try TRUE proof / 50% Mace4 brute-force order 2-4 magmas.
4. **Reward shaping** — partial credit for `incorrect` (proof compiles, just wrong) vs `unparsed` (worse).
5. **Tactic injection** — preface every proof attempt with `decide` / `polyrith` / `aesop` heuristic call.
6. **Cheatsheet ICL** — distill K accepted proofs into 4KB compact summary, prepend to prompt.
7. **LoRA rank** — sweep r in {8, 16, 32, 64}.
8. **Sampling** — temperature schedule, top-p, top-k.
9. **Curriculum** — start on normal/, advance to hard1/hard2/hard3 as accuracy crosses threshold.
10. **Verifier-in-the-loop** — every K rollouts, compile and feed Lean error message back as extra context (PROOF-VERIFIER pattern).

## Stop criteria

- Wall-clock: stop at 2026-08-25 23:59 UTC (5 days buffer before deadline).
- Plateau: 10 consecutive generations without >= 0.5pp improvement.
- Compute: stop if Colab credits < 20 CU remaining.

## Constraints

- Solver final binary <= 500 KB (Stage 2 hard limit). Approach: distill final LoRA weights into prompt cheatsheet rather than ship LoRA weights.
- Lean axioms allowed: `propext`, `Quot.sound`, `Classical.choice`. No `sorry`/`admit`.
- Solver runs in isolated subprocess, no inherited env, LLM only via organizer proxy.

## Refs (consulted)

- DeepSeek-Prover-V2 (arXiv:2504.21801) — subgoal decomp + RL.
- Kimina-Prover Preview (arXiv:2504.11354) — `<think>` blocks + GRPO + Lean server.
- Leanabell-Prover-V2 (arXiv:2507.08649) — verifier-integrated reasoning.
- ETP paper (arXiv:2512.07087) — domain: 22M magma implications.
- Mace4 (LADR-2026) — finite counterexample search.
- Cheat-sheet ICL (arXiv:2509.20820) — Stage 2 inspiration.
- PROOF-VERIFIER (OpenReview) — refine via Lean error feedback.
- RLVR + GRPO post-training (llm-stats.com 2026 review).
