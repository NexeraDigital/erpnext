#!/usr/bin/env bash
set -euo pipefail

export NVM_DIR="$HOME/.nvm"
# shellcheck disable=SC1091
. "$NVM_DIR/nvm.sh"
export PATH="$HOME/.local/bin:$PATH"

cd "$HOME/frappe-bench"

echo "=== current erpnext editable install ==="
./env/bin/python -c "import erpnext; print('erpnext ver:', erpnext.__version__); print('erpnext path:', erpnext.__file__)" 2>&1 || true

echo "=== reinstalling apps/erpnext editable ==="
./env/bin/python -m uv pip install --upgrade -e ./apps/erpnext --python ./env/bin/python 2>&1 | tail -15

echo "=== verify ==="
./env/bin/python -c "import erpnext; print('erpnext ver:', erpnext.__version__); print('erpnext path:', erpnext.__file__)"

echo "=== confirm ap_closed_loop module importable ==="
./env/bin/python -c "from erpnext.accounts import ap_closed_loop; print('module OK:', ap_closed_loop.__file__)"
