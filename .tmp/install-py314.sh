#!/usr/bin/env bash
set -euo pipefail
echo "$SUDO_PASS" | sudo -S -p '' DEBIAN_FRONTEND=noninteractive apt install -y \
  python3.14 python3.14-venv python3.14-dev 2>&1 | tail -15
echo "[py] versions"
python3.14 --version
which python3.14
