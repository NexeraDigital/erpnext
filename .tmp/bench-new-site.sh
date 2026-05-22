#!/usr/bin/env bash
set -euo pipefail

export NVM_DIR="$HOME/.nvm"
# shellcheck disable=SC1091
. "$NVM_DIR/nvm.sh"
export PATH="$HOME/.local/bin:$PATH"

cd "$HOME/frappe-bench"

SITE="erpnext.localhost"
ADMIN_PASS="admin"

if [ -d "sites/$SITE" ]; then
  echo "[site] $SITE already exists; skipping new-site"
else
  echo "[site] creating $SITE"
  bench new-site "$SITE" \
    --admin-password "$ADMIN_PASS" \
    --db-root-username root \
    --db-root-password "$DB_ROOT_PASS" \
    --no-mariadb-socket 2>&1 | tee /tmp/bench-new-site.log | tail -30
fi

echo "[site] installing erpnext app"
bench --site "$SITE" install-app erpnext 2>&1 | tee /tmp/bench-install-app.log | tail -30

echo "[site] enabling developer_mode + setting default site"
bench --site "$SITE" set-config developer_mode 1
bench use "$SITE"
bench --site "$SITE" clear-cache

echo "[site] DONE"
bench --site "$SITE" list-apps
