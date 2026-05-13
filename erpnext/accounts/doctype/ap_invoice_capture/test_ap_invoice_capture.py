# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

from io import BytesIO

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import getdate
from pypdf import PdfWriter

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
	OCR_STATUS_CONFIRMED,
	OCR_STATUS_NEEDS_CORRECTION,
	OCR_STATUS_NOT_EXTRACTED,
	OCR_STATUS_PROPOSED,
	PAYMENT_READINESS_BLOCKED,
	PAYMENT_READINESS_NOT_READY,
	PAYMENT_READINESS_READY,
	PROMOTION_STATUS_NOT_PROMOTED,
	PROMOTION_STATUS_PROMOTED,
	PURCHASE_REF_NON_PO,
	PURCHASE_REF_PURCHASE_ORDER,
	PURCHASE_REF_PURCHASE_RECEIPT,
	STATUS_CONFIRMED,
	STATUS_NEEDS_CORRECTION,
	STATUS_PENDING_REVIEW,
	STATUS_PROPOSED,
	STATUS_UNSUPPORTED,
	SUPPLIER_MATCH_AMBIGUOUS,
	SUPPLIER_MATCH_MATCHED,
	SUPPLIER_MATCH_UNKNOWN,
	SUPPORTED_EXTENSIONS,
	VALIDATION_SOURCE_DEFAULT,
	VALIDATION_STATUS_BLOCKED,
	VALIDATION_STATUS_NOT_VALIDATED,
	VALIDATION_STATUS_VALIDATED,
	AmbiguousSourceError,
	CaptureApprovalError,
	CapturePromotionError,
	CaptureValidationError,
	OCRExtractionError,
	confirm_extracted_fields,
	create_capture_from_file,
	is_payment_blocked,
	is_ready_for_payment,
	promote_to_purchase_invoice,
	record_manager_decision,
	request_approval,
	run_fake_extraction,
	validate_for_purchase_invoice,
)

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
		from erpnext.accounts.doctype.ap_invoice_capture import ap_invoice_capture as mod

		original = mod._match_supplier
		try:
			mod._match_supplier = lambda name: (None, SUPPLIER_MATCH_AMBIGUOUS)
			capture = self._confirmed_capture(
				"validate-ambiguous.pdf",
				supplier="Some Shared Name",
			)
			validate_for_purchase_invoice(capture)
			capture.reload()
			self.assertEqual(capture.supplier_match_status, SUPPLIER_MATCH_AMBIGUOUS)
			self.assertEqual(capture.validation_status, VALIDATION_STATUS_BLOCKED)
			self.assertIn("ambiguous", capture.validation_result.lower())
		finally:
			mod._match_supplier = original


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
