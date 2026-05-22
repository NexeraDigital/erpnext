#!/usr/bin/env bash
cd "$HOME/frappe-bench"
echo "=== fork's pyproject deps ==="
grep -E "pandas|numpy|gocardless|youtube|plaid|googlemaps" apps/erpnext/pyproject.toml || echo "(none of those listed)"
echo "=== installed in venv ==="
./env/bin/python -m pip list 2>/dev/null | grep -iE "pandas|numpy|gocardless|plaid|googlemaps|frappe|erpnext" || true
echo "=== try importing pandas ==="
./env/bin/python -c "import pandas; print('pandas', pandas.__version__)" 2>&1 || echo "PANDAS MISSING"
