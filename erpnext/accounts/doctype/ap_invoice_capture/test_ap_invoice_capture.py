# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

from io import BytesIO
import json
import os
import shutil
import unittest

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, flt, getdate, now_datetime, today
from pypdf import PdfWriter

try:
	import imagehash  # noqa: F401
	from PIL import Image as _PILImage  # noqa: F401

	_IMAGEHASH_AVAILABLE = True
except ImportError:
	_IMAGEHASH_AVAILABLE = False

# The PDF branch of _compute_phash additionally shells out to the poppler binary
# via pdf2image; gate those tests so the suite stays green on a bench without it.
_POPPLER_AVAILABLE = _IMAGEHASH_AVAILABLE and shutil.which("pdftoppm") is not None

from erpnext.accounts.doctype.ap_invoice_capture.ap_invoice_capture import (
	APPROVAL_SOURCE_DEFAULT,
	APPROVAL_STATUS_AUTO_APPROVED,
	APPROVAL_STATUS_MANAGER_APPROVED,
	APPROVAL_STATUS_NOT_REQUIRED,
	APPROVAL_STATUS_PENDING_MANAGER,
	APPROVAL_STATUS_REJECTED,
	AUTO_APPROVAL_THRESHOLD_DEFAULT,
	FAKE_OCR_PROVIDER,
	INTAKE_MANUAL_UPLOAD,
	MANDATORY_HEADER_FIELDS,
	MANAGER_APPROVAL_ROLE_DEFAULT,
	MOCK_CLEARING_ACCOUNT_DEFAULT,
	MOCK_PAYMENT_PREFIX,
	MOCK_PAYMENT_PROVIDER,
	MOCK_PAYMENT_REMARK,
	OCR_STATUS_CONFIRMED,
	OCR_STATUS_NEEDS_CORRECTION,
	OCR_STATUS_NOT_EXTRACTED,
	OCR_STATUS_PROPOSED,
	PAYMENT_READINESS_BLOCKED,
	PAYMENT_READINESS_NOT_READY,
	PAYMENT_READINESS_READY,
	PAYMENT_LIFECYCLE_CLOSED,
	PAYMENT_LIFECYCLE_NOT_REQUESTED,
	PROMOTION_STATUS_NOT_PROMOTED,
	PROMOTION_STATUS_PROMOTED,
	PURCHASE_REF_NON_PO,
	PURCHASE_REF_PURCHASE_ORDER,
	PURCHASE_REF_PURCHASE_RECEIPT,
	STATUS_CONFIRMED,
	STATUS_DUPLICATE,
	STATUS_NEEDS_CORRECTION,
	STATUS_PENDING_REVIEW,
	STATUS_PROPOSED,
	STATUS_UNSUPPORTED,
	SUPPLIER_MATCH_ALIAS,
	SUPPLIER_MATCH_AMBIGUOUS,
	SUPPLIER_MATCH_MATCHED,
	SUPPLIER_MATCH_UNKNOWN,
	SUPPLIER_TIER_ALIAS,
	SUPPLIER_TIER_EXACT,
	SUPPLIER_TIER_FUZZY,
	SUPPLIER_TIER_NONE,
	STREAM_INVOICE,
	STREAM_RECEIPT,
	SUPPORTED_EXTENSIONS,
	VALIDATION_SOURCE_DEFAULT,
	VALIDATION_STATUS_BLOCKED,
	VALIDATION_STATUS_NOT_VALIDATED,
	VALIDATION_STATUS_VALIDATED,
	AmbiguousSourceError,
	CaptureApprovalError,
	CapturePaymentError,
	CapturePromotionError,
	CaptureValidationError,
	OCRExtractionError,
	build_closure_evidence,
	confirm_extracted_fields,
	create_capture_from_file,
	detect_duplicates_for,
	get_ap_lifecycle_rows,
	get_manager_approval_queue,
	is_payment_blocked,
	is_ready_for_payment,
	issue_mock_payment,
	promote_to_purchase_invoice,
	queue_supplier_create_request,
	record_manager_decision,
	request_approval,
	run_fake_extraction,
	validate_for_purchase_invoice,
	apply_coding_profile_for,
	is_fully_coded,
	CODING_STATUS_AMBIGUOUS,
	CODING_STATUS_CODED,
	CODING_STATUS_FLAGGED,
	CODING_STATUS_PENDING,
	classify_document_type,
	promote_already_paid,
	DOCUMENT_TYPE_UNPAID_BILL,
	DOCUMENT_TYPE_ALREADY_PAID,
	DOCUMENT_TYPE_EMPLOYEE_REIMBURSEMENT,
	DOCUMENT_TYPE_MANUAL_REVIEW,
	STATUS_MANUAL_REVIEW,
	STREAM_AGREEMENT_AGREE,
	STREAM_AGREEMENT_DISAGREE,
	STREAM_AGREEMENT_UNCONFIRMED,
	CLASSIFIED_STREAM_I,
	CLASSIFIED_STREAM_R,
	CLASSIFICATION_SOURCE_OVERRIDE,
	_apply_dimensions_to_row,
	_match_supplier,
	_resolve_supplier,
	three_way_match_for,
	detect_amount_anomaly_for,
	detect_vendor_bank_change_for,
	override_three_way_match,
	has_approved_bank_change,
	refresh_anomaly_baselines,
	_upsert_anomaly_baseline,
	_anomaly_baseline,
	_resolve_gate_config,
	THREE_WAY_MATCH_NOT_CHECKED,
	THREE_WAY_MATCH_NOT_APPLICABLE,
	THREE_WAY_MATCH_MATCHED,
	THREE_WAY_MATCH_EXCEPTION,
	THREE_WAY_MATCH_OVERRIDE,
	ANOMALY_NORMAL,
	ANOMALY_ANOMALOUS,
	ANOMALY_INSUFFICIENT_HISTORY,
	APPROVAL_STATUS_NEEDS_REVIEW,
	ROUTING_AXIS_CONFIDENCE,
	ROUTING_AXIS_VALIDATION_FLAG,
	_evaluate_routing_signals,
	_resolve_approval_threshold,
	reroute_after_review,
	STATUS_REJECTED,
	reject_capture,
	reopen_capture,
	emit_review_event,
	REVIEW_ACTION_REJECTED,
	REVIEW_ACTION_FIELD_CORRECTED,
	REVIEW_ACTION_CODING_COMPLETED,
	REVIEW_ACTION_CLASSIFIED_OTHER,
	ROOT_CAUSE_POLICY_VIOLATION,
	REJECTION_ACTION_REJECTED,
	REJECTION_ACTION_REOPENED,
	_evaluate_confirm_signals,
	auto_confirm_extracted_fields_for,
	_derive_coding_from_history,
	ROOT_CAUSE_STREAM_MISTAG,
	resolve_approver_role,
	reconcile_bank_for,
	PAYMENT_LIFECYCLE_BANK_CLEARED,
	build_audit_trail_for,
	enforce_retention_policy,
	_resolve_mock_pay_account,
	MOCK_CLEARING_ACCOUNT_DEFAULT,
	CODING_SOURCE_NATIVE_DEFAULT,
	CODING_SOURCE_DEFAULT,
	get_coding_review_queue_for,
)
from erpnext.accounts.doctype.ap_invoice_capture import ap_invoice_capture as _apic_mod

EXTRA_TEST_RECORD_DEPENDENCIES = ["Supplier", "Item", "Cost Center"]

_PROMOTION_DEFAULTS = {
	"company": "_Test Company",
	"item_code": "_Test Item",
	"warehouse": "_Test Warehouse - _TC",
	"expense_account": "_Test Account Cost for Goods Sold - _TC",
	"cost_center": "_Test Cost Center - _TC",
	"uom": "_Test UOM",
	"qty": 1,
}

MINIMAL_PNG = (
	b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
	b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\xf8\x0f"
	b"\x00\x01\x01\x01\x00\x18\xdd\x8d\xb0\x00\x00\x00\x00IEND\xaeB`\x82"
)
MINIMAL_JPEG = (
	b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xff\xdb"
	b"\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r"
	b"\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c "
	b"$.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\xff\xc0\x00\x0b\x08\x00\x01"
	b"\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x14\x00\x01\x00\x00\x00\x00\x00\x00"
	b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x08\xff\xc4\x00\x14\x10\x01"
	b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff"
	b"\xda\x00\x08\x01\x01\x00\x00?\x00\x7f\xff\xd9"
)


def _content_for(filename: str) -> bytes:
	extension = filename.rsplit(".", 1)[-1].lower()
	if extension == "pdf":
		buffer = BytesIO()
		writer = PdfWriter()
		writer.add_blank_page(width=1, height=1)
		writer.write(buffer)
		return buffer.getvalue()
	if extension == "png":
		return MINIMAL_PNG
	if extension in ("jpg", "jpeg"):
		return MINIMAL_JPEG
	if extension == "docx":
		return b"PK\x03\x04"
	if extension == "exe":
		return b"MZ"
	return b"test"


def _make_file(filename: str, content: bytes | None = None) -> "frappe.Document":
	"""Create a private Frappe File record with the given filename.

	Frappe's File DocType validates PDF/image content during insert, so
	supported-format fixtures need minimal valid bytes.
	"""

	file_doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": filename,
			"is_private": 1,
			"content": content or _content_for(filename),
		}
	)
	file_doc.insert(ignore_permissions=True)
	return file_doc


class TestAPInvoiceCapture(IntegrationTestCase):
	def tearDown(self):
		frappe.db.rollback()

	# AC-I1: a supported source image must create a reviewable capture.
	def test_supported_pdf_creates_pending_review_capture(self):
		f = _make_file("invoice-001.pdf")

		capture = create_capture_from_file(file_doc=f, source_context="Manual test upload")

		self.assertEqual(capture.intake_channel, INTAKE_MANUAL_UPLOAD)
		self.assertEqual(capture.status, STATUS_PENDING_REVIEW)
		self.assertEqual(capture.file_extension, "pdf")
		self.assertEqual(capture.is_supported_format, 1)
		# AC-I3: clerk must see action-required + received_at + source context.
		self.assertEqual(capture.action_required, 1)
		self.assertTrue(capture.action_required_reason)
		self.assertTrue(capture.received_at)
		self.assertEqual(capture.source_context, "Manual test upload")

	def test_supported_extensions_are_case_insensitive(self):
		for filename, ext in [
			("Scan.PNG", "png"),
			("receipt.JPG", "jpg"),
			("Bill.Jpeg", "jpeg"),
			("doc.PDF", "pdf"),
		]:
			with self.subTest(filename=filename):
				f = _make_file(filename)
				capture = create_capture_from_file(file_doc=f)
				self.assertEqual(capture.file_extension, ext)
				self.assertIn(capture.file_extension, SUPPORTED_EXTENSIONS)
				self.assertEqual(capture.is_supported_format, 1)
				self.assertEqual(capture.status, STATUS_PENDING_REVIEW)

	# AC-I2: original File / source must remain linked to the capture.
	def test_source_file_link_and_filename_are_preserved(self):
		f = _make_file("preserve-me.pdf")

		capture = create_capture_from_file(file_doc=f)

		self.assertEqual(capture.source_file, f.name)
		self.assertEqual(capture.source_filename, "preserve-me.pdf")
		# URL fetched from the File record so the capture is traceable
		# back to the original artifact in storage.
		self.assertTrue(capture.source_file_url)
		self.assertEqual(capture.source_file_url, f.file_url)

		# File record still exists independently of the capture.
		self.assertTrue(frappe.db.exists("File", f.name))

	def test_capture_accepts_raw_url_when_no_file_record(self):
		capture = create_capture_from_file(
			file_url="https://example.invalid/uploads/ext-invoice.pdf",
			file_name="ext-invoice.pdf",
		)

		self.assertIsNone(capture.source_file)
		self.assertEqual(capture.source_file_url, "https://example.invalid/uploads/ext-invoice.pdf")
		self.assertEqual(capture.source_filename, "ext-invoice.pdf")
		self.assertEqual(capture.status, STATUS_PENDING_REVIEW)
		self.assertEqual(capture.is_supported_format, 1)

	# AC-I4: unsupported / ambiguous artifacts must be blocked, not silent.
	def test_unsupported_extension_is_flagged_and_blocked(self):
		f = _make_file("ransom.exe", content=b"MZ")

		capture = create_capture_from_file(file_doc=f)

		self.assertEqual(capture.status, STATUS_UNSUPPORTED)
		self.assertEqual(capture.is_supported_format, 0)
		self.assertEqual(capture.action_required, 1)
		self.assertTrue(capture.validation_message)
		self.assertIn("Unsupported", capture.validation_message)

	def test_missing_source_reference_is_rejected(self):
		with self.assertRaises(AmbiguousSourceError):
			create_capture_from_file(file_name="anonymous.pdf")

	# AC-I4: intake must NOT silently create any accounting/payment record.
	def test_intake_does_not_create_accounting_artifacts(self):
		pi_before = frappe.db.count("Purchase Invoice")
		pe_before = frappe.db.count("Payment Entry")
		bt_before = (
			frappe.db.count("Bank Transaction")
			if frappe.db.exists("DocType", "Bank Transaction")
			else 0
		)

		f_ok = _make_file("happy-path.pdf")
		create_capture_from_file(file_doc=f_ok)

		f_bad = _make_file("not-an-invoice.docx")
		create_capture_from_file(file_doc=f_bad)

		self.assertEqual(frappe.db.count("Purchase Invoice"), pi_before)
		self.assertEqual(frappe.db.count("Payment Entry"), pe_before)
		if frappe.db.exists("DocType", "Bank Transaction"):
			self.assertEqual(frappe.db.count("Bank Transaction"), bt_before)

	# AC-I3: status/action-required fields must be queryable for AP clerk views.
	def test_capture_is_visible_to_ap_clerk_via_list(self):
		f = _make_file("listable.pdf")
		capture = create_capture_from_file(file_doc=f)

		rows = frappe.get_all(
			"AP Invoice Capture",
			filters={"name": capture.name},
			fields=[
				"name",
				"source_filename",
				"status",
				"action_required",
				"received_at",
				"intake_channel",
				"is_supported_format",
			],
		)
		self.assertEqual(len(rows), 1)
		row = rows[0]
		self.assertEqual(row.status, STATUS_PENDING_REVIEW)
		self.assertEqual(row.action_required, 1)
		self.assertEqual(row.intake_channel, INTAKE_MANUAL_UPLOAD)
		self.assertEqual(row.is_supported_format, 1)
		self.assertTrue(row.received_at)


class TestAPInvoiceCaptureOCRReview(IntegrationTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def _fresh_capture(self, filename: str = "ocr-invoice.pdf"):
		f = _make_file(filename)
		return create_capture_from_file(file_doc=f, source_context="OCR test")

	# AC-O1 / AC-E2E5: extraction proposes all mandatory header fields for a
	# clean invoice and the proposal is deterministic across runs.
	def test_fake_extraction_proposes_all_mandatory_fields(self):
		capture = self._fresh_capture("clean-invoice.pdf")

		run_fake_extraction(capture)
		capture.reload()

		self.assertEqual(capture.ocr_provider, FAKE_OCR_PROVIDER)
		self.assertEqual(capture.ocr_status, OCR_STATUS_PROPOSED)
		self.assertEqual(capture.status, STATUS_PROPOSED)
		self.assertTrue(capture.ocr_extracted_at)
		self.assertTrue(capture.proposed_supplier)
		self.assertTrue(capture.proposed_supplier_invoice_no)
		self.assertTrue(capture.proposed_invoice_date)
		self.assertGreater(capture.proposed_total_amount or 0, 0)
		self.assertTrue(capture.proposed_currency)
		self.assertFalse(capture.proposed_missing_fields)
		# Raw response is preserved verbatim for auditability.
		self.assertIn("fake-deterministic", capture.ocr_raw_response)

	def test_fake_extraction_is_deterministic_across_runs(self):
		a = self._fresh_capture("deterministic-a.pdf")

		run_fake_extraction(a)
		a.reload()
		first = (
			a.proposed_supplier,
			a.proposed_supplier_invoice_no,
			a.proposed_invoice_date,
			a.proposed_total_amount,
			a.proposed_currency,
		)

		run_fake_extraction(a)
		a.reload()

		# Same capture/source reference -> same proposal values.
		self.assertEqual(
			first,
			(
				a.proposed_supplier,
				a.proposed_supplier_invoice_no,
				a.proposed_invoice_date,
				a.proposed_total_amount,
				a.proposed_currency,
			),
		)

		# A different filename yields a different proposal.
		c = self._fresh_capture("deterministic-b.pdf")
		run_fake_extraction(c)
		c.reload()
		self.assertNotEqual(
			(a.proposed_supplier, a.proposed_supplier_invoice_no, a.proposed_total_amount),
			(c.proposed_supplier, c.proposed_supplier_invoice_no, c.proposed_total_amount),
		)

	# AC-O1 / AC-O4: missing mandatory fields are flagged and block silent progression.
	def test_missing_mandatory_field_via_filename_marker_is_flagged(self):
		capture = self._fresh_capture("scan_missing_supplier.pdf")

		run_fake_extraction(capture)
		capture.reload()

		self.assertIsNone(capture.proposed_supplier)
		self.assertIn("supplier", capture.proposed_missing_fields)
		# Still flagged for AP action; not auto-confirmed.
		self.assertEqual(capture.ocr_status, OCR_STATUS_PROPOSED)
		self.assertEqual(capture.action_required, 1)

	def test_missing_mandatory_field_via_explicit_arg_is_flagged(self):
		capture = self._fresh_capture("explicit-missing.pdf")

		run_fake_extraction(capture, simulate_missing=["total_amount", "currency"])
		capture.reload()

		self.assertIsNone(capture.proposed_currency)
		# proposed_total_amount may be 0.0 when stripped; missing_fields is authoritative.
		self.assertIn("total_amount", capture.proposed_missing_fields)
		self.assertIn("currency", capture.proposed_missing_fields)

	def test_extraction_refuses_unsupported_source(self):
		f = _make_file("not-an-invoice.docx")
		capture = create_capture_from_file(file_doc=f)
		self.assertEqual(capture.status, STATUS_UNSUPPORTED)
		with self.assertRaises(OCRExtractionError):
			run_fake_extraction(capture)

	# AC-O3: proposal must be visible but NOT authoritative; final_* stays empty.
	def test_proposal_does_not_populate_final_fields(self):
		capture = self._fresh_capture("non-authoritative.pdf")

		run_fake_extraction(capture)
		capture.reload()

		self.assertTrue(capture.proposed_supplier)
		# Final / authoritative fields remain empty until AP review.
		self.assertFalse(capture.final_supplier)
		self.assertFalse(capture.final_supplier_invoice_no)
		self.assertFalse(capture.final_invoice_date)
		self.assertFalse(capture.final_total_amount)
		self.assertFalse(capture.final_currency)
		self.assertFalse(capture.reviewed_by)
		self.assertFalse(capture.reviewed_at)

	# AC-O2 / AC-E2E5: AP review confirms proposed values into final_* fields.
	def test_confirm_copies_proposal_into_final_fields(self):
		capture = self._fresh_capture("confirm-clean.pdf")

		run_fake_extraction(capture)
		capture.reload()
		proposed_snapshot = {
			"supplier": capture.proposed_supplier,
			"supplier_invoice_no": capture.proposed_supplier_invoice_no,
			"invoice_date": capture.proposed_invoice_date,
			"total_amount": capture.proposed_total_amount,
			"currency": capture.proposed_currency,
		}

		confirm_extracted_fields(capture, reviewer="Administrator", notes="Looks good.")
		capture.reload()

		self.assertEqual(capture.final_supplier, proposed_snapshot["supplier"])
		self.assertEqual(
			capture.final_supplier_invoice_no, proposed_snapshot["supplier_invoice_no"]
		)
		self.assertEqual(capture.final_invoice_date, proposed_snapshot["invoice_date"])
		self.assertEqual(capture.final_total_amount, proposed_snapshot["total_amount"])
		self.assertEqual(capture.final_currency, proposed_snapshot["currency"])
		self.assertEqual(capture.ocr_status, OCR_STATUS_CONFIRMED)
		self.assertEqual(capture.status, STATUS_CONFIRMED)
		self.assertEqual(capture.action_required, 0)
		self.assertEqual(capture.reviewed_by, "Administrator")
		self.assertTrue(capture.reviewed_at)
		self.assertEqual(capture.review_notes, "Looks good.")

	# AC-E2E5: AP corrections override the proposal.
	def test_confirm_applies_corrections_over_proposal(self):
		capture = self._fresh_capture("with-corrections.pdf")
		run_fake_extraction(capture)
		capture.reload()

		corrections = {
			"supplier": "Manually Keyed Supplier Co.",
			"total_amount": "1234.56",
			"invoice_date": "2026-02-15",
		}
		confirm_extracted_fields(
			capture, corrections=corrections, reviewer="Administrator"
		)
		capture.reload()

		self.assertEqual(capture.final_supplier, "Manually Keyed Supplier Co.")
		self.assertEqual(capture.final_total_amount, 1234.56)
		self.assertEqual(str(capture.final_invoice_date), "2026-02-15")
		# Untouched fields fall back to proposal.
		self.assertEqual(capture.final_currency, capture.proposed_currency)
		self.assertEqual(capture.ocr_status, OCR_STATUS_CONFIRMED)
		self.assertEqual(capture.status, STATUS_CONFIRMED)

	# AC-O4: missing mandatory fields at review time must block silent progression.
	def test_confirm_with_missing_mandatory_field_blocks_progression(self):
		capture = self._fresh_capture("missing_currency-blocker.pdf")
		# Filename marker drops currency from the proposal.
		run_fake_extraction(capture)
		capture.reload()
		self.assertIn("currency", capture.proposed_missing_fields or "")

		# AP confirms without supplying the missing currency.
		confirm_extracted_fields(capture, reviewer="Administrator")
		capture.reload()

		self.assertEqual(capture.ocr_status, OCR_STATUS_NEEDS_CORRECTION)
		self.assertEqual(capture.status, STATUS_NEEDS_CORRECTION)
		self.assertEqual(capture.action_required, 1)
		self.assertTrue(capture.action_required_reason)
		self.assertIn("currency", capture.action_required_reason)
		# Final currency is empty because nothing filled it.
		self.assertFalse(capture.final_currency)

	def test_confirm_resolves_block_when_correction_supplies_missing_field(self):
		capture = self._fresh_capture("missing_supplier-fixable.pdf")
		run_fake_extraction(capture)
		capture.reload()

		# First pass without correction -> blocked.
		confirm_extracted_fields(capture, reviewer="Administrator")
		capture.reload()
		self.assertEqual(capture.status, STATUS_NEEDS_CORRECTION)

		# Second pass supplying the missing field -> confirmed.
		confirm_extracted_fields(
			capture,
			corrections={"supplier": "Late-Added Supplier LLC"},
			reviewer="Administrator",
		)
		capture.reload()
		self.assertEqual(capture.status, STATUS_CONFIRMED)
		self.assertEqual(capture.ocr_status, OCR_STATUS_CONFIRMED)
		self.assertEqual(capture.final_supplier, "Late-Added Supplier LLC")
		self.assertEqual(capture.action_required, 0)

	def test_confirm_requires_extraction_first(self):
		capture = self._fresh_capture("never-extracted.pdf")
		self.assertEqual(capture.ocr_status, OCR_STATUS_NOT_EXTRACTED)
		with self.assertRaises(OCRExtractionError):
			confirm_extracted_fields(capture, reviewer="Administrator")

	# AC-O3: AI attribution is visible.
	def test_ocr_attribution_metadata_is_visible(self):
		capture = self._fresh_capture("attribution.pdf")
		run_fake_extraction(capture)
		capture.reload()

		row = frappe.get_all(
			"AP Invoice Capture",
			filters={"name": capture.name},
			fields=[
				"ocr_provider",
				"ocr_status",
				"ocr_extracted_at",
				"proposed_supplier",
			],
		)[0]
		self.assertEqual(row.ocr_provider, FAKE_OCR_PROVIDER)
		self.assertEqual(row.ocr_status, OCR_STATUS_PROPOSED)
		self.assertTrue(row.ocr_extracted_at)
		self.assertTrue(row.proposed_supplier)

	# AC-I4 carryover: review/confirm must not create any accounting/payment object.
	def test_review_does_not_create_accounting_artifacts(self):
		pi_before = frappe.db.count("Purchase Invoice")
		pe_before = frappe.db.count("Payment Entry")
		bt_before = (
			frappe.db.count("Bank Transaction")
			if frappe.db.exists("DocType", "Bank Transaction")
			else 0
		)

		capture = self._fresh_capture("no-accounting-side-effects.pdf")
		run_fake_extraction(capture)
		confirm_extracted_fields(capture, reviewer="Administrator")

		self.assertEqual(frappe.db.count("Purchase Invoice"), pi_before)
		self.assertEqual(frappe.db.count("Payment Entry"), pe_before)
		if frappe.db.exists("DocType", "Bank Transaction"):
			self.assertEqual(frappe.db.count("Bank Transaction"), bt_before)

	def test_mandatory_header_fields_constant_covers_pilot_scope(self):
		# Guard against accidental scope drift on the AP closed-loop pilot:
		# the mandatory header set must remain exactly the five pilot fields.
		self.assertEqual(
			{name for name, _, _ in MANDATORY_HEADER_FIELDS},
			{"supplier", "supplier_invoice_no", "invoice_date", "total_amount", "currency"},
		)


class TestAPInvoiceCaptureValidationAndPromotion(IntegrationTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def _confirmed_capture(
		self,
		filename: str = "validate-me.pdf",
		supplier: str = "_Test Supplier",
		corrections: dict | None = None,
	):
		f = _make_file(filename)
		capture = create_capture_from_file(file_doc=f, source_context="Validation test")
		run_fake_extraction(capture)
		capture.reload()
		merged = {"supplier": supplier, "currency": "INR"}
		if corrections:
			merged.update(corrections)
		confirm_extracted_fields(capture, corrections=merged, reviewer="Administrator")
		capture.reload()
		self.assertEqual(capture.status, STATUS_CONFIRMED)
		return capture

	# AC-V1 + AC-V4 + AC-V5: known supplier yields a clean validated outcome with audit.
	def test_validate_matches_known_supplier_and_records_audit(self):
		capture = self._confirmed_capture("validate-known-supplier.pdf")

		validate_for_purchase_invoice(capture, source=VALIDATION_SOURCE_DEFAULT)
		capture.reload()

		self.assertEqual(capture.supplier_match_status, SUPPLIER_MATCH_MATCHED)
		self.assertEqual(capture.matched_supplier, "_Test Supplier")
		self.assertEqual(capture.validation_status, VALIDATION_STATUS_VALIDATED)
		self.assertTrue(capture.validation_result)
		self.assertIn("_Test Supplier", capture.validation_result)
		# AC-V5: auditable outcome — who, when, source identifier.
		self.assertEqual(capture.validated_by, "Administrator")
		self.assertTrue(capture.validated_at)
		self.assertEqual(capture.validation_source, VALIDATION_SOURCE_DEFAULT)

	# AC-V1: unknown supplier is flagged/blocked and is NOT auto-created.
	def test_validate_blocks_unknown_supplier_without_auto_create(self):
		unknown_name = "Definitely Not A Real Supplier {0}".format(
			frappe.generate_hash(length=6)
		)
		self.assertFalse(frappe.db.exists("Supplier", unknown_name))
		supplier_count_before = frappe.db.count("Supplier")

		capture = self._confirmed_capture(
			"validate-unknown-supplier.pdf", supplier=unknown_name
		)

		validate_for_purchase_invoice(capture)
		capture.reload()

		self.assertEqual(capture.supplier_match_status, SUPPLIER_MATCH_UNKNOWN)
		self.assertIsNone(capture.matched_supplier)
		self.assertEqual(capture.validation_status, VALIDATION_STATUS_BLOCKED)
		self.assertIn("unknown", capture.validation_result.lower())
		self.assertEqual(capture.action_required, 1)
		# AC-V1 specifically: no Supplier was created behind the AP clerk's back.
		self.assertEqual(frappe.db.count("Supplier"), supplier_count_before)
		self.assertFalse(frappe.db.exists("Supplier", unknown_name))

	# AC-V3: explicit Non-PO classification when no references are supplied.
	def test_validate_classifies_non_po_when_no_references(self):
		capture = self._confirmed_capture("validate-non-po.pdf")

		validate_for_purchase_invoice(capture)
		capture.reload()

		self.assertEqual(capture.purchase_reference_status, PURCHASE_REF_NON_PO)
		self.assertEqual(capture.validation_status, VALIDATION_STATUS_VALIDATED)

	# AC-V3: explicit Purchase Order classification when PO reference is set.
	def test_validate_classifies_purchase_order_reference(self):
		capture = self._confirmed_capture("validate-with-po.pdf")
		# Skip Link target validation: this test asserts the explicit
		# classification of purchase references, not Purchase Order existence.
		capture.purchase_order_reference = "PO-AP-TEST-001"
		capture.flags.ignore_links = True

		validate_for_purchase_invoice(capture)
		capture.reload()

		self.assertEqual(capture.purchase_reference_status, PURCHASE_REF_PURCHASE_ORDER)

	# AC-V3: explicit Purchase Receipt classification when PR reference is set.
	def test_validate_classifies_purchase_receipt_reference(self):
		capture = self._confirmed_capture("validate-with-pr.pdf")
		capture.purchase_receipt_reference = "PR-AP-TEST-001"
		capture.flags.ignore_links = True

		validate_for_purchase_invoice(capture)
		capture.reload()

		self.assertEqual(capture.purchase_reference_status, PURCHASE_REF_PURCHASE_RECEIPT)

	def test_validate_requires_confirmed_status(self):
		f = _make_file("validate-too-early.pdf")
		capture = create_capture_from_file(file_doc=f)
		# Capture is in Pending Review — validation must refuse.
		self.assertEqual(capture.status, STATUS_PENDING_REVIEW)
		with self.assertRaises(CaptureValidationError):
			validate_for_purchase_invoice(capture)

	# AC-V2: a validated capture promotes into a native Purchase Invoice.
	def test_promote_creates_native_purchase_invoice(self):
		capture = self._confirmed_capture(
			"promote-happy.pdf",
			corrections={"total_amount": "250.00", "currency": "INR"},
		)
		validate_for_purchase_invoice(capture)
		capture.reload()
		self.assertEqual(capture.validation_status, VALIDATION_STATUS_VALIDATED)

		pi_count_before = frappe.db.count("Purchase Invoice")
		pi = promote_to_purchase_invoice(capture, defaults=_PROMOTION_DEFAULTS)
		capture.reload()

		# Native Purchase Invoice was created and linked back.
		self.assertEqual(pi.doctype, "Purchase Invoice")
		self.assertTrue(frappe.db.exists("Purchase Invoice", pi.name))
		self.assertEqual(frappe.db.count("Purchase Invoice"), pi_count_before + 1)
		self.assertEqual(capture.purchase_invoice, pi.name)
		self.assertEqual(capture.promotion_status, PROMOTION_STATUS_PROMOTED)
		# Header values flowed from AP-reviewed finals.
		self.assertEqual(pi.supplier, "_Test Supplier")
		self.assertEqual(pi.bill_no, capture.final_supplier_invoice_no)
		self.assertEqual(getdate(pi.bill_date), getdate(capture.final_invoice_date))
		self.assertEqual(pi.currency, "INR")
		# Header-only Phase 1: single default service/item row carries the total.
		self.assertEqual(len(pi.items), 1)
		self.assertEqual(pi.items[0].item_code, "_Test Item")
		self.assertAlmostEqual(float(pi.items[0].rate), 250.00, places=2)

	# AC-V3: explicit purchase reference handling is preserved on the capture
	# through the validation -> promotion handoff (auditable on the capture).
	def test_promote_preserves_purchase_reference_classification(self):
		capture = self._confirmed_capture(
			"promote-with-po.pdf",
			corrections={"total_amount": "99.00"},
		)
		capture.purchase_order_reference = "PO-AP-TEST-PROMOTE"
		capture.flags.ignore_links = True
		validate_for_purchase_invoice(capture)
		capture.reload()
		self.assertEqual(capture.purchase_reference_status, PURCHASE_REF_PURCHASE_ORDER)

		capture.flags.ignore_links = True
		promote_to_purchase_invoice(capture, defaults=_PROMOTION_DEFAULTS)
		capture.reload()

		# Reference remains pinned to the capture for auditability.
		self.assertEqual(capture.purchase_order_reference, "PO-AP-TEST-PROMOTE")
		self.assertEqual(capture.purchase_reference_status, PURCHASE_REF_PURCHASE_ORDER)
		self.assertEqual(capture.promotion_status, PROMOTION_STATUS_PROMOTED)

	# AC-V1: unknown-supplier capture cannot be promoted (blocks at validation).
	def test_promote_blocks_when_validation_failed(self):
		capture = self._confirmed_capture(
			"promote-unknown.pdf",
			supplier="Nobody Inc {0}".format(frappe.generate_hash(length=6)),
		)
		validate_for_purchase_invoice(capture)
		capture.reload()
		self.assertEqual(capture.validation_status, VALIDATION_STATUS_BLOCKED)

		with self.assertRaises(CapturePromotionError):
			promote_to_purchase_invoice(capture, defaults=_PROMOTION_DEFAULTS)

	def test_promote_requires_validation_first(self):
		capture = self._confirmed_capture("promote-without-validation.pdf")
		self.assertEqual(
			capture.validation_status or VALIDATION_STATUS_NOT_VALIDATED,
			VALIDATION_STATUS_NOT_VALIDATED,
		)
		with self.assertRaises(CapturePromotionError):
			promote_to_purchase_invoice(capture, defaults=_PROMOTION_DEFAULTS)

	def test_promote_is_idempotent_guard(self):
		capture = self._confirmed_capture("promote-idempotent.pdf")
		validate_for_purchase_invoice(capture)
		capture.reload()
		promote_to_purchase_invoice(capture, defaults=_PROMOTION_DEFAULTS)
		capture.reload()
		self.assertEqual(capture.promotion_status, PROMOTION_STATUS_PROMOTED)
		# Second promote attempt must refuse rather than silently double-create.
		with self.assertRaises(CapturePromotionError):
			promote_to_purchase_invoice(capture, defaults=_PROMOTION_DEFAULTS)

	# Architecture guardrail: this slice does NOT create Payment Entry or Bank Transaction.
	def test_validation_and_promotion_create_no_payment_artifacts(self):
		pe_before = frappe.db.count("Payment Entry")
		bt_before = (
			frappe.db.count("Bank Transaction")
			if frappe.db.exists("DocType", "Bank Transaction")
			else 0
		)

		capture = self._confirmed_capture("no-payment-artifacts.pdf")
		validate_for_purchase_invoice(capture)
		capture.reload()
		promote_to_purchase_invoice(capture, defaults=_PROMOTION_DEFAULTS)

		self.assertEqual(frappe.db.count("Payment Entry"), pe_before)
		if frappe.db.exists("DocType", "Bank Transaction"):
			self.assertEqual(frappe.db.count("Bank Transaction"), bt_before)

	# AC-V5: validation outcome is queryable / auditable from list views.
	def test_validation_outcome_is_visible_to_ap_clerk_via_list(self):
		capture = self._confirmed_capture("auditable-validation.pdf")
		validate_for_purchase_invoice(capture)

		rows = frappe.get_all(
			"AP Invoice Capture",
			filters={"name": capture.name},
			fields=[
				"name",
				"matched_supplier",
				"supplier_match_status",
				"purchase_reference_status",
				"validation_status",
				"validation_source",
				"validated_by",
				"validated_at",
				"promotion_status",
			],
		)
		self.assertEqual(len(rows), 1)
		row = rows[0]
		self.assertEqual(row.matched_supplier, "_Test Supplier")
		self.assertEqual(row.supplier_match_status, SUPPLIER_MATCH_MATCHED)
		self.assertEqual(row.purchase_reference_status, PURCHASE_REF_NON_PO)
		self.assertEqual(row.validation_status, VALIDATION_STATUS_VALIDATED)
		self.assertEqual(row.validation_source, VALIDATION_SOURCE_DEFAULT)
		self.assertEqual(row.validated_by, "Administrator")
		self.assertTrue(row.validated_at)
		self.assertEqual(row.promotion_status, PROMOTION_STATUS_NOT_PROMOTED)

	# AC-V1: a supplier_name-only match (autoname is by name, but exact-name path
	# is the primary contract); guard the helper handles ambiguity.
	def test_validate_flags_ambiguous_supplier(self):
		# Real ambiguity through the 3-tier resolver: two active aliases match the
		# same candidate but point at different Suppliers (spec 05 §5.3 Tier-1).
		group = (
			frappe.db.get_value("Supplier", "_Test Supplier", "supplier_group")
			or "All Supplier Groups"
		)
		token = frappe.generate_hash(length=6)
		names = []
		for prefix in ("Alpha", "Beta"):
			doc = frappe.get_doc(
				{
					"doctype": "Supplier",
					"supplier_name": f"{prefix} {token}",
					"supplier_group": group,
					"supplier_type": "Company",
				}
			)
			doc.insert(ignore_permissions=True)
			names.append(doc.name)
		candidate = f"SHARED {token} PMT 7"
		frappe.get_doc(
			{
				"doctype": "AP Supplier Alias",
				"canonical_supplier": names[0],
				"alias_pattern": f"SHARED {token}*",
				"match_type": "glob",
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "AP Supplier Alias",
				"canonical_supplier": names[1],
				"alias_pattern": f"SHARED {token} PMT*",
				"match_type": "glob",
			}
		).insert(ignore_permissions=True)

		capture = self._confirmed_capture("validate-ambiguous.pdf", supplier=candidate)
		validate_for_purchase_invoice(capture)
		capture.reload()
		self.assertEqual(capture.supplier_match_status, SUPPLIER_MATCH_AMBIGUOUS)
		self.assertEqual(capture.validation_status, VALIDATION_STATUS_BLOCKED)
		self.assertIn("ambiguous", capture.validation_result.lower())


class TestAPInvoiceCaptureApproval(IntegrationTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def _promoted_capture(
		self,
		filename: str = "approval.pdf",
		total_amount: str = "250.00",
	):
		f = _make_file(filename)
		capture = create_capture_from_file(file_doc=f, source_context="Approval test")
		run_fake_extraction(capture)
		capture.reload()
		confirm_extracted_fields(
			capture,
			corrections={
				"supplier": "_Test Supplier",
				"total_amount": total_amount,
				"currency": "INR",
			},
			reviewer="Administrator",
		)
		capture.reload()
		validate_for_purchase_invoice(capture)
		capture.reload()
		promote_to_purchase_invoice(capture, defaults=_PROMOTION_DEFAULTS)
		capture.reload()
		self.assertEqual(capture.promotion_status, PROMOTION_STATUS_PROMOTED)
		self.assertTrue(capture.purchase_invoice)
		return capture

	# AC-A1 / AC-A3 / AC-A4: below-threshold captures auto-approve with audit.
	def test_auto_approval_below_threshold_records_reason_and_decision(self):
		capture = self._promoted_capture("approval-auto.pdf", total_amount="250.00")

		request_approval(capture, threshold=1000, source=APPROVAL_SOURCE_DEFAULT)
		capture.reload()

		self.assertEqual(capture.approval_status, APPROVAL_STATUS_AUTO_APPROVED)
		self.assertEqual(capture.payment_readiness, PAYMENT_READINESS_READY)
		self.assertTrue(is_ready_for_payment(capture))
		self.assertIn("Auto-approved", capture.routing_reason)
		self.assertIn("threshold", capture.routing_reason)
		self.assertEqual(capture.approval_threshold, 1000)
		self.assertEqual(capture.approval_threshold_source, APPROVAL_SOURCE_DEFAULT)
		self.assertEqual(capture.decision_by, "Administrator")
		self.assertTrue(capture.decision_at)
		self.assertEqual(capture.action_required, 0)

	# AC-A2 / AC-A3: above-threshold captures route to manager with visible reason.
	def test_manager_route_above_threshold_records_reason(self):
		capture = self._promoted_capture("approval-manager.pdf", total_amount="1500.00")

		request_approval(capture, threshold=1000)
		capture.reload()

		self.assertEqual(capture.approval_status, APPROVAL_STATUS_PENDING_MANAGER)
		self.assertEqual(capture.payment_readiness, PAYMENT_READINESS_NOT_READY)
		self.assertFalse(is_ready_for_payment(capture))
		self.assertIn("Manager approval required", capture.routing_reason)
		self.assertIn("threshold", capture.routing_reason)
		self.assertEqual(capture.assigned_approver_role, MANAGER_APPROVAL_ROLE_DEFAULT)
		self.assertEqual(capture.action_required, 1)
		self.assertEqual(capture.action_required_reason, "Manager approval required")
		self.assertFalse(capture.decision_by)

	# AC-A4 / AC-A5: manager approval captures actor/timestamp/notes and resumes flow.
	def test_manager_approve_records_audit_and_marks_ready(self):
		capture = self._promoted_capture("approval-approve.pdf", total_amount="1500.00")
		request_approval(capture, threshold=1000)
		capture.reload()

		record_manager_decision(
			capture,
			approve=True,
			actor="Administrator",
			notes="Approved for Phase 1 mock payment.",
		)
		capture.reload()

		self.assertEqual(capture.approval_status, APPROVAL_STATUS_MANAGER_APPROVED)
		self.assertEqual(capture.payment_readiness, PAYMENT_READINESS_READY)
		self.assertTrue(is_ready_for_payment(capture))
		self.assertEqual(capture.decision_by, "Administrator")
		self.assertTrue(capture.decision_at)
		self.assertEqual(capture.decision_notes, "Approved for Phase 1 mock payment.")
		self.assertEqual(capture.action_required, 0)

	# AC-A4 / AC-A6: rejection captures audit and blocks the payment handoff.
	def test_manager_reject_records_audit_and_blocks_payment(self):
		capture = self._promoted_capture("approval-reject.pdf", total_amount="1500.00")
		request_approval(capture, threshold=1000)
		capture.reload()

		record_manager_decision(
			capture,
			approve=False,
			actor="Administrator",
			notes="Rejected: supplier dispute.",
		)
		capture.reload()

		self.assertEqual(capture.approval_status, APPROVAL_STATUS_REJECTED)
		self.assertEqual(capture.payment_readiness, PAYMENT_READINESS_BLOCKED)
		self.assertFalse(is_ready_for_payment(capture))
		self.assertTrue(is_payment_blocked(capture))
		self.assertEqual(capture.decision_by, "Administrator")
		self.assertTrue(capture.decision_at)
		self.assertEqual(capture.decision_notes, "Rejected: supplier dispute.")
		self.assertEqual(capture.action_required, 1)
		self.assertIn("blocked from payment", capture.action_required_reason)

	def test_approval_requires_validated_capture(self):
		f = _make_file("approval-too-early.pdf")
		capture = create_capture_from_file(file_doc=f)

		with self.assertRaises(CaptureApprovalError):
			request_approval(capture)

	def test_approval_requires_promoted_purchase_invoice(self):
		f = _make_file("approval-not-promoted.pdf")
		capture = create_capture_from_file(file_doc=f)
		run_fake_extraction(capture)
		capture.reload()
		confirm_extracted_fields(
			capture,
			corrections={"supplier": "_Test Supplier", "currency": "INR"},
			reviewer="Administrator",
		)
		capture.reload()
		validate_for_purchase_invoice(capture)
		capture.reload()

		with self.assertRaises(CaptureApprovalError):
			request_approval(capture)

	def test_routing_is_idempotent_guard(self):
		capture = self._promoted_capture("approval-idempotent.pdf", total_amount="250.00")
		request_approval(capture, threshold=AUTO_APPROVAL_THRESHOLD_DEFAULT)
		capture.reload()
		self.assertEqual(capture.approval_status, APPROVAL_STATUS_AUTO_APPROVED)

		with self.assertRaises(CaptureApprovalError):
			request_approval(capture, threshold=AUTO_APPROVAL_THRESHOLD_DEFAULT)

	# AC-A6: not-routed and rejected captures are both unavailable to payment issuance.
	def test_rejected_and_unrouted_captures_are_not_ready_for_payment(self):
		unrouted = self._promoted_capture("approval-unrouted.pdf", total_amount="250.00")
		self.assertEqual(
			unrouted.approval_status or APPROVAL_STATUS_NOT_REQUIRED,
			APPROVAL_STATUS_NOT_REQUIRED,
		)
		self.assertFalse(is_ready_for_payment(unrouted))

		rejected = self._promoted_capture("approval-blocked.pdf", total_amount="1500.00")
		request_approval(rejected, threshold=1000)
		record_manager_decision(rejected, approve=False)
		rejected.reload()

		self.assertFalse(is_ready_for_payment(rejected))
		self.assertTrue(is_payment_blocked(rejected))

	# Architecture guardrail: approval routing does not issue payment artifacts.
	def test_approval_creates_no_payment_or_bank_artifacts(self):
		pe_before = frappe.db.count("Payment Entry")
		bt_before = (
			frappe.db.count("Bank Transaction")
			if frappe.db.exists("DocType", "Bank Transaction")
			else 0
		)

		auto = self._promoted_capture("approval-no-payment-auto.pdf", total_amount="250.00")
		request_approval(auto, threshold=1000)

		approved = self._promoted_capture(
			"approval-no-payment-approve.pdf", total_amount="1500.00"
		)
		request_approval(approved, threshold=1000)
		record_manager_decision(approved, approve=True)

		rejected = self._promoted_capture(
			"approval-no-payment-reject.pdf", total_amount="1500.00"
		)
		request_approval(rejected, threshold=1000)
		record_manager_decision(rejected, approve=False)

		self.assertEqual(frappe.db.count("Payment Entry"), pe_before)
		if frappe.db.exists("DocType", "Bank Transaction"):
			self.assertEqual(frappe.db.count("Bank Transaction"), bt_before)

	# AC-A3 / AC-A4: AP Clerk can query reason and decision outcome.
	def test_approval_outcome_is_visible_to_ap_clerk_via_list(self):
		capture = self._promoted_capture("approval-listable.pdf", total_amount="1500.00")
		request_approval(capture, threshold=1000)
		record_manager_decision(capture, approve=True, notes="Reviewed.")
		capture.reload()

		rows = frappe.get_all(
			"AP Invoice Capture",
			filters={"name": capture.name},
			fields=[
				"name",
				"approval_status",
				"routing_reason",
				"assigned_approver_role",
				"decision_by",
				"decision_at",
				"decision_notes",
				"payment_readiness",
			],
		)
		self.assertEqual(len(rows), 1)
		row = rows[0]
		self.assertEqual(row.approval_status, APPROVAL_STATUS_MANAGER_APPROVED)
		self.assertIn("Manager approval required", row.routing_reason)
		self.assertEqual(row.assigned_approver_role, MANAGER_APPROVAL_ROLE_DEFAULT)
		self.assertEqual(row.decision_by, "Administrator")
		self.assertTrue(row.decision_at)
		self.assertEqual(row.decision_notes, "Reviewed.")
		self.assertEqual(row.payment_readiness, PAYMENT_READINESS_READY)


class TestAPInvoiceCaptureMockPayment(IntegrationTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def _approved_capture(
		self,
		filename: str = "mock-payment.pdf",
		total_amount: str = "250.00",
		approve: bool = True,
	):
		f = _make_file(filename)
		capture = create_capture_from_file(file_doc=f, source_context="Mock payment test")
		run_fake_extraction(capture)
		capture.reload()
		confirm_extracted_fields(
			capture,
			corrections={
				"supplier": "_Test Supplier",
				"total_amount": total_amount,
				"currency": "INR",
			},
			reviewer="Administrator",
		)
		capture.reload()
		validate_for_purchase_invoice(capture)
		capture.reload()
		promote_to_purchase_invoice(capture, defaults=_PROMOTION_DEFAULTS)
		capture.reload()
		request_approval(capture, threshold=1000)
		capture.reload()
		if capture.approval_status == APPROVAL_STATUS_PENDING_MANAGER:
			record_manager_decision(capture, approve=approve)
			capture.reload()
		return capture

	# AC-P1 / AC-P2 / AC-P3 / AC-P4 / AC-R2: approved capture issues mock PE.
	def test_issue_mock_payment_creates_labeled_payment_entry_and_writeback(self):
		capture = self._approved_capture("mock-payment-happy.pdf", total_amount="250.00")

		pe = issue_mock_payment(capture)
		capture.reload()

		self.assertEqual(pe.doctype, "Payment Entry")
		self.assertEqual(pe.docstatus, 1)
		self.assertEqual(capture.payment_entry, pe.name)
		self.assertEqual(capture.mock_payment_provider, MOCK_PAYMENT_PROVIDER)
		self.assertTrue(capture.mock_payment_reference.startswith(MOCK_PAYMENT_PREFIX))
		self.assertEqual(capture.mock_payment_reference, pe.reference_no)
		self.assertEqual(capture.mock_payment_status, "confirmed-mock")
		self.assertEqual(capture.payment_lifecycle_status, PAYMENT_LIFECYCLE_CLOSED)
		self.assertAlmostEqual(flt(capture.mock_payment_amount), flt(pe.paid_amount), places=2)

		response = json.loads(capture.mock_payment_response)
		self.assertTrue(response["is_mock"])
		self.assertEqual(response["provider"], MOCK_PAYMENT_PROVIDER)
		self.assertEqual(response["payment_entry"], pe.name)
		self.assertEqual(response["purchase_invoice"], capture.purchase_invoice)
		self.assertEqual(response["bank_transaction_count"], 0)

		pe.reload()
		self.assertEqual(pe.remarks, MOCK_PAYMENT_REMARK)
		self.assertIn("MOCK PAYMENT", pe.remarks)
		self.assertEqual(pe.paid_from, MOCK_CLEARING_ACCOUNT_DEFAULT)
		self.assertEqual(pe.references[0].reference_doctype, "Purchase Invoice")
		self.assertEqual(pe.references[0].reference_name, capture.purchase_invoice)

	# AC-P5 / AC-R1: native PI state shows the mock payment closed the invoice.
	def test_issue_mock_payment_updates_native_invoice_state(self):
		capture = self._approved_capture("mock-payment-state.pdf", total_amount="375.00")
		issue_mock_payment(capture)
		capture.reload()

		pi_state = frappe.db.get_value(
			"Purchase Invoice",
			capture.purchase_invoice,
			["docstatus", "status", "outstanding_amount"],
			as_dict=True,
		)
		self.assertEqual(pi_state.docstatus, 1)
		self.assertEqual(pi_state.status, "Paid")
		self.assertEqual(flt(pi_state.outstanding_amount), 0.0)
		self.assertEqual(capture.payment_lifecycle_status, PAYMENT_LIFECYCLE_CLOSED)

	def test_issue_mock_payment_requires_approved_ready_capture(self):
		capture = self._approved_capture(
			"mock-payment-rejected.pdf", total_amount="1500.00", approve=False
		)
		self.assertTrue(is_payment_blocked(capture))

		with self.assertRaises(CapturePaymentError):
			issue_mock_payment(capture)

		capture.reload()
		self.assertFalse(capture.payment_entry)
		self.assertNotEqual(capture.payment_lifecycle_status, PAYMENT_LIFECYCLE_CLOSED)

	def test_issue_mock_payment_is_idempotent_guard(self):
		capture = self._approved_capture("mock-payment-idempotent.pdf", total_amount="250.00")
		issue_mock_payment(capture)
		capture.reload()

		with self.assertRaises(CapturePaymentError):
			issue_mock_payment(capture)

	# AC-P2: no Bank Transaction or reconciliation row is created.
	def test_issue_mock_payment_does_not_create_bank_transaction(self):
		bt_before = (
			frappe.db.count("Bank Transaction")
			if frappe.db.exists("DocType", "Bank Transaction")
			else 0
		)
		capture = self._approved_capture("mock-payment-no-bank.pdf", total_amount="250.00")
		issue_mock_payment(capture)
		capture.reload()

		if frappe.db.exists("DocType", "Bank Transaction"):
			self.assertEqual(frappe.db.count("Bank Transaction"), bt_before)
		bt_rows = frappe.db.get_all(
			"Bank Transaction Payments",
			filters={
				"payment_document": "Payment Entry",
				"payment_entry": capture.payment_entry,
			},
		)
		self.assertEqual(bt_rows, [])

	def test_unpaid_approved_capture_reports_not_requested(self):
		capture = self._approved_capture(
			"mock-payment-not-requested.pdf", total_amount="250.00"
		)
		self.assertFalse(capture.payment_entry)
		self.assertEqual(
			capture.payment_lifecycle_status or PAYMENT_LIFECYCLE_NOT_REQUESTED,
			PAYMENT_LIFECYCLE_NOT_REQUESTED,
		)


class TestAPInvoiceCaptureClosureEvidence(IntegrationTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def _capture_through_payment(
		self,
		filename: str = "closure.pdf",
		total_amount: str = "250.00",
	):
		f = _make_file(filename)
		capture = create_capture_from_file(file_doc=f, source_context="Closure test")
		run_fake_extraction(capture)
		capture.reload()
		confirm_extracted_fields(
			capture,
			corrections={
				"supplier": "_Test Supplier",
				"total_amount": total_amount,
				"currency": "INR",
			},
			reviewer="Administrator",
		)
		capture.reload()
		validate_for_purchase_invoice(capture)
		capture.reload()
		promote_to_purchase_invoice(capture, defaults=_PROMOTION_DEFAULTS)
		capture.reload()
		request_approval(capture, threshold=1000)
		capture.reload()
		if capture.approval_status == APPROVAL_STATUS_PENDING_MANAGER:
			record_manager_decision(capture, approve=True, notes="Approved for closure test.")
			capture.reload()
		issue_mock_payment(capture)
		capture.reload()
		return capture

	# AC-R3 / AC-R4 / AC-R5 / AC-R6 / AC-E2E4.
	def test_closure_evidence_reconstructs_full_lifecycle(self):
		capture = self._capture_through_payment("closure-evidence.pdf", total_amount="250.00")

		evidence = build_closure_evidence(capture)

		self.assertEqual(evidence["capture"]["name"], capture.name)
		self.assertEqual(evidence["capture"]["source_filename"], "closure-evidence.pdf")
		self.assertEqual(evidence["ocr"]["proposal"]["supplier"], capture.proposed_supplier)
		self.assertEqual(evidence["ocr"]["final"]["supplier"], "_Test Supplier")
		self.assertEqual(evidence["validation"]["matched_supplier"], "_Test Supplier")
		self.assertEqual(evidence["approval"]["status"], APPROVAL_STATUS_AUTO_APPROVED)
		self.assertEqual(evidence["payment"]["entry"], capture.payment_entry)
		self.assertEqual(evidence["payment"]["provider"], MOCK_PAYMENT_PROVIDER)
		self.assertEqual(evidence["native"]["purchase_invoice"]["name"], capture.purchase_invoice)
		self.assertEqual(evidence["native"]["payment_entry"]["name"], capture.payment_entry)
		self.assertGreater(evidence["native"]["gl_entry_count"], 0)
		self.assertEqual(evidence["native"]["bank_transaction_count"], 0)
		# Dual-signal closure (spec 13/14): after mock payment the capture is SETTLED
		# (internal) but NOT yet bank_cleared (no external bank-feed match) → not closed.
		self.assertTrue(evidence["settled"])
		self.assertFalse(evidence["bank_cleared"])
		self.assertFalse(evidence["closed"])
		self.assertIn("No custom closed flag", evidence["closure_basis"])

	# AC-E2E2: AP Clerk can see lifecycle state and next action fields.
	def test_ap_lifecycle_rows_expose_current_state_and_next_action(self):
		capture = self._capture_through_payment("closure-ap-list.pdf", total_amount="250.00")

		rows = [row for row in get_ap_lifecycle_rows() if row.name == capture.name]
		self.assertEqual(len(rows), 1)
		row = rows[0]
		self.assertEqual(row.source_filename, "closure-ap-list.pdf")
		self.assertEqual(row.action_required, 0)
		self.assertEqual(row.validation_status, VALIDATION_STATUS_VALIDATED)
		self.assertEqual(row.approval_status, APPROVAL_STATUS_AUTO_APPROVED)
		self.assertEqual(row.payment_lifecycle_status, PAYMENT_LIFECYCLE_CLOSED)
		self.assertEqual(row.purchase_invoice, capture.purchase_invoice)
		self.assertEqual(row.payment_entry, capture.payment_entry)

	# AC-E2E3: manager queue includes only approval-required captures.
	def test_manager_queue_is_scoped_to_pending_manager_approvals(self):
		pending = self._capture_through_payment(
			"closure-manager-approved.pdf", total_amount="1500.00"
		)
		# Create a second capture and leave it pending manager approval.
		f = _make_file("closure-manager-pending.pdf")
		candidate = create_capture_from_file(file_doc=f, source_context="Closure queue")
		run_fake_extraction(candidate)
		candidate.reload()
		confirm_extracted_fields(
			candidate,
			corrections={
				"supplier": "_Test Supplier",
				"total_amount": "1500.00",
				"currency": "INR",
			},
			reviewer="Administrator",
		)
		candidate.reload()
		validate_for_purchase_invoice(candidate)
		candidate.reload()
		promote_to_purchase_invoice(candidate, defaults=_PROMOTION_DEFAULTS)
		candidate.reload()
		request_approval(candidate, threshold=1000)
		candidate.reload()
		self.assertEqual(candidate.approval_status, APPROVAL_STATUS_PENDING_MANAGER)

		rows = get_manager_approval_queue()
		names = {row.name for row in rows}
		self.assertIn(candidate.name, names)
		self.assertNotIn(pending.name, names)
		queue_row = next(row for row in rows if row.name == candidate.name)
		self.assertIn("Manager approval required", queue_row.routing_reason)
		self.assertEqual(queue_row.assigned_approver_role, MANAGER_APPROVAL_ROLE_DEFAULT)

	# AC-E2E1: full AP happy path is demonstrable through capture evidence.
	def test_capture_happy_path_is_demonstrable_end_to_end(self):
		capture = self._capture_through_payment("closure-e2e.pdf", total_amount="250.00")
		evidence = build_closure_evidence(capture)

		self.assertEqual(evidence["validation"]["status"], VALIDATION_STATUS_VALIDATED)
		self.assertEqual(evidence["approval"]["payment_readiness"], PAYMENT_READINESS_READY)
		self.assertEqual(evidence["payment"]["lifecycle_status"], PAYMENT_LIFECYCLE_CLOSED)
		self.assertTrue(evidence["payment"]["response"]["is_mock"])
		# Settled internally; closure now also needs the external bank-feed match (spec 13/14).
		self.assertTrue(evidence["settled"])
		self.assertFalse(evidence["closed"])


# ---------------------------------------------------------------------------
# Auto-progression cascade
# ---------------------------------------------------------------------------
#
# The cascade pauses at every human-decision point (OCR review, manual
# promote, manager approval) and runs everything else automatically. These
# tests exercise the chain end-to-end via the whitelisted `*_for` wrappers
# rather than the pure functions, since the cascade hangs off the wrappers.
# `frappe.flags.ap_auto_progress_enabled` opts each test into cascading;
# without it, the single-step tests above behave as Brandon designed them.

from erpnext.accounts.doctype.ap_invoice_capture.ap_invoice_capture import (  # noqa: E402
	confirm_extracted_fields_for,
	issue_mock_payment_for,
	promote_to_purchase_invoice_for,
	record_manager_decision_for,
	request_approval_for,
	validate_for_purchase_invoice_for,
)


class TestAPInvoiceCaptureAutoProgress(IntegrationTestCase):
	def setUp(self):
		# Opt this test class into cascade; reset between tests so flag
		# leaks don't pollute other suites that run in the same process.
		frappe.flags.ap_auto_progress_enabled = True

	def tearDown(self):
		frappe.flags.ap_auto_progress_enabled = False
		frappe.db.rollback()

	def test_intake_auto_runs_ocr_via_after_insert(self):
		"""after_insert + cascade should land a supported file at Proposed."""
		f = _make_file("auto-intake.pdf")
		capture = create_capture_from_file(file_doc=f, source_context="auto-intake")
		capture.reload()

		# OCR ran automatically; the capture is now waiting on human review.
		self.assertEqual(capture.ocr_status, OCR_STATUS_PROPOSED)
		self.assertEqual(capture.status, STATUS_PROPOSED)
		self.assertTrue(capture.proposed_supplier)
		self.assertEqual(capture.action_required, 1)

	def test_intake_does_not_cascade_for_unsupported_format(self):
		"""Unsupported uploads must not advance — cascade stops at Unsupported."""
		bad = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "auto-bad.docx",
				"is_private": 1,
				"content": _content_for("auto-bad.docx"),
			}
		)
		bad.insert(ignore_permissions=True)
		capture = create_capture_from_file(file_doc=bad)
		capture.reload()

		self.assertEqual(capture.status, STATUS_UNSUPPORTED)
		self.assertEqual(capture.ocr_status, OCR_STATUS_NOT_EXTRACTED)
		self.assertEqual(capture.action_required, 1)

	def test_confirm_cascades_to_validate(self):
		"""Confirming OCR fields should auto-trigger validation."""
		f = _make_file("auto-confirm.pdf")
		capture = create_capture_from_file(file_doc=f)
		capture.reload()  # status = Proposed after cascade

		confirm_extracted_fields_for(
			capture.name,
			corrections={
				"supplier": "_Test Supplier",
				"total_amount": "250.00",
				"currency": "INR",
			},
		)
		capture.reload()

		self.assertEqual(capture.ocr_status, OCR_STATUS_CONFIRMED)
		self.assertEqual(capture.validation_status, VALIDATION_STATUS_VALIDATED)
		self.assertEqual(capture.matched_supplier, "_Test Supplier")
		self.assertEqual(capture.promotion_status, PROMOTION_STATUS_NOT_PROMOTED)

	def test_cascade_stops_at_validated_until_manual_promote(self):
		"""Validated captures stay parked until a clerk supplies promote defaults."""
		f = _make_file("auto-stop-at-validated.pdf")
		capture = create_capture_from_file(file_doc=f)
		capture.reload()
		confirm_extracted_fields_for(
			capture.name,
			corrections={
				"supplier": "_Test Supplier",
				"total_amount": "250.00",
				"currency": "INR",
			},
		)
		capture.reload()

		# Validated, but no PI yet — the cascade can't promote without defaults.
		self.assertEqual(capture.validation_status, VALIDATION_STATUS_VALIDATED)
		self.assertEqual(capture.promotion_status, PROMOTION_STATUS_NOT_PROMOTED)
		self.assertFalse(capture.purchase_invoice)

	def test_promote_resumes_cascade_through_auto_approval_and_payment(self):
		"""Auto-approval (<= threshold) captures should reach Closed after promote."""
		# Spec 12: only an auto-pay-eligible vendor flows approved → paid hands-free.
		frappe.db.set_value("Supplier", "_Test Supplier", "auto_pay_eligible", 1)
		f = _make_file("auto-cascade-small.pdf")
		capture = create_capture_from_file(file_doc=f)
		capture.reload()
		confirm_extracted_fields_for(
			capture.name,
			corrections={
				"supplier": "_Test Supplier",
				"total_amount": "250.00",
				"currency": "INR",
			},
		)
		capture.reload()

		# Manual seam: clerk clicks Promote with defaults. Cascade should then
		# advance through approval routing and mock-payment issuance.
		promote_to_purchase_invoice_for(capture.name, defaults=_PROMOTION_DEFAULTS)
		capture.reload()

		self.assertEqual(capture.promotion_status, PROMOTION_STATUS_PROMOTED)
		self.assertEqual(capture.approval_status, APPROVAL_STATUS_AUTO_APPROVED)
		self.assertEqual(capture.payment_readiness, PAYMENT_READINESS_READY)
		self.assertTrue(capture.payment_entry)
		self.assertEqual(capture.payment_lifecycle_status, PAYMENT_LIFECYCLE_CLOSED)

	def test_over_threshold_pauses_at_pending_manager(self):
		"""Over-threshold captures stop at Pending Manager — no auto-payment."""
		f = _make_file("auto-cascade-big.pdf")
		capture = create_capture_from_file(file_doc=f)
		capture.reload()
		confirm_extracted_fields_for(
			capture.name,
			corrections={
				"supplier": "_Test Supplier",
				"total_amount": "1500.00",
				"currency": "INR",
			},
		)
		capture.reload()
		promote_to_purchase_invoice_for(capture.name, defaults=_PROMOTION_DEFAULTS)
		capture.reload()

		# Cascade routed to manager, then paused — no PE.
		self.assertEqual(capture.approval_status, APPROVAL_STATUS_PENDING_MANAGER)
		self.assertEqual(capture.payment_readiness, PAYMENT_READINESS_NOT_READY)
		self.assertFalse(capture.payment_entry)

	def test_manager_approve_resumes_cascade_to_payment(self):
		"""Manager approve resumes the cascade through to Closed."""
		# Spec 12: only an auto-pay-eligible vendor flows approved → paid hands-free.
		frappe.db.set_value("Supplier", "_Test Supplier", "auto_pay_eligible", 1)
		f = _make_file("auto-mgr-approve.pdf")
		capture = create_capture_from_file(file_doc=f)
		capture.reload()
		confirm_extracted_fields_for(
			capture.name,
			corrections={
				"supplier": "_Test Supplier",
				"total_amount": "1500.00",
				"currency": "INR",
			},
		)
		capture.reload()
		promote_to_purchase_invoice_for(capture.name, defaults=_PROMOTION_DEFAULTS)
		capture.reload()
		self.assertEqual(capture.approval_status, APPROVAL_STATUS_PENDING_MANAGER)

		record_manager_decision_for(capture.name, approve=True, notes="ok via cascade")
		capture.reload()

		self.assertEqual(capture.approval_status, APPROVAL_STATUS_MANAGER_APPROVED)
		self.assertTrue(capture.payment_entry)
		self.assertEqual(capture.payment_lifecycle_status, PAYMENT_LIFECYCLE_CLOSED)

	def test_manager_reject_blocks_cascade(self):
		"""Manager reject must not auto-trigger payment."""
		f = _make_file("auto-mgr-reject.pdf")
		capture = create_capture_from_file(file_doc=f)
		capture.reload()
		confirm_extracted_fields_for(
			capture.name,
			corrections={
				"supplier": "_Test Supplier",
				"total_amount": "1500.00",
				"currency": "INR",
			},
		)
		capture.reload()
		promote_to_purchase_invoice_for(capture.name, defaults=_PROMOTION_DEFAULTS)
		capture.reload()
		record_manager_decision_for(capture.name, approve=False, notes="rejected by cascade test")
		capture.reload()

		self.assertEqual(capture.approval_status, APPROVAL_STATUS_REJECTED)
		self.assertEqual(capture.payment_readiness, PAYMENT_READINESS_BLOCKED)
		self.assertFalse(capture.payment_entry)

	def test_unknown_supplier_blocks_cascade_at_validate(self):
		"""Cascade must surface a real failure (unknown supplier) via action_required."""
		f = _make_file("auto-unknown-supplier.pdf")
		capture = create_capture_from_file(file_doc=f)
		capture.reload()
		# Confirm with a supplier that doesn't exist as a Supplier record.
		# Validation should fail and the cascade should NOT proceed.
		try:
			confirm_extracted_fields_for(
				capture.name,
				corrections={
					"supplier": "Definitely Not A Real Supplier",
					"total_amount": "250.00",
					"currency": "INR",
				},
			)
		except CaptureValidationError:
			pass  # expected — validate raises on unknown supplier
		capture.reload()

		self.assertEqual(capture.ocr_status, OCR_STATUS_CONFIRMED)
		self.assertIn(
			capture.supplier_match_status,
			(SUPPLIER_MATCH_UNKNOWN, SUPPLIER_MATCH_AMBIGUOUS),
		)
		self.assertNotEqual(capture.validation_status, VALIDATION_STATUS_VALIDATED)
		self.assertEqual(capture.action_required, 1)
		self.assertFalse(capture.payment_entry)

	def test_skip_flag_disables_cascade(self):
		"""skip_ap_auto_progress short-circuits even when the test-mode opt-in is set."""
		frappe.flags.skip_ap_auto_progress = True
		try:
			f = _make_file("skip-flag.pdf")
			capture = create_capture_from_file(file_doc=f)
			capture.reload()
			# With skip set, OCR should NOT have auto-run.
			self.assertEqual(capture.ocr_status, OCR_STATUS_NOT_EXTRACTED)
			self.assertEqual(capture.status, STATUS_PENDING_REVIEW)
		finally:
			frappe.flags.skip_ap_auto_progress = False


class TestAPInvoiceCaptureDedup(IntegrationTestCase):
	"""Spec 03 — pre-extraction deduplication, detection logic (AC-03-1..10).

	Cascade integration (AC-03-12) lives in TestAPInvoiceCaptureDedupCascade.
	AC-03-11 (get_dedupe_config) lives in test_ap_closed_loop_settings.
	AC-03-13 (fieldtype/index guard) is a post-migrate schema assertion
	(DESCRIBE / SHOW INDEX), not a Python unit test.

	The cascade is OFF in this class (no ap_auto_progress flag), so each test
	drives detect_duplicates_for directly. _compute_phash is neutralised in
	setUp so the exact-pass tests never depend on poppler/imagehash; the two
	perceptual tests override it to return controlled pHash hex strings, so the
	fuzzy-distance logic — not the rasterizer — is under test.
	"""

	def setUp(self):
		from erpnext.accounts.doctype.ap_invoice_capture import ap_invoice_capture as mod

		self.mod = mod
		self._orig_phash = mod._compute_phash
		mod._compute_phash = lambda capture: None
		self._counter = 0
		# Pin the dedupe window so the boundary math is deterministic regardless
		# of site state; rolled back in tearDown.
		frappe.db.set_single_value("AP Closed Loop Settings", "dedupe_enabled", 1)
		frappe.db.set_single_value("AP Closed Loop Settings", "dedupe_window_days", 90)

	def tearDown(self):
		self.mod._compute_phash = self._orig_phash
		frappe.db.rollback()

	def _unique_pdf(self) -> bytes:
		"""A valid but per-call-distinct PDF (distinct page width -> distinct bytes
		-> distinct File content_hash). Tests that need a controlled exact-match key
		override capture.content_hash explicitly."""

		self._counter += 1
		buffer = BytesIO()
		writer = PdfWriter()
		writer.add_blank_page(width=self._counter + 1, height=1)
		writer.write(buffer)
		return buffer.getvalue()

	def _capture(
		self,
		filename,
		*,
		content_hash=None,
		perceptual_hash=None,
		received_at=None,
		status=None,
	):
		f = _make_file(filename, content=self._unique_pdf())
		cap = create_capture_from_file(file_doc=f, received_at=received_at)
		dirty = False
		if content_hash is not None:
			cap.content_hash = content_hash
			dirty = True
		if perceptual_hash is not None:
			cap.perceptual_hash = perceptual_hash
			dirty = True
		if status is not None:
			cap.status = status
			dirty = True
		if dirty:
			cap.save()
		return cap

	# AC-03-1
	def test_exact_duplicate_flags_and_blocks_ocr(self):
		now = now_datetime()
		original = self._capture("dup-a.pdf", content_hash="HASHEXACT1", received_at=now)
		dup = self._capture("dup-b.pdf", content_hash="HASHEXACT1", received_at=now)

		result = detect_duplicates_for(dup)

		self.assertEqual(result["status"], "duplicate")
		self.assertEqual(result["kind"], "exact")
		self.assertEqual(result["original"], original.name)
		dup.reload()
		self.assertEqual(dup.status, STATUS_DUPLICATE)
		self.assertEqual(dup.duplicate_of, original.name)
		self.assertEqual(dup.action_required, 1)
		self.assertIn("Exact duplicate", dup.action_required_reason)
		# OCR never ran on the duplicate (status Duplicate fails the OCR guard).
		self.assertEqual(dup.ocr_status, OCR_STATUS_NOT_EXTRACTED)

	# AC-03-2
	def test_exact_match_outside_window_not_flagged(self):
		now = now_datetime()
		self._capture("win-a.pdf", content_hash="HW", received_at=add_to_date(now, days=-200))
		dup = self._capture("win-b.pdf", content_hash="HW", received_at=now)

		result = detect_duplicates_for(dup)

		self.assertEqual(result["status"], "clean")
		dup.reload()
		self.assertEqual(dup.status, STATUS_PENDING_REVIEW)

	# AC-03-3
	def test_distinct_hash_and_far_phash_is_clean(self):
		now = now_datetime()
		self._capture(
			"dist-a.pdf", content_hash="HA", perceptual_hash="0000000000000000", received_at=now
		)
		dup = self._capture("dist-b.pdf", content_hash="HB", received_at=now)
		# pHash 32 bits away from the candidate -> well over the threshold.
		self.mod._compute_phash = lambda capture: "ffffffff00000000"

		self.assertEqual(detect_duplicates_for(dup)["status"], "clean")

	# AC-03-4
	def test_single_capture_never_flags_itself(self):
		cap = self._capture("solo.pdf", content_hash="HSOLO", received_at=now_datetime())

		result = detect_duplicates_for(cap)

		self.assertEqual(result["status"], "clean")
		cap.reload()
		self.assertEqual(cap.status, STATUS_PENDING_REVIEW)

	# AC-03-5
	def test_chain_points_to_oldest_original(self):
		now = now_datetime()
		oldest = self._capture(
			"chain-1.pdf", content_hash="HC", received_at=add_to_date(now, days=-2)
		)
		# Middle is already flagged Duplicate -> excluded by the status filter.
		self._capture(
			"chain-2.pdf",
			content_hash="HC",
			received_at=add_to_date(now, days=-1),
			status=STATUS_DUPLICATE,
		)
		newest = self._capture("chain-3.pdf", content_hash="HC", received_at=now)

		result = detect_duplicates_for(newest)

		self.assertEqual(result["status"], "duplicate")
		self.assertEqual(result["original"], oldest.name)
		newest.reload()
		self.assertEqual(newest.duplicate_of, oldest.name)

	# AC-03-6
	def test_perceptual_suspect_flags_without_duplicate_status(self):
		now = now_datetime()
		candidate = self._capture(
			"near-a.pdf", content_hash="HN1", perceptual_hash="ffffffffffffffff", received_at=now
		)
		dup = self._capture("near-b.pdf", content_hash="HN2", received_at=now)
		# Distance 1 (<= 6) from the candidate's pHash.
		self.mod._compute_phash = lambda capture: "fffffffffffffffe"

		result = detect_duplicates_for(dup)

		self.assertEqual(result["status"], "suspected")
		self.assertEqual(result["kind"], "perceptual")
		self.assertEqual(result["original"], candidate.name)
		dup.reload()
		self.assertEqual(dup.action_required, 1)
		self.assertNotEqual(dup.status, STATUS_DUPLICATE)
		self.assertEqual(dup.status, STATUS_PENDING_REVIEW)
		self.assertFalse(dup.duplicate_of)
		self.assertIn("near-duplicate", dup.action_required_reason.lower())

	# AC-03-7
	def test_perceptual_distance_over_threshold_not_flagged(self):
		now = now_datetime()
		self._capture(
			"far-a.pdf", content_hash="HF1", perceptual_hash="0000000000000000", received_at=now
		)
		dup = self._capture("far-b.pdf", content_hash="HF2", received_at=now)
		# 0x3ff has ten 1-bits -> distance 10 > 6.
		self.mod._compute_phash = lambda capture: "00000000000003ff"

		self.assertEqual(detect_duplicates_for(dup)["status"], "clean")

	# AC-03-8
	def test_compute_phash_failure_is_swallowed(self):
		now = now_datetime()
		self._capture(
			"swallow-a.pdf",
			content_hash="HS1",
			perceptual_hash="ffffffffffffffff",
			received_at=now,
		)
		dup = self._capture("swallow-b.pdf", content_hash="HS2", received_at=now)

		def boom(capture):
			raise RuntimeError("poppler missing")

		self.mod._compute_phash = boom

		# Must NOT raise; perceptual degrades, exact-only runs (no exact match here).
		result = detect_duplicates_for(dup)

		self.assertEqual(result["status"], "clean")
		dup.reload()
		self.assertFalse(dup.perceptual_hash)

	# AC-03-9
	def test_kill_switch_skips_with_no_mutation(self):
		cap = self._capture("kill.pdf", content_hash="HK", received_at=now_datetime())
		frappe.db.set_single_value("AP Closed Loop Settings", "dedupe_enabled", 0)

		result = detect_duplicates_for(cap)

		self.assertEqual(result["status"], "skipped")
		cap.reload()
		self.assertIsNone(cap.duplicate_detected_at)
		self.assertEqual(cap.status, STATUS_PENDING_REVIEW)

	# AC-03-10
	def test_window_boundary_inclusive(self):
		now = now_datetime()
		cutoff = add_to_date(now, days=-90)
		# Just inside the 90-day window (>= cutoff) -> hit.
		self._capture(
			"bnd-in-a.pdf", content_hash="HB1", received_at=add_to_date(cutoff, seconds=30)
		)
		inside_dup = self._capture("bnd-in-b.pdf", content_hash="HB1", received_at=now)
		self.assertEqual(detect_duplicates_for(inside_dup)["status"], "duplicate")
		# Just outside the window -> miss.
		self._capture(
			"bnd-out-a.pdf", content_hash="HB2", received_at=add_to_date(cutoff, seconds=-30)
		)
		outside_dup = self._capture("bnd-out-b.pdf", content_hash="HB2", received_at=now)
		self.assertEqual(detect_duplicates_for(outside_dup)["status"], "clean")

	def test_phash_distance_helper(self):
		# Sanity-check the pure-Python Hamming distance used by the perceptual pass.
		self.assertEqual(self.mod._phash_distance("ffffffffffffffff", "ffffffffffffffff"), 0)
		self.assertEqual(self.mod._phash_distance("ffffffffffffffff", "fffffffffffffffe"), 1)
		self.assertEqual(self.mod._phash_distance("0000000000000000", "00000000000003ff"), 10)
		self.assertIsNone(self.mod._phash_distance(None, "ffffffffffffffff"))
		self.assertIsNone(self.mod._phash_distance("", ""))


class TestAPInvoiceCaptureDedupCascade(IntegrationTestCase):
	"""Spec 03 — AC-03-12: dedupe wired into the async cascade (Step 0, pre-OCR).

	Opts into the cascade (ap_auto_progress flag) so the full intake -> dedupe ->
	OCR rail runs synchronously (now=True in tests). Requires the deterministic
	fake OCR provider, pinned for the whole run by the test harness.
	"""

	def setUp(self):
		frappe.flags.ap_auto_progress_enabled = True

	def tearDown(self):
		frappe.flags.ap_auto_progress_enabled = False
		frappe.db.rollback()

	def test_duplicate_file_short_circuits_before_ocr(self):
		shared = _content_for("dupc.pdf")
		f1 = _make_file("dupc-original.pdf", content=shared)
		original = create_capture_from_file(file_doc=f1)
		original.reload()
		# First upload is unique at intake -> dedupe clean -> OCR ran to Proposed.
		self.assertEqual(original.status, STATUS_PROPOSED)
		self.assertEqual(original.ocr_status, OCR_STATUS_PROPOSED)

		f2 = _make_file("dupc-second.pdf", content=shared)
		dup = create_capture_from_file(file_doc=f2)
		dup.reload()
		# Identical bytes -> dedupe terminal, OCR never reached (no cost).
		self.assertEqual(dup.status, STATUS_DUPLICATE)
		self.assertEqual(dup.duplicate_of, original.name)
		self.assertEqual(dup.ocr_status, OCR_STATUS_NOT_EXTRACTED)
		self.assertEqual(dup.action_required, 1)

	def test_unique_file_proceeds_to_proposed(self):
		f = _make_file("uniqueflow.pdf")
		cap = create_capture_from_file(file_doc=f)
		cap.reload()
		# Dedupe ran first (stamped), found nothing, OCR proceeded as today.
		self.assertTrue(cap.duplicate_detected_at)
		self.assertEqual(cap.status, STATUS_PROPOSED)
		self.assertEqual(cap.ocr_status, OCR_STATUS_PROPOSED)


def _structured_png(variant: str, *, noise: float = 0.0) -> bytes:
	"""A structured, invoice-like PNG with enough low-frequency content for a
	meaningful pHash. ``noise`` adds deterministic gaussian noise to emulate a
	re-scan (same layout, different bytes). ``variant`` changes the layout so a
	'distinct' image hashes far away. No Chromium / poppler — pure Pillow+numpy."""

	import numpy as np
	from PIL import Image, ImageDraw

	img = Image.new("RGB", (400, 560), "white")
	d = ImageDraw.Draw(img)
	if variant == "distinct":
		d.ellipse([40, 40, 360, 300], fill=(112, 36, 89))
		d.rectangle([40, 360, 360, 520], outline=(0, 0, 0))
		d.text((60, 420), "A COMPLETELY DIFFERENT LAYOUT", fill=(0, 0, 0))
	else:
		d.rectangle([20, 20, 380, 90], fill=(43, 108, 176))
		d.text((30, 40), f"INVOICE — {variant}", fill=(255, 255, 255))
		for i, y in enumerate(range(120, 520, 40)):
			d.rectangle([20, y, 360, y + 24], outline=(0, 0, 0))
			d.text((28, y + 6), f"Line item {i}  qty {i + 1}  $ {100 * (i + 1)}.00", fill=(20, 20, 20))
	if noise:
		arr = np.asarray(img).astype(np.int16)
		rng = np.random.default_rng(7)  # fixed -> deterministic test
		arr = np.clip(arr + rng.normal(0, noise, arr.shape), 0, 255).astype(np.uint8)
		img = Image.fromarray(arr)
	buf = BytesIO()
	img.save(buf, format="PNG")
	return buf.getvalue()


class TestAPInvoiceCaptureDedupPerceptualLive(IntegrationTestCase):
	"""Spec 03 — the REAL perceptual pipeline, with NO _compute_phash monkeypatch.

	Exercises the actual imagehash (and, for the PDF branch, pdf2image/poppler)
	code path end-to-end. The image branch needs only imagehash+Pillow; the PDF
	branch also needs the poppler binary — each test skips when its dep is absent
	so the suite stays green on a bench without the optional perceptual deps.
	(The mocked fuzzy-distance logic is covered by TestAPInvoiceCaptureDedup.)
	"""

	def setUp(self):
		frappe.db.set_single_value("AP Closed Loop Settings", "dedupe_enabled", 1)
		frappe.db.set_single_value("AP Closed Loop Settings", "dedupe_window_days", 90)
		frappe.db.set_single_value("AP Closed Loop Settings", "dedupe_phash_max_distance", 6)

	def tearDown(self):
		frappe.db.rollback()

	@unittest.skipUnless(_IMAGEHASH_AVAILABLE, "imagehash/Pillow not installed")
	def test_real_phash_image_branch_flags_near_duplicate(self):
		# Original: a structured invoice image -> real pHash computed + persisted.
		orig = create_capture_from_file(
			file_doc=_make_file("perc_base.png", content=_structured_png("acme"))
		)
		detect_duplicates_for(orig)
		orig.reload()
		self.assertTrue(orig.perceptual_hash, "real _compute_phash should hash a PNG")
		self.assertRegex(orig.perceptual_hash, r"^[0-9a-f]{16}$")

		# Near-duplicate re-scan (same layout + mild noise) -> SUSPECT via real pHash.
		dup = create_capture_from_file(
			file_doc=_make_file("perc_rescan.png", content=_structured_png("acme", noise=8.0))
		)
		result = detect_duplicates_for(dup)
		self.assertEqual(result["status"], "suspected")
		self.assertEqual(result["kind"], "perceptual")
		self.assertEqual(result["original"], orig.name)
		dup.reload()
		self.assertEqual(dup.action_required, 1)
		self.assertNotEqual(dup.status, STATUS_DUPLICATE)
		self.assertFalse(dup.duplicate_of)

		# A genuinely different image -> clean (distance over threshold).
		other = create_capture_from_file(
			file_doc=_make_file("perc_distinct.png", content=_structured_png("distinct"))
		)
		self.assertEqual(detect_duplicates_for(other)["status"], "clean")

	@unittest.skipUnless(_POPPLER_AVAILABLE, "poppler/pdf2image not installed")
	def test_real_phash_pdf_branch(self):
		# Rasterize a committed PDF fixture through the real pdf2image/poppler path.
		from erpnext.accounts.doctype.ap_invoice_capture import ap_invoice_capture as mod

		fixture = os.path.join(
			frappe.get_app_path("erpnext"), "..", "test", "invoices",
			"deduplication", "near-duplicate", "01_globex_original.pdf",
		)
		cap = create_capture_from_file(
			file_doc=_make_file("perc_globex.pdf", content=open(fixture, "rb").read())
		)
		phash = mod._compute_phash(cap)
		self.assertIsNotNone(phash, "real _compute_phash should rasterize+hash a PDF")
		self.assertRegex(phash, r"^[0-9a-f]{16}$")


class TestAPInvoiceCaptureResolveAbove(IntegrationTestCase):
	"""Spec 04 — per-field threshold resolution (AC-04-8)."""

	def test_resolution_order_and_line_base_field(self):
		from erpnext.accounts.doctype.ap_invoice_capture.ap_invoice_capture import (
			_base_field,
			_resolve_above,
		)

		cfg = {
			"confidence_threshold": 0.70,
			"field_thresholds": {"supplier": 0.90, "amount": 0.80},
		}
		# (a) per-field override wins for supplier.
		self.assertTrue(_resolve_above("supplier", 0.90, cfg))
		self.assertFalse(_resolve_above("supplier", 0.89, cfg))
		# (b) no override -> canonical confidence_threshold (the ocr_confidence_threshold).
		self.assertTrue(_resolve_above("currency", 0.70, cfg))
		self.assertFalse(_resolve_above("currency", 0.699, cfg))
		# Line key strips to its base field 'amount' -> uses the amount override.
		self.assertTrue(_resolve_above("line_0_amount", 0.80, cfg))
		self.assertFalse(_resolve_above("line_0_amount", 0.79, cfg))
		self.assertEqual(_base_field("line_3_description"), "description")
		self.assertEqual(_base_field("supplier"), "supplier")


class TestAPInvoiceCaptureExtractionDetail(IntegrationTestCase):
	"""Spec 04 — run_extraction write-back of confidence rows + line items."""

	def tearDown(self):
		frappe.db.rollback()

	def _inmem_capture(self):
		c = frappe.new_doc("AP Invoice Capture")
		c.source_filename = "extract_detail.pdf"
		c.file_extension = "pdf"
		c.intake_channel = INTAKE_MANUAL_UPLOAD
		c.is_supported_format = 1
		c.source_file_url = "/private/files/extract_detail.pdf"
		c.received_at = now_datetime()
		c.final_currency = "USD"
		return c

	# AC-04-6, AC-04-7, AC-04-10
	def test_write_back_builds_confidence_and_line_rows(self):
		from erpnext.accounts.ap_closed_loop.extractors.base import ExtractionResult
		from erpnext.accounts.doctype.ap_invoice_capture.ap_invoice_capture import (
			_write_extraction_detail,
		)

		result = ExtractionResult(
			proposal={
				"supplier": "Acme",
				"total_amount": 300.0,
				"subtotal": 250.0,
				"tax": 50.0,
				"po_reference": "PO-DOES-NOT-EXIST",
			},
			confidence={
				"supplier": 0.95,
				"total_amount": 0.70,
				"line_0_description": 0.9,
				"line_0_amount": 0.699,
			},
			lines=[
				{
					"description": "Widget",
					"qty": 2,
					"rate": 150.0,
					"amount": 300.0,
					"confidence": {"description": 0.9, "amount": 0.699},
				}
			],
			score_sources={
				"supplier": "Model",
				"total_amount": "Model",
				"line_0_description": "Model",
				"line_0_amount": "Derived-Mapping",
			},
		)
		cfg = {"confidence_threshold": 0.70, "field_thresholds": {"supplier": 0.90}}
		cap = self._inmem_capture()
		_write_extraction_detail(cap, result, cfg)

		rows = {r.field_name: r for r in cap.field_confidences}
		self.assertEqual(len(cap.field_confidences), 4)
		# supplier 0.95 >= field override 0.90 -> above.
		self.assertEqual(rows["supplier"].is_above_threshold, 1)
		# total_amount 0.70 >= 0.70 -> above (boundary inclusive).
		self.assertEqual(rows["total_amount"].is_above_threshold, 1)
		# line_0_amount 0.699 < 0.70 -> below (boundary), source preserved.
		self.assertEqual(rows["line_0_amount"].is_above_threshold, 0)
		self.assertEqual(rows["line_0_amount"].score_source, "Derived-Mapping")

		self.assertEqual(len(cap.line_items), 1)
		self.assertEqual(cap.line_items[0].amount, 300.0)
		self.assertEqual(cap.line_items[0].currency, "USD")
		self.assertTrue(cap.line_items[0].confidence_summary)

		self.assertEqual(cap.subtotal_amount, 250.0)
		self.assertEqual(cap.tax_amount, 50.0)
		# Non-existent PO -> blank Link (no dangling ref); raw value stays in result.
		self.assertFalse(cap.purchase_order_reference)

	# AC-04-9 (security): no credentials echoed even with confidence/lines added.
	def test_ocr_raw_response_has_no_credentials(self):
		f = _make_file("sec_check.pdf")
		cap = create_capture_from_file(file_doc=f)
		run_fake_extraction(cap, save=True)
		cap.reload()
		raw = (cap.ocr_raw_response or "").lower()
		for needle in ("api_key", "x-api-key", "sk-ant", "authorization"):
			self.assertNotIn(needle, raw)
		parsed = json.loads(cap.ocr_raw_response)
		self.assertIn("confidence", parsed)
		self.assertIn("lines", parsed)


class TestAPInvoiceCapturePromoteLineAware(IntegrationTestCase):
	"""Spec 04 — promote builds one PI item per capture line (AC-04-11/12)."""

	def tearDown(self):
		frappe.db.rollback()

	def _validated_capture(self, lines, total, tax=0.0):
		f = _make_file("promote_lines.pdf")
		cap = create_capture_from_file(file_doc=f)
		run_fake_extraction(cap)
		confirm_extracted_fields(
			cap,
			corrections={"supplier": "_Test Supplier", "total_amount": str(total), "currency": "INR"},
		)
		validate_for_purchase_invoice(cap)
		cap.reload()
		cap.set("line_items", lines)
		cap.tax_amount = tax
		cap.save()
		return cap

	# AC-04-11
	def test_promote_creates_one_pi_item_per_line(self):
		cap = self._validated_capture(
			[
				{"description": "Line A", "qty": 1, "rate": 150.0, "amount": 150.0, "currency": "INR"},
				{"description": "Line B", "qty": 1, "rate": 100.0, "amount": 100.0, "currency": "INR"},
			],
			total=250.0,
		)
		pi = promote_to_purchase_invoice(cap, defaults=_PROMOTION_DEFAULTS)
		self.assertEqual(len(pi.items), 2)
		self.assertAlmostEqual(sum(i.amount for i in pi.items), 250.0, places=2)

	# AC-04-11 (tax-aware reconciliation): PRE-tax lines + a separate tax reconcile
	# to the tax-inclusive total. Regression for the bug the real-Anthropic e2e
	# found — a 19%-VAT invoice whose lines sum to the SUBTOTAL must still promote.
	def test_promote_reconciles_pretax_lines_plus_tax(self):
		cap = self._validated_capture(
			[
				{"description": "Cloud hosting", "qty": 1, "rate": 100.0, "amount": 100.0, "currency": "INR"},
				{"description": "Support", "qty": 1, "rate": 100.0, "amount": 100.0, "currency": "INR"},
			],
			total=220.0,  # tax-inclusive grand total
			tax=20.0,     # lines (200) + tax (20) == 220
		)
		pi = promote_to_purchase_invoice(cap, defaults=_PROMOTION_DEFAULTS)
		self.assertEqual(len(pi.items), 2)
		cap.reload()
		self.assertEqual(cap.promotion_status, PROMOTION_STATUS_PROMOTED)

	# AC-04-12
	def test_promote_reconciliation_mismatch_raises(self):
		cap = self._validated_capture(
			[{"description": "Only line", "qty": 1, "rate": 150.0, "amount": 150.0, "currency": "INR"}],
			total=250.0,  # lines sum to 150, no tax -> reconciles under neither rule
		)
		with self.assertRaises(CapturePromotionError):
			promote_to_purchase_invoice(cap, defaults=_PROMOTION_DEFAULTS)
		cap.reload()
		self.assertEqual(cap.action_required, 1)
		self.assertNotEqual(cap.promotion_status, PROMOTION_STATUS_PROMOTED)

	# A partial/wrong tax that still doesn't close the gap must also raise.
	def test_promote_mismatch_not_rescued_by_partial_tax(self):
		cap = self._validated_capture(
			[{"description": "Only line", "qty": 1, "rate": 150.0, "amount": 150.0, "currency": "INR"}],
			total=250.0,
			tax=20.0,  # 150 + 20 = 170 != 250 -> still a mismatch
		)
		with self.assertRaises(CapturePromotionError):
			promote_to_purchase_invoice(cap, defaults=_PROMOTION_DEFAULTS)


class TestAPSupplierResolution3Tier(IntegrationTestCase):
	"""Spec 05 — three-tier supplier resolver, stream branching, Tier-3 gate."""

	def setUp(self):
		# Pin Fake OCR so the synthetic blank PDF yields a complete deterministic
		# proposal (spec 01 test-env note); rolled back per-test in tearDown.
		frappe.db.set_single_value(
			"AP Closed Loop Settings", "ocr_provider", "Fake (Deterministic)"
		)

	def tearDown(self):
		frappe.db.rollback()

	# --- helpers ---------------------------------------------------------
	def _supplier_group(self):
		return (
			frappe.db.get_value("Supplier", "_Test Supplier", "supplier_group")
			or "All Supplier Groups"
		)

	def _sup(self, name, *, disabled=0):
		doc = frappe.get_doc(
			{
				"doctype": "Supplier",
				"supplier_name": name,
				"supplier_group": self._supplier_group(),
				"supplier_type": "Company",
				"disabled": disabled,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc.name

	def _alias(self, canonical, pattern, match_type="glob", **kw):
		frappe.get_doc(
			{
				"doctype": "AP Supplier Alias",
				"canonical_supplier": canonical,
				"alias_pattern": pattern,
				"match_type": match_type,
				"is_active": kw.get("is_active", 1),
				"priority": kw.get("priority", 0),
			}
		).insert(ignore_permissions=True)

	def _set(self, field, value):
		frappe.db.set_single_value("AP Closed Loop Settings", field, value)

	def _confirmed(self, supplier, *, stream=None, confidence=None):
		f = _make_file(f"res-{frappe.generate_hash(length=6)}.pdf")
		capture = create_capture_from_file(file_doc=f, source_context="resolver test")
		run_fake_extraction(capture)
		capture.reload()
		confirm_extracted_fields(
			capture,
			corrections={"supplier": supplier, "currency": "INR", "total_amount": "100.00"},
			reviewer="Administrator",
		)
		capture.reload()
		if stream:
			capture.stream = stream
		if confidence is not None:
			capture.proposed_supplier_confidence = confidence
		return capture

	# --- Tier 1: alias ---------------------------------------------------
	def test_ac_05_1_tier1_exact(self):
		sup = self._sup(f"AWS {frappe.generate_hash(length=6)}")
		self._alias(sup, "Amazon Web Services", match_type="exact")
		res = _resolve_supplier("Amazon Web Services")
		self.assertEqual(res["matched_supplier"], sup)
		self.assertEqual(res["match_status"], SUPPLIER_MATCH_ALIAS)
		self.assertEqual(res["confidence"], 100.0)
		self.assertEqual(res["tier"], SUPPLIER_TIER_ALIAS)

	def test_ac_05_2_tier1_glob(self):
		sup = self._sup(f"Amazon {frappe.generate_hash(length=6)}")
		self._alias(sup, "AMZN Mktp US*", match_type="glob")
		res = _resolve_supplier("AMZN Mktp US*4Z9")
		self.assertEqual(res["matched_supplier"], sup)
		self.assertEqual(res["match_status"], SUPPLIER_MATCH_ALIAS)

	def test_ac_05_3_tier1_regex(self):
		sup = self._sup(f"Stripe {frappe.generate_hash(length=6)}")
		self._alias(sup, "^STRIPE.*", match_type="regex")
		res = _resolve_supplier("STRIPE PAYMENTS")
		self.assertEqual(res["matched_supplier"], sup)
		self.assertIn(res["match_status"], (SUPPLIER_MATCH_ALIAS, SUPPLIER_MATCH_MATCHED))

	def test_ac_05_4_tier1_bad_regex_is_safe(self):
		sup = self._sup(f"Vendor {frappe.generate_hash(length=6)}")
		self._alias(sup, "(unbalanced", match_type="regex")
		# Must not raise; falls through to Tier 2 (no such Supplier) -> Unknown.
		res = _resolve_supplier("(unbalanced")
		self.assertEqual(res["match_status"], SUPPLIER_MATCH_UNKNOWN)

	def test_ac_05_5_tier1_ambiguous(self):
		a = self._sup(f"AlphaCo {frappe.generate_hash(length=6)}")
		b = self._sup(f"BetaCo {frappe.generate_hash(length=6)}")
		self._alias(a, "SHARED*", match_type="glob")
		self._alias(b, "SHARED PMT*", match_type="glob")
		res = _resolve_supplier("SHARED PMT 7")
		self.assertEqual(res["match_status"], SUPPLIER_MATCH_AMBIGUOUS)
		self.assertEqual(set(res["competing"]), {a, b})

	def test_ac_05_6_tier1_inactive_ignored(self):
		sup = self._sup(f"Ghost {frappe.generate_hash(length=6)}")
		self._alias(sup, "GHOSTPAY*", match_type="glob", is_active=0)
		res = _resolve_supplier("GHOSTPAY 0001")
		self.assertNotEqual(res["match_status"], SUPPLIER_MATCH_ALIAS)

	# --- Tier 2: fuzzy ---------------------------------------------------
	def test_ac_05_7_tier2_single_hit(self):
		from rapidfuzz import fuzz

		token = frappe.generate_hash(length=6)
		name = f"Northwind Traders {token}"
		sup = self._sup(name)
		candidate = f"Northwind Trader {token}"
		self._set("supplier_fuzzy_threshold", 80)
		expected = float(fuzz.token_set_ratio(candidate, name))
		res = _resolve_supplier(candidate)
		self.assertEqual(res["matched_supplier"], sup)
		self.assertEqual(res["match_status"], SUPPLIER_MATCH_MATCHED)
		self.assertEqual(res["tier"], SUPPLIER_TIER_FUZZY)
		self.assertEqual(res["confidence"], expected)

	def test_ac_05_8_tier2_boundary_inclusive(self):
		from rapidfuzz import fuzz

		token = frappe.generate_hash(length=6)
		name = f"Contoso Manufacturing {token}"
		self._sup(name)
		candidate = f"Contoso Mfg {token}"
		score = float(fuzz.token_set_ratio(candidate, name))
		# Cutoff exactly equal to the score must still match (>= is inclusive).
		self._set("supplier_fuzzy_threshold", score)
		res = _resolve_supplier(candidate)
		self.assertEqual(res["match_status"], SUPPLIER_MATCH_MATCHED)
		# And just above the score, it must NOT match.
		if score < 100:
			self._set("supplier_fuzzy_threshold", score + 0.5)
			res2 = _resolve_supplier(candidate)
			self.assertNotEqual(res2["match_status"], SUPPLIER_MATCH_MATCHED)

	def test_ac_05_9_tier2_multiple(self):
		token = frappe.generate_hash(length=6)
		base = f"Globex {token} Trading"
		a = self._sup(f"{base} Incorporated")
		b = self._sup(f"{base} Limited")
		self._set("supplier_fuzzy_threshold", 80)
		res = _resolve_supplier(base)
		self.assertEqual(res["match_status"], SUPPLIER_MATCH_AMBIGUOUS)
		self.assertEqual(set(res["competing"]), {a, b})

	def test_ac_05_10_tier2_none(self):
		# A candidate that matches nothing -> Unknown, confidence holds best score seen.
		self._set("supplier_fuzzy_threshold", 95)
		candidate = f"Zzqwx Unrelated Vendor {frappe.generate_hash(length=8)}"
		res = _resolve_supplier(candidate)
		self.assertEqual(res["match_status"], SUPPLIER_MATCH_UNKNOWN)
		self.assertEqual(res["tier"], SUPPLIER_TIER_NONE)
		self.assertLess(res["confidence"], 95)

	def test_ac_05_11_exact_still_wins(self):
		token = frappe.generate_hash(length=6)
		name = f"Acme Exact {token}"
		sup = self._sup(name)
		# Exact PK name.
		res_pk = _resolve_supplier(sup)
		self.assertEqual(res_pk["matched_supplier"], sup)
		self.assertEqual(res_pk["match_status"], SUPPLIER_MATCH_MATCHED)
		self.assertEqual(res_pk["tier"], SUPPLIER_TIER_EXACT)
		# Unique supplier_name.
		res_name = _resolve_supplier(name)
		self.assertEqual(res_name["matched_supplier"], sup)
		self.assertEqual(res_name["tier"], SUPPLIER_TIER_EXACT)

	def test_ac_05_back_compat_match_supplier_tuple(self):
		token = frappe.generate_hash(length=6)
		name = f"BackCompat {token}"
		sup = self._sup(name)
		matched, status = _match_supplier(name)
		self.assertEqual((matched, status), (sup, SUPPLIER_MATCH_MATCHED))
		# Unknown still returns the legacy tuple shape.
		self.assertEqual(_match_supplier(f"No Vendor {token}"), (None, SUPPLIER_MATCH_UNKNOWN))
		# A Tier-1 alias hit folds to the legacy "Matched" value.
		self._alias(sup, "BC-ALIAS*", match_type="glob")
		self.assertEqual(_match_supplier("BC-ALIAS 99"), (sup, SUPPLIER_MATCH_MATCHED))

	# --- AC-05-12: no-auto-create invariant ------------------------------
	def test_ac_05_12_no_auto_create_on_any_unknown(self):
		self._set("supplier_fuzzy_threshold", 95)
		before = frappe.db.count("Supplier")
		# (a) Tier-2 zero-hit Unknown.
		_resolve_supplier(f"Nope Vendor {frappe.generate_hash(length=8)}")
		self.assertEqual(frappe.db.count("Supplier"), before)
		# (b) Tier-3 gate OFF + high confidence on a blocked capture.
		self._set("enable_gated_supplier_creation", 0)
		cap = self._confirmed(
			f"Unknown Co {frappe.generate_hash(length=6)}",
			stream=STREAM_INVOICE,
			confidence=0.99,
		)
		validate_for_purchase_invoice(cap)
		self.assertEqual(frappe.db.count("Supplier"), before)
		# (c) Tier-3 gate ON but request only queued (no Supplier yet).
		self._set("enable_gated_supplier_creation", 1)
		self._set("supplier_autocreate_confidence_threshold", 0.85)
		cap2 = self._confirmed(
			f"Unknown Two {frappe.generate_hash(length=6)}",
			stream=STREAM_INVOICE,
			confidence=0.99,
		)
		validate_for_purchase_invoice(cap2)
		self.assertEqual(frappe.db.count("Supplier"), before)

	# --- AC-05-13 / 14: stream branching ---------------------------------
	def test_ac_05_13_stream_invoice_blocks_unknown(self):
		cap = self._confirmed(
			f"Unknown Inv {frappe.generate_hash(length=6)}", stream=STREAM_INVOICE
		)
		validate_for_purchase_invoice(cap)
		cap.reload()
		self.assertEqual(cap.supplier_match_status, SUPPLIER_MATCH_UNKNOWN)
		self.assertEqual(cap.validation_status, VALIDATION_STATUS_BLOCKED)
		self.assertEqual(cap.action_required, 1)

	def test_ac_05_14_stream_receipt_soft_unknown(self):
		vendor = f"Card Vendor {frappe.generate_hash(length=6)}"
		cap = self._confirmed(vendor, stream=STREAM_RECEIPT)
		validate_for_purchase_invoice(cap)
		cap.reload()
		self.assertEqual(cap.validation_status, VALIDATION_STATUS_VALIDATED)
		self.assertEqual(cap.supplier_match_status, SUPPLIER_MATCH_UNKNOWN)
		# Raw vendor string preserved verbatim for the Stream-R JE memo.
		self.assertEqual(cap.final_supplier, vendor)
		self.assertIn("Unmapped card spend", cap.validation_result)

	# --- AC-05-15 / 16 / 17: Tier-3 gated creation -----------------------
	def test_ac_05_15_tier3_gate_off(self):
		self._set("enable_gated_supplier_creation", 0)
		cap = self._confirmed(
			f"Gate Off {frappe.generate_hash(length=6)}", stream=STREAM_INVOICE, confidence=0.99
		)
		validate_for_purchase_invoice(cap)
		cap.reload()
		self.assertFalse(cap.supplier_change_request)

	def test_ac_05_16_tier3_gate_on_confident(self):
		self._set("enable_gated_supplier_creation", 1)
		self._set("supplier_autocreate_confidence_threshold", 0.85)
		before = frappe.db.count("Supplier")
		cap = self._confirmed(
			f"Gate On {frappe.generate_hash(length=6)}", stream=STREAM_INVOICE, confidence=0.95
		)
		validate_for_purchase_invoice(cap)
		cap.reload()
		self.assertTrue(cap.supplier_change_request)
		req = frappe.get_doc("Supplier Master Change Request", cap.supplier_change_request)
		self.assertEqual(req.workflow_state, "Draft")
		self.assertEqual(req.change_type, "Create")
		# No Supplier created yet.
		self.assertEqual(frappe.db.count("Supplier"), before)

	def test_ac_05_17_tier3_gate_on_not_confident(self):
		self._set("enable_gated_supplier_creation", 1)
		self._set("supplier_autocreate_confidence_threshold", 0.85)
		cap = self._confirmed(
			f"Low Conf {frappe.generate_hash(length=6)}", stream=STREAM_INVOICE, confidence=0.50
		)
		validate_for_purchase_invoice(cap)
		cap.reload()
		self.assertFalse(cap.supplier_change_request)

	# --- AC-05-24/25/26: T-018 — gate defaults ON for high confidence ----
	# AC-05-24 — default ON: a confident unknown auto-files a Draft request, no human enable.
	def test_ac_05_24_gate_defaults_on_high_confidence(self):
		from erpnext.accounts.doctype.ap_closed_loop_settings.ap_closed_loop_settings import (
			get_supplier_resolution_settings,
		)

		self._set("enable_gated_supplier_creation", "")  # unset → fresh-site default
		self._set("supplier_autocreate_confidence_threshold", 0.85)
		self.assertTrue(get_supplier_resolution_settings()["enable_gated_supplier_creation"])
		before = frappe.db.count("Supplier")
		cap = self._confirmed(
			f"Auto Default {frappe.generate_hash(length=6)}", stream=STREAM_INVOICE, confidence=0.95
		)
		validate_for_purchase_invoice(cap)
		cap.reload()
		self.assertTrue(cap.supplier_change_request)  # auto-filed with no explicit enable
		self.assertEqual(frappe.db.count("Supplier"), before)  # no Supplier created

	# AC-05-25 — default ON but low confidence still no auto-file (escalation preserved).
	def test_ac_05_25_default_on_low_confidence_no_file(self):
		self._set("enable_gated_supplier_creation", "")
		self._set("supplier_autocreate_confidence_threshold", 0.85)
		cap = self._confirmed(
			f"Default Low {frappe.generate_hash(length=6)}", stream=STREAM_INVOICE, confidence=0.50
		)
		validate_for_purchase_invoice(cap)
		cap.reload()
		self.assertFalse(cap.supplier_change_request)
		self.assertEqual(cap.validation_status, VALIDATION_STATUS_BLOCKED)  # stays blocked

	# AC-05-26 — control intact: auto-filed request is Draft; no Supplier without approval.
	def test_ac_05_26_no_supplier_without_approval(self):
		self._set("enable_gated_supplier_creation", "")
		self._set("supplier_autocreate_confidence_threshold", 0.85)
		before = frappe.db.count("Supplier")
		cap = self._confirmed(
			f"Default Ctrl {frappe.generate_hash(length=6)}", stream=STREAM_INVOICE, confidence=0.95
		)
		validate_for_purchase_invoice(cap)
		cap.reload()
		req = frappe.get_doc("Supplier Master Change Request", cap.supplier_change_request)
		self.assertEqual(req.workflow_state, "Draft")
		self.assertEqual(req.change_type, "Create")
		self.assertEqual(frappe.db.count("Supplier"), before)

	# --- queue idempotency (Tier-3 helper) -------------------------------
	def test_tier3_queue_is_idempotent_per_capture(self):
		cap = self._confirmed(f"Once {frappe.generate_hash(length=6)}", stream=STREAM_INVOICE)
		r1 = queue_supplier_create_request(cap.name, "Once Vendor")
		r2 = queue_supplier_create_request(cap.name, "Once Vendor")
		self.assertEqual(r1, r2)


class TestAPCodingProfile(IntegrationTestCase):
	"""Spec 06 — GL coding: three-layer merge, cost-center inference + conflict,
	tax validation, submitted-PI guard, Stream-R catch-all, the is_fully_coded gate."""

	_COGS = "_Test Account Cost for Goods Sold - _TC"
	_VAT = "_Test Account VAT - _TC"
	_CC = "_Test Cost Center - _TC"

	def setUp(self):
		frappe.db.set_single_value("AP Closed Loop Settings", "ocr_provider", "Fake (Deterministic)")
		# Clean slate for the Settings GL-coding layer (tests set what they need).
		for f in ("default_expense_account", "default_cost_center", "unmapped_card_spend_account", "default_purchase_tax_template"):
			frappe.db.set_single_value("AP Closed Loop Settings", f, None)

	def tearDown(self):
		frappe.db.rollback()

	# --- helpers ---------------------------------------------------------
	def _supplier_group(self):
		return frappe.db.get_value("Supplier", "_Test Supplier", "supplier_group") or "All Supplier Groups"

	def _supplier(self, tag="V"):
		name = f"SPEC06 {tag} {frappe.generate_hash(length=6)}"
		frappe.get_doc(
			{"doctype": "Supplier", "supplier_name": name, "supplier_group": self._supplier_group(), "supplier_type": "Company"}
		).insert(ignore_permissions=True)
		return name

	def _profile(self, supplier, **fields):
		frappe.get_doc(
			{
				"doctype": "AP Supplier Coding Profile",
				"supplier": supplier,
				"default_expense_account": fields.get("expense_account"),
				"default_cost_center": fields.get("cost_center"),
				"default_purchase_tax_template": fields.get("tax_template"),
			}
		).insert(ignore_permissions=True)

	def _tax_template(self, rate=10):
		doc = frappe.get_doc(
			{
				"doctype": "Purchase Taxes and Charges Template",
				"company": "_Test Company",
				"title": f"SPEC06 Tax {frappe.generate_hash(length=6)}",
				"taxes": [
					{"charge_type": "On Net Total", "account_head": self._VAT, "rate": rate, "description": f"VAT {rate}%"}
				],
			}
		)
		doc.insert(ignore_permissions=True)
		return doc.name

	def _validated_capture(self, supplier, total="300.00", subtotal=None, tax=None):
		f = _make_file(f"cod-{frappe.generate_hash(length=6)}.pdf")
		cap = create_capture_from_file(file_doc=f, source_context="SPEC06 coding test")
		run_fake_extraction(cap)
		cap.reload()
		confirm_extracted_fields(
			cap, corrections={"supplier": supplier, "currency": "INR", "total_amount": total}, reviewer="Administrator"
		)
		cap.reload()
		validate_for_purchase_invoice(cap)
		cap.reload()
		if subtotal is not None:
			cap.subtotal_amount = subtotal
		if tax is not None:
			cap.tax_amount = tax
		if subtotal is not None or tax is not None:
			cap.save(ignore_permissions=True)
			cap.reload()
		return cap

	# --- AC-06-2: layer 1 (profile) beats layer 0 (settings) -------------
	def test_ac_06_2_profile_beats_settings(self):
		frappe.db.set_single_value("AP Closed Loop Settings", "default_expense_account", self._COGS)
		sup = self._supplier()
		self._profile(sup, expense_account=self._VAT, cost_center=self._CC)
		cap = self._validated_capture(sup)
		apply_coding_profile_for(cap)
		cap.reload()
		self.assertEqual(cap.applied_expense_account, self._VAT)  # profile, not settings COGS

	# --- AC-06-3: caller defaults win; settings-only key flows through ---
	def test_ac_06_3_three_layer_precedence(self):
		frappe.db.set_single_value("AP Closed Loop Settings", "default_cost_center", self._CC)  # settings-only key
		sup = self._supplier()
		self._profile(sup, expense_account=self._VAT)
		cap = self._validated_capture(sup)
		apply_coding_profile_for(cap, defaults={"expense_account": self._COGS})  # caller override
		cap.reload()
		self.assertEqual(cap.applied_expense_account, self._COGS)  # caller wins
		self.assertEqual(cap.applied_cost_center, self._CC)  # settings-only flows through

	# --- AC-06-4: single cost-center signal (profile) --------------------
	def test_ac_06_4_cost_center_single_signal(self):
		sup = self._supplier()
		self._profile(sup, expense_account=self._VAT, cost_center=self._CC)
		cap = self._validated_capture(sup)
		apply_coding_profile_for(cap)
		cap.reload()
		self.assertEqual(cap.applied_cost_center, self._CC)
		self.assertEqual(cap.coding_status, CODING_STATUS_CODED)

	# --- AC-06-5: conflicting cost-center signals -> ambiguous, no write -
	def test_ac_06_5_cost_center_ambiguity(self):
		sup = self._supplier()
		self._profile(sup, expense_account=self._VAT, cost_center=self._CC)
		cap = self._validated_capture(sup)
		cap.receipt_location = "Berlin"
		cap.card_last4 = "4242"
		cap.save(ignore_permissions=True)
		cap.reload()
		orig_loc, orig_card = _apic_mod._location_cost_center, _apic_mod._card_cost_center
		try:
			_apic_mod._location_cost_center = lambda v: "CC-LOCATION"
			_apic_mod._card_cost_center = lambda v: "CC-CARD"
			apply_coding_profile_for(cap)
		finally:
			_apic_mod._location_cost_center, _apic_mod._card_cost_center = orig_loc, orig_card
		cap.reload()
		self.assertEqual(cap.coding_status, CODING_STATUS_AMBIGUOUS)
		self.assertFalse(cap.applied_cost_center)  # no CC written on conflict
		self.assertEqual(cap.action_required, 1)
		self.assertIn("conflict", (cap.coding_review_reason or "").lower())

	# --- AC-06-6 / 7: tax match / mismatch -------------------------------
	def test_ac_06_6_tax_match(self):
		tmpl = self._tax_template(rate=10)
		sup = self._supplier()
		self._profile(sup, expense_account=self._VAT, cost_center=self._CC, tax_template=tmpl)
		cap = self._validated_capture(sup, subtotal=300, tax=30)  # 10% of 300 == 30
		apply_coding_profile_for(cap)
		cap.reload()
		self.assertEqual(cap.applied_tax_template, tmpl)
		self.assertNotEqual(cap.coding_status, CODING_STATUS_FLAGGED)

	def test_ac_06_7_tax_mismatch(self):
		tmpl = self._tax_template(rate=10)
		sup = self._supplier()
		self._profile(sup, expense_account=self._VAT, cost_center=self._CC, tax_template=tmpl)
		cap = self._validated_capture(sup, subtotal=300, tax=25)  # expected 30, off by 5
		apply_coding_profile_for(cap)
		cap.reload()
		self.assertEqual(cap.coding_status, CODING_STATUS_FLAGGED)
		self.assertFalse(is_fully_coded(cap))

	# --- AC-06-8: submitted-PI guard -------------------------------------
	def test_ac_06_8_submitted_pi_guard(self):
		sup = self._supplier()
		self._profile(sup, expense_account=self._COGS, cost_center=self._CC)
		cap = self._validated_capture(sup)
		pi = promote_to_purchase_invoice(cap, defaults=_PROMOTION_DEFAULTS)
		frappe.get_doc("Purchase Invoice", pi.name).submit()
		cap.reload()
		with self.assertRaises(CapturePromotionError):
			apply_coding_profile_for(cap)
		self.assertEqual(frappe.db.get_value("Purchase Invoice", pi.name, "docstatus"), 1)

	# --- AC-06-9: Stream-R catch-all -------------------------------------
	def test_ac_06_9_stream_r_catch_all(self):
		frappe.db.set_single_value("AP Closed Loop Settings", "unmapped_card_spend_account", self._COGS)
		f = _make_file(f"receipt_{frappe.generate_hash(length=6)}.pdf")
		cap = create_capture_from_file(file_doc=f, source_context="SPEC06 stream-r")
		run_fake_extraction(cap)
		cap.reload()
		confirm_extracted_fields(
			cap, corrections={"supplier": f"Ghost {frappe.generate_hash(length=6)}", "currency": "INR", "total_amount": "50.00"}, reviewer="Administrator"
		)
		cap.reload()
		cap.matched_supplier = None
		cap.stream = "Receipt (R)"
		cap.save(ignore_permissions=True)
		apply_coding_profile_for(cap)
		cap.reload()
		self.assertEqual(cap.applied_expense_account, self._COGS)
		self.assertEqual(cap.coding_status, CODING_STATUS_FLAGGED)
		self.assertEqual(cap.action_required, 1)

	def test_ac_06_9b_catch_all_unset_blocks(self):
		f = _make_file(f"receipt_{frappe.generate_hash(length=6)}.pdf")
		cap = create_capture_from_file(file_doc=f, source_context="SPEC06 stream-r2")
		run_fake_extraction(cap)
		cap.reload()
		confirm_extracted_fields(
			cap, corrections={"supplier": f"Ghost {frappe.generate_hash(length=6)}", "currency": "INR", "total_amount": "50.00"}, reviewer="Administrator"
		)
		cap.reload()
		cap.matched_supplier = None
		cap.stream = "Receipt (R)"
		cap.save(ignore_permissions=True)
		apply_coding_profile_for(cap)
		cap.reload()
		self.assertFalse(cap.applied_expense_account)
		self.assertFalse(is_fully_coded(cap))

	# --- AC-06-10: the gate ----------------------------------------------
	def test_ac_06_10_is_fully_coded_gate(self):
		sup = self._supplier()
		self._profile(sup, expense_account=self._VAT, cost_center=self._CC)
		cap = self._validated_capture(sup)
		apply_coding_profile_for(cap)
		cap.reload()
		self.assertTrue(is_fully_coded(cap))  # expense + cc + no tax flag
		# Missing cost center -> not fully coded.
		sup2 = self._supplier()
		self._profile(sup2, expense_account=self._VAT)  # no cost center
		cap2 = self._validated_capture(sup2)
		apply_coding_profile_for(cap2)
		cap2.reload()
		self.assertFalse(is_fully_coded(cap2))

	# --- AC-06-11: re-run after corrected supplier mutates the draft PI --
	def test_ac_06_11_recode_draft_pi_on_supplier_change(self):
		a = self._supplier("A")
		b = self._supplier("B")
		self._profile(a, expense_account=self._COGS, cost_center=self._CC)
		self._profile(b, expense_account=self._VAT, cost_center=self._CC)
		cap = self._validated_capture(a)
		pi = promote_to_purchase_invoice(cap, defaults=_PROMOTION_DEFAULTS)  # draft
		cap.reload()
		apply_coding_profile_for(cap)  # codes draft PI with A's profile
		self.assertEqual(frappe.db.get_value("Purchase Invoice Item", {"parent": pi.name}, "expense_account"), self._COGS)
		# Correct the supplier to B and re-code.
		cap.matched_supplier = b
		cap.save(ignore_permissions=True)
		apply_coding_profile_for(cap)
		self.assertEqual(frappe.db.get_value("Purchase Invoice Item", {"parent": pi.name}, "expense_account"), self._VAT)

	# --- AC-06-12: settings footgun regression ---------------------------
	def test_ac_06_12_get_promote_defaults_omits_empty(self):
		from erpnext.accounts.doctype.ap_closed_loop_settings.ap_closed_loop_settings import (
			get_promote_defaults,
		)

		frappe.db.set_single_value("AP Closed Loop Settings", "default_warehouse", None)
		self.assertNotIn("warehouse", get_promote_defaults())

	# --- AC-06-14: dimension with a missing column is skipped, no error --
	def test_ac_06_14_missing_dimension_column_skipped(self):
		# An unknown Accounting Dimension yields no fieldname -> skipped silently.
		item = frappe.new_doc("Purchase Invoice Item")
		try:
			_apply_dimensions_to_row(item, [{"dimension": "No Such Dim", "dimension_value": "X"}])
		except Exception as exc:  # noqa: BLE001
			self.fail(f"_apply_dimensions_to_row raised on a missing dimension: {exc}")


class TestAPInvoiceCaptureDocumentTypeBranching(IntegrationTestCase):
	"""Spec 07 — Step-6 document-type classification + stream-aware doctype branching
	(Already-Paid posts an is_paid Purchase Invoice, the locked Option C)."""

	_BANK = "_Test Bank - _TC"

	def setUp(self):
		frappe.db.set_single_value("AP Closed Loop Settings", "ocr_provider", "Fake (Deterministic)")
		frappe.db.set_single_value("AP Closed Loop Settings", "employee_supplier_group", None)
		frappe.db.set_single_value("AP Closed Loop Settings", "credit_card_clearing_account", None)

	def tearDown(self):
		frappe.db.rollback()

	# --- helpers ---------------------------------------------------------
	def _confirmed(self, supplier="_Test Supplier", source_context="ordinary bill", total="100.00"):
		f = _make_file(f"cls-{frappe.generate_hash(length=6)}.pdf")
		cap = create_capture_from_file(file_doc=f, source_context=source_context)
		run_fake_extraction(cap)
		cap.reload()
		confirm_extracted_fields(
			cap, corrections={"supplier": supplier, "currency": "INR", "total_amount": total}, reviewer="Administrator"
		)
		cap.reload()
		return cap

	def _employee_group(self):
		name = f"SPEC07 Employees {frappe.generate_hash(length=6)}"
		frappe.get_doc({"doctype": "Supplier Group", "supplier_group_name": name, "parent_supplier_group": "All Supplier Groups"}).insert(ignore_permissions=True)
		frappe.db.set_single_value("AP Closed Loop Settings", "employee_supplier_group", name)
		return name

	def _supplier_in_group(self, group):
		name = f"SPEC07 Emp {frappe.generate_hash(length=6)}"
		frappe.get_doc({"doctype": "Supplier", "supplier_name": name, "supplier_group": group, "supplier_type": "Individual"}).insert(ignore_permissions=True)
		return name

	# --- AC-07-1: classify Already Paid ----------------------------------
	def test_ac_07_1_classify_already_paid(self):
		cap = self._confirmed(source_context="Receipt — paid by Visa ****1234")
		classify_document_type(cap)
		cap.reload()
		self.assertEqual(cap.document_type, DOCUMENT_TYPE_ALREADY_PAID)
		self.assertEqual(cap.classified_stream, CLASSIFIED_STREAM_R)
		self.assertEqual(cap.detected_last4, "1234")
		self.assertTrue(cap.card_charge_marker)

	# --- AC-07-2: classify Employee Reimbursement ------------------------
	def test_ac_07_2_classify_employee(self):
		group = self._employee_group()
		emp = self._supplier_in_group(group)
		cap = self._confirmed(supplier=emp)
		cap.matched_supplier = emp  # classifier keys on matched_supplier
		cap.save(ignore_permissions=True)
		classify_document_type(cap)
		cap.reload()
		self.assertEqual(cap.document_type, DOCUMENT_TYPE_EMPLOYEE_REIMBURSEMENT)
		self.assertEqual(cap.status, STATUS_MANUAL_REVIEW)
		self.assertFalse(cap.expense_claim)  # no live link (hrms absent)

	# --- AC-07-3: classify Unpaid Bill -----------------------------------
	def test_ac_07_3_classify_unpaid_bill(self):
		cap = self._confirmed()
		cap.matched_supplier = "_Test Supplier"
		cap.save(ignore_permissions=True)
		classify_document_type(cap)
		cap.reload()
		self.assertEqual(cap.document_type, DOCUMENT_TYPE_UNPAID_BILL)
		self.assertEqual(cap.classified_stream, CLASSIFIED_STREAM_I)

	# --- AC-07-4: override wins ------------------------------------------
	def test_ac_07_4_override_wins(self):
		cap = self._confirmed(source_context="paid by Visa ****1234")  # would be Already Paid
		classify_document_type(cap, override=DOCUMENT_TYPE_UNPAID_BILL)
		cap.reload()
		self.assertEqual(cap.document_type, DOCUMENT_TYPE_UNPAID_BILL)
		self.assertEqual(cap.classification_source, CLASSIFICATION_SOURCE_OVERRIDE)

	# --- AC-07-5: stream disagreement -> Manual Review -------------------
	def test_ac_07_5_disagreement_manual_review(self):
		cap = self._confirmed(source_context="paid by Visa ****1234")  # classifier reads R
		cap.stream = "Invoice (I)"  # intake tagged I
		cap.save(ignore_permissions=True)
		classify_document_type(cap)
		cap.reload()
		self.assertEqual(cap.document_type, DOCUMENT_TYPE_MANUAL_REVIEW)
		self.assertEqual(cap.status, STATUS_MANUAL_REVIEW)
		self.assertEqual(cap.stream_tag_agreement, STREAM_AGREEMENT_DISAGREE)
		self.assertEqual(cap.action_required, 1)
		self.assertIn("conflict", (cap.action_required_reason or "").lower())

	# --- AC-07-6: unmatched supplier when employee-check needed -> review -
	def test_ac_07_6_ambiguous_manual_review(self):
		self._employee_group()  # employee distinction is configured
		cap = self._confirmed(source_context="ordinary bill")
		cap.matched_supplier = None
		cap.save(ignore_permissions=True)
		classify_document_type(cap)
		cap.reload()
		self.assertEqual(cap.document_type, DOCUMENT_TYPE_MANUAL_REVIEW)
		self.assertEqual(cap.status, STATUS_MANUAL_REVIEW)

	# --- AC-07-7: Already-Paid -> is_paid PI with both GL layers ----------
	def test_ac_07_7_already_paid_is_paid_invoice(self):
		frappe.db.set_single_value("AP Closed Loop Settings", "credit_card_clearing_account", self._BANK)
		cap = self._confirmed(source_context="paid by Visa ****1234", total="100.00")
		classify_document_type(cap)
		cap.reload()
		self.assertEqual(cap.document_type, DOCUMENT_TYPE_ALREADY_PAID)
		validate_for_purchase_invoice(cap)  # resolve supplier (Stream R still needs a Supplier for the PI)
		cap.reload()
		pi = promote_already_paid(cap, defaults=_PROMOTION_DEFAULTS)
		cap.reload()
		self.assertEqual(int(pi.is_paid), 1)
		self.assertEqual(pi.cash_bank_account, self._BANK)
		self.assertEqual(cap.purchase_invoice, pi.name)
		self.assertEqual(cap.promotion_status, PROMOTION_STATUS_PROMOTED)
		# Submit and prove the is-paid payment leg posts to the bank account.
		frappe.get_doc("Purchase Invoice", pi.name).submit()
		bank_gl = frappe.get_all("GL Entry", filters={"voucher_no": pi.name, "account": self._BANK})
		self.assertTrue(bank_gl, "expected a GL entry against the bank account from the is_paid leg")

	# --- AC-07-8: wrong document_type on already-paid promote ------------
	def test_ac_07_8_already_paid_wrong_doctype(self):
		cap = self._confirmed()
		cap.matched_supplier = "_Test Supplier"
		cap.save(ignore_permissions=True)
		classify_document_type(cap)  # -> Unpaid Bill
		cap.reload()
		with self.assertRaises(CapturePromotionError):
			promote_already_paid(cap)

	# --- AC-07-9: idempotency guard --------------------------------------
	def test_ac_07_9_already_paid_idempotent(self):
		frappe.db.set_single_value("AP Closed Loop Settings", "credit_card_clearing_account", self._BANK)
		cap = self._confirmed(source_context="paid by Visa ****1234")
		classify_document_type(cap)
		validate_for_purchase_invoice(cap)
		cap.reload()
		promote_already_paid(cap, defaults=_PROMOTION_DEFAULTS)
		cap.reload()
		with self.assertRaises(CapturePromotionError):
			promote_already_paid(cap, defaults=_PROMOTION_DEFAULTS)

	# --- AC-07-10: missing config -> raises, no PI -----------------------
	def test_ac_07_10_missing_config(self):
		frappe.db.set_single_value("AP Closed Loop Settings", "credit_card_clearing_account", None)
		cap = self._confirmed(source_context="paid by Visa ****1234")
		classify_document_type(cap)
		validate_for_purchase_invoice(cap)
		cap.reload()
		pi_before = frappe.db.count("Purchase Invoice")
		with self.assertRaises(CapturePromotionError):
			promote_already_paid(cap, defaults=_PROMOTION_DEFAULTS)
		self.assertEqual(frappe.db.count("Purchase Invoice"), pi_before)

	# --- AC-07-11: PI guard rejects Already-Paid -------------------------
	def test_ac_07_11_pi_guard_rejects_already_paid(self):
		cap = self._confirmed(source_context="paid by Visa ****1234")
		classify_document_type(cap)
		validate_for_purchase_invoice(cap)
		cap.reload()
		with self.assertRaises(CapturePromotionError):
			promote_to_purchase_invoice(cap, defaults=_PROMOTION_DEFAULTS)  # standard path

	# --- AC-07-12: cascade routing decisions at each fork ----------------
	def test_ac_07_12_cascade_routing(self):
		frappe.db.set_single_value("AP Closed Loop Settings", "credit_card_clearing_account", self._BANK)
		# Confirmed + unclassified -> classify first.
		unpaid = self._confirmed(source_context="ordinary bill")
		self.assertEqual(unpaid._determine_next_step()[0], "classify_document_type_for")
		# Unpaid Bill -> validation path.
		classify_document_type(unpaid)
		unpaid.reload()
		self.assertEqual(unpaid.document_type, DOCUMENT_TYPE_UNPAID_BILL)
		self.assertEqual(unpaid._determine_next_step()[0], "validate_for_purchase_invoice_for")
		# Already Paid -> after validation, routes to the already-paid posting.
		paid = self._confirmed(source_context="paid by Visa ****1234")
		classify_document_type(paid)
		paid.reload()
		self.assertEqual(paid.document_type, DOCUMENT_TYPE_ALREADY_PAID)
		validate_for_purchase_invoice(paid)
		paid.reload()
		self.assertEqual(paid._determine_next_step()[0], "promote_already_paid_for")
		# Manual Review (stream conflict) halts the cascade.
		mr = self._confirmed(source_context="paid by Visa ****1234")
		mr.stream = "Invoice (I)"
		mr.save(ignore_permissions=True)
		classify_document_type(mr)
		mr.reload()
		self.assertEqual(mr.document_type, DOCUMENT_TYPE_MANUAL_REVIEW)
		self.assertIsNone(mr._determine_next_step())

	# --- AC-07-13: get_already_paid_config -------------------------------
	def test_ac_07_13_already_paid_config(self):
		from erpnext.accounts.doctype.ap_closed_loop_settings.ap_closed_loop_settings import (
			get_already_paid_config,
		)

		frappe.db.set_single_value("AP Closed Loop Settings", "credit_card_clearing_account", self._BANK)
		cfg = get_already_paid_config()
		self.assertEqual(cfg["paid_from_account"], self._BANK)
		frappe.db.set_single_value("AP Closed Loop Settings", "credit_card_clearing_account", None)
		self.assertIsNone(get_already_paid_config()["paid_from_account"])

	# --- AC-07-14: migrate safety ----------------------------------------
	def test_ac_07_14_schema(self):
		meta = frappe.get_meta("AP Invoice Capture")
		self.assertEqual(meta.get_field("document_type").fieldtype, "Select")
		self.assertEqual(meta.get_field("expense_claim").fieldtype, "Data")  # NOT a Link
		self.assertIn("Manual Review", (meta.get_field("status").options or "").split("\n"))


class TestAPInvoiceCaptureValidationGates(IntegrationTestCase):
	"""Spec 08 — three-way match, amount anomaly, vendor bank-change gates.

	Gates are stream-aware: blocking on Stream I, recorded-only on Stream R. Each
	test rolls back in tearDown so the suite stays reentrant.
	"""

	def tearDown(self):
		frappe.db.rollback()

	# ---- fixtures ---------------------------------------------------------

	def _new_supplier(self):
		"""A fresh Supplier with NO PI / PE / bank history (clean baseline)."""
		s = frappe.get_doc(
			{
				"doctype": "Supplier",
				"supplier_name": "AP Gate Vendor " + frappe.generate_hash(length=8),
				"supplier_group": "_Test Supplier Group",
				"supplier_type": "Company",
			}
		).insert(ignore_permissions=True)
		return s.name

	def _confirmed(
		self,
		*,
		supplier="_Test Supplier",
		matched=None,
		total=1000.0,
		stream=STREAM_INVOICE,
		lines=None,
		po_ref=None,
	):
		"""A Confirmed capture with gate-relevant fields set (no validate run yet)."""
		f = _make_file("gate-" + frappe.generate_hash(length=6) + ".pdf")
		cap = create_capture_from_file(file_doc=f)
		run_fake_extraction(cap)
		confirm_extracted_fields(
			cap,
			corrections={"supplier": supplier, "total_amount": str(total), "currency": "INR"},
		)
		cap.reload()
		cap.stream = stream
		cap.matched_supplier = supplier if matched is None else matched
		if po_ref:
			cap.purchase_order_reference = po_ref
		if lines is not None:
			cap.set("line_items", lines)
		cap.flags.ignore_links = True
		cap.save()
		return cap

	def _make_po(self, *, qty=10, rate=100, received_qty=None):
		from erpnext.buying.doctype.purchase_order.test_purchase_order import create_purchase_order

		po = create_purchase_order(qty=qty, rate=rate)
		if received_qty is not None:
			frappe.db.set_value("Purchase Order Item", po.items[0].name, "received_qty", received_qty)
		return po.name

	def _line(self, qty, rate, po_ref=None):
		row = {
			"description": "Item",
			"qty": qty,
			"rate": rate,
			"amount": qty * rate,
			"currency": "INR",
		}
		if po_ref:
			row["po_reference"] = po_ref
		return row

	def _seed_baseline(self, supplier, *, n, mean, stddev, window=6):
		"""Plant a FRESH anomaly baseline cache row (O(1) read path)."""
		_upsert_anomaly_baseline(supplier, n, mean, stddev, window)

	# ---- three-way match --------------------------------------------------

	# AC-08-1
	def test_ac_08_1_three_way_match_matched(self):
		po = self._make_po(qty=10, rate=100, received_qty=10)  # ordered 1000, received 10
		cap = self._confirmed(total=1000.0, po_ref=po, lines=[self._line(10, 100, po)])
		three_way_match_for(cap)
		cap.reload()
		self.assertEqual(cap.three_way_match_status, THREE_WAY_MATCH_MATCHED)
		result = json.loads(cap.three_way_match_result)
		self.assertTrue(result["within_tolerance"])
		self.assertTrue(cap.three_way_match_checked_at)

	# AC-08-2
	def test_ac_08_2_three_way_match_qty_exception(self):
		po = self._make_po(qty=10, rate=100, received_qty=10)
		# invoiced qty 12 > received 10 (tol 0); amount kept within (final_total 1000)
		cap = self._confirmed(total=1000.0, po_ref=po, lines=[self._line(12, 100, po)])
		three_way_match_for(cap)
		cap.reload()
		self.assertEqual(cap.three_way_match_status, THREE_WAY_MATCH_EXCEPTION)
		self.assertGreater(json.loads(cap.three_way_match_result)["qty_diff_pct"], 0)

	# AC-08-3
	def test_ac_08_3_three_way_match_amount_exception(self):
		po = self._make_po(qty=10, rate=100, received_qty=10)  # ordered 1000
		# invoiced amount 1100 over PO 1000 beyond 0 tolerance; qty within
		cap = self._confirmed(total=1100.0, po_ref=po, lines=[self._line(10, 110, po)])
		three_way_match_for(cap)
		cap.reload()
		self.assertEqual(cap.three_way_match_status, THREE_WAY_MATCH_EXCEPTION)
		self.assertGreater(json.loads(cap.three_way_match_result)["amount_diff_pct"], 0)

	# AC-08-4
	def test_ac_08_4_strict_boundary(self):
		po = self._make_po(qty=10, rate=100, received_qty=10)  # ordered 1000
		exact = self._confirmed(total=1000.0, po_ref=po, lines=[self._line(10, 100, po)])
		three_way_match_for(exact)
		exact.reload()
		self.assertEqual(exact.three_way_match_status, THREE_WAY_MATCH_MATCHED)

		over = self._confirmed(total=1000.01, po_ref=po, lines=[self._line(10, 100, po)])
		three_way_match_for(over)
		over.reload()
		self.assertEqual(over.three_way_match_status, THREE_WAY_MATCH_EXCEPTION)

	# AC-08-5
	def test_ac_08_5_per_supplier_override_widens(self):
		supplier = self._new_supplier()
		profile = frappe.get_doc(
			{
				"doctype": "AP Supplier Coding Profile",
				"supplier": supplier,
				"amount_tolerance_pct": 20.0,  # widen so 1100 vs 1000 passes
			}
		).insert(ignore_permissions=True)
		self.assertTrue(profile.name)
		po = self._make_po(qty=10, rate=100, received_qty=10)  # ordered 1000
		cap = self._confirmed(
			supplier=supplier, matched=supplier, total=1100.0, po_ref=po, lines=[self._line(10, 110, po)]
		)
		# Sanity: the resolver actually picked up the override.
		self.assertEqual(_resolve_gate_config(cap)["amount_tolerance_pct"], 20.0)
		three_way_match_for(cap)
		cap.reload()
		self.assertEqual(cap.three_way_match_status, THREE_WAY_MATCH_MATCHED)

	# AC-08-6
	def test_ac_08_6_no_profile_settings_fallback(self):
		supplier = self._new_supplier()  # no coding profile
		self.assertFalse(frappe.db.exists("AP Supplier Coding Profile", supplier))
		cfg = _resolve_gate_config(self._confirmed(supplier=supplier, matched=supplier))
		# Hard-default settings (strict 0 tolerance, defaults for anomaly).
		self.assertEqual(cfg["amount_tolerance_pct"], 0.0)
		self.assertEqual(cfg["qty_tolerance_pct"], 0.0)
		self.assertEqual(cfg["anomaly_multiple"], 3.0)

	# AC-08-7
	def test_ac_08_7_override_three_way_match(self):
		po = self._make_po(qty=10, rate=100, received_qty=10)
		cap = self._confirmed(total=1100.0, po_ref=po, lines=[self._line(10, 110, po)])
		validate_for_purchase_invoice(cap)
		cap.reload()
		self.assertEqual(cap.three_way_match_status, THREE_WAY_MATCH_EXCEPTION)

		# empty notes -> raises
		with self.assertRaises(CaptureValidationError):
			override_three_way_match(cap, notes="   ")

		override_three_way_match(cap, notes="Approved variance per PO amendment.")
		cap.reload()
		self.assertEqual(cap.three_way_match_status, THREE_WAY_MATCH_OVERRIDE)
		self.assertEqual(cap.three_way_match_override_by, "Administrator")
		self.assertTrue(cap.three_way_match_override_at)
		self.assertIn("variance", cap.three_way_match_override_notes)

		# non-Exception status -> raises (already Override now)
		with self.assertRaises(CaptureValidationError):
			override_three_way_match(cap, notes="again")

	# AC-08-8
	def test_ac_08_8_not_applicable_no_po_and_stream_r(self):
		no_po = self._confirmed(total=500.0)  # Stream I, no PO, require_po off
		three_way_match_for(no_po)
		no_po.reload()
		self.assertEqual(no_po.three_way_match_status, THREE_WAY_MATCH_NOT_APPLICABLE)

		stream_r = self._confirmed(total=500.0, stream=STREAM_RECEIPT)
		three_way_match_for(stream_r)
		stream_r.reload()
		self.assertEqual(stream_r.three_way_match_status, THREE_WAY_MATCH_NOT_APPLICABLE)

	# AC-08-9
	def test_ac_08_9_require_po_policy(self):
		frappe.db.set_single_value("AP Closed Loop Settings", "require_po_for_invoices", 1)
		try:
			cap = self._confirmed(total=500.0)  # Stream I, no PO
			three_way_match_for(cap)
			cap.reload()
			self.assertEqual(cap.three_way_match_status, THREE_WAY_MATCH_EXCEPTION)
		finally:
			frappe.db.set_single_value("AP Closed Loop Settings", "require_po_for_invoices", 0)

	# ---- amount anomaly ---------------------------------------------------

	# AC-08-10
	def test_ac_08_10_anomaly_normal(self):
		supplier = self._new_supplier()
		self._seed_baseline(supplier, n=6, mean=5000.0, stddev=300.0)
		cap = self._confirmed(supplier=supplier, matched=supplier, total=5500.0)
		detect_amount_anomaly_for(cap)
		cap.reload()
		self.assertEqual(cap.anomaly_status, ANOMALY_NORMAL)
		self.assertTrue(cap.anomaly_result)

	# AC-08-11
	def test_ac_08_11_anomaly_anomalous(self):
		supplier = self._new_supplier()
		self._seed_baseline(supplier, n=6, mean=5200.0, stddev=400.0)
		cap = self._confirmed(supplier=supplier, matched=supplier, total=18400.0)
		detect_amount_anomaly_for(cap)
		cap.reload()
		self.assertEqual(cap.anomaly_status, ANOMALY_ANOMALOUS)
		self.assertIn("18,400", cap.anomaly_result)

		# Through validate -> Blocked, and action_required_reason (a 140-char Data
		# field) must not overflow on the long anomaly evidence.
		validate_for_purchase_invoice(cap)
		cap.reload()
		self.assertEqual(cap.validation_status, VALIDATION_STATUS_BLOCKED)
		self.assertLessEqual(len(cap.action_required_reason or ""), 140)
		self.assertIn("anomaly", cap.validation_result.lower())

	# AC-08-12
	def test_ac_08_12_insufficient_history_not_blocking(self):
		supplier = self._new_supplier()
		self._seed_baseline(supplier, n=3, mean=5000.0, stddev=200.0)  # n < 5
		cap = self._confirmed(supplier=supplier, matched=supplier, total=50000.0)
		validate_for_purchase_invoice(cap)
		cap.reload()
		self.assertEqual(cap.anomaly_status, ANOMALY_INSUFFICIENT_HISTORY)
		# Not blocked on anomaly alone (no PO -> 3WM N/A, no PE -> bank soft).
		self.assertEqual(cap.validation_status, VALIDATION_STATUS_VALIDATED)

	# AC-08-13
	def test_ac_08_13_empty_history(self):
		supplier = self._new_supplier()  # zero PIs, no baseline row
		cap = self._confirmed(supplier=supplier, matched=supplier, total=9999.0)
		detect_amount_anomaly_for(cap)
		cap.reload()
		self.assertEqual(cap.anomaly_status, ANOMALY_INSUFFICIENT_HISTORY)

	# AC-08-14
	def test_ac_08_14_refresh_baseline_matches_recompute_and_idempotent(self):
		supplier = self._new_supplier()
		self._submit_pi(supplier, 1000.0)
		self._submit_pi(supplier, 2000.0)
		self._submit_pi(supplier, 3000.0)

		refresh_anomaly_baselines()
		row = frappe.db.get_value(
			"AP Supplier Anomaly Baseline",
			supplier,
			["sample_count", "mean_grand_total", "stddev_grand_total"],
			as_dict=True,
		)
		self.assertIsNotNone(row)
		# Direct recompute (population stats over 1000/2000/3000).
		self.assertEqual(int(row.sample_count), 3)
		self.assertAlmostEqual(flt(row.mean_grand_total), 2000.0, places=2)
		self.assertAlmostEqual(flt(row.stddev_grand_total), (2_000_000 / 3) ** 0.5, places=2)

		# Idempotent: a second run keeps one row, same values.
		before = frappe.db.count("AP Supplier Anomaly Baseline", {"supplier": supplier})
		refresh_anomaly_baselines()
		after = frappe.db.count("AP Supplier Anomaly Baseline", {"supplier": supplier})
		self.assertEqual(before, after)
		row2 = frappe.db.get_value(
			"AP Supplier Anomaly Baseline", supplier, "mean_grand_total"
		)
		self.assertAlmostEqual(flt(row2), 2000.0, places=2)

	def _submit_pi(self, supplier, amount):
		pi = frappe.get_doc(
			{
				"doctype": "Purchase Invoice",
				"supplier": supplier,
				"company": "_Test Company",
				"currency": "INR",
				"posting_date": frappe.utils.today(),
				"bill_no": "GATE-" + frappe.generate_hash(length=6),
				"items": [
					{
						"item_code": "_Test Item",
						"qty": 1,
						"rate": amount,
						"expense_account": "_Test Account Cost for Goods Sold - _TC",
						"cost_center": "_Test Cost Center - _TC",
					}
				],
			}
		)
		pi.insert(ignore_permissions=True)
		pi.submit()
		return pi.name

	# ---- vendor bank change ----------------------------------------------

	# AC-08-15 / AC-08-16
	def _bank_setup(self, supplier):
		"""Give the supplier a default Bank Account; return (bank, bank_account)."""
		bank_name = "AP Gate Bank " + frappe.generate_hash(length=6)
		bank = frappe.get_doc({"doctype": "Bank", "bank_name": bank_name}).insert(
			ignore_permissions=True
		)
		ba = frappe.get_doc(
			{
				"doctype": "Bank Account",
				"account_name": "Vendor Acct " + frappe.generate_hash(length=4),
				"bank": bank.name,
				"party_type": "Supplier",
				"party": supplier,
				"iban": "GB29NWBK60161331926819",
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Supplier", supplier, "default_bank_account", ba.name)
		return bank.name, ba.name

	def _submit_pe(self, supplier):
		from erpnext.accounts.doctype.payment_entry.test_payment_entry import create_payment_entry

		pe = create_payment_entry(party=supplier, paid_amount=500, save=True, submit=True)
		return pe.name

	def test_ac_08_15_bank_change_none(self):
		supplier = self._new_supplier()
		self._bank_setup(supplier)
		self._submit_pe(supplier)  # anchor; no change afterward
		cap = self._confirmed(supplier=supplier, matched=supplier, total=500.0)
		detect_vendor_bank_change_for(cap)
		cap.reload()
		self.assertEqual(int(cap.vendor_bank_change_detected), 0)

	def test_ac_08_16_bank_change_detected_blocks_promotion(self):
		supplier = self._new_supplier()
		bank, ba = self._bank_setup(supplier)
		self._submit_pe(supplier)  # anchor
		# Mutate a watched field AFTER the payment -> Version row written.
		# Frappe v16 defaults ignore_version=True under frappe.in_test, which would
		# suppress the Bank Account Version the change-detector diffs against; force
		# it on so the test mirrors production (where in_test is False).
		ba_doc = frappe.get_doc("Bank Account", ba)
		ba_doc.iban = "DE89370400440532013000"
		ba_doc.save(ignore_permissions=True, ignore_version=False)
		self.assertTrue(
			frappe.db.exists("Version", {"ref_doctype": "Bank Account", "docname": ba})
		)
		cap = self._confirmed(supplier=supplier, matched=supplier, total=500.0)
		validate_for_purchase_invoice(cap)
		cap.reload()
		self.assertEqual(int(cap.vendor_bank_change_detected), 1)
		self.assertEqual(cap.validation_status, VALIDATION_STATUS_BLOCKED)
		self.assertEqual(cap.action_required, 1)
		# Promotion is hard-blocked while no approved request exists.
		with self.assertRaises(CapturePromotionError):
			promote_to_purchase_invoice(cap, defaults=_PROMOTION_DEFAULTS)

	def test_ac_08_17_no_prior_pe_soft_skip(self):
		supplier = self._new_supplier()
		bank, ba = self._bank_setup(supplier)
		# Change bank but NEVER paid this supplier -> baseline not established.
		ba_doc = frappe.get_doc("Bank Account", ba)
		ba_doc.iban = "DE89370400440532013000"
		ba_doc.save(ignore_permissions=True)
		cap = self._confirmed(supplier=supplier, matched=supplier, total=500.0)
		detect_vendor_bank_change_for(cap)
		cap.reload()
		self.assertEqual(int(cap.vendor_bank_change_detected), 0)

	# AC-08-16 (re-check): a bank change AFTER a clean validation is caught at
	# promotion time (the promotion gate re-runs detection, not just the stored flag).
	def test_ac_08_16b_promotion_recheck_after_clean_validation(self):
		supplier = self._new_supplier()
		bank, ba = self._bank_setup(supplier)
		self._submit_pe(supplier)  # anchor
		cap = self._confirmed(supplier=supplier, matched=supplier, total=500.0)
		# Validate while the bank is unchanged -> clean Validated, flag 0.
		validate_for_purchase_invoice(cap)
		cap.reload()
		self.assertEqual(int(cap.vendor_bank_change_detected), 0)
		self.assertEqual(cap.validation_status, VALIDATION_STATUS_VALIDATED)
		# Fraudster changes the bank AFTER validation. (Force versioning so the
		# detector has a Bank Account Version to diff against under v16 in_test —
		# see test_ac_08_16 above.)
		ba_doc = frappe.get_doc("Bank Account", ba)
		ba_doc.iban = "DE89370400440532013000"
		ba_doc.save(ignore_permissions=True, ignore_version=False)
		# Promotion re-detects and blocks with the bank-specific error.
		with self.assertRaises(CapturePromotionError):
			promote_to_purchase_invoice(cap, defaults=_PROMOTION_DEFAULTS)

	# AC-08-18
	def _user_with_roles(self, tag, roles):
		email = "{0}-{1}@example.com".format(tag, frappe.generate_hash(length=6))
		u = frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": tag, "send_welcome_email": 0}
		).insert(ignore_permissions=True)
		u.add_roles(*roles)
		return u.name

	def test_ac_08_18_sod_ap_self_approval_does_not_lift(self):
		supplier = self._new_supplier()
		ap_user = self._user_with_roles("ap", ["Accounts User"])
		ap_user2 = self._user_with_roles("ap2", ["Accounts User"])
		treasury = self._user_with_roles("treasury", ["Treasury Approver"])

		def _smcr(requested_by, decision_by):
			req = frappe.get_doc(
				{
					"doctype": "Supplier Master Change Request",
					"change_type": "Update Bank Details",
					"target_supplier": supplier,
					"requested_by": requested_by,
					"decision_by": decision_by,
				}
			)
			req.insert(ignore_permissions=True, ignore_mandatory=True)
			frappe.db.set_value("Supplier Master Change Request", req.name, "workflow_state", "Posted")
			return req.name

		# (1) Self-approved (requester == decider) → NOT lifted.
		name = _smcr(ap_user, ap_user)
		self.assertFalse(has_approved_bank_change(supplier))
		# (2) Non-self but the decider lacks the Treasury Approver role → still NOT
		#     lifted (T-012: an AP clerk can't lift a bank-change block).
		frappe.db.set_value("Supplier Master Change Request", name, "decision_by", ap_user2)
		self.assertFalse(has_approved_bank_change(supplier))
		# (3) A non-requester Treasury Approver lifts it.
		frappe.db.set_value("Supplier Master Change Request", name, "decision_by", treasury)
		self.assertTrue(has_approved_bank_change(supplier))

	# ---- wiring / integration --------------------------------------------

	# AC-08-19
	def test_ac_08_19_stream_r_short_circuits_gates(self):
		supplier = self._new_supplier()
		self._seed_baseline(supplier, n=6, mean=5000.0, stddev=100.0)
		po = self._make_po(qty=10, rate=100, received_qty=0)  # would be an Exception on Stream I
		cap = self._confirmed(
			supplier=supplier,
			matched=supplier,
			total=99999.0,  # would be Anomalous on Stream I
			stream=STREAM_RECEIPT,
			po_ref=po,
			lines=[self._line(10, 100, po)],
		)
		validate_for_purchase_invoice(cap)
		cap.reload()
		self.assertEqual(cap.three_way_match_status, THREE_WAY_MATCH_NOT_APPLICABLE)
		# Stream R records anomaly but never blocks.
		self.assertEqual(cap.validation_status, VALIDATION_STATUS_VALIDATED)

	# AC-08-20
	def test_ac_08_20_closure_evidence_includes_gates(self):
		cap = self._confirmed(total=500.0)
		validate_for_purchase_invoice(cap)
		evidence = build_closure_evidence(cap)
		self.assertIn("gates", evidence)
		self.assertIn("three_way_match", evidence["gates"])
		self.assertIn("anomaly", evidence["gates"])
		self.assertIn("vendor_bank_change", evidence["gates"])

	# AC-08-21 (local sentinel; full-suite regression run separately)
	def test_ac_08_21_happy_path_not_falsely_blocked(self):
		# Stream I, no PO, no bank history, fresh supplier (insufficient history):
		# none of the gates should add a false block.
		supplier = self._new_supplier()
		cap = self._confirmed(supplier=supplier, matched=supplier, total=750.0)
		validate_for_purchase_invoice(cap)
		cap.reload()
		self.assertEqual(cap.validation_status, VALIDATION_STATUS_VALIDATED)
		self.assertEqual(cap.three_way_match_status, THREE_WAY_MATCH_NOT_APPLICABLE)
		self.assertEqual(cap.anomaly_status, ANOMALY_INSUFFICIENT_HISTORY)
		self.assertEqual(int(cap.vendor_bank_change_detected), 0)


class TestAPInvoiceCaptureConfidenceRouting(IntegrationTestCase):
	"""Spec 09 — confidence-based routing (auto-advance vs Needs-Review queue)."""

	def tearDown(self):
		frappe.db.rollback()

	# ---- fixtures ---------------------------------------------------------

	def _promoted(self, *, total="250.00", stream=STREAM_INVOICE):
		"""A promoted Stream-I capture whose 5 mandatory confidence rows are all
		above threshold (the fake extractor populates them at 0.95)."""
		f = _make_file("route-" + frappe.generate_hash(length=6) + ".pdf")
		cap = create_capture_from_file(file_doc=f, source_context="Routing test")
		run_fake_extraction(cap)
		cap.reload()
		confirm_extracted_fields(
			cap,
			corrections={"supplier": "_Test Supplier", "total_amount": total, "currency": "INR"},
			reviewer="Administrator",
		)
		cap.reload()
		validate_for_purchase_invoice(cap)
		cap.reload()
		promote_to_purchase_invoice(cap, defaults=_PROMOTION_DEFAULTS)
		cap.reload()
		self.assertEqual(cap.promotion_status, PROMOTION_STATUS_PROMOTED)
		if stream is not None:
			cap.stream = stream
			cap.save()
			cap.reload()
		return cap

	def _set_conf(self, cap, field_name, above):
		for row in cap.field_confidences:
			if row.field_name == field_name:
				row.is_above_threshold = 1 if above else 0
		cap.save()
		cap.reload()

	def _drop_conf(self, cap, field_name):
		cap.set(
			"field_confidences",
			[r for r in cap.field_confidences if r.field_name != field_name],
		)
		cap.save()
		cap.reload()

	# ---- evaluator (pure) -------------------------------------------------

	# AC-09-1 / AC-09-11
	def test_ac_09_1_evaluator_all_clean(self):
		cap = self._promoted(total="250.00")
		d = _evaluate_routing_signals(cap, threshold=1000)
		self.assertEqual((d.amount_ok, d.fields_ok, d.flags_ok), (True, True, True))
		self.assertIsNone(d.failing_field)
		self.assertIsNone(d.failing_flag)

	# AC-09-12 (single-field short-circuit) + AC-09-4 evaluator side
	def test_ac_09_12_one_low_confidence_field(self):
		cap = self._promoted(total="250.00")
		self._set_conf(cap, "invoice_date", above=False)
		d = _evaluate_routing_signals(cap, threshold=1000)
		self.assertFalse(d.fields_ok)
		self.assertEqual(d.failing_field, "invoice_date")

	# AC-09-6 (missing row → fail-closed)
	def test_ac_09_6_missing_confidence_row_fails_closed(self):
		cap = self._promoted(total="250.00")
		self._drop_conf(cap, "currency")
		d = _evaluate_routing_signals(cap, threshold=1000)
		self.assertFalse(d.fields_ok)
		self.assertEqual(d.failing_field, "currency")

	# AC-09-7 (boundary)
	def test_ac_09_7_amount_at_threshold_is_auto_lane(self):
		cap = self._promoted(total="1000.00")
		d = _evaluate_routing_signals(cap, threshold=1000)
		self.assertTrue(d.amount_ok)  # <= boundary stays auto

	# AC-09-11 (axis independence): empty-table degrade does NOT gate confidence
	def test_ac_09_11_empty_confidence_table_degrades(self):
		cap = self._promoted(total="250.00")
		cap.set("field_confidences", [])
		cap.save()
		cap.reload()
		d = _evaluate_routing_signals(cap, threshold=1000)
		self.assertTrue(d.fields_ok)  # no rows -> don't gate (graceful degrade)

	# ---- request_approval matrix -----------------------------------------

	# AC-09-1
	def test_ac_09_1_clean_under_threshold_auto_approves(self):
		cap = self._promoted(total="250.00")
		request_approval(cap, threshold=1000)
		cap.reload()
		self.assertEqual(cap.approval_status, APPROVAL_STATUS_AUTO_APPROVED)
		self.assertEqual(cap.action_required, 0)

	# AC-09-3
	def test_ac_09_3_clean_over_threshold_pending_manager(self):
		cap = self._promoted(total="5000.00")
		request_approval(cap, threshold=1000)
		cap.reload()
		self.assertEqual(cap.approval_status, APPROVAL_STATUS_PENDING_MANAGER)
		self.assertEqual(cap.assigned_approver_role, MANAGER_APPROVAL_ROLE_DEFAULT)
		self.assertEqual(cap.action_required, 1)

	# AC-09-4 (low confidence → review queue, named field, not auto-posted)
	def test_ac_09_4_low_confidence_routes_to_review(self):
		cap = self._promoted(total="250.00")
		self._set_conf(cap, "invoice_date", above=False)
		request_approval(cap, threshold=1000)
		cap.reload()
		self.assertEqual(cap.approval_status, APPROVAL_STATUS_NEEDS_REVIEW)
		self.assertEqual(cap.action_required, 1)
		self.assertIn("invoice_date", cap.routing_reason)
		# Not an auto state; payment not ready.
		self.assertNotEqual(cap.approval_status, APPROVAL_STATUS_AUTO_APPROVED)

	# AC-09-5 (open validation flag → review queue, named flag)
	def test_ac_09_5_open_validation_flag_routes_to_review(self):
		cap = self._promoted(total="250.00")
		# Force a residual spec-08 gate exception on the promoted capture.
		cap.three_way_match_status = THREE_WAY_MATCH_EXCEPTION
		cap.save()
		cap.reload()
		request_approval(cap, threshold=1000)
		cap.reload()
		self.assertEqual(cap.approval_status, APPROVAL_STATUS_NEEDS_REVIEW)
		self.assertIn("three-way match", cap.routing_reason)

	# AC-09-2 (reconciled): Stream-R Already-Paid skips approval entirely (spec 07).
	def test_ac_09_2_already_paid_skips_approval(self):
		cap = self._promoted(total="250.00")
		# Simulate the spec-07 already-paid posted state.
		cap.document_type = DOCUMENT_TYPE_ALREADY_PAID
		cap.save()
		cap.reload()
		# The cascade's Step-3 approval routing excludes Already-Paid captures.
		nxt = cap._determine_next_step()
		method = nxt[0] if nxt else None
		self.assertNotEqual(method, "request_approval_for")

	# AC-09-13 (stream unset → routes stream-agnostically; never special-cased / no JE).
	# `stream` is a mandatory field, so unset it only in-memory (save=False) to prove
	# the evaluator does not depend on it.
	def test_ac_09_13_stream_unset_routes_normally(self):
		cap = self._promoted(total="250.00")
		cap.stream = None
		request_approval(cap, threshold=1000, save=False)
		self.assertEqual(cap.approval_status, APPROVAL_STATUS_AUTO_APPROVED)

	# AC-09-14 (telemetry doctype absent → route-to-review still completes).
	# Spec 10 ships the AP Review Event doctype, so absence is simulated by
	# monkeypatching the existence guard — the invariant is that routing never
	# fails on the telemetry sink being unavailable.
	def test_ac_09_14_review_event_doctype_absent_is_graceful(self):
		cap = self._promoted(total="250.00")
		self._set_conf(cap, "total_amount", above=False)
		real_exists = frappe.db.exists

		def _fake_exists(*args, **kwargs):
			if args and args[0] == "DocType" and len(args) > 1 and args[1] == "AP Review Event":
				return None
			return real_exists(*args, **kwargs)

		frappe.db.exists = _fake_exists
		try:
			request_approval(cap, threshold=1000)  # must not raise
		finally:
			frappe.db.exists = real_exists
		cap.reload()
		self.assertEqual(cap.approval_status, APPROVAL_STATUS_NEEDS_REVIEW)

	# ---- re-route + guards ------------------------------------------------

	# AC-09-8 (two-hop: flagged → cleared → Pending Manager)
	def test_ac_09_8_reroute_after_review(self):
		cap = self._promoted(total="5000.00")  # over threshold
		self._set_conf(cap, "invoice_date", above=False)
		request_approval(cap, threshold=1000)
		cap.reload()
		self.assertEqual(cap.approval_status, APPROVAL_STATUS_NEEDS_REVIEW)
		# Clerk clears the low-confidence field, then re-routes.
		self._set_conf(cap, "invoice_date", above=True)
		reroute_after_review(cap)
		cap.reload()
		self.assertEqual(cap.approval_status, APPROVAL_STATUS_PENDING_MANAGER)

	# AC-09-9 (double-route + ineligible re-route both raise)
	def test_ac_09_9_double_route_and_ineligible_reroute_raise(self):
		cap = self._promoted(total="250.00")
		request_approval(cap, threshold=1000)
		cap.reload()
		# Normal entrypoint refuses an already-routed capture.
		with self.assertRaises(CaptureApprovalError):
			request_approval(cap, threshold=1000)
		# Re-route refuses a capture that is not in Needs Review.
		with self.assertRaises(CaptureApprovalError):
			reroute_after_review(cap)
		# Re-route refuses a still-flagged Needs-Review capture.
		cap2 = self._promoted(total="250.00")
		self._set_conf(cap2, "currency", above=False)
		request_approval(cap2, threshold=1000)
		cap2.reload()
		self.assertEqual(cap2.approval_status, APPROVAL_STATUS_NEEDS_REVIEW)
		with self.assertRaises(CaptureApprovalError):
			reroute_after_review(cap2)  # still flagged

	# AC-09-10 (settings fallback to the 1000.0 constant + source)
	def test_ac_09_10_threshold_settings_fallback(self):
		threshold, source = _resolve_approval_threshold(None, None)
		self.assertEqual(threshold, 1000.0)
		self.assertEqual(source, APPROVAL_SOURCE_DEFAULT)
		# Explicit override wins.
		t2, s2 = _resolve_approval_threshold(2500.0, None)
		self.assertEqual(t2, 2500.0)
		self.assertEqual(s2, "explicit-override")


class TestAPReviewGate(IntegrationTestCase):
	"""Spec 10 — reject/reopen transitions + step-9 instrumentation wiring."""

	def tearDown(self):
		frappe.db.rollback()

	def _proposed(self, filename="reject-me.pdf"):
		"""A capture parked at Proposed (post-OCR, pre-confirm)."""
		f = _make_file(filename)
		cap = create_capture_from_file(file_doc=f, source_context="Reject test")
		run_fake_extraction(cap)
		cap.reload()
		self.assertEqual(cap.status, STATUS_PROPOSED)
		return cap

	def _events(self, capture_name):
		return frappe.get_all(
			"AP Review Event",
			filters={"capture": capture_name},
			fields=["name", "action_taken", "root_cause_tag"],
		)

	# AC-10-1 (reject positive)
	def test_ac_10_1_reject_positive(self):
		cap = self._proposed()
		reject_capture(cap, reason="bad scan")
		cap.reload()
		self.assertEqual(cap.status, STATUS_REJECTED)
		self.assertEqual(cap.action_required, 0)
		rows = cap.rejection_log
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].action, REJECTION_ACTION_REJECTED)
		self.assertEqual(rows[0].from_status, STATUS_PROPOSED)
		self.assertEqual(rows[0].actor, "Administrator")
		evs = [e for e in self._events(cap.name) if e.action_taken == REVIEW_ACTION_REJECTED]
		self.assertEqual(len(evs), 1)

	# AC-10-2 (reject blocked when promoted)
	def test_ac_10_2_reject_blocked_when_promoted(self):
		cap = self._proposed()
		confirm_extracted_fields(
			cap, corrections={"supplier": "_Test Supplier", "total_amount": "250", "currency": "INR"}
		)
		cap.reload()
		validate_for_purchase_invoice(cap)
		cap.reload()
		promote_to_purchase_invoice(cap, defaults=_PROMOTION_DEFAULTS)
		cap.reload()
		self.assertEqual(cap.promotion_status, PROMOTION_STATUS_PROMOTED)
		events_before = len(self._events(cap.name))
		with self.assertRaises(CaptureValidationError):
			reject_capture(cap, reason="too late")
		cap.reload()
		self.assertNotEqual(cap.status, STATUS_REJECTED)
		self.assertEqual(len(cap.rejection_log), 0)
		# No rejected event added by the failed call.
		rejected = [e for e in self._events(cap.name) if e.action_taken == REVIEW_ACTION_REJECTED]
		self.assertEqual(len(rejected), 0)

	# AC-10-3 (reject idempotency)
	def test_ac_10_3_double_reject_raises(self):
		cap = self._proposed()
		reject_capture(cap, reason="bad scan")
		cap.reload()
		with self.assertRaises(CaptureValidationError):
			reject_capture(cap, reason="again")
		cap.reload()
		self.assertEqual(len([r for r in cap.rejection_log if r.action == REJECTION_ACTION_REJECTED]), 1)

	# AC-10-4 (Rejected survives save / re-validate)
	def test_ac_10_4_rejected_survives_save(self):
		cap = self._proposed()
		reject_capture(cap, reason="bad scan")
		# Reload from DB and save again — validate() must not clobber Rejected.
		fresh = frappe.get_doc("AP Invoice Capture", cap.name)
		self.assertEqual(fresh.status, STATUS_REJECTED)
		fresh.save()
		fresh.reload()
		self.assertEqual(fresh.status, STATUS_REJECTED)

	# AC-10-5 (reject audit — Version row written)
	def test_ac_10_5_reject_writes_version(self):
		cap = self._proposed()
		reject_capture(cap, reason="bad scan")
		self.assertTrue(
			frappe.db.exists("Version", {"ref_doctype": "AP Invoice Capture", "docname": cap.name})
		)

	# AC-10-6 (reopen positive — restores recorded from_status)
	def test_ac_10_6_reopen_restores_stage(self):
		cap = self._proposed()
		confirm_extracted_fields(cap, corrections={"supplier": ""})  # force Needs Correction
		cap.reload()
		self.assertEqual(cap.status, STATUS_NEEDS_CORRECTION)
		reject_capture(cap, reason="bounce")
		cap.reload()
		reopen_capture(cap, reason="vendor resent")
		cap.reload()
		self.assertEqual(cap.status, STATUS_NEEDS_CORRECTION)
		self.assertEqual(cap.action_required, 1)
		self.assertTrue(any(r.action == REJECTION_ACTION_REOPENED for r in cap.rejection_log))

	# AC-10-7 (reopen blocked when not rejected)
	def test_ac_10_7_reopen_blocked_when_not_rejected(self):
		cap = self._proposed()
		with self.assertRaises(CaptureValidationError):
			reopen_capture(cap, reason="nope")

	# AC-10-8 (trail preserved across cycles)
	def test_ac_10_8_trail_preserved(self):
		cap = self._proposed()
		reject_capture(cap, reason="r1")
		cap.reload()
		reopen_capture(cap, reason="o1")
		cap.reload()
		reject_capture(cap, reason="r2")
		cap.reload()
		actions = [r.action for r in cap.rejection_log]
		self.assertEqual(
			actions,
			[REJECTION_ACTION_REJECTED, REJECTION_ACTION_REOPENED, REJECTION_ACTION_REJECTED],
		)

	# AC-10-12 (confirm emits one event with the corrected field)
	def test_ac_10_12_confirm_emits_event(self):
		cap = self._proposed()
		confirm_extracted_fields(
			cap,
			corrections={"supplier": "_Test Supplier", "total_amount": "999", "currency": "INR"},
		)
		cap.reload()
		evs = [
			e
			for e in self._events(cap.name)
			if e.action_taken in (REVIEW_ACTION_FIELD_CORRECTED, REVIEW_ACTION_CODING_COMPLETED)
		]
		self.assertEqual(len(evs), 1)
		fc = frappe.db.get_value("AP Review Event", evs[0].name, "fields_changed")
		self.assertIn("total_amount", fc or "")

	# AC-10-13 (manager reject emits one event)
	def test_ac_10_13_manager_reject_emits_event(self):
		cap = self._proposed()
		confirm_extracted_fields(
			cap, corrections={"supplier": "_Test Supplier", "total_amount": "5000", "currency": "INR"}
		)
		cap.reload()
		validate_for_purchase_invoice(cap)
		cap.reload()
		promote_to_purchase_invoice(cap, defaults=_PROMOTION_DEFAULTS)
		cap.reload()
		request_approval(cap, threshold=1000)  # over threshold -> Pending Manager
		cap.reload()
		self.assertEqual(cap.approval_status, APPROVAL_STATUS_PENDING_MANAGER)
		record_manager_decision(cap, approve=False, notes="policy")
		cap.reload()
		rejected = [e for e in self._events(cap.name) if e.action_taken == REVIEW_ACTION_REJECTED]
		self.assertEqual(len(rejected), 1)
		self.assertEqual(rejected[0].root_cause_tag, ROOT_CAUSE_POLICY_VIOLATION)

	# AC-10-14 (Stream R does not emit an approval/rejection-root-cause event)
	def test_ac_10_14_stream_r_no_approval_root_cause(self):
		cap = self._proposed()
		confirm_extracted_fields(
			cap, corrections={"supplier": "_Test Supplier", "total_amount": "5000", "currency": "INR"}
		)
		cap.reload()
		validate_for_purchase_invoice(cap)
		cap.reload()
		promote_to_purchase_invoice(cap, defaults=_PROMOTION_DEFAULTS)
		cap.reload()
		request_approval(cap, threshold=1000)
		cap.reload()
		# Flip to Stream R before the manager reject.
		cap.stream = STREAM_RECEIPT
		cap.save()
		cap.reload()
		record_manager_decision(cap, approve=False, notes="junk")
		cap.reload()
		rejected = [e for e in self._events(cap.name) if e.action_taken == REVIEW_ACTION_REJECTED]
		self.assertEqual(len(rejected), 0)  # Stream R emits no approval/rejection root cause

	# AC-10-15 (Rejected excluded from cascade)
	def test_ac_10_15_rejected_excluded_from_cascade(self):
		cap = self._proposed()
		reject_capture(cap, reason="bad scan")
		cap.reload()
		self.assertIsNone(cap._determine_next_step())

	# AC-10-16 (report renders grouped by root_cause_tag)
	def test_ac_10_16_report_renders(self):
		cap = self._proposed()
		emit_review_event(cap, action_taken=REVIEW_ACTION_FIELD_CORRECTED, root_cause_tag="extraction_miss")
		emit_review_event(cap, action_taken=REVIEW_ACTION_REJECTED, root_cause_tag="policy_violation")
		report = frappe.get_doc("Report", "AP Top Step 9 Root Causes")
		self.assertEqual(report.report_type, "Query Report")
		self.assertEqual(report.ref_doctype, "AP Review Event")
		self.assertEqual(report.is_standard, "Yes")
		from frappe.desk.query_report import run

		res = run("AP Top Step 9 Root Causes", filters={"from_date": None, "to_date": None})
		# Rows may be dicts or tuples depending on the runner; assert tag presence
		# shape-agnostically over the serialized result.
		blob = json.dumps(res["result"], default=str)
		self.assertIn("extraction_miss", blob)
		self.assertIn("policy_violation", blob)
		self.assertGreaterEqual(len(res["result"]), 2)

	# AC-10-17 (chart groups by root_cause_tag)
	def test_ac_10_17_chart_groups_by_root_cause(self):
		chart = frappe.get_doc("Dashboard Chart", "AP Review Root Causes")
		self.assertEqual(chart.document_type, "AP Review Event")
		self.assertEqual(chart.chart_type, "Group By")
		self.assertEqual(chart.group_by_based_on, "root_cause_tag")


class TestAPInvoiceCaptureAutoConfirm(IntegrationTestCase):
	"""T-015 — confidence-gated auto-confirm (spec 04/09 §5.6).

	The cascade auto-confirms the OCR proposal (skipping the human pause at Proposed)
	when every mandatory header field cleared its confidence threshold, no validation
	flag is open, and the opt-in setting is ON. Off by default — escalate the doubtful.
	"""

	def tearDown(self):
		frappe.db.rollback()

	def _set_auto_confirm(self, on):
		frappe.db.set_single_value("AP Closed Loop Settings", "auto_confirm_enabled", 1 if on else 0)

	def _proposed(self):
		"""A capture at Proposed with all 5 mandatory confidences above threshold
		(the fake extractor scores them 0.95)."""
		f = _make_file("auto-confirm-" + frappe.generate_hash(length=6) + ".pdf")
		cap = create_capture_from_file(file_doc=f, source_context="Auto-confirm test")
		run_fake_extraction(cap)
		cap.reload()
		self.assertEqual(cap.status, STATUS_PROPOSED)
		return cap

	def _low_conf(self, cap, field_name):
		for row in cap.field_confidences:
			if row.field_name == field_name:
				row.is_above_threshold = 0
		cap.save()
		cap.reload()

	# --- evaluator ---------------------------------------------------------

	def test_confirm_signals_clean(self):
		cap = self._proposed()
		d = _evaluate_confirm_signals(cap)
		self.assertTrue(d.fields_ok)
		self.assertTrue(d.flags_ok)

	def test_confirm_signals_low_confidence(self):
		cap = self._proposed()
		self._low_conf(cap, "invoice_date")
		d = _evaluate_confirm_signals(cap)
		self.assertFalse(d.fields_ok)
		self.assertEqual(d.failing_field, "invoice_date")

	def test_confirm_signals_open_flag(self):
		cap = self._proposed()
		cap.three_way_match_status = THREE_WAY_MATCH_EXCEPTION
		cap.save()
		cap.reload()
		d = _evaluate_confirm_signals(cap)
		self.assertFalse(d.flags_ok)

	# --- cascade routing (the hop) ----------------------------------------

	# AC-04-16 / AC-09-15 (routing): clean + ON → the cascade picks the auto-confirm hop.
	def test_ac_04_16_hop_selected_when_clean(self):
		cap = self._proposed()
		self._set_auto_confirm(True)
		nxt = cap._determine_next_step()
		self.assertEqual(nxt[0], "auto_confirm_extracted_fields_for")

	# AC-04-17 / AC-09-16 (fail-safe): low confidence → no auto-confirm hop.
	def test_ac_04_17_failsafe_low_confidence(self):
		cap = self._proposed()
		self._low_conf(cap, "currency")
		self._set_auto_confirm(True)
		nxt = cap._determine_next_step()
		self.assertNotEqual((nxt or [None])[0], "auto_confirm_extracted_fields_for")

	# AC-04-18 (fail-safe): open validation flag → no auto-confirm hop.
	def test_ac_04_18_failsafe_open_flag(self):
		cap = self._proposed()
		cap.three_way_match_status = THREE_WAY_MATCH_EXCEPTION
		cap.save()
		cap.reload()
		self._set_auto_confirm(True)
		nxt = cap._determine_next_step()
		self.assertNotEqual((nxt or [None])[0], "auto_confirm_extracted_fields_for")

	# AC-04-19 / AC-09-17 (regression): default OFF → still pauses at Proposed.
	def test_ac_04_19_default_off_pauses(self):
		cap = self._proposed()
		self._set_auto_confirm(False)
		nxt = cap._determine_next_step()
		self.assertNotEqual((nxt or [None])[0], "auto_confirm_extracted_fields_for")

	# --- the action -------------------------------------------------------

	# AC-04-16 (action): auto-confirm advances to Confirmed with no human + no event.
	def test_ac_04_16_action_confirms_without_human(self):
		cap = self._proposed()
		self._set_auto_confirm(True)
		events_before = frappe.db.count("AP Review Event", {"capture": cap.name})
		auto_confirm_extracted_fields_for(cap.name)
		cap.reload()
		self.assertEqual(cap.ocr_status, OCR_STATUS_CONFIRMED)
		self.assertIn("Auto-confirmed", cap.review_notes or "")
		# No field_corrected/coding AP Review Event emitted (auto-confirm is not an escalation).
		fc = frappe.get_all(
			"AP Review Event",
			filters={"capture": cap.name, "action_taken": ["in", ["field_corrected", "coding_completed"]]},
		)
		self.assertEqual(len(fc), 0)

	# AC-04-16 (end-to-end): with auto-confirm ON, resuming the cascade from Proposed
	# auto-advances past the human pause with no human click.
	def test_ac_04_16_end_to_end_skips_proposed(self):
		cap = self._proposed()  # built with auto-confirm OFF → parked at Proposed
		self._set_auto_confirm(True)
		cap.reload()
		# The cascade is opt-in under in_test; enable it to drive the auto-confirm hop.
		frappe.flags.ap_auto_progress_enabled = True
		try:
			cap._kick_next_step()
		finally:
			frappe.flags.ap_auto_progress_enabled = False
		cap.reload()
		self.assertEqual(cap.ocr_status, OCR_STATUS_CONFIRMED)
		self.assertNotEqual(cap.status, STATUS_PROPOSED)

	# Gate lost after enqueue → the action no-ops (stays at Proposed).
	def test_action_noops_when_gate_lost(self):
		cap = self._proposed()
		self._low_conf(cap, "supplier")  # gate no longer holds
		self._set_auto_confirm(True)
		auto_confirm_extracted_fields_for(cap.name)
		cap.reload()
		self.assertEqual(cap.ocr_status, OCR_STATUS_PROPOSED)


class TestAPCodingHistory(IntegrationTestCase):
	"""T-016 — coding bootstrap from history (spec 06 §5.3.1).

	A routine vendor with no coding profile self-codes from its own prior posted PIs
	when their coding is consistent; a split history escalates to Coding Review; thin
	history falls through; a profile/caller value always wins over history.
	"""

	_A = "_Test Account Cost for Goods Sold - _TC"
	_B = "Administrative Expenses - _TC"
	_C = "Cost of Goods Sold - _TC"
	_CC = "_Test Cost Center - _TC"

	def tearDown(self):
		frappe.db.rollback()

	def _supplier(self):
		return frappe.get_doc(
			{
				"doctype": "Supplier",
				"supplier_name": "Hist Vendor " + frappe.generate_hash(length=8),
				"supplier_group": "_Test Supplier Group",
				"supplier_type": "Company",
			}
		).insert(ignore_permissions=True).name

	def _submit_pi(self, supplier, expense, cc):
		pi = frappe.get_doc(
			{
				"doctype": "Purchase Invoice",
				"supplier": supplier,
				"company": "_Test Company",
				"currency": "INR",
				"posting_date": frappe.utils.today(),
				"bill_no": "HIST-" + frappe.generate_hash(length=6),
				"items": [
					{"item_code": "_Test Item", "qty": 1, "rate": 100, "expense_account": expense, "cost_center": cc}
				],
			}
		)
		pi.insert(ignore_permissions=True)
		pi.submit()
		return pi.name

	def _capture(self, supplier):
		f = _make_file("hist-" + frappe.generate_hash(length=6) + ".pdf")
		cap = create_capture_from_file(file_doc=f, source_context="coding-history test")
		run_fake_extraction(cap)
		cap.reload()
		confirm_extracted_fields(cap, corrections={"supplier": supplier, "total_amount": "100", "currency": "INR"})
		cap.reload()
		validate_for_purchase_invoice(cap)
		cap.reload()
		self.assertEqual(cap.matched_supplier, supplier)
		return cap

	# AC-06-15 — consistent history auto-codes with no profile.
	def test_ac_06_15_consistent_history_auto_codes(self):
		sup = self._supplier()
		for _ in range(3):
			self._submit_pi(sup, self._A, self._CC)
		derived, ambiguous = _derive_coding_from_history(sup)
		self.assertEqual(derived.get("expense_account"), self._A)
		self.assertEqual(derived.get("cost_center"), self._CC)
		self.assertEqual(ambiguous, {})
		cap = self._capture(sup)
		self.assertFalse(frappe.db.exists("AP Supplier Coding Profile", sup))  # no profile
		apply_coding_profile_for(cap)
		cap.reload()
		self.assertEqual(cap.applied_expense_account, self._A)
		self.assertEqual(cap.applied_cost_center, self._CC)
		self.assertEqual(cap.coding_status, CODING_STATUS_CODED)
		self.assertTrue(is_fully_coded(cap))

	# AC-06-16 — split history escalates to Coding Review naming the competing values.
	def test_ac_06_16_split_history_escalates(self):
		sup = self._supplier()
		for e in (self._A, self._A, self._B, self._B):  # 50/50, no consensus
			self._submit_pi(sup, e, self._CC)
		derived, ambiguous = _derive_coding_from_history(sup)
		self.assertNotIn("expense_account", derived)
		self.assertIn("expense_account", ambiguous)
		cap = self._capture(sup)
		apply_coding_profile_for(cap)
		cap.reload()
		self.assertEqual(cap.coding_status, CODING_STATUS_AMBIGUOUS)
		self.assertIn("history split", cap.coding_review_reason or "")
		self.assertFalse(is_fully_coded(cap))

	# AC-06-17 — thin history (< min samples) falls through; no auto-post on shaky evidence.
	def test_ac_06_17_thin_history_falls_through(self):
		sup = self._supplier()
		for _ in range(2):  # below min_samples (3)
			self._submit_pi(sup, self._A, self._CC)
		derived, ambiguous = _derive_coding_from_history(sup)
		self.assertEqual(derived, {})
		self.assertEqual(ambiguous, {})
		cap = self._capture(sup)
		apply_coding_profile_for(cap)
		cap.reload()
		self.assertNotEqual(cap.applied_expense_account, self._A)  # thin history did not apply

	# AC-06-18 — profile (then caller) win over history.
	def test_ac_06_18_profile_and_caller_win(self):
		sup = self._supplier()
		for _ in range(3):
			self._submit_pi(sup, self._A, self._CC)  # consistent history = A
		frappe.get_doc(
			{"doctype": "AP Supplier Coding Profile", "supplier": sup, "default_expense_account": self._B}
		).insert(ignore_permissions=True)  # profile = B
		cap = self._capture(sup)
		apply_coding_profile_for(cap)
		cap.reload()
		self.assertEqual(cap.applied_expense_account, self._B)  # profile beats history
		cap2 = self._capture(sup)
		apply_coding_profile_for(cap2, defaults={"expense_account": self._C})
		cap2.reload()
		self.assertEqual(cap2.applied_expense_account, self._C)  # caller beats both


class TestAPClassificationTrustContent(IntegrationTestCase):
	"""T-017 — classification trusts confident content over a disagreeing intake tag
	(spec 07 §5.3). Default OFF; only genuinely ambiguous content still escalates."""

	def tearDown(self):
		frappe.db.rollback()

	def _set(self, on):
		frappe.db.set_single_value("AP Closed Loop Settings", "enable_classification_trust_content", 1 if on else 0)

	def _confirmed(self, source_context, supplier="_Test Supplier"):
		f = _make_file("t017-" + frappe.generate_hash(length=6) + ".pdf")
		cap = create_capture_from_file(file_doc=f, source_context=source_context)
		run_fake_extraction(cap)
		cap.reload()
		confirm_extracted_fields(cap, corrections={"supplier": supplier, "currency": "INR", "total_amount": "100"}, reviewer="Administrator")
		cap.reload()
		cap.matched_supplier = supplier
		cap.save(ignore_permissions=True)
		return cap

	# AC-07-15 — confident content (card marker) beats a disagreeing intake tag, no human.
	def test_ac_07_15_confident_content_beats_intake(self):
		cap = self._confirmed(source_context="paid by Visa ****1234")  # content → Already Paid (R)
		cap.stream = "Invoice (I)"  # intake tagged I → disagreement
		cap.save(ignore_permissions=True)
		self._set(True)
		classify_document_type(cap)
		cap.reload()
		self.assertEqual(cap.document_type, DOCUMENT_TYPE_ALREADY_PAID)
		self.assertEqual(cap.classified_stream, CLASSIFIED_STREAM_R)
		self.assertEqual(cap.stream_tag_agreement, STREAM_AGREEMENT_DISAGREE)
		self.assertNotEqual(cap.status, STATUS_MANUAL_REVIEW)  # did NOT halt
		self.assertEqual(cap.action_required, 0)
		# Exactly one stream_mistag AP Review Event recording the silent correction.
		evs = frappe.get_all("AP Review Event", filters={"capture": cap.name, "root_cause_tag": ROOT_CAUSE_STREAM_MISTAG})
		self.assertEqual(len(evs), 1)

	# AC-07-16 — genuinely ambiguous content still escalates to Manual Review.
	def test_ac_07_16_ambiguous_content_escalates(self):
		cap = self._confirmed(source_context="ordinary bill")  # no marker → Unpaid Bill (I)
		cap.stream = "Receipt (R)"  # intake tagged R → disagreement (R vs I)
		# Make the content NOT confident: drop a mandatory field below threshold.
		for r in cap.field_confidences:
			if r.field_name == "total_amount":
				r.is_above_threshold = 0
		cap.save(ignore_permissions=True)
		self._set(True)
		classify_document_type(cap)
		cap.reload()
		self.assertEqual(cap.document_type, DOCUMENT_TYPE_MANUAL_REVIEW)
		self.assertEqual(cap.status, STATUS_MANUAL_REVIEW)
		self.assertEqual(cap.action_required, 1)

	# Regression — default OFF: a disagreement unconditionally escalates as shipped.
	def test_default_off_escalates(self):
		cap = self._confirmed(source_context="paid by Visa ****1234")
		cap.stream = "Invoice (I)"
		cap.save(ignore_permissions=True)
		self._set(False)
		classify_document_type(cap)
		cap.reload()
		self.assertEqual(cap.document_type, DOCUMENT_TYPE_MANUAL_REVIEW)
		self.assertEqual(cap.status, STATUS_MANUAL_REVIEW)


class TestAPApprovalSoD(IntegrationTestCase):
	"""Spec 11 (automation-first pilot) — segregation-of-duties identity guard + roles.

	The real control: a role check alone can't stop a manager from approving an invoice
	they themselves prepared. The app-code SoD guard blocks self-approval above threshold
	(Administrator is the audited break-glass exception).
	"""

	def tearDown(self):
		frappe.db.rollback()

	def _user(self, tag):
		email = "{0}-{1}@example.com".format(tag, frappe.generate_hash(length=6))
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": tag, "send_welcome_email": 0}
		).insert(ignore_permissions=True)
		return email

	def _pending_manager(self):
		"""A promoted capture routed to Pending Manager (total over threshold)."""
		f = _make_file("sod-" + frappe.generate_hash(length=6) + ".pdf")
		cap = create_capture_from_file(file_doc=f, source_context="SoD test")
		run_fake_extraction(cap)
		cap.reload()
		confirm_extracted_fields(cap, corrections={"supplier": "_Test Supplier", "total_amount": "5000", "currency": "INR"})
		cap.reload()
		validate_for_purchase_invoice(cap)
		cap.reload()
		promote_to_purchase_invoice(cap, defaults=_PROMOTION_DEFAULTS)
		cap.reload()
		request_approval(cap, threshold=1000)
		cap.reload()
		self.assertEqual(cap.approval_status, APPROVAL_STATUS_PENDING_MANAGER)
		return cap

	# AC-11-4 — the recorded preparer may NOT approve above threshold (the control).
	def test_ac_11_4_preparer_cannot_self_approve(self):
		prep = self._user("prep")
		cap = self._pending_manager()
		cap.reviewed_by = prep
		cap.validated_by = prep
		cap.save(ignore_permissions=True)
		with self.assertRaises(CaptureApprovalError):
			record_manager_decision(cap, approve=True, actor=prep)
		cap.reload()
		self.assertEqual(cap.approval_status, APPROVAL_STATUS_PENDING_MANAGER)  # not advanced

	# AC-11-5 — a clean approver (not the preparer) passes.
	def test_ac_11_5_clean_approver_passes(self):
		prep = self._user("prep")
		approver = self._user("appr")
		cap = self._pending_manager()
		cap.reviewed_by = prep
		cap.validated_by = prep
		cap.save(ignore_permissions=True)
		record_manager_decision(cap, approve=True, actor=approver)
		cap.reload()
		self.assertEqual(cap.approval_status, APPROVAL_STATUS_MANAGER_APPROVED)

	# Self-REJECT is allowed (the control blocks self-approval, not self-rejection).
	def test_preparer_may_self_reject(self):
		prep = self._user("prep")
		cap = self._pending_manager()
		cap.reviewed_by = prep
		cap.validated_by = prep
		cap.save(ignore_permissions=True)
		record_manager_decision(cap, approve=False, actor=prep)  # must not raise
		cap.reload()
		self.assertEqual(cap.approval_status, APPROVAL_STATUS_REJECTED)

	# Administrator is the audited break-glass exception (also the test harness).
	def test_administrator_exempt(self):
		cap = self._pending_manager()  # reviewed_by/validated_by = Administrator
		record_manager_decision(cap, approve=True, actor="Administrator")
		cap.reload()
		self.assertEqual(cap.approval_status, APPROVAL_STATUS_MANAGER_APPROVED)

	# AC-11-8 — resolve_approver_role returns the default; never raises on no matrix.
	def test_ac_11_8_resolve_approver_role_default(self):
		cap = self._pending_manager()
		self.assertEqual(resolve_approver_role(cap), MANAGER_APPROVAL_ROLE_DEFAULT)

	# AC-11-9 — the AP closed-loop roles are installed.
	def test_ac_11_9_roles_installed(self):
		for role in ("AP Clerk", "Treasury Approver", "Auditor (Read Only)"):
			self.assertTrue(frappe.db.exists("Role", role))


class TestAPPaymentAutoPay(IntegrationTestCase):
	"""Spec 12 — per-supplier auto-pay opt-in. A trusted vendor flows approved → paid
	hands-free; every other vendor pauses for a human 'Pay' click (the safe default for
	moving money)."""

	def setUp(self):
		frappe.flags.ap_auto_progress_enabled = True

	def tearDown(self):
		frappe.flags.ap_auto_progress_enabled = False
		frappe.db.rollback()

	def _promoted_small(self, supplier="_Test Supplier"):
		f = _make_file("autopay-" + frappe.generate_hash(length=6) + ".pdf")
		cap = create_capture_from_file(file_doc=f)
		cap.reload()
		confirm_extracted_fields_for(
			cap.name, corrections={"supplier": supplier, "total_amount": "250.00", "currency": "INR"}
		)
		cap.reload()
		promote_to_purchase_invoice_for(cap.name, defaults=_PROMOTION_DEFAULTS)
		cap.reload()
		return cap

	# Non-eligible vendor: auto-approved + Ready but NOT auto-paid — pauses for a human.
	def test_non_eligible_vendor_pauses_at_ready(self):
		frappe.db.set_value("Supplier", "_Test Supplier", "auto_pay_eligible", 0)
		cap = self._promoted_small()
		self.assertEqual(cap.approval_status, APPROVAL_STATUS_AUTO_APPROVED)
		self.assertEqual(cap.payment_readiness, PAYMENT_READINESS_READY)
		self.assertFalse(cap.payment_entry)  # NOT auto-paid
		# The cascade stops here (no auto-pay hop) until a human pays.
		self.assertNotEqual(
			(cap._determine_next_step() or [None])[0], "issue_mock_payment_for"
		)
		# A human 'Pay' click still works.
		issue_mock_payment(cap.name)
		cap.reload()
		self.assertTrue(cap.payment_entry)

	# Eligible vendor: flows approved → paid hands-free (no human Pay click).
	def test_eligible_vendor_auto_pays(self):
		frappe.db.set_value("Supplier", "_Test Supplier", "auto_pay_eligible", 1)
		cap = self._promoted_small()
		self.assertEqual(cap.approval_status, APPROVAL_STATUS_AUTO_APPROVED)
		self.assertTrue(cap.payment_entry)  # auto-paid by the cascade
		self.assertEqual(cap.payment_lifecycle_status, PAYMENT_LIFECYCLE_CLOSED)


class TestAPBankReconciliation(IntegrationTestCase):
	"""Spec 13/14 — bank-feed match is the EXTERNAL close signal; closure is dual-signal
	(settled AND bank_cleared). The Phase-1 'no Bank Transaction' guardrail is retired."""

	def tearDown(self):
		frappe.db.rollback()

	def _settled(self):
		f = _make_file("bank-" + frappe.generate_hash(length=6) + ".pdf")
		cap = create_capture_from_file(file_doc=f, source_context="Bank recon test")
		run_fake_extraction(cap)
		cap.reload()
		confirm_extracted_fields(cap, corrections={"supplier": "_Test Supplier", "total_amount": "250.00", "currency": "INR"})
		cap.reload()
		validate_for_purchase_invoice(cap)
		cap.reload()
		promote_to_purchase_invoice(cap, defaults=_PROMOTION_DEFAULTS)
		cap.reload()
		request_approval(cap, threshold=1000)
		cap.reload()
		issue_mock_payment(cap)
		cap.reload()
		return cap

	def _bank_transaction_for(self, pe_name, amount):
		bank = frappe.get_doc({"doctype": "Bank", "bank_name": "S13 Bank " + frappe.generate_hash(length=4)}).insert(ignore_permissions=True)
		ba = frappe.get_doc(
			{
				"doctype": "Bank Account",
				"account_name": "S13 Acct " + frappe.generate_hash(length=4),
				"bank": bank.name,
				"is_company_account": 1,
				"company": "_Test Company",
				"account": "_Test Bank - _TC",
			}
		).insert(ignore_permissions=True)
		bt = frappe.get_doc(
			{
				"doctype": "Bank Transaction",
				"date": frappe.utils.today(),
				"bank_account": ba.name,
				"company": "_Test Company",
				"currency": "INR",
				"withdrawal": amount,
				"payment_entries": [
					{"payment_document": "Payment Entry", "payment_entry": pe_name, "allocated_amount": amount}
				],
			}
		)
		bt.insert(ignore_permissions=True)
		return bt.name

	# Settled but no bank match → not bank_cleared, not closed (the dual-signal split).
	def test_settled_not_closed_until_bank_match(self):
		cap = self._settled()
		ev = build_closure_evidence(cap)
		self.assertTrue(ev["settled"])
		self.assertFalse(ev["bank_cleared"])
		self.assertFalse(ev["closed"])

	# Dual-signal closure logic: settled AND bank_cleared → closed.
	def test_dual_signal_closed(self):
		cap = self._settled()
		cap.bank_cleared = 1
		cap.save(ignore_permissions=True)
		ev = build_closure_evidence(cap)
		self.assertTrue(ev["settled"])
		self.assertTrue(ev["bank_cleared"])
		self.assertTrue(ev["closed"])

	# reconcile_bank_for surfaces the native Bank Transaction match → bank_cleared.
	def test_reconcile_bank_sets_cleared(self):
		cap = self._settled()
		self.assertTrue(cap.payment_entry)
		bt = self._bank_transaction_for(cap.payment_entry, 250.0)
		reconcile_bank_for(cap)
		cap.reload()
		self.assertEqual(int(cap.bank_cleared), 1)
		self.assertEqual(cap.bank_transaction, bt)
		self.assertEqual(cap.payment_lifecycle_status, PAYMENT_LIFECYCLE_BANK_CLEARED)
		# Now truly closed (settled AND bank_cleared).
		self.assertTrue(build_closure_evidence(cap)["closed"])

	# The retired guardrail: a Bank Transaction no longer breaks closure (it enables it).
	def test_guardrail_retired(self):
		cap = self._settled()
		self._bank_transaction_for(cap.payment_entry, 250.0)
		reconcile_bank_for(cap)
		cap.reload()
		ev = build_closure_evidence(cap)
		self.assertGreaterEqual(ev["native"]["bank_transaction_count"], 1)  # a BT exists
		self.assertTrue(ev["closed"])  # and that is what CLOSES it now


class TestAPClosureAudit(IntegrationTestCase):
	"""Spec 14 — single-record audit retrieval (closure evidence + Version history) and
	the flag-only 7-year IRS retention scan (NEVER deletes)."""

	def tearDown(self):
		frappe.db.rollback()

	def _settled(self, filename="audit.pdf", total_amount="250.00"):
		f = _make_file(filename)
		cap = create_capture_from_file(file_doc=f, source_context="Audit test")
		run_fake_extraction(cap)
		cap.reload()
		confirm_extracted_fields(
			cap,
			corrections={"supplier": "_Test Supplier", "total_amount": total_amount, "currency": "INR"},
			reviewer="Administrator",
		)
		cap.reload()
		validate_for_purchase_invoice(cap)
		cap.reload()
		promote_to_purchase_invoice(cap, defaults=_PROMOTION_DEFAULTS)
		cap.reload()
		request_approval(cap, threshold=1000)
		cap.reload()
		if cap.approval_status == APPROVAL_STATUS_PENDING_MANAGER:
			record_manager_decision(cap, approve=True, notes="Approved for audit test.")
			cap.reload()
		issue_mock_payment(cap)
		cap.reload()
		return cap

	# AC-14: the audit trail composes the full closure evidence PLUS field-level history.
	def test_audit_trail_composes_evidence_and_history(self):
		cap = self._settled("audit-compose.pdf")
		# Frappe v16 defaults ignore_version=True under frappe.in_test, so the
		# lifecycle's own saves leave no Version in test mode. Write one tracked
		# Version explicitly so the audit-history block is exercised deterministically
		# (in production the lifecycle saves produce these versions on their own).
		audit_doc = frappe.get_doc("AP Invoice Capture", cap.name)
		audit_doc.source_context = (audit_doc.source_context or "") + " [audit-review]"
		audit_doc.save(ignore_version=False)
		cap.reload()

		trail = build_audit_trail_for(cap)

		# Closure-evidence backbone is present (composite includes everything closure has).
		self.assertEqual(trail["capture"]["name"], cap.name)
		self.assertIn("ocr", trail)
		self.assertIn("validation", trail)
		self.assertIn("approval", trail)
		self.assertIn("payment", trail)
		self.assertIn("settled", trail)
		self.assertIn("closed", trail)
		# Version history block (track_changes=1 → the lifecycle saves produced versions).
		self.assertIsInstance(trail["history"], list)
		self.assertIsInstance(trail["history_count"], int)
		self.assertEqual(trail["history_count"], len(trail["history"]))
		self.assertGreater(trail["history_count"], 0)
		entry = trail["history"][0]
		self.assertIn("version", entry)
		self.assertIn("by", entry)
		self.assertIn("at", entry)
		self.assertIsInstance(entry["changes"], list)
		# Every recorded change is a well-formed {field, from, to} triple.
		for chg in entry["changes"]:
			self.assertIn("field", chg)
			self.assertIn("from", chg)
			self.assertIn("to", chg)

	# AC-14-3 (audit-trail negative): an unknown capture raises DoesNotExistError.
	def test_audit_trail_unknown_raises(self):
		with self.assertRaises(frappe.DoesNotExistError):
			build_audit_trail_for("AP-DOES-NOT-EXIST-0000")

	# AC-14-4 (audit-trail edge): a capture with no PI/PE yields bank_match == None
	# and does NOT throw (history may be empty in test mode).
	def test_audit_trail_no_payment_no_throw(self):
		f = _make_file("audit-nopay.pdf")
		cap = create_capture_from_file(file_doc=f, source_context="Audit no-pay")
		run_fake_extraction(cap)
		cap.reload()
		trail = build_audit_trail_for(cap)  # must not raise
		# No PE yet → unmatched bank_match (bank_cleared False, no Bank Transaction),
		# not settled, not closed, empty history — all without throwing.
		self.assertFalse(trail["bank_match"]["bank_cleared"])
		self.assertIsNone(trail["bank_match"]["bank_transaction"])
		self.assertFalse(trail["settled"])
		self.assertFalse(trail["closed"])
		self.assertIsInstance(trail["history"], list)

	# AC-14: the whitelisted wrapper resolves a name and returns the same composite shape.
	def test_audit_trail_by_name_matches_doc(self):
		cap = self._settled("audit-byname.pdf")
		by_doc = build_audit_trail_for(cap)
		by_name = build_audit_trail_for(cap.name)
		self.assertEqual(by_name["capture"]["name"], by_doc["capture"]["name"])
		self.assertEqual(by_name["history_count"], by_doc["history_count"])

	# AC-14: retention is flag-only — old captures are COUNTED, never deleted.
	def test_retention_flags_old_captures_without_deleting(self):
		cap = self._settled("audit-old.pdf")
		# Backdate beyond the 7-year IRS window.
		old_date = add_to_date(today(), years=-8)
		frappe.db.set_value("AP Invoice Capture", cap.name, "received_at", old_date)

		before = frappe.db.count("AP Invoice Capture")
		result = enforce_retention_policy()
		after = frappe.db.count("AP Invoice Capture")

		self.assertEqual(result["cutoff"], add_to_date(today(), years=-7))
		self.assertGreaterEqual(result["past_retention"], 1)
		# NEVER deletes: the record still exists and the row count is unchanged.
		self.assertEqual(before, after)
		self.assertTrue(frappe.db.exists("AP Invoice Capture", cap.name))

	# AC-14: a recently-received capture is NOT past retention.
	def test_retention_excludes_recent_capture(self):
		cap = self._settled("audit-recent.pdf")
		frappe.db.set_value("AP Invoice Capture", cap.name, "received_at", today())
		# Sweep all backdated captures so only the recent one is in scope for the delta check.
		past_names = set(
			frappe.get_all(
				"AP Invoice Capture",
				filters={"received_at": ["<", add_to_date(today(), years=-7)]},
				pluck="name",
			)
		)
		self.assertNotIn(cap.name, past_names)


class TestAPMockPaymentAccountResolution(IntegrationTestCase):
	"""The mock Payment Entry's disbursing account must be scoped to the PI's company.

	Regression: a hardcoded ``_Test Bank - _TC`` made `issue_mock_payment` fail for any
	other company with ``Account ... does not belong to Company ...``. The resolver must
	pick a company-appropriate account."""

	def tearDown(self):
		frappe.db.rollback()

	def _make_company(self):
		name = "AP MockPay Co " + frappe.generate_hash(length=5)
		co = frappe.get_doc(
			{
				"doctype": "Company",
				"company_name": name,
				"abbr": "MP" + frappe.generate_hash(length=3).upper(),
				"default_currency": "USD",
				"country": "United States",
			}
		).insert(ignore_permissions=True)
		return co.name

	# Positive: explicit override is returned verbatim.
	def test_explicit_override_wins(self):
		self.assertEqual(
			_resolve_mock_pay_account("_Test Company", "Cash - _TC"), "Cash - _TC"
		)

	# Existing behaviour preserved: _Test Company keeps the legacy clearing account.
	def test_test_company_keeps_legacy_default(self):
		self.assertEqual(
			_resolve_mock_pay_account("_Test Company"), MOCK_CLEARING_ACCOUNT_DEFAULT
		)

	# The fix: another company resolves its OWN account, never the _TC bank.
	def test_other_company_resolves_own_account(self):
		company = self._make_company()
		acc = _resolve_mock_pay_account(company)
		self.assertNotEqual(acc, MOCK_CLEARING_ACCOUNT_DEFAULT)
		self.assertEqual(frappe.db.get_value("Account", acc, "company"), company)
		self.assertIn(
			frappe.db.get_value("Account", acc, "account_type"), ("Bank", "Cash")
		)


class TestAPDefaultCodingReflection(IntegrationTestCase):
	"""Mark-and-continue: a capture that promotes WITHOUT the AP coding engine having
	run (graceful-degrade) posts on ERPNext native defaults — that fallback must be
	reflected on the capture (flagged + queued + honest provenance + backfilled
	applied_*), without blocking the cascade."""

	def tearDown(self):
		frappe.db.rollback()

	def _validated(self, filename="defcode.pdf", total="250.00"):
		f = _make_file(filename)
		cap = create_capture_from_file(file_doc=f, source_context="default-coding test")
		run_fake_extraction(cap)
		cap.reload()
		confirm_extracted_fields(
			cap,
			corrections={"supplier": "_Test Supplier", "total_amount": total, "currency": "INR"},
			reviewer="Administrator",
		)
		cap.reload()
		validate_for_purchase_invoice(cap)
		cap.reload()
		return cap

	# Promote without coding → the fallback is reflected, not silent.
	def test_uncoded_promote_reflects_native_defaults(self):
		cap = self._validated("defcode-reflect.pdf")
		self.assertEqual(cap.coding_status, CODING_STATUS_PENDING)  # coding engine never ran
		promote_to_purchase_invoice(cap, defaults=_PROMOTION_DEFAULTS)
		cap.reload()

		# Flagged + honest provenance + reason — no longer silent.
		self.assertEqual(cap.coding_status, CODING_STATUS_FLAGGED)
		self.assertEqual(cap.coding_source, CODING_SOURCE_NATIVE_DEFAULT)
		self.assertTrue(cap.coding_review_reason)
		self.assertIn("native defaults", cap.coding_review_reason)
		# applied_* backfilled from what the PI actually posted.
		pi = frappe.get_doc("Purchase Invoice", cap.purchase_invoice)
		self.assertEqual(cap.applied_expense_account, pi.items[0].expense_account)
		self.assertEqual(cap.applied_cost_center, pi.items[0].cost_center)
		# Queued for coding review…
		queue = {r["name"] for r in get_coding_review_queue_for()}
		self.assertIn(cap.name, queue)

	# Mark-AND-CONTINUE: flagged + queued for review, but approval still proceeds.
	def test_reflected_default_does_not_block_cascade(self):
		cap = self._validated("defcode-continue.pdf")
		promote_to_purchase_invoice(cap, defaults=_PROMOTION_DEFAULTS)
		cap.reload()
		self.assertEqual(cap.coding_status, CODING_STATUS_FLAGGED)
		self.assertEqual(int(cap.action_required), 1)  # surfaced for review…
		# …but the cascade does NOT gate on coding_status/action_required — approval routes.
		request_approval(cap, threshold=1000)
		cap.reload()
		self.assertIn(
			cap.approval_status, (APPROVAL_STATUS_AUTO_APPROVED, APPROVAL_STATUS_PENDING_MANAGER)
		)

	# A genuinely-coded capture is NOT overwritten by the fallback stamp.
	def test_real_coding_not_overwritten_on_promote(self):
		cap = self._validated("defcode-realcoded.pdf")
		apply_coding_profile_for(
			cap,
			defaults={
				"expense_account": "_Test Account Cost for Goods Sold - _TC",
				"cost_center": "_Test Cost Center - _TC",
			},
		)
		cap.reload()
		self.assertEqual(cap.coding_status, CODING_STATUS_CODED)
		promote_to_purchase_invoice(cap, defaults=_PROMOTION_DEFAULTS)
		cap.reload()
		# Real coding preserved — reflection did not fire.
		self.assertEqual(cap.coding_status, CODING_STATUS_CODED)
		self.assertEqual(cap.coding_source, CODING_SOURCE_DEFAULT)
