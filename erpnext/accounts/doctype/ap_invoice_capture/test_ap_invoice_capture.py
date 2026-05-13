# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

from io import BytesIO

import frappe
from frappe.tests import IntegrationTestCase
from pypdf import PdfWriter

from erpnext.accounts.doctype.ap_invoice_capture.ap_invoice_capture import (
	INTAKE_MANUAL_UPLOAD,
	STATUS_PENDING_REVIEW,
	STATUS_UNSUPPORTED,
	SUPPORTED_EXTENSIONS,
	AmbiguousSourceError,
	create_capture_from_file,
)

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
