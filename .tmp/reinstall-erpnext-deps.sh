#!/usr/bin/env bash
set -euo pipefail

export PATH="$HOME/.local/bin:$PATH"
cd "$HOME/frappe-bench"

echo "=== re-installing erpnext editable (refresh deps) ==="
# bench installs uv globally; call it as a module from the bench venv? No — bench uses host uv.
# Use the same uv that bench used (from frappe-bench install).
uv pip install --upgrade -e ./apps/erpnext --python ./env/bin/python 2>&1 | tail -20

echo "=== verify pandas ==="
./env/bin/python -c "import pandas; print('pandas', pandas.__version__)"
echo "=== verify python-youtube ==="
./env/bin/python -c "import pyyoutube; print('pyyoutube OK')" 2>&1 || echo "missing pyyoutube"
