# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""Tests for the Tier-1 AP Supplier Alias resolver (spec 05).

Exercised through ``_resolve_supplier`` (the real consumer) so these prove the
alias table as the resolver sees it: each match_type resolves its key, precedence
is exact > glob > regex, a bad regex is skipped (never raises), inactive aliases
never match, and an alias pointing at a disabled Supplier is ignored.
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from erpnext.accounts.doctype.ap_invoice_capture.ap_invoice_capture import (
	SUPPLIER_MATCH_ALIAS,
	SUPPLIER_MATCH_AMBIGUOUS,
	SUPPLIER_TIER_ALIAS,
	_resolve_supplier,
)

EXTRA_TEST_RECORD_DEPENDENCIES = ["Supplier"]


def _supplier_group() -> str:
	return frappe.db.get_value("Supplier", "_Test Supplier", "supplier_group") or "All Supplier Groups"


def _make_supplier(name: str, *, disabled: int = 0) -> str:
	doc = frappe.get_doc(
		{
			"doctype": "Supplier",
			"supplier_name": name,
			"supplier_group": _supplier_group(),
			"supplier_type": "Company",
			"disabled": disabled,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _make_alias(canonical: str, pattern: str, match_type: str = "glob", **kw) -> str:
	doc = frappe.get_doc(
		{
			"doctype": "AP Supplier Alias",
			"canonical_supplier": canonical,
			"alias_pattern": pattern,
			"match_type": match_type,
			"is_active": kw.get("is_active", 1),
			"priority": kw.get("priority", 0),
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


class TestAPSupplierAlias(IntegrationTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_exact_match_type_resolves(self):
		sup = _make_supplier(f"AWS {frappe.generate_hash(length=6)}")
		_make_alias(sup, "Amazon Web Services", match_type="exact")
		res = _resolve_supplier("Amazon Web Services")
		self.assertEqual(res["matched_supplier"], sup)
		self.assertEqual(res["match_status"], SUPPLIER_MATCH_ALIAS)
		self.assertEqual(res["tier"], SUPPLIER_TIER_ALIAS)
		# Exact alias does NOT match a different string.
		self.assertNotEqual(_resolve_supplier("Amazon Web Service")["match_status"], SUPPLIER_MATCH_ALIAS)

	def test_glob_match_type_resolves(self):
		sup = _make_supplier(f"Amazon {frappe.generate_hash(length=6)}")
		_make_alias(sup, "AMZN Mktp US*", match_type="glob")
		res = _resolve_supplier("AMZN Mktp US*4Z9")
		self.assertEqual(res["matched_supplier"], sup)
		self.assertEqual(res["match_status"], SUPPLIER_MATCH_ALIAS)

	def test_regex_match_type_resolves(self):
		sup = _make_supplier(f"Stripe {frappe.generate_hash(length=6)}")
		_make_alias(sup, "^STRIPE.*", match_type="regex")
		res = _resolve_supplier("STRIPE PAYMENTS")
		self.assertEqual(res["matched_supplier"], sup)
		self.assertEqual(res["match_status"], SUPPLIER_MATCH_ALIAS)

	def test_bad_regex_is_skipped_not_raised(self):
		sup = _make_supplier(f"Vendor {frappe.generate_hash(length=6)}")
		# Insert a malformed regex alias straight to the DB to bypass the controller
		# msgprint and prove the RESOLVER tolerates it at match time.
		_make_alias(sup, "(unbalanced", match_type="regex")
		# Must not raise; falls through to Tier 2 (no Supplier named this) -> Unknown.
		res = _resolve_supplier("(unbalanced")
		self.assertNotEqual(res["match_status"], SUPPLIER_MATCH_ALIAS)

	def test_precedence_exact_beats_glob(self):
		# Precedence tie-breaks among aliases pointing at the SAME supplier — it
		# selects the representative alias_id (exact > glob), not a winner between
		# two different suppliers (that case is Ambiguous, tested separately).
		sup = _make_supplier(f"AcmeCo {frappe.generate_hash(length=6)}")
		_make_alias(sup, "ACME*", match_type="glob")
		exact_alias = _make_alias(sup, "ACME CORP", match_type="exact")
		res = _resolve_supplier("ACME CORP")
		self.assertEqual(res["matched_supplier"], sup)
		self.assertEqual(res["match_status"], SUPPLIER_MATCH_ALIAS)
		# The exact alias is chosen as the representative (precedence exact > glob).
		self.assertEqual(res["alias_id"], exact_alias)
		self.assertEqual(
			frappe.db.get_value("AP Supplier Alias", res["alias_id"], "match_type"), "exact"
		)

	def test_inactive_alias_never_matches(self):
		sup = _make_supplier(f"Inactive {frappe.generate_hash(length=6)}")
		_make_alias(sup, "GHOSTPAY*", match_type="glob", is_active=0)
		res = _resolve_supplier("GHOSTPAY 0001")
		self.assertNotEqual(res["match_status"], SUPPLIER_MATCH_ALIAS)

	def test_alias_to_disabled_supplier_is_excluded(self):
		sup = _make_supplier(f"Disabled {frappe.generate_hash(length=6)}", disabled=1)
		_make_alias(sup, "DEADVENDOR*", match_type="glob")
		res = _resolve_supplier("DEADVENDOR 99")
		self.assertNotEqual(res["match_status"], SUPPLIER_MATCH_ALIAS)
		self.assertIsNone(res["matched_supplier"])

	def test_two_aliases_to_different_suppliers_is_ambiguous(self):
		a = _make_supplier(f"AlphaCo {frappe.generate_hash(length=6)}")
		b = _make_supplier(f"BetaCo {frappe.generate_hash(length=6)}")
		_make_alias(a, "SHARED*", match_type="glob")
		_make_alias(b, "SHARED PMT*", match_type="glob")
		res = _resolve_supplier("SHARED PMT 7")
		self.assertEqual(res["match_status"], SUPPLIER_MATCH_AMBIGUOUS)
		self.assertEqual(set(res["competing"]), {a, b})
