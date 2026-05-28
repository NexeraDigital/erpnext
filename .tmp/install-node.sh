#!/usr/bin/env bash
set -euo pipefail

echo "[node] HOME=$HOME user=$(whoami)"

# Install nvm (user-local, no sudo)
if [ ! -d "$HOME/.nvm" ]; then
  curl -sSL -o /tmp/nvm-install.sh https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh
  PROFILE=/dev/null bash /tmp/nvm-install.sh >/tmp/nvm-install.log 2>&1
  echo "[node] nvm installed"
else
  echo "[node] nvm already present"
fi

export NVM_DIR="$HOME/.nvm"
# shellcheck disable=SC1091
. "$NVM_DIR/nvm.sh"

nvm install 20 >/tmp/nvm-node.log 2>&1
nvm alias default 20 >/dev/null
echo "[node] node=$(node --version)  npm=$(npm --version)"

npm install -g yarn >/tmp/yarn-install.log 2>&1
echo "[node] yarn=$(yarn --version)"

# Make sure future shells pick up nvm
if ! grep -q 'NVM_DIR' "$HOME/.bashrc" 2>/dev/null; then
  {
    echo ''
    echo 'export NVM_DIR="$HOME/.nvm"'
    echo '[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"'
  } >> "$HOME/.bashrc"
  echo "[node] added nvm sourcing to ~/.bashrc"
fi

echo "[node] DONE"
