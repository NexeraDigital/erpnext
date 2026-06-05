# Copyright (c) 2026, NexeraDigital and contributors
# For license information, please see license.txt

"""Per-tool data-shape integration tests (plan §7.1 #2 data path, §5).

Runs each tool as Administrator against freshly seeded AP data and asserts the
returned shape, filters, and aggregation correctness. A dedicated supplier with a
known number of invoices makes the vendor-balance aggregation deterministic.
"""

import uuid

import frappe
from frappe.tests import IntegrationTestCase

from erpnext.mcp.tests._helpers import cleanup_seeded_docs, make_submitted_pi, make_supplier
from erpnext.mcp.tools.ap_invoices import GetAPInvoice, ListAPInvoices
from erpnext.mcp.tools.schema import GetDoctypeMeta
from erpnext.mcp.tools.vendors import GetVendorBalance, ListVendors


class TestToolsIntegration(IntegrationTestCase):
	# Declaring the doctype makes IntegrationTestCase provision Purchase Invoice's
	# full test-record dependency chain (Company, Supplier, Item, Customer, …).
	doctype = "Purchase Invoice"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.supplier = make_supplier(f"_MCP Vendor {uuid.uuid4().hex[:6]}")
		cls.pi1 = make_submitted_pi(cls.supplier, rate=100, qty=1)
		cls.pi2 = make_submitted_pi(cls.supplier, rate=150, qty=1)

	@classmethod
	def tearDownClass(cls):
		# setUpClass commits the seeded Supplier to disk (see cleanup_seeded_docs),
		# so the class rollback can't reclaim it — delete our seed explicitly.
		cleanup_seeded_docs(
			[
				("Purchase Invoice", getattr(getattr(cls, "pi1", None), "name", None)),
				("Purchase Invoice", getattr(getattr(cls, "pi2", None), "name", None)),
				("Supplier", getattr(cls, "supplier", None)),
			]
		)
		super().tearDownClass()

	def test_list_ap_invoices_returns_our_invoices(self):
		out = ListAPInvoices().run({"supplier": self.supplier, "limit": 50})
		names = {r["name"] for r in out["results"]}
		self.assertIn(self.pi1.name, names)
		self.assertIn(self.pi2.name, names)
		# Supplier display name is joined in.
		self.assertTrue(all(r["supplier"] == self.supplier for r in out["results"]))

	def test_list_ap_invoices_min_grand_total_filter(self):
		out = ListAPInvoices().run({"supplier": self.supplier, "min_grand_total": 1000000})
		self.assertEqual(out["results"], [])

	def test_list_ap_invoices_respects_limit(self):
		out = ListAPInvoices().run({"supplier": self.supplier, "limit": 1})
		self.assertLessEqual(len(out["results"]), 1)

	def test_get_ap_invoice_includes_items(self):
		out = GetAPInvoice().run({"name": self.pi1.name})
		self.assertEqual(out["name"], self.pi1.name)
		self.assertEqual(out["supplier"], self.supplier)
		self.assertGreaterEqual(len(out["items"]), 1)

	def test_list_vendors_finds_supplier(self):
		out = ListVendors().run({"name_like": self.supplier, "limit": 50})
		names = {r["name"] for r in out["results"]}
		self.assertIn(self.supplier, names)

	def test_get_vendor_balance_aggregation_is_correct(self):
		out = GetVendorBalance().run({"supplier": self.supplier})
		# Two submitted, unpaid invoices => count 2, total = 100 + 150.
		self.assertEqual(out["open_invoice_count"], 2)
		self.assertAlmostEqual(out["outstanding_total"], 250.0, places=2)

	def test_get_vendor_balance_unknown_supplier_zero(self):
		out = GetVendorBalance().run({"supplier": "ACME-DOES-NOT-EXIST"})
		self.assertEqual(out["open_invoice_count"], 0)
		self.assertEqual(out["outstanding_total"], 0.0)

	def test_get_doctype_meta_allowlisted(self):
		out = GetDoctypeMeta().run({"doctype": "Supplier"})
		fieldnames = {f["fieldname"] for f in out["fields"]}
		self.assertIn("supplier_name", fieldnames)
		# Layout-only fields are filtered out.
		self.assertNotIn("supplier_details_section", fieldnames - fieldnames)

	def test_get_doctype_meta_rejects_non_allowlisted_at_execute(self):
		# Bypass the Pydantic Literal to prove the execute-layer re-check also guards.
		from erpnext.mcp.tools.schema import GetDoctypeMetaInput

		bad = GetDoctypeMetaInput.model_construct(doctype="User")
		with self.assertRaises(frappe.PermissionError):
			GetDoctypeMeta().execute(bad)
