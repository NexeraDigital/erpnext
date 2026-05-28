#!/usr/bin/env bash
cd "$HOME/frappe-bench/sites"
../env/bin/python - <<'PY'
import frappe, json
frappe.init(site="erpnext.localhost")
frappe.connect()

# Set System Settings home_page to a known workspace path
try:
    ss = frappe.get_doc("System Settings")
    ss.home_page = "home"  # the Home workspace
    ss.save(ignore_permissions=True)
    print("System Settings home_page set to 'home'")
except Exception as e:
    print("ss.home_page:", e)

# Also explicitly set Administrator's home_settings to pin a default workspace
home_settings = {
    "workspace_visibility_map": {},
    "hidden_modules": [],
    "default_workspace": "Home",
}
frappe.db.set_value("User", "Administrator", "home_settings", json.dumps(home_settings))

frappe.db.commit()

# Clear cache so the change propagates
frappe.clear_cache()
print("cleared cache")

# Verify
v = frappe.db.get_value("System Settings", "System Settings", "home_page")
print("verified home_page:", v)
PY
