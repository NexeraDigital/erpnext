#!/usr/bin/env bash
set -euo pipefail

if [ -z "${SUDO_PASS:-}" ] || [ -z "${DB_ROOT_PASS:-}" ]; then
  echo "missing env vars"; exit 2
fi

# Refresh sudo cache once for this script's process tree
echo "$SUDO_PASS" | sudo -S -p '' -v

echo "[db] current root auth:"
sudo -n mariadb -uroot -e "SELECT user,host,plugin,authentication_string FROM mysql.user WHERE user='root';"

echo "[db] testing current passwordless root via socket"
if sudo -n mariadb -uroot -e "SELECT 1" >/dev/null 2>&1; then
  echo "[db] socket login works"
else
  echo "[db] socket login DOES NOT work"
fi

echo "[db] applying ALTER USER ... IDENTIFIED BY ..."
sudo -n mariadb -uroot -e "ALTER USER 'root'@'localhost' IDENTIFIED BY '$DB_ROOT_PASS'; FLUSH PRIVILEGES;"

echo "[db] verifying password-based root login from localhost"
mariadb -uroot -p"$DB_ROOT_PASS" -h 127.0.0.1 -e "SELECT 'ok' AS status;" || {
  echo "[db] 127.0.0.1 failed, trying default host"
  mariadb -uroot -p"$DB_ROOT_PASS" -e "SELECT 'ok' AS status;"
}

echo "[db] DONE"
