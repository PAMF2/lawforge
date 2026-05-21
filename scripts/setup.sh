#!/usr/bin/env bash
# eqt-trm setup
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# 1. clone stage2 official repo as upstream
if [ ! -d upstream ]; then
  git clone https://github.com/SAIRcompetition/equational-theories-lean-stage2 upstream
fi

# 2. pull HF datasets
mkdir -p data/hf
python3 -c "
from huggingface_hub import snapshot_download
snapshot_download(
  repo_id='SAIRfoundation/equational-theories-selected-problems',
  repo_type='dataset',
  local_dir='data/hf'
)
" || echo "skip HF download - install huggingface_hub first"

# 3. python env
if [ ! -d .venv ]; then
  python3.12 -m venv .venv
fi
source .venv/bin/activate
pip install --upgrade pip
pip install torch numpy huggingface_hub transformers datasets

# 4. Lean toolchain (assumes elan present)
if ! command -v lean >/dev/null; then
  curl https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -sSf | sh -s -- -y
  source "$HOME/.elan/env"
fi

# 5. build upstream judge
cd upstream
[ -f scripts/setup.sh ] && bash scripts/setup.sh
echo "setup done"
