#!/usr/bin/env bash
set -euo pipefail
cd "$HOME/frappe-bench/apps/erpnext"

echo "=== status before ==="
git status -s

echo "=== adding files ==="
git add docs/DEVELOPMENT-GUIDE.md docs/architecture/FORK-CHANGES-PLAIN.md

echo "=== commit ==="
git commit -m "$(cat <<'EOF'
docs: add development guide and plain-english fork explainer

- docs/DEVELOPMENT-GUIDE.md: local dev + debugging workflow for the WSL setup
- docs/architecture/FORK-CHANGES-PLAIN.md: plain-english companion to FORK-CHANGES.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"

echo "=== push ==="
git push origin russ/bryanwork

echo "=== status after ==="
git status -s
git log --oneline -3
