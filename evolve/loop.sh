#!/usr/bin/env bash
# Karpathy outer loop with Agent57 arm selection + autoresearch.
#
# One generation:
#   1. autoresearch (every N gens) -> may add new arms to library
#   2. agent57 picks arm
#   3. arm.apply() mutates train.py / prompt / agent.py
#   4. git commit (so we can rollback)
#   5. smoke train (5 min budget)
#   6. eval on dev_split -> val_solved_rate
#   7. if improved: keep + log; else: git reset --hard + log
#   8. agent57.update(arm, reward = delta)
#
# Usage:
#   bash evolve/loop.sh smoke     # one generation, then exit
#   bash evolve/loop.sh infinite  # run until stop criteria met
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

MODE="${1:-smoke}"
DEADLINE_EPOCH=$(date -d "2026-08-25 23:59" +%s 2>/dev/null || echo 9999999999)
PLATEAU_LIMIT=10
AUTORESEARCH_EVERY=5
SMOKE_BUDGET_SEC=300
GEN_HARD_CAP_S=3600  # 1h max per generation; nothing runs longer

plateau=0
gen=0
last_progress=$(date +%s)

while true; do
  gen=$((gen + 1))
  now=$(date +%s)
  if [ "$now" -ge "$DEADLINE_EPOCH" ]; then
    echo "[loop] deadline reached, stop"
    break
  fi
  if [ "$plateau" -ge "$PLATEAU_LIMIT" ]; then
    echo "[loop] plateau ($plateau gens no-improve), stop"
    break
  fi
  if [ $((now - last_progress)) -ge 7200 ]; then
    echo "[loop] >2h since last generation completed, abort"
    break
  fi

  echo "==== gen $gen ===="

  if [ $((gen % AUTORESEARCH_EVERY)) -eq 1 ]; then
    timeout 120 python3 evolve/autoresearch.py || echo "[loop] autoresearch failed, continuing"
  fi

  # Wall-clock cap on driver: select arm -> apply -> commit -> smoke train -> eval -> keep|reset.
  timeout --kill-after=30 "$GEN_HARD_CAP_S" \
    python3 -m evolve.driver --gen "$gen" --smoke-sec "$SMOKE_BUDGET_SEC"
  rc=$?
  if [ $rc -eq 124 ] || [ $rc -eq 137 ]; then
    echo "[loop] gen $gen exceeded ${GEN_HARD_CAP_S}s — killed"
  fi
  last_progress=$(date +%s)

  improved=$(tail -1 evolve/results.tsv 2>/dev/null | awk -F'\t' '{print $5}')
  if [ "$improved" = "1" ]; then
    plateau=0
  else
    plateau=$((plateau + 1))
  fi

  if [ "$MODE" = "smoke" ]; then
    echo "[loop] smoke mode, exit after one gen"
    break
  fi
done
