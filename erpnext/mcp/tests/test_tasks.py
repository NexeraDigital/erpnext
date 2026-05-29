# Copyright (c) 2026, NexeraDigital and contributors
# For license information, please see license.txt

"""Audit-log retention scheduler test (plan §7 / P2.8)."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, now_datetime

from erpnext.mcp import tasks


def _make_audit_row(tool: str, age_days: int):
	doc = frappe.new_doc("MCP Audit Log")
	doc.timestamp = add_to_date(now_datetime(), days=-age_days)
	doc.user = "Administrator"
	doc.tool = tool
	doc.result_status = "Success"
	doc.insert(ignore_permissions=True)
	return doc.name


class TestPruneAuditLogs(IntegrationTestCase):
	def setUp(self):
		s = frappe.get_single("MCP Settings")
		s.audit_retention_days = 180
		s.save(ignore_permissions=True)
		frappe.clear_document_cache("MCP Settings", "MCP Settings")

	def test_prunes_old_keeps_recent(self):
		old = _make_audit_row("t_old", age_days=400)
		recent = _make_audit_row("t_recent", age_days=5)
		tasks.prune_audit_logs()
		self.assertFalse(frappe.db.exists("MCP Audit Log", old))
		self.assertTrue(frappe.db.exists("MCP Audit Log", recent))

	def test_retention_zero_is_noop(self):
		s = frappe.get_single("MCP Settings")
		s.audit_retention_days = 0
		s.save(ignore_permissions=True)
		frappe.clear_document_cache("MCP Settings", "MCP Settings")
		old = _make_audit_row("t_old2", age_days=400)
		tasks.prune_audit_logs()
		self.assertTrue(frappe.db.exists("MCP Audit Log", old))
