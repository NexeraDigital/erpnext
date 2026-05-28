#!/usr/bin/env bash
set -euo pipefail
export NVM_DIR="$HOME/.nvm"
# shellcheck disable=SC1091
. "$NVM_DIR/nvm.sh"

nvm install 24 >/tmp/nvm-24.log 2>&1
nvm alias default 24 >/dev/null
nvm use 24 >/dev/null

echo "[node] node=$(node --version) npm=$(npm --version)"
npm install -g yarn >/tmp/yarn-24.log 2>&1
echo "[node] yarn=$(yarn --version)"
