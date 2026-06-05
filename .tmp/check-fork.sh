#!/usr/bin/env bash
set -euo pipefail
cd "$HOME/frappe-bench/apps/erpnext"
echo "=== remote ==="
git remote -v
echo "=== current branch ==="
git rev-parse --abbrev-ref HEAD
echo "=== HEAD log ==="
git log --oneline -5
echo "=== local branches ==="
git branch -a | head -10
echo "=== fork markers (looking for AP closed loop commits) ==="
git log --all --oneline | grep -iE 'ap.closed.loop|nexeradigital|closure.evidence' || echo "NO FORK COMMITS FOUND"
echo "=== ap_closed_loop directory ==="
ls erpnext/accounts/ap_closed_loop 2>/dev/null || echo "NO ap_closed_loop dir"
echo "=== document_capture doctype ==="
ls erpnext/accounts/doctype/document_capture 2>/dev/null || echo "NO document_capture dir"
