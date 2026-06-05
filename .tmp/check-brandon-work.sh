#!/usr/bin/env bash
cd "$HOME/frappe-bench/apps/erpnext"

echo "=== current branch ==="
git rev-parse --abbrev-ref HEAD

echo
echo "=== AP files present on this branch? ==="
for f in \
  erpnext/accounts/ap_closed_loop/walking_skeleton.py \
  erpnext/accounts/ap_closed_loop/test_walking_skeleton.py \
  erpnext/accounts/doctype/document_capture/document_capture.json \
  erpnext/accounts/doctype/document_capture/document_capture.py \
  erpnext/accounts/doctype/document_capture/test_document_capture.py \
  AGENTS.md \
  docs/architecture/FORK-CHANGES.md; do
  if [ -f "$f" ]; then echo "OK   $f"; else echo "MISS $f"; fi
done

echo
echo "=== are develop's AP commits ancestors of russ/bryanwork? ==="
git fetch origin develop --quiet 2>/dev/null || true
for c in c95d2d963a 10e3a7faf3 4e2fe5a 1c1c6fa 2fae4ef 04ffeb6 dbabb28 ae93cf8 f40e4b6; do
  if git merge-base --is-ancestor "$c" HEAD 2>/dev/null; then
    echo "YES  $c $(git log -1 --format='%s' $c 2>/dev/null)"
  else
    echo "NO   $c $(git log -1 --format='%s' $c 2>/dev/null || echo '(commit not fetched)')"
  fi
done

echo
echo "=== commits on russ/bryanwork NOT on develop (Bryan's added work) ==="
git log --oneline origin/develop..HEAD 2>/dev/null | head -20

echo
echo "=== commits on develop NOT on russ/bryanwork (missing from this branch) ==="
git log --oneline HEAD..origin/develop 2>/dev/null | head -20
