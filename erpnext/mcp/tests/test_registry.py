# Copyright (c) 2026, NexeraDigital and contributors
# For license information, please see license.txt

"""Scope/visibility unit tests (plan L4/L5): the tools/list filter + call gate."""

import unittest
from types import SimpleNamespace

import frappe

from erpnext.mcp.tools import _scope
from erpnext.mcp.tools.ap_invoices import ListAPInvoices


def _ctx(scopes=None, user="someone@example.com"):
	return SimpleNamespace(user=user, scopes=scopes or [])


class TestScopeResolution(unittest.TestCase):
	def test_config_scope_overrides_tool_default(self):
		cfg = {"required_oauth_scope": "custom:scope"}
		self.assertEqual(_scope.required_scope(ListAPInvoices, cfg), "custom:scope")

	def test_falls_back_to_tool_default(self):
		self.assertEqual(
			_scope.required_scope(ListAPInvoices, None), "erpnext:ap_invoice:read"
		)

	def test_enabled_defaults_true_without_config(self):
		self.assertTrue(_scope.is_enabled(None))

	def test_disabled_when_config_says_so(self):
		self.assertFalse(_scope.is_enabled({"enabled": 0}))

	def test_scope_required_for_visibility(self):
		self.assertFalse(_scope.has_required_scope(_ctx(scopes=[]), ListAPInvoices, None))
		self.assertTrue(
			_scope.has_required_scope(
				_ctx(scopes=["erpnext:ap_invoice:read"]), ListAPInvoices, None
			)
		)


class TestRoleGate(unittest.TestCase):
	def setUp(self):
		self._orig = frappe.get_roles

	def tearDown(self):
		frappe.get_roles = self._orig

	def test_no_role_required_passes(self):
		self.assertTrue(_scope.has_required_role(_ctx(), None))

	def test_required_role_present(self):
		frappe.get_roles = lambda user: ["Accounts Manager"]
		self.assertTrue(_scope.has_required_role(_ctx(), {"required_role": "Accounts Manager"}))

	def test_required_role_absent(self):
		frappe.get_roles = lambda user: ["Blogger"]
		self.assertFalse(_scope.has_required_role(_ctx(), {"required_role": "Accounts Manager"}))


class TestVisibility(unittest.TestCase):
	def setUp(self):
		self._orig = frappe.get_roles
		frappe.get_roles = lambda user: []

	def tearDown(self):
		frappe.get_roles = self._orig

	def test_visible_only_with_scope(self):
		self.assertFalse(_scope.is_visible(_ctx(scopes=[]), ListAPInvoices, None))
		self.assertTrue(
			_scope.is_visible(_ctx(scopes=["erpnext:ap_invoice:read"]), ListAPInvoices, None)
		)
