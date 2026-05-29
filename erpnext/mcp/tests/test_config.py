# Copyright (c) 2026, NexeraDigital and contributors
# For license information, please see license.txt

"""Settings/Tool-Config accessor + install idempotency tests."""

import json

import frappe
from frappe.tests import IntegrationTestCase

from erpnext.mcp import config, install
from erpnext.mcp.tools import get_catalogue


class TestSettingsAccessors(IntegrationTestCase):
	def setUp(self):
		self.s = frappe.get_single("MCP Settings")

	def test_blank_fields_fall_back_to_defaults(self):
		self.s.allowed_origins = ""
		self.s.allowed_protocol_versions = ""
		self.s.audit_retention_days = 0
		self.s.audit_output_max_bytes = 0
		self.s.save(ignore_permissions=True)
		frappe.clear_document_cache("MCP Settings", "MCP Settings")
		self.assertIn("http://localhost", config.allowed_origins())
		self.assertIn("2025-11-25", config.allowed_protocol_versions())
		self.assertEqual(config.audit_retention_days(), 180)
		self.assertEqual(config.audit_output_max_bytes(), 51200)

	def test_json_lists_parsed(self):
		self.s.allowed_origins = json.dumps(["https://a.example.com"])
		self.s.allowed_protocol_versions = json.dumps(["2025-11-25"])
		self.s.save(ignore_permissions=True)
		frappe.clear_document_cache("MCP Settings", "MCP Settings")
		self.assertEqual(config.allowed_origins(), ["https://a.example.com"])
		self.assertEqual(config.allowed_protocol_versions(), ["2025-11-25"])

	def test_invalid_json_is_rejected_on_validate(self):
		self.s.allowed_origins = "{not json"
		with self.assertRaises(frappe.ValidationError):
			self.s.save(ignore_permissions=True)


class TestToolConfigSync(IntegrationTestCase):
	def test_sync_creates_a_row_per_catalogue_tool(self):
		install.sync_tool_configs()
		for name in get_catalogue():
			self.assertTrue(frappe.db.exists("MCP Tool Config", name), f"missing config: {name}")

	def test_sync_is_idempotent(self):
		install.sync_tool_configs()
		install.sync_tool_configs()
		for name in get_catalogue():
			count = frappe.db.count("MCP Tool Config", {"tool_name": name})
			self.assertEqual(count, 1, f"duplicate config rows for {name}")

	def test_sync_does_not_overwrite_existing(self):
		install.sync_tool_configs()
		# An admin disables a tool; a later sync must not re-enable it.
		frappe.db.set_value("MCP Tool Config", "list_vendors", "enabled", 0)
		install.sync_tool_configs()
		self.assertEqual(frappe.db.get_value("MCP Tool Config", "list_vendors", "enabled"), 0)

	def test_tool_config_map_contains_seeded_tools(self):
		install.sync_tool_configs()
		frappe.cache.delete_value("mcp_tool_config")
		cfg_map = config.get_tool_config_map()
		self.assertIn("list_ap_invoices", cfg_map)
		self.assertEqual(
			cfg_map["list_ap_invoices"]["required_oauth_scope"], "erpnext:ap_invoice:read"
		)
