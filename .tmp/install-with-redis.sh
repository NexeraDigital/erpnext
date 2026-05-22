#!/usr/bin/env bash
set -euo pipefail

export NVM_DIR="$HOME/.nvm"
# shellcheck disable=SC1091
. "$NVM_DIR/nvm.sh"
export PATH="$HOME/.local/bin:$PATH"

cd "$HOME/frappe-bench"

SITE="erpnext.localhost"
ADMIN_PASS="admin"

echo "=== starting bench redis services in background ==="
# Kill any prior bench redis just in case
pkill -f "redis-server config/redis_" 2>/dev/null || true
sleep 1
nohup redis-server config/redis_cache.conf >/tmp/redis_cache.log 2>&1 &
nohup redis-server config/redis_queue.conf >/tmp/redis_queue.log 2>&1 &
sleep 2

echo "=== verifying redis ==="
redis-cli -p 13000 ping || echo "redis_cache NOT UP"
redis-cli -p 11000 ping || echo "redis_queue NOT UP"

echo "=== dropping site db cleanly ==="
DB_NAME=$(./env/bin/python -c "import json; print(json.load(open('sites/$SITE/site_config.json'))['db_name'])" 2>/dev/null || echo "")
if [ -n "$DB_NAME" ]; then
  mariadb -uroot -p"$DB_ROOT_PASS" -e "DROP DATABASE IF EXISTS \`$DB_NAME\`; DROP USER IF EXISTS '$DB_NAME'@'%'; DROP USER IF EXISTS '$DB_NAME'@'localhost';"
fi
rm -rf "sites/$SITE"

echo "=== creating site ==="
bench new-site "$SITE" \
  --admin-password "$ADMIN_PASS" \
  --db-root-username root \
  --db-root-password "$DB_ROOT_PASS" \
  --mariadb-user-host-login-scope='%' 2>&1 | tee /tmp/bench-new-site.log | tail -8

echo "=== installing erpnext ==="
bench --site "$SITE" install-app erpnext 2>&1 | tee /tmp/install-app.log | tail -15

echo "=== developer mode + default ==="
bench --site "$SITE" set-config developer_mode 1
bench use "$SITE"
bench --site "$SITE" clear-cache

echo "=== final state ==="
bench --site "$SITE" list-apps
echo "=== redis still running ==="
pgrep -af 'redis-server config' || echo "(redis processes already stopped)"
