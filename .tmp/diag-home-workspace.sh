#!/usr/bin/env bash
cd "$HOME/frappe-bench/sites"
../env/bin/python - <<'PY'
import frappe, json
frappe.init(site="erpnext.localhost")
frappe.connect()

print("=== Home workspace content (raw) ===")
home = frappe.get_doc("Workspace", "Home")
print("title:", home.title)
print("public:", home.public)
print("content (first 2000 chars):")
print((home.content or "")[:2000])

print("\n=== Home workspace links (Workspace Link child rows) ===")
for l in (home.links or []):
    print(f"  type={l.type:20} label={l.label!r:35} link_to={l.link_to!r:30} link_type={l.link_type!r:15} hidden={l.hidden}")

print("\n=== Home workspace shortcuts ===")
for s in (home.shortcuts or []):
    print(f"  type={s.type:15} label={s.label!r:25} link_to={s.link_to!r:25}")

print("\n=== Home workspace number_cards ===")
for n in (getattr(home, 'number_cards', None) or []):
    print(f"  label={n.label!r} number_card_name={getattr(n, 'number_card_name', '?')!r}")
PY
