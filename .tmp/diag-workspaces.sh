#!/usr/bin/env bash
cd "$HOME/frappe-bench/sites"
../env/bin/python - <<'PY'
import frappe
frappe.init(site="erpnext.localhost")
frappe.connect()

print("=== All Workspace rows ===")
rows = frappe.db.sql("""
    SELECT name, title, label, icon, public, hide_custom, module, sequence_id, parent_page, for_user
    FROM `tabWorkspace` ORDER BY sequence_id, name
""", as_dict=True)
for r in rows:
    print(r)

print("\n=== Workspace named exactly 'Accounts'? ===")
exists = frappe.db.exists("Workspace", "Accounts")
print(f"Workspace 'Accounts' exists: {exists}")

print("\n=== Module Def named 'Accounts' ===")
md = frappe.db.get_value("Module Def", "Accounts", ["name", "app_name", "module_name"], as_dict=True)
print(md)

print("\n=== valid icons available (sample) ===")
# Try Frappe's icon list
try:
    from frappe.utils import get_assets_json
    print("(get_assets_json present)")
except Exception as e:
    print("get_assets_json:", e)
PY
