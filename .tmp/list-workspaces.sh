#!/usr/bin/env bash
cd "$HOME/frappe-bench/sites"
../env/bin/python - <<'PY'
import frappe
frappe.init(site="erpnext.localhost")
frappe.connect()
rows = frappe.db.sql("""
    SELECT name, title, label, public, icon, module
    FROM `tabWorkspace`
    ORDER BY public DESC, name
""", as_dict=True)
for r in rows:
    icon = r.get("icon") or ""
    print(f"{r['name']:35} title={r.get('title','-'):25} label={r.get('label','-'):25} public={r['public']} icon={icon!r} module={r.get('module') or '-'}")
PY
