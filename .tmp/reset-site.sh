#!/usr/bin/env bash
set -euo pipefail

export NVM_DIR="$HOME/.nvm"
# shellcheck disable=SC1091
. "$NVM_DIR/nvm.sh"
export PATH="$HOME/.local/bin:$PATH"

cd "$HOME/frappe-bench"

SITE="erpnext.localhost"
ADMIN_PASS="admin"

echo "=== identifying site db ==="
DB_NAME=$(./env/bin/python -c "import json; print(json.load(open('sites/$SITE/site_config.json'))['db_name'])" 2>/dev/null || echo "")
DB_USER=$(./env/bin/python -c "import json; print(json.load(open('sites/$SITE/site_config.json')).get('db_user',''))" 2>/dev/null || echo "")
echo "db_name=$DB_NAME db_user=$DB_USER"

echo "=== dropping database + user directly via MariaDB ==="
if [ -n "$DB_NAME" ]; then
  mariadb -uroot -p"$DB_ROOT_PASS" -e "DROP DATABASE IF EXISTS \`$DB_NAME\`;"
fi
if [ -n "$DB_USER" ] && [ "$DB_USER" != "$DB_NAME" ]; then
  mariadb -uroot -p"$DB_ROOT_PASS" -e "DROP USER IF EXISTS '$DB_USER'@'%'; DROP USER IF EXISTS '$DB_USER'@'localhost';"
fi
if [ -n "$DB_NAME" ]; then
  mariadb -uroot -p"$DB_ROOT_PASS" -e "DROP USER IF EXISTS '$DB_NAME'@'%'; DROP USER IF EXISTS '$DB_NAME'@'localhost';"
fi

echo "=== removing sites/$SITE directory ==="
rm -rf "sites/$SITE"

echo "=== creating $SITE ==="
bench new-site "$SITE" \
  --admin-password "$ADMIN_PASS" \
  --db-root-username root \
  --db-root-password "$DB_ROOT_PASS" \
  --mariadb-user-host-login-scope='%' 2>&1 | tee /tmp/bench-new-site.log | tail -8

echo "=== installing erpnext ==="
bench --site "$SITE" install-app erpnext 2>&1 | tee /tmp/install-app.log | tail -15

echo "=== set defaults ==="
bench --site "$SITE" set-config developer_mode 1
bench use "$SITE"
bench --site "$SITE" clear-cache

echo "=== final state ==="
bench --site "$SITE" list-apps
