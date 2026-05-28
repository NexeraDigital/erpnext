#!/usr/bin/env bash
set -euo pipefail

# Refresh sudo cache so subsequent sudo calls don't re-prompt
echo "$SUDO_PASS" | sudo -S -p '' -v

sudo install -m 0755 -d /etc/apt/keyrings

curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
  | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg >/dev/null
sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg

ARCH=$(dpkg --print-architecture)
LINE="deb [arch=$ARCH signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main"
echo "$LINE" | sudo tee /etc/apt/sources.list.d/github-cli.list >/dev/null

sudo apt update -qq 2>&1 | tail -3
sudo DEBIAN_FRONTEND=noninteractive apt install -y gh 2>&1 | tail -5

gh --version
