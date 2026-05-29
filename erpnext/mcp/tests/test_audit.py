# Copyright (c) 2026, NexeraDigital and contributors
# For license information, please see license.txt

"""Audit unit tests (plan §7.1 #3): argument sanitization is belt-and-braces."""

import unittest

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
