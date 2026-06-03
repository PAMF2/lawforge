# lawforge-harvest

AlphaProof-style expert iteration: bigger LLM (Kimina-Prover-RL-1.7B) runs
offline on the train + dev + hard splits, accepted proofs distill into
solver/cheatsheet.md for the SAIR-runtime LLM to imitate.

## Files

- `lawforge_harvest.ipynb` - Kaggle T4 notebook. Loads Kimina via vLLM,
  samples pass@K with the official Qwen3 chat template, writes raw
  candidates to `/kaggle/working/harvested.jsonl`.
- `kernel-metadata.json` - kaggle CLI kernel spec.
- `inputs/{train,dev,hard2,hard3}_split.jsonl` - problem manifests.

## Pipeline

1. Launch Kaggle kernel:
   ```bash
   cd kaggle/harvest && kaggle kernels push
   ```
   ETA ~6-8h at K=32 batch=8. Override knobs via env: `LAWFORGE_HARVEST_K`,
   `_TEMP`, `_TOP_P`, `_MAX_TOKENS`, `_BATCH`, `_DTYPE`.

2. Download artifact:
   ```bash
   kaggle kernels output pedroafonso2/lawforge-harvest -p .
   ```

3. Install upstream Lean judge (one-time, ~30min):
   ```bash
   bash scripts/setup.sh
   ```
   Pulls SAIRcompetition/equational-theories-lean-stage2, installs elan,
   builds judge modules. Required because mock judge has false positives.

4. Distill:
   ```bash
   python3 -m scripts.distill_harvested --in harvested.jsonl
   ```
   Parallelizes across CPU cores via `multiprocessing.Pool`. Drops
   candidates that reference Mathlib-only identifiers (Nat./Real./Mathlib./
   linarith/ring/etc) since SAIR sandbox is sympy-only. Prints PATTERN
   block candidates for novel skeletons.

   Quick iteration without Lean install:
   ```bash
   python3 -m scripts.distill_harvested --in harvested.jsonl --allow-mock
   ```
   Mock is heuristic-only, expect false positives.

5. Manual curation: paste strongest novel PATTERN blocks into
   `solver/cheatsheet.md` (current 4654 / 10240 bytes, ~5500 bytes free).

6. Smoke + ship:
   ```bash
   python3 -m pytest tests/
   python3 -m eval_harness --split dev --limit 20
   git add solver/cheatsheet.md && git commit && git push
   ```
