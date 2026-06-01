# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""Tests for AP Supplier Coding Profile + the _resolve_supplier_coding resolver (spec 06)."""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from erpnext.accounts.doctype.ap_invoice_capture.ap_invoice_capture import (
	_resolve_supplier_coding,
)

EXTRA_TEST_RECORD_DEPENDENCIES = ["Supplier", "Account", "Cost Center"]

_EXPENSE = "_Test Account Cost for Goods Sold - _TC"
_COST_CENTER = "_Test Cost Center - _TC"


def _supplier_group() -> str:
	return frappe.db.get_value("Supplier", "_Test Supplier", "supplier_group") or "All Supplier Groups"


def _make_supplier(name: str) -> str:
	doc = frappe.get_doc(
		{
			"doctype": "Supplier",
			"supplier_name": name,
			"supplier_group": _supplier_group(),
			"supplier_type": "Company",
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _make_profile(supplier: str, **fields) -> "frappe.Document":
	doc = frappe.get_doc(
		{
			"doctype": "AP Supplier Coding Profile",
			"supplier": supplier,
			"default_expense_account": fields.get("expense_account"),
			"default_cost_center": fields.get("cost_center"),
		}
	)
	doc.insert(ignore_permissions=True)
	return doc


class TestAPSupplierCodingProfile(IntegrationTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_profile_round_trips(self):
		sup = _make_supplier(f"CodeCo {frappe.generate_hash(length=6)}")
		_make_profile(sup, expense_account=_EXPENSE, cost_center=_COST_CENTER)
		doc = frappe.get_doc("AP Supplier Coding Profile", sup)
		self.assertEqual(doc.supplier, sup)
		self.assertEqual(doc.default_expense_account, _EXPENSE)
		self.assertEqual(doc.default_cost_center, _COST_CENTER)
		# autoname is field:supplier -> docname == supplier
		self.assertEqual(doc.name, sup)

	def test_resolver_returns_dict(self):
		sup = _make_supplier(f"ResolveCo {frappe.generate_hash(length=6)}")
		_make_profile(sup, expense_account=_EXPENSE, cost_center=_COST_CENTER)
		out = _resolve_supplier_coding(sup)
		self.assertEqual(out.get("expense_account"), _EXPENSE)
		self.assertEqual(out.get("cost_center"), _COST_CENTER)

	def test_resolver_none_and_unknown_yield_empty(self):
		self.assertEqual(_resolve_supplier_coding(None), {})
		self.assertEqual(_resolve_supplier_coding(f"No Such Supplier {frappe.generate_hash(length=6)}"), {})

	# AC-06-1
	def test_duplicate_profile_raises(self):
		sup = _make_supplier(f"DupCo {frappe.generate_hash(length=6)}")
		_make_profile(sup, expense_account=_EXPENSE)
		with self.assertRaises((frappe.DuplicateEntryError, frappe.UniqueValidationError)):
			_make_profile(sup, expense_account=_EXPENSE)

	# AC-06-14 (resolver half): empty dimensions -> no dimensions key, no error
	def test_empty_dimensions_resolver(self):
		sup = _make_supplier(f"DimCo {frappe.generate_hash(length=6)}")
		_make_profile(sup, expense_account=_EXPENSE)
		out = _resolve_supplier_coding(sup)
		self.assertNotIn("accounting_dimensions", out)
