# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""Unit tests for the benchmark's pure scoring logic (no API calls).

The live run() is a manual evaluation tool and is not exercised here; only the
match_field / score functions, which decide pass/fail, are tested.
"""

from __future__ import annotations

from frappe.tests import IntegrationTestCase

from erpnext.accounts.ap_closed_loop.extractors.benchmark import FIELDS, match_field, score


class TestMatchField(IntegrationTestCase):
	def test_exact_text_match(self):
		self.assertTrue(match_field("supplier_invoice_no", "INV-1", "INV-1", [], set()))
		self.assertFalse(match_field("supplier_invoice_no", "INV-1", "INV-2", [], set()))

	def test_supplier_is_fuzzy(self):
		# trailing period / case / punctuation differences are tolerated
		self.assertTrue(match_field("supplier", "Northwind Traders Ltd.", "Northwind Traders Ltd", [], set()))
		self.assertTrue(match_field("supplier", "ACME Inc", "acme  inc.", [], set()))
		self.assertFalse(match_field("supplier", "ACME Inc", "Globex", [], set()))

	def test_total_numeric(self):
		self.assertTrue(match_field("total_amount", 1274.81, 1274.81, [], set()))
		self.assertTrue(match_field("total_amount", 1274.81, 1274.809, [], set()))  # within epsilon
		self.assertFalse(match_field("total_amount", 1274.81, 1300.00, [], set()))
		self.assertFalse(match_field("total_amount", 1274.81, None, [], set()))

	def test_currency_exact(self):
		self.assertTrue(match_field("currency", "EUR", "EUR", [], set()))
		self.assertFalse(match_field("currency", "EUR", "USD", [], set()))

	def test_expected_missing_passes_when_none(self):
		self.assertTrue(match_field("currency", None, None, ["currency"], set()))

	def test_expected_missing_passes_when_flagged_missing(self):
		# even if the model returned a value, being in missing_fields counts
		self.assertTrue(match_field("currency", None, "USD", ["currency"], {"currency"}))

	def test_expected_missing_fails_when_confidently_inferred(self):
		# returned a value AND did not flag missing -> wrong for a missing field
		self.assertFalse(match_field("currency", None, "USD", ["currency"], set()))


class TestScore(IntegrationTestCase):
	def _defn(self, **expected):
		base = {
			"supplier": "ACME Inc",
			"supplier_invoice_no": "INV-1",
			"invoice_date": "2026-01-01",
			"total_amount": 100.0,
			"currency": "USD",
		}
		base.update(expected)
		return {"expected": base, "expected_missing": expected.get("_missing", [])}

	def test_perfect_score(self):
		defn = self._defn()
		proposal = dict(defn["expected"])
		s = score(defn, proposal, set())
		self.assertEqual(s["n_ok"], len(FIELDS))
		self.assertTrue(all(s["marks"].values()))

	def test_partial_score(self):
		defn = self._defn()
		proposal = dict(defn["expected"])
		proposal["total_amount"] = 999.0  # wrong
		s = score(defn, proposal, set())
		self.assertEqual(s["n_ok"], len(FIELDS) - 1)
		self.assertFalse(s["marks"]["total_amount"])
