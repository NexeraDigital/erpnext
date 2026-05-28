#!/usr/bin/env bash
H='Host: erpnext.localhost'
for p in /desk /desk/accounting /desk/home; do
  echo "=== $p ==="
  curl -sSIL -H "$H" "http://127.0.0.1:8000$p" 2>&1
  echo
done
