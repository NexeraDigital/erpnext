#!/usr/bin/env bash
set -euo pipefail

# Cleanup the failed bench
if [ -d "$HOME/frappe-bench" ]; then
  echo "[py] removing partial $HOME/frappe-bench"
  rm -rf "$HOME/frappe-bench"
fi

echo "[py] enabling deadsnakes PPA"
echo "$SUDO_PASS" | sudo -S -p '' apt install -y software-properties-common 2>&1 | tail -3
echo "$SUDO_PASS" | sudo -S -p '' add-apt-repository -y ppa:deadsnakes/ppa 2>&1 | tail -3
echo "$SUDO_PASS" | sudo -S -p '' apt update -qq 2>&1 | tail -3

echo "[py] installing python3.12 + venv + dev + distutils"
echo "$SUDO_PASS" | sudo -S -p '' DEBIAN_FRONTEND=noninteractive apt install -y \
  python3.12 python3.12-venv python3.12-dev 2>&1 | tail -10

echo "[py] versions"
python3.12 --version
which python3.12
