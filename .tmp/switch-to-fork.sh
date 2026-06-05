#!/usr/bin/env bash
set -euo pipefail

cd "$HOME/frappe-bench/apps/erpnext"

echo "=== before ==="
git remote -v
git log --oneline -1

# Add the fork as origin
if git remote | grep -q '^origin$'; then
  git remote set-url origin https://github.com/NexeraDigital/erpnext.git
else
  git remote add origin https://github.com/NexeraDigital/erpnext.git
fi

# The current clone is --depth 1 from upstream/develop. Unshallow + fetch the fork.
echo "=== fetching fork (unshallow) ==="
git fetch --unshallow origin develop 2>&1 | tail -3 || git fetch origin develop 2>&1 | tail -3

echo "=== checking out fork/develop ==="
git checkout -B develop origin/develop
git reset --hard origin/develop

echo "=== after ==="
git remote -v
git log --oneline -8
echo "=== fork markers ==="
git log --oneline | grep -iE 'ap.closed.loop|nexeradigital|closure.evidence|walking.skeleton' | head -10
echo "=== ap_closed_loop dir ==="
ls erpnext/accounts/ap_closed_loop 2>/dev/null && echo OK || echo MISSING
echo "=== document_capture dir ==="
ls erpnext/accounts/doctype/document_capture 2>/dev/null && echo OK || echo MISSING
