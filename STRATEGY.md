# Strategy

## Pivot (critical)

Stage 2 does **not** host our model weights. The organizer runs the LLM behind
a proxy; our solver calls it via stdin/stdout JSON. So fine-tuning gpt-oss-20b
on our side is **wrong** - we would never ship those weights to the evaluator.

What we **do** ship: a single `solver.py` ≤ 500 KB containing prompt template,
cheatsheet, deterministic search code, and the strategy ladder below.

What we **do** optimize via Karpathy Loop: the contents of `solver.py` and its
support files (`cheatsheet.md`, `prompt_template.txt`, flag files).

## 5-Layer Solver Ladder

For each problem the solver descends until something is `accepted`. Cheap
layers go first to spend tokens only when needed.

| L | Mechanism | Token cost | Wall-clock |
|---|-----------|------------|------------|
| **L1** | Syntactic match (Eq1 ≡ Eq2, trivial reflexivity) | 0 | <100ms |
| **L2** | Mace4-style brute-force counterexample, orders 2-5 | 0 | 1-30s |
| **L3** | LLM one-shot with cheatsheet (tactic ladder: rfl/decide/aesop/polyrith) | ~2k | 30s |
| **L4** | DeepSeek-Prover-V2-style subgoal decomposition (LLM lists 3 subgoals, proves each) | ~10k | 5min |
| **L5** | Verifier-in-loop refinement - feed Lean error back to LLM, retry K times | ~20k | rest |

Solo per-problem budget: 3600 s / 65536 tokens / 100 KB Lean.
Marathon per-run budget: `0.5 × N × Solo` shared across N problems.

## Karpathy Outer Loop

Single metric: `val_solved_rate` on `data/dev_split.jsonl`. Tiebreaker:
`val_tokens_per_solve` (lower is better).

Each generation:
1. **autoresearch** (every 5 gens) - scan arXiv, score abstracts, write
   `evolve/autoresearch/proposals.jsonl`.
2. **Agent57.select()** - UCB1-tuned + windowed mean (w=8) + novelty bonus
   over 22 core arms + dynamic autoresearch arms.
3. **arm.apply(repo_root)** - mutate `solver/`, `train.py`, flag files.
4. **git commit** "gen{N}: try arm={name}".
5. **train.py --smoke --budget-sec 300** - calibration pass: run solver
   against `train_split.jsonl` (up to budget), cache accepted proofs into
   `proofs/accepted/<hash>.lean`.
6. **eval.py --split dev --limit 50** - solver against dev_split via
   subprocess; eval harness plays both LLM proxy and Lean judge roles.
   Prints `SOLVED_RATE=<float>`.
7. **Decision**: if `Δ rate ≥ 0.5pp`, KEEP commit; else `git reset --hard
   pre_sha`.
8. **Agent57.update(arm, reward=Δ)** - bandit learns.
9. **Log** to `evolve/results.tsv` (gen, arm, before, after, kept, commit).

## Stop criteria

- Wall-clock: stop at 2026-08-25 23:59 UTC (5 days buffer before deadline).
- Plateau: 10 consecutive gens with Δ < 0.5pp.
- Compute: stop at <20 CU Colab credits.

## Hypothesis Library (22 core arms)

**Prompts:** `prompt_base`, `prompt_kimina` (`<think>` blocks), `prompt_subgoal`
(DeepSeek decomp).

**Hyperparams:** `max_order_{3,5}`, `temp_{low,med,high}` (0.1/0.3/0.8),
`tokens_{2k,8k}`, `refine_{1,5}`.

**Structural:** `mace4_first`, `no_mace4_first`, `cheatsheet_{8,16,off}`,
`aesop_prelude` (always-try-aesop pattern injection).

**Curriculum:** `curriculum_easy` (normal-difficulty problems only),
`curriculum_hard` (hard1 only).

**Reward shaping:** `reward_shaping_{on,off}` (partial credit for `incorrect`
vs `unparsed` - risk of reward hacking, monitor).

**Dynamic (autoresearch):** New arms added from arXiv proposals after manual
or LLM-driven code-edit-agent review.

## Inner-loop reward (RLVR, when training a local model in the future)

Currently inner loop is just "run solver, count accepted". If we later host
our own model (e.g. distill organizer's gpt-oss-20b into a smaller open model
for offline experimentation), reward = `judge accepted ? 1.0 : 0.0`. Optional
shaping: `incorrect → 0.10`, `incomplete_proof → 0.05`, `malformed → 0.02`,
`unparsed → 0.0`. Pure RLVR; no reward model.

## Compute budgets

- **Dev:** free T4 Colab for prototype LLM calls (gpt-oss-20b MXFP4 via
  Unsloth). Smoke generations on 20-50 problems.
- **Real:** Colab Pro A100 + Gemma-4-31B int4 for larger smoke. OpenRouter
  for gpt-oss-120B final eval distillation.
- **Per-generation cost:** ~5 min calibrate + ~3 min eval = ~8 min. At 8 hr/day
  → ~60 gens/day. Over 100 days to deadline → ~6000 potential gens. Plateau
  will cut this drastically.

## Risk register

1. **500 KB solver limit.** Mitigation: cheatsheet is text, easily fits.
   Counterex code <30 KB. Total budget plenty.
2. **No local LLM during loop.** Mitigation: `LAWFORGE_LLM_URL` env points to
   Colab vLLM endpoint OR OpenRouter. eval harness uses `_call_local()`.
3. **Mace4 brute-force at order 5 = expensive.** Mitigation: random sampling
   `MAX_SAMPLES_PER_ORDER` + `timeout_per_order=8s`. Bandit can tune via
   `max_order_{3,5}` arms.
4. **Reward hacking via shaping.** Mitigation: ablate `reward_shaping_off`
   regularly; default binary.
5. **Lean judge unavailable in CI.** Mitigation: `lean/judge.py` falls back
   to mock when `upstream/scripts/judge.sh` missing.
6. **Bandit local optimum.** Mitigation: novelty bonus + autoresearch arms
   inject exploration over time.

## Open questions

- Marathon vs Solo: ship same `solver.py` to both? Solo first; Marathon needs
  state-sharing across problems (use `marathon_llm.call_llm`).
- LLM choice at organizer side: Stage 1 used GPT-OSS-120B / Llama-3.3-70B /
  Gemma-4-31B-IT. Stage 2 TBD. Cheatsheet probably needs ablating per model.
- Cheatsheet auto-distillation: mine `proofs/accepted/` periodically and
  compress into compact patterns (Honda+ 2025 protocol). Future arm.
