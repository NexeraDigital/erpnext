# Copyright (c) 2026, NexeraDigital and contributors
# For license information, please see license.txt

"""Audit unit tests (plan §7.1 #3): argument sanitization is belt-and-braces."""

import unittest
from types import SimpleNamespace

import frappe
from frappe.tests import IntegrationTestCase

from erpnext.mcp import audit
from erpnext.mcp.audit import _REDACTED, sanitize_args


class TestSanitizeArgs(unittest.TestCase):
	def test_none_and_non_dict(self):
		self.assertEqual(sanitize_args(None), {})
		self.assertEqual(sanitize_args("nope"), {})

	def test_redacts_sensitive_keys(self):
		out = sanitize_args({"supplier": "ACME", "password": "hunter2", "api_key": "k"})
		self.assertEqual(out["supplier"], "ACME")
		self.assertEqual(out["password"], _REDACTED)
		self.assertEqual(out["api_key"], _REDACTED)

	def test_case_insensitive_keys(self):
		out = sanitize_args({"Password": "x", "TOKEN": "y"})
		self.assertEqual(out["Password"], _REDACTED)
		self.assertEqual(out["TOKEN"], _REDACTED)

	def test_nested_dict_redaction(self):
		out = sanitize_args({"outer": {"secret": "s", "ok": 1}})
		self.assertEqual(out["outer"]["secret"], _REDACTED)
		self.assertEqual(out["outer"]["ok"], 1)

	def test_preserves_non_sensitive(self):
		args = {"supplier": "ACME", "limit": 50, "status_in": ["Unpaid"]}
		self.assertEqual(sanitize_args(args), args)


def _ctx(user="Administrator"):
	return SimpleNamespace(
		user=user,
		client_id="cid-1",
		session_id="sess-1",
		protocol_version="2025-11-25",
		ip_address="127.0.0.1",
	)


def _rows(tool):
	return frappe.get_all(
		"MCP Audit Log",
		filters={"tool": tool},
		fields=["name", "result_status", "error_type", "args_json", "result_truncated", "user"],
	)


class TestAuditIntegration(IntegrationTestCase):
	"""safe_execute writes exactly one audit row per call (plan §7.1 #3, L13)."""

	def test_success_writes_one_row(self):
		tool = "t_success"
		out = audit.safe_execute(tool, _ctx(), None, lambda: {"ok": 1}, {"supplier": "ACME"})
		self.assertEqual(out, {"ok": 1})
		rows = _rows(tool)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].result_status, "Success")
		self.assertEqual(rows[0].user, "Administrator")

	def test_error_writes_one_row_and_reraises(self):
		tool = "t_error"

		def boom():
			raise ValueError("nope")

		with self.assertRaises(ValueError):
			audit.safe_execute(tool, _ctx(), None, boom, {})
		rows = _rows(tool)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].result_status, "Error")
		self.assertEqual(rows[0].error_type, "ValueError")

	def test_permission_error_classified(self):
		tool = "t_perm"

		def denied():
			raise frappe.PermissionError("no")

		with self.assertRaises(frappe.PermissionError):
			audit.safe_execute(tool, _ctx(), None, denied, {})
		self.assertEqual(_rows(tool)[0].result_status, "PermissionDenied")

	def test_args_sanitized_at_sink(self):
		tool = "t_sanitize"
		audit.safe_execute(tool, _ctx(), None, lambda: {"ok": 1}, {"password": "hunter2", "supplier": "ACME"})
		import json as _json

		stored = _json.loads(_rows(tool)[0].args_json)
		self.assertEqual(stored["password"], _REDACTED)
		self.assertEqual(stored["supplier"], "ACME")

	def test_truncation_flag_set_for_large_result(self):
		tool = "t_big"
		# Force a tiny cap so any result trips the truncation flag.
		orig = audit.config.audit_output_max_bytes
		audit.config.audit_output_max_bytes = lambda: 1
		try:
			audit.safe_execute(tool, _ctx(), None, lambda: {"data": "x" * 100}, {})
		finally:
			audit.config.audit_output_max_bytes = orig
		self.assertTrue(_rows(tool)[0].result_truncated)
