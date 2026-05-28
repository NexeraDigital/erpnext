#!/usr/bin/env bash
set -euo pipefail
cd "$HOME"

# Load nvm + PATH for the bench binary
export NVM_DIR="$HOME/.nvm"
# shellcheck disable=SC1091
. "$NVM_DIR/nvm.sh"
export PATH="$HOME/.local/bin:$PATH"

echo "[init] node=$(node --version) bench=$(bench --version) python=$(python3.14 --version)"

if [ -d "$HOME/frappe-bench" ]; then
  echo "[init] $HOME/frappe-bench already exists; skipping bench init"
  exit 0
fi

echo "[init] running bench init (this can take 5-15 min)"
bench init \
  --frappe-branch version-16 \
  --python python3.14 \
  --verbose \
  frappe-bench 2>&1 | tee /tmp/bench-init.log | tail -60

echo "[init] DONE"
ls -la "$HOME/frappe-bench" | head -20
