#!/usr/bin/env bash
# lawforge preflight: validate full pipeline before unleashing the loop.
#
# Exits 0 = green; non-zero = red. Each check prints PASS/FAIL/SKIP with reason.

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

fail=0
pass=0
skip=0

check() {
  local name="$1"; shift
  if "$@" >/dev/null 2>&1; then
    printf "  PASS  %s\n" "$name"
    pass=$((pass + 1))
  else
    printf "  FAIL  %s\n" "$name"
    fail=$((fail + 1))
  fi
}

note() {
  printf "  SKIP  %s\n" "$1"
  skip=$((skip + 1))
}

echo "=== lawforge preflight ==="

echo "[1/7] python + deps"
check "python3.10+" python3 -c "import sys; assert sys.version_info >= (3,10)"
check "pytest"      python3 -c "import pytest"
check "datasets"    python3 -c "import datasets"
check "hf hub"      python3 -c "import huggingface_hub"

echo "[2/7] repo state"
check "git repo"    git rev-parse --git-dir
check "no uncommitted .py" bash -c '[ -z "$(git status --porcelain | grep -E "\\.py$" || true)" ]'

echo "[3/7] data"
if [ -f data/dev_split.jsonl ] && [ "$(wc -l < data/dev_split.jsonl)" -ge 100 ]; then
  printf "  PASS  dev_split.jsonl (%s rows)\n" "$(wc -l < data/dev_split.jsonl)"
  pass=$((pass + 1))
else
  printf "  FAIL  dev_split.jsonl missing or <100 rows. Run: python3 scripts/prep_data.py\n"
  fail=$((fail + 1))
fi
if [ -f data/train_split.jsonl ] && [ "$(wc -l < data/train_split.jsonl)" -ge 100 ]; then
  printf "  PASS  train_split.jsonl (%s rows)\n" "$(wc -l < data/train_split.jsonl)"
  pass=$((pass + 1))
else
  printf "  FAIL  train_split.jsonl missing or <100 rows\n"
  fail=$((fail + 1))
fi

echo "[4/7] tests"
if python3 -m pytest -q tests/ >/tmp/lawforge_pytest.log 2>&1; then
  n=$(grep -oE "[0-9]+ passed" /tmp/lawforge_pytest.log | head -1)
  printf "  PASS  pytest (%s)\n" "$n"
  pass=$((pass + 1))
else
  printf "  FAIL  pytest — see /tmp/lawforge_pytest.log\n"
  tail -15 /tmp/lawforge_pytest.log | sed 's/^/        /'
  fail=$((fail + 1))
fi

echo "[5/7] solver smoke (no LLM, mock judge)"
if LAWFORGE_LLM_URL=http://localhost:1 \
   timeout 60 python3 -m eval --split dev --limit 5 --timeout 10 \
   >/tmp/lawforge_eval.log 2>&1; then
  rate=$(grep "^SOLVED_RATE=" /tmp/lawforge_eval.log | cut -d= -f2)
  printf "  PASS  eval ran (rate=%s; ok to be 0 without LLM)\n" "$rate"
  pass=$((pass + 1))
else
  printf "  FAIL  eval crashed — see /tmp/lawforge_eval.log\n"
  tail -10 /tmp/lawforge_eval.log | sed 's/^/        /'
  fail=$((fail + 1))
fi

echo "[6/7] LLM endpoint"
if [ -n "${LAWFORGE_LLM_URL:-}" ]; then
  if curl -s -o /dev/null -w '%{http_code}' --max-time 5 \
     "${LAWFORGE_LLM_URL%/v1/chat/completions}/v1/models" | grep -qE '^(200|404)$'; then
    printf "  PASS  LAWFORGE_LLM_URL reachable\n"
    pass=$((pass + 1))
  else
    printf "  FAIL  LAWFORGE_LLM_URL set but unreachable\n"
    fail=$((fail + 1))
  fi
else
  note "LAWFORGE_LLM_URL not set — loop will fall through L3-L5 silently"
fi

echo "[7/7] Lean judge"
if [ -x upstream/scripts/judge.sh ]; then
  printf "  PASS  upstream Lean judge found\n"
  pass=$((pass + 1))
else
  note "upstream/scripts/judge.sh missing — using mock (run: bash scripts/setup.sh)"
fi

echo "---"
printf "summary: PASS=%d FAIL=%d SKIP=%d\n" "$pass" "$fail" "$skip"
exit "$fail"
