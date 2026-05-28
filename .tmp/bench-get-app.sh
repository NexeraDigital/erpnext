#!/usr/bin/env bash
set -euo pipefail

export NVM_DIR="$HOME/.nvm"
# shellcheck disable=SC1091
. "$NVM_DIR/nvm.sh"
export PATH="$HOME/.local/bin:$PATH"

cd "$HOME/frappe-bench"

if [ -d "apps/erpnext" ]; then
  echo "[get-app] apps/erpnext already present; verifying remote"
  git -C apps/erpnext remote -v | head -2
  git -C apps/erpnext log --oneline -3
  exit 0
fi

echo "[get-app] fetching NexeraDigital/erpnext develop branch"
bench get-app \
  --branch develop \
  --resolve-deps \
  https://github.com/NexeraDigital/erpnext erpnext 2>&1 | tee /tmp/bench-get-app.log | tail -30

echo "[get-app] DONE"
git -C apps/erpnext log --oneline -3
