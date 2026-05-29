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
		with self.assertRaises(frappe.PermissionError):
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
