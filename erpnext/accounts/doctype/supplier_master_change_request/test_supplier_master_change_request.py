# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""Tests for the Tier-3 Supplier Master Change Request (spec 05).

Covers the gated create flow: approve (as a different user) creates the Supplier
from the allow-listed payload and re-validates the originating capture; the SoD
backstop (requester != approver); the approver-role gate; idempotency; and reject.
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from erpnext.accounts.doctype.ap_invoice_capture.ap_invoice_capture import (
	STATUS_CONFIRMED,
	VALIDATION_STATUS_BLOCKED,
	VALIDATION_STATUS_VALIDATED,
	CaptureApprovalError,
	confirm_extracted_fields,
	create_capture_from_file,
	queue_supplier_create_request,
	run_fake_extraction,
	validate_for_purchase_invoice,
)
from erpnext.accounts.doctype.ap_invoice_capture.test_ap_invoice_capture import _make_file
from erpnext.accounts.doctype.supplier_master_change_request.supplier_master_change_request import (
	STATE_POSTED,
	STATE_REJECTED,
	approve_supplier_master_change_request,
	reject_supplier_master_change_request,
)

EXTRA_TEST_RECORD_DEPENDENCIES = ["Supplier", "Item", "Cost Center"]


def _make_user(roles: list[str]) -> str:
	email = f"smcr-{frappe.generate_hash(length=8)}@example.com"
	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": "SMCR Test",
			"send_welcome_email": 0,
			"roles": [{"role": r} for r in roles],
		}
	)
	user.insert(ignore_permissions=True)
	return email


class TestSupplierMasterChangeRequest(IntegrationTestCase):
	def setUp(self):
		# Pin the deterministic Fake OCR provider so run_fake_extraction never calls
		# a live provider on the synthetic blank PDF (spec 01 test-env note). Rolled
		# back per-test in tearDown, so the site's real provider is untouched.
		frappe.db.set_single_value(
			"AP Closed Loop Settings", "ocr_provider", "Fake (Deterministic)"
		)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def _blocked_capture(self, unknown_name: str):
		"""A Confirmed Stream-I capture whose supplier is unknown -> BLOCKED."""
		f = _make_file(f"smcr-{frappe.generate_hash(length=6)}.pdf")
		capture = create_capture_from_file(file_doc=f, source_context="SMCR test")
		run_fake_extraction(capture)
		capture.reload()
		confirm_extracted_fields(
			capture,
			corrections={"supplier": unknown_name, "currency": "INR", "total_amount": "500.00"},
			reviewer="Administrator",
		)
		capture.reload()
		self.assertEqual(capture.status, STATUS_CONFIRMED)
		validate_for_purchase_invoice(capture)
		capture.reload()
		self.assertEqual(capture.validation_status, VALIDATION_STATUS_BLOCKED)
		return capture

	def _create_request(self, capture, unknown_name, requester):
		frappe.set_user(requester)
		try:
			payload = {
				"supplier_name": unknown_name,
				"supplier_group": frappe.db.get_value("Supplier", "_Test Supplier", "supplier_group")
				or "All Supplier Groups",
				"supplier_type": "Company",
			}
			req_name = queue_supplier_create_request(capture.name, unknown_name, payload)
		finally:
			frappe.set_user("Administrator")
		return req_name

	# AC-05-18: approve (as a different user) creates Supplier + re-validates capture.
	def test_approve_creates_supplier_and_revalidates(self):
		requester = _make_user(["Accounts User", "Accounts Manager"])
		approver = _make_user(["Accounts Manager"])
		unknown_name = f"NewVendor {frappe.generate_hash(length=6)}"
		capture = self._blocked_capture(unknown_name)
		req_name = self._create_request(capture, unknown_name, requester)
		capture.reload()
		self.assertEqual(capture.supplier_change_request, req_name)

		supplier_count_before = frappe.db.count("Supplier")
		frappe.set_user(approver)
		approve_supplier_master_change_request(req_name)
		frappe.set_user("Administrator")

		req = frappe.get_doc("Supplier Master Change Request", req_name)
		self.assertEqual(req.workflow_state, STATE_POSTED)
		self.assertTrue(req.created_supplier)
		self.assertEqual(frappe.db.count("Supplier"), supplier_count_before + 1)

		capture.reload()
		self.assertEqual(capture.validation_status, VALIDATION_STATUS_VALIDATED)
		self.assertEqual(capture.matched_supplier, req.created_supplier)

	# AC-05-19: SoD — the requester may not approve their own request.
	def test_requester_cannot_approve_own_request(self):
		requester = _make_user(["Accounts User", "Accounts Manager"])
		unknown_name = f"SelfVendor {frappe.generate_hash(length=6)}"
		capture = self._blocked_capture(unknown_name)
		req_name = self._create_request(capture, unknown_name, requester)

		supplier_count_before = frappe.db.count("Supplier")
		frappe.set_user(requester)
		with self.assertRaises(CaptureApprovalError):
			approve_supplier_master_change_request(req_name)
		frappe.set_user("Administrator")
		# No Supplier created on the SoD failure.
		self.assertEqual(frappe.db.count("Supplier"), supplier_count_before)

	# AC-05-20: a user lacking the approver role -> PermissionError.
	def test_approver_role_gate(self):
		requester = _make_user(["Accounts User", "Accounts Manager"])
		no_role = _make_user(["Accounts User"])  # lacks Accounts Manager
		unknown_name = f"GateVendor {frappe.generate_hash(length=6)}"
		capture = self._blocked_capture(unknown_name)
		req_name = self._create_request(capture, unknown_name, requester)

		frappe.set_user(no_role)
		with self.assertRaises(frappe.PermissionError):
			approve_supplier_master_change_request(req_name)
		frappe.set_user("Administrator")

	# AC-05-21: re-approving a Posted request does not create a second Supplier.
	def test_approve_is_idempotent(self):
		requester = _make_user(["Accounts User", "Accounts Manager"])
		approver = _make_user(["Accounts Manager"])
		unknown_name = f"IdemVendor {frappe.generate_hash(length=6)}"
		capture = self._blocked_capture(unknown_name)
		req_name = self._create_request(capture, unknown_name, requester)

		frappe.set_user(approver)
		approve_supplier_master_change_request(req_name)
		count_after_first = frappe.db.count("Supplier")
		# Second call is a no-op.
		approve_supplier_master_change_request(req_name)
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.count("Supplier"), count_after_first)

	# Edge: reject keeps the Stream-I capture BLOCKED and records the reason.
	def test_reject_keeps_capture_blocked(self):
		requester = _make_user(["Accounts User", "Accounts Manager"])
		approver = _make_user(["Accounts Manager"])
		unknown_name = f"RejectVendor {frappe.generate_hash(length=6)}"
		capture = self._blocked_capture(unknown_name)
		req_name = self._create_request(capture, unknown_name, requester)

		supplier_count_before = frappe.db.count("Supplier")
		frappe.set_user(approver)
		reject_supplier_master_change_request(req_name, reason="Not a real vendor")
		frappe.set_user("Administrator")

		req = frappe.get_doc("Supplier Master Change Request", req_name)
		self.assertEqual(req.workflow_state, STATE_REJECTED)
		self.assertEqual(req.decision_reason, "Not a real vendor")
		self.assertEqual(frappe.db.count("Supplier"), supplier_count_before)
		capture.reload()
		self.assertEqual(capture.validation_status, VALIDATION_STATUS_BLOCKED)

	# Edge: blank approver_role on the request falls back to the settings default.
	def test_blank_approver_role_falls_back_to_default(self):
		requester = _make_user(["Accounts User", "Accounts Manager"])
		approver = _make_user(["Accounts Manager"])
		unknown_name = f"FallbackVendor {frappe.generate_hash(length=6)}"
		capture = self._blocked_capture(unknown_name)
		req_name = self._create_request(capture, unknown_name, requester)
		# Clear the stamped approver_role to exercise the fallback path.
		frappe.db.set_value("Supplier Master Change Request", req_name, "approver_role", None)

		frappe.set_user(approver)
		approve_supplier_master_change_request(req_name)
		frappe.set_user("Administrator")
		req = frappe.get_doc("Supplier Master Change Request", req_name)
		self.assertEqual(req.workflow_state, STATE_POSTED)
