#!/usr/bin/env bash
set -euo pipefail
cd "$HOME/frappe-bench"

export PATH="$HOME/.local/bin:$PATH"

echo "[debug] installing debugpy into bench venv"
uv pip install debugpy --python ./env/bin/python 2>&1 | tail -5

echo "[debug] verify"
./env/bin/python -c "import debugpy; print('debugpy', debugpy.__version__)"

echo "[debug] dropping .vscode in bench root"
mkdir -p .vscode
cp /mnt/c/GitHub/erpnext-1/.tmp/launch.json .vscode/launch.json
cp /mnt/c/GitHub/erpnext-1/.tmp/settings.json .vscode/settings.json
ls -la .vscode/
