#!/usr/bin/env bash
cd "$HOME/frappe-bench/apps/erpnext"
echo "=== current branch ==="
git rev-parse --abbrev-ref HEAD
echo
echo "=== local branches ==="
git branch
echo
echo "=== remote branches ==="
git branch -r
echo
echo "=== russ/bryanwork on origin ==="
git ls-remote origin 'refs/heads/russ/bryanwork' || true
echo
echo "=== any branch matching bryan ==="
git ls-remote origin | grep -i bryan || echo "(no match)"
