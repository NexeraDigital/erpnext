#!/usr/bin/env bash
H='Host: erpnext.localhost'
for path in /app /app/workspace/Accounts /desk /desk/workspace/Accounts; do
  echo "=== $path ==="
  curl -sSI -H "$H" "http://127.0.0.1:8000$path" 2>&1 | head -10
  echo
done
