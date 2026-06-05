# Copyright (c) 2026, NexeraDigital and contributors
# For license information, please see license.txt

"""MANDATORY permission-regression tests (plan §7.1 #1).

Every read tool, invoked as a user without the relevant DocType read permission,
must raise ``frappe.PermissionError`` (or return nothing) — never leaked rows.
"""

import frappe
from frappe.tests import IntegrationTestCase

from erpnext.mcp.permissions import permitted_names
from erpnext.mcp.tools.ap_invoices import GetAPInvoice, ListAPInvoices
from erpnext.mcp.tools.vendors import GetVendorBalance, ListVendors

_LOW_PRIV_USER = "mcp-lowpriv@example.com"


class TestPermissionRegression(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("User", _LOW_PRIV_USER):
			user = frappe.new_doc("User")
			user.email = _LOW_PRIV_USER
			user.first_name = "MCP"
			user.last_name = "LowPriv"
			user.send_welcome_email = 0
			# Deliberately no Accounts roles.
			user.insert(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_list_ap_invoices_denies_low_priv_role(self):
		frappe.set_user(_LOW_PRIV_USER)
		with self.assertRaises(frappe.PermissionError):
			ListAPInvoices().execute(ListAPInvoices.input_model())

	def test_get_ap_invoice_denies_low_priv_role(self):
		frappe.set_user(_LOW_PRIV_USER)
		# Either outcome leaks nothing: PermissionError (doc exists, no read) or
		# DoesNotExistError (has_permission on a missing doc). Both are acceptable.
		with self.assertRaises((frappe.PermissionError, frappe.DoesNotExistError)):
			GetAPInvoice().execute(GetAPInvoice.input_model(name="ANY-PINV-0001"))

	def test_list_vendors_denies_low_priv_role(self):
		frappe.set_user(_LOW_PRIV_USER)
		with self.assertRaises(frappe.PermissionError):
			ListVendors().execute(ListVendors.input_model())

	def test_get_vendor_balance_denies_low_priv_role(self):
		frappe.set_user(_LOW_PRIV_USER)
		with self.assertRaises(frappe.PermissionError):
			GetVendorBalance().execute(GetVendorBalance.input_model(supplier="ANY"))

	def test_permitted_names_raises_for_low_priv(self):
		frappe.set_user(_LOW_PRIV_USER)
		with self.assertRaises(frappe.PermissionError):
			permitted_names("Purchase Invoice", filters={}, limit=10)

	def test_administrator_can_read(self):
		# Sanity: a privileged user is not blocked by our gate.
		frappe.set_user("Administrator")
		# Should not raise.
		ListAPInvoices().execute(ListAPInvoices.input_model(limit=1))


class TestUserPermissionScoping(IntegrationTestCase):
	"""L7: a User Permission on Supplier must scope both permitted_names and the
	qb-backed aggregation — no rows or totals leak for the disallowed supplier."""

	# Provision Purchase Invoice's test-record dependency chain.
	doctype = "Purchase Invoice"

	SCOPED_USER = "mcp-scoped@example.com"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		import uuid

		from frappe.permissions import add_user_permission

		from erpnext.mcp.tests._helpers import make_submitted_pi, make_supplier

		frappe.set_user("Administrator")
		cls.supplier_a = make_supplier(f"_MCP Allowed {uuid.uuid4().hex[:6]}")
		cls.supplier_b = make_supplier(f"_MCP Denied {uuid.uuid4().hex[:6]}")
		cls.pi_a = make_submitted_pi(cls.supplier_a, rate=100, qty=1)
		cls.pi_b = make_submitted_pi(cls.supplier_b, rate=200, qty=1)

		if not frappe.db.exists("User", cls.SCOPED_USER):
			u = frappe.new_doc("User")
			u.email = cls.SCOPED_USER
			u.first_name = "Scoped"
			u.send_welcome_email = 0
			u.append("roles", {"role": "Accounts User"})
			u.insert(ignore_permissions=True)
		else:
			u = frappe.get_doc("User", cls.SCOPED_USER)
			if "Accounts User" not in [r.role for r in u.roles]:
				u.append("roles", {"role": "Accounts User"})
				u.save(ignore_permissions=True)

		# Restrict this user to supplier_a only.
		add_user_permission("Supplier", cls.supplier_a, cls.SCOPED_USER, ignore_permissions=True)

	@classmethod
	def tearDownClass(cls):
		# setUpClass commits the seeded Suppliers to disk (see cleanup_seeded_docs),
		# so they survive the class rollback — delete our seeds explicitly. The User
		# Permission references supplier_a, so it must go before the Supplier.
		from erpnext.mcp.tests._helpers import cleanup_seeded_docs

		up = frappe.db.get_value(
			"User Permission",
			{"user": cls.SCOPED_USER, "allow": "Supplier", "for_value": cls.supplier_a},
		)
		cleanup_seeded_docs(
			[
				("User Permission", up),
				("Purchase Invoice", getattr(getattr(cls, "pi_a", None), "name", None)),
				("Purchase Invoice", getattr(getattr(cls, "pi_b", None), "name", None)),
				("Supplier", getattr(cls, "supplier_a", None)),
				("Supplier", getattr(cls, "supplier_b", None)),
			]
		)
		super().tearDownClass()

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_permitted_names_scoped_to_allowed_supplier(self):
		frappe.set_user(self.SCOPED_USER)
		names = permitted_names("Purchase Invoice", filters={}, limit=500)
		self.assertIn(self.pi_a.name, names)
		self.assertNotIn(self.pi_b.name, names)

	def test_vendor_balance_no_leak_for_denied_supplier(self):
		frappe.set_user(self.SCOPED_USER)
		out = GetVendorBalance().execute(GetVendorBalance.input_model(supplier=self.supplier_b))
		# The user cannot see supplier_b's invoices, so the aggregate is empty.
		self.assertEqual(out["open_invoice_count"], 0)
		self.assertEqual(out["outstanding_total"], 0.0)

	def test_vendor_balance_visible_for_allowed_supplier(self):
		frappe.set_user(self.SCOPED_USER)
		out = GetVendorBalance().execute(GetVendorBalance.input_model(supplier=self.supplier_a))
		self.assertEqual(out["open_invoice_count"], 1)
		self.assertAlmostEqual(out["outstanding_total"], 100.0, places=2)
