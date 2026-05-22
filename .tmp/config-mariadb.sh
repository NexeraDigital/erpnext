#!/usr/bin/env bash
set -euo pipefail

# Requires: SUDO_PASS env var (propagated via WSLENV)
# Requires: DB_ROOT_PASS env var (the password to set for MariaDB root)

if [ -z "${SUDO_PASS:-}" ]; then
  echo "[db] ERROR: SUDO_PASS not set"; exit 2
fi
if [ -z "${DB_ROOT_PASS:-}" ]; then
  echo "[db] ERROR: DB_ROOT_PASS not set"; exit 2
fi

sudoo() { echo "$SUDO_PASS" | sudo -S "$@" 2>/dev/null; }
sudoo_v() { echo "$SUDO_PASS" | sudo -S -p '' "$@"; }

CNF=/etc/mysql/mariadb.conf.d/50-server.cnf
echo "[db] inspecting $CNF"

# Detect existing utf8mb4 config
HAVE_UTF8MB4=0
if sudoo grep -q "character-set-server[[:space:]]*=[[:space:]]*utf8mb4" "$CNF"; then
  HAVE_UTF8MB4=1
fi

if [ "$HAVE_UTF8MB4" = "0" ]; then
  echo "[db] appending utf8mb4 config"
  sudoo cp "$CNF" "${CNF}.bak.$(date +%s)"
  sudoo tee -a "$CNF" >/dev/null <<'EOF'

# --- ERPNext bench: utf8mb4 ---
[mysqld]
character-set-client-handshake = FALSE
character-set-server = utf8mb4
collation-server = utf8mb4_unicode_ci

[mysql]
default-character-set = utf8mb4
EOF
  echo "[db] restarting mariadb"
  sudoo service mariadb restart
else
  echo "[db] utf8mb4 already configured"
fi

# Wait briefly for restart
for i in 1 2 3 4 5; do
  if sudoo mariadb -uroot -e "SELECT 1" >/dev/null 2>&1; then break; fi
  sleep 1
done

echo "[db] confirming server charset"
sudoo mariadb -uroot -e "SHOW VARIABLES WHERE Variable_name IN ('character_set_server','collation_server');"

# Check current root auth state
echo "[db] inspecting root auth"
ROOT_INFO=$(sudoo mariadb -uroot -N -B -e "SELECT user,host,plugin FROM mysql.global_priv WHERE user='root';" 2>/dev/null || \
            sudoo mariadb -uroot -N -B -e "SELECT user,host,plugin FROM mysql.user WHERE user='root';")
echo "$ROOT_INFO"

# Switch root@localhost to mysql_native_password with our chosen pass so bench can connect.
# Also keep unix_socket access by adding a separate 'rsmith' admin? No — bench expects root.
# We'll set root@localhost to use mysql_native_password.
echo "[db] setting root@localhost password (mysql_native_password)"
sudoo mariadb -uroot <<SQL
ALTER USER 'root'@'localhost' IDENTIFIED VIA mysql_native_password USING PASSWORD('$DB_ROOT_PASS');
FLUSH PRIVILEGES;
SQL

echo "[db] verifying password-based root login"
if mariadb -uroot -p"$DB_ROOT_PASS" -e "SELECT 'ok' AS status;" 2>/dev/null; then
  echo "[db] OK — root login with password works"
else
  echo "[db] ERROR — could not log in as root with password"; exit 3
fi

echo "[db] DONE"
