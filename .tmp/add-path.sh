#!/usr/bin/env bash
set -euo pipefail
if ! grep -q '\.local/bin' "$HOME/.bashrc"; then
  echo '' >> "$HOME/.bashrc"
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
  echo "[path] added .local/bin to .bashrc"
else
  echo "[path] already present"
fi
grep '\.local/bin' "$HOME/.bashrc"
