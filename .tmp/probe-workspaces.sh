#!/usr/bin/env bash
H='Host: erpnext.localhost'
for path in /desk/home /desk/accounting /desk/Accounting /desk/welcome-workspace /desk/build; do
  echo "=== $path ==="
  curl -sSI -H "$H" "http://127.0.0.1:8000$path" 2>&1 | head -6
  echo
done
