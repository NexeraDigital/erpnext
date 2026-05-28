#!/usr/bin/env bash
set -euo pipefail

export NVM_DIR="$HOME/.nvm"
# shellcheck disable=SC1091
. "$NVM_DIR/nvm.sh"
export PATH="$HOME/.local/bin:$PATH"

cd "$HOME/frappe-bench"
SITE="erpnext.localhost"

echo "=== current site state ==="
bench --site "$SITE" list-apps 2>&1 || true

echo "=== install-app erpnext ==="
bench --site "$SITE" install-app erpnext 2>&1 | tee /tmp/install-app.log | tail -30 || {
  echo "[!] install-app failed — see /tmp/install-app.log for full trace"
  exit 1
}

echo "=== post-install state ==="
bench --site "$SITE" list-apps
