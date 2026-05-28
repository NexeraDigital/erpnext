#!/usr/bin/env bash
cd "$HOME/frappe-bench/sites"
../env/bin/python - <<'PY'
import frappe
frappe.init(site="erpnext.localhost")
frappe.connect()

# Print current System Settings home_page / default workspace state
ss = frappe.get_doc("System Settings")
print("home_page:", getattr(ss, "home_page", None))
print("default_app:", getattr(ss, "default_app", None))

# User-level default workspace
user = frappe.get_doc("User", "Administrator")
print("user.home_settings:", getattr(user, "home_settings", None)[:200] if getattr(user, "home_settings", None) else "(none)")
print("user.default_workspace:", getattr(user, "default_workspace", None))

# What does /desk actually serve? frappe's get_default_path
try:
    from frappe.www.app import get_default_path
    print("get_default_path:", get_default_path())
except Exception as e:
    print("get_default_path err:", e)

# List workspaces with their `for_user` / role visibility
print("\n=== first non-sidebar workspace user can see ===")
for ws in frappe.get_all("Workspace", filters={"public": 1}, fields=["name","sequence_id"], order_by="sequence_id"):
    print(ws)
PY
