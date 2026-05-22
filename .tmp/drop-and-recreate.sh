#!/usr/bin/env bash
set -euo pipefail

export NVM_DIR="$HOME/.nvm"
# shellcheck disable=SC1091
. "$NVM_DIR/nvm.sh"
export PATH="$HOME/.local/bin:$PATH"

cd "$HOME/frappe-bench"

SITE="erpnext.localhost"
ADMIN_PASS="admin"

echo "=== dropping $SITE ==="
bench drop-site "$SITE" --root-username root --root-password "$DB_ROOT_PASS" --no-backup --force 2>&1 | tail -5 || true

echo "=== creating $SITE ==="
bench new-site "$SITE" \
  --admin-password "$ADMIN_PASS" \
  --db-root-username root \
  --db-root-password "$DB_ROOT_PASS" \
  --mariadb-user-host-login-scope='%' 2>&1 | tee /tmp/bench-new-site.log | tail -10

echo "=== installing erpnext ==="
bench --site "$SITE" install-app erpnext 2>&1 | tee /tmp/install-app.log | tail -15

echo "=== set defaults ==="
bench --site "$SITE" set-config developer_mode 1
bench use "$SITE"
bench --site "$SITE" clear-cache

echo "=== final state ==="
bench --site "$SITE" list-apps
