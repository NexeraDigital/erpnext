# Copyright (c) 2026, NexeraDigital and contributors
# For license information, please see license.txt

"""Idempotent provisioning of MCP Tool Config rows.

Runs via the ``after_migrate`` hook. Creates a config row for each catalogue tool
that does not already have one, seeded from the tool's declared scope and the
plan's default limits (O2). Existing rows are never overwritten — ops edits win.
"""

import frappe

# O2 defaults (plan §0). Adjustable per-row in Desk afterward.
_DEFAULT_RATE_LIMIT_PER_MINUTE = 30
_DEFAULT_CONCURRENCY_CAP = 5
_DEFAULT_TIMEOUT_SECONDS = 30


def sync_tool_configs():
	# Import lazily so this module is importable without the doctypes installed yet.
	from erpnext.mcp.tools import get_catalogue

	if not frappe.db.table_exists("MCP Tool Config"):
		return

	for tool_cls in get_catalogue().values():
		if frappe.db.exists("MCP Tool Config", tool_cls.name):
			continue
		doc = frappe.new_doc("MCP Tool Config")
		doc.tool_name = tool_cls.name
		doc.enabled = 1
		doc.required_oauth_scope = getattr(tool_cls, "required_scope", "") or None
		doc.rate_limit_per_minute = _DEFAULT_RATE_LIMIT_PER_MINUTE
		doc.concurrency_cap = _DEFAULT_CONCURRENCY_CAP
		doc.timeout_seconds = _DEFAULT_TIMEOUT_SECONDS
		doc.insert(ignore_permissions=True)

	if not frappe.flags.in_test:
		frappe.db.commit()
	frappe.cache.delete_value("mcp_tool_config")
