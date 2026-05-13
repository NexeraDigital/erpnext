# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""AP Invoice Capture.

Narrow pre-accounting capture record for the AP Closed Loop pilot.

This DocType is the manual intake landing pad for invoice images. It is
explicitly NOT an accounting document and must not progress silently into
Purchase Invoice, Payment Entry, or Bank Transaction. Its job is to:

* preserve the original uploaded artifact (or a traceable reference to it),
* expose source context, received time, lifecycle state, and action-required
  status so an AP clerk can review it,
* reject / flag unsupported or ambiguous formats so they cannot silently
  proceed to payment.

Phase 1 intake channel is Manual ERPNext Upload. Supported formats are PDF,
PNG, JPG, JPEG (case-insensitive).
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date, timedelta

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, now_datetime

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({"pdf", "png", "jpg", "jpeg"})

STATUS_PENDING_REVIEW = "Pending Review"
STATUS_UNSUPPORTED = "Unsupported"
STATUS_REJECTED = "Rejected"
STATUS_PROPOSED = "Proposed"
STATUS_NEEDS_CORRECTION = "Needs Correction"
STATUS_CONFIRMED = "Confirmed"

OCR_STATUS_NOT_EXTRACTED = "Not Extracted"
OCR_STATUS_PROPOSED = "Proposed"
OCR_STATUS_CONFIRMED = "Confirmed"
OCR_STATUS_NEEDS_CORRECTION = "Needs Correction"

INTAKE_MANUAL_UPLOAD = "Manual ERPNext Upload"

FAKE_OCR_PROVIDER = "fake-deterministic-v1"

# Mandatory header fields the AP closed-loop pilot requires before a capture
# can be considered ready for any downstream accounting use. Mapped from the
# logical field name used in the OCR proposal payload to the corresponding
# proposed_* and final_* DocType fieldnames.
MANDATORY_HEADER_FIELDS: tuple[tuple[str, str, str], ...] = (
	("supplier", "proposed_supplier", "final_supplier"),
	("supplier_invoice_no", "proposed_supplier_invoice_no", "final_supplier_invoice_no"),
	("invoice_date", "proposed_invoice_date", "final_invoice_date"),
	("total_amount", "proposed_total_amount", "final_total_amount"),
	("currency", "proposed_currency", "final_currency"),
)

_FAKE_SUPPLIERS: tuple[str, ...] = (
	"Acme Office Supplies",
	"Globex Logistics",
	"Initech Services",
	"Umbrella Holdings",
	"Soylent Foods",
	"Wayne Industries",
)
_FAKE_CURRENCIES: tuple[str, ...] = ("USD", "EUR", "GBP", "CAD")


class AmbiguousSourceError(frappe.ValidationError):
	"""Raised when a capture cannot identify its source artifact."""


class OCRExtractionError(frappe.ValidationError):
	"""Raised when OCR extraction cannot proceed (e.g. unsupported source)."""


class APInvoiceCapture(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		action_required: DF.Check
		action_required_reason: DF.Data | None
		file_extension: DF.Data | None
		final_currency: DF.Data | None
		final_invoice_date: DF.Date | None
		final_supplier: DF.Data | None
		final_supplier_invoice_no: DF.Data | None
		final_total_amount: DF.Float
		intake_channel: DF.Literal["Manual ERPNext Upload"]
		is_supported_format: DF.Check
		ocr_extracted_at: DF.Datetime | None
		ocr_provider: DF.Data | None
		ocr_raw_response: DF.LongText | None
		ocr_status: DF.Literal["Not Extracted", "Proposed", "Confirmed", "Needs Correction"]
		proposed_ambiguous_fields: DF.SmallText | None
		proposed_currency: DF.Data | None
		proposed_invoice_date: DF.Date | None
		proposed_missing_fields: DF.SmallText | None
		proposed_supplier: DF.Data | None
		proposed_supplier_invoice_no: DF.Data | None
		proposed_total_amount: DF.Float
		received_at: DF.Datetime
		review_notes: DF.SmallText | None
		reviewed_at: DF.Datetime | None
		reviewed_by: DF.Link | None
		source_context: DF.SmallText | None
		source_file: DF.Link | None
		source_file_url: DF.Data | None
		source_filename: DF.Data
		status: DF.Literal[
			"Pending Review",
			"Unsupported",
			"Rejected",
			"Proposed",
			"Needs Correction",
			"Confirmed",
		]
		validation_message: DF.SmallText | None
	# end: auto-generated types

	def validate(self):
		if not self.received_at:
			self.received_at = now_datetime()

		self._hydrate_from_linked_file()
		self._require_source_reference()

		extension = _normalize_extension(self.file_extension or self.source_filename or "")
		self.file_extension = extension or None
		supported = extension in SUPPORTED_EXTENSIONS
		self.is_supported_format = 1 if supported else 0

		if not supported:
			# Unsupported / ambiguous artifacts must be visibly blocked from
			# silently progressing to any accounting object.
			self.status = STATUS_UNSUPPORTED
			self.action_required = 1
			if not self.action_required_reason:
				self.action_required_reason = _("Unsupported source format")
			if not self.validation_message:
				self.validation_message = _(
					"Unsupported source format: {0}. Supported formats are PDF, PNG, JPG, JPEG."
				).format(extension or _("unknown"))
		else:
			if not self.status:
				self.status = STATUS_PENDING_REVIEW
			if not self.ocr_status:
				self.ocr_status = OCR_STATUS_NOT_EXTRACTED

			if self.status == STATUS_PENDING_REVIEW:
				self.action_required = 1
				if not self.action_required_reason:
					self.action_required_reason = _("Pending AP review")
			elif self.status == STATUS_PROPOSED:
				# OCR proposal is non-authoritative; AP review is still required.
				self.action_required = 1
				if not self.action_required_reason:
					self.action_required_reason = _("AP review of OCR proposal required")
			elif self.status == STATUS_NEEDS_CORRECTION:
				# Missing mandatory header values must block silent progression.
				self.action_required = 1
				if not self.action_required_reason:
					self.action_required_reason = _("Mandatory fields missing — correction required")

	def _hydrate_from_linked_file(self) -> None:
		"""Pull filename / url off the linked File record when available."""

		if not self.source_file:
			return

		file_row = frappe.db.get_value(
			"File",
			self.source_file,
			["file_name", "file_url"],
			as_dict=True,
		)
		if not file_row:
			return

		if not self.source_filename and file_row.file_name:
			self.source_filename = file_row.file_name
		if not self.source_file_url and file_row.file_url:
			self.source_file_url = file_row.file_url

	def _require_source_reference(self) -> None:
		"""AC-I2: a capture must always carry a traceable source reference."""

		if not (self.source_file or self.source_file_url):
			raise AmbiguousSourceError(
				_("AP Invoice Capture requires a Source File or Source File URL.")
			)
		if not self.source_filename:
			raise AmbiguousSourceError(
				_("AP Invoice Capture requires a Source Filename for traceability.")
			)


def _normalize_extension(value: str) -> str:
	"""Return a lowercase extension without a leading dot.

	Accepts either a bare extension ("PDF", ".pdf") or a path/filename
	("invoice.PDF", "/private/files/invoice.PDF"). Returns "" if no
	extension can be determined.
	"""

	if not value:
		return ""

	candidate = value.strip().lower()
	if "." in candidate:
		# os.path.splitext handles both bare filenames and full paths.
		_, ext = os.path.splitext(candidate)
		candidate = ext

	candidate = candidate.lstrip(".")
	return candidate


def _resolve_filename(file_doc, explicit_filename: str | None) -> str:
	if explicit_filename:
		return explicit_filename
	if file_doc and getattr(file_doc, "file_name", None):
		return file_doc.file_name
	if file_doc and getattr(file_doc, "file_url", None):
		return os.path.basename(file_doc.file_url)
	return ""


def create_capture_from_file(
	file_doc=None,
	file_name: str | None = None,
	file_url: str | None = None,
	source_context: str | None = None,
	intake_channel: str = INTAKE_MANUAL_UPLOAD,
	received_at=None,
):
	"""Deterministic API for creating an AP Invoice Capture.

	Accepts either a Frappe ``File`` document (or its name) via
	``file_doc``, or a raw ``file_url`` / ``file_name`` pair. Always
	creates a capture record; if the source artifact is unsupported the
	capture is created in ``Unsupported`` status with ``action_required``
	set so it cannot silently progress.

	Returns the saved ``AP Invoice Capture`` document.
	"""

	resolved_file = None
	resolved_file_name = None
	if file_doc is not None:
		if isinstance(file_doc, str):
			resolved_file = frappe.get_doc("File", file_doc)
		else:
			resolved_file = file_doc
		resolved_file_name = resolved_file.name

	effective_filename = _resolve_filename(resolved_file, file_name)
	effective_url = file_url or (resolved_file.file_url if resolved_file else None)

	capture = frappe.new_doc("AP Invoice Capture")
	capture.intake_channel = intake_channel or INTAKE_MANUAL_UPLOAD
	capture.received_at = received_at or now_datetime()
	capture.source_filename = effective_filename
	capture.source_file = resolved_file_name
	capture.source_file_url = effective_url
	capture.source_context = source_context
	capture.insert()
	return capture


@frappe.whitelist()
def create_capture_from_uploaded_file(file_name: str, source_context: str | None = None):
	"""Whitelisted entrypoint for the manual ERPNext upload flow.

	``file_name`` is the ``name`` of an existing Frappe ``File`` record
	(the one created when the user uploads through the ERPNext UI).
	"""

	return create_capture_from_file(file_doc=file_name, source_context=source_context).name


# ---------------------------------------------------------------------------
# Deterministic fake OCR / extraction
# ---------------------------------------------------------------------------


def _hash_bytes(seed: str) -> bytes:
	return hashlib.sha256(seed.encode("utf-8")).digest()


def _propose_for_seed(seed: str) -> dict:
	"""Build a deterministic proposal payload from a seed string.

	The same seed always yields the same proposal so tests and dev flows are
	repeatable. The seed should be derived from stable source identifiers
	(filename + url) on the capture.
	"""

	digest = _hash_bytes(seed)
	supplier = _FAKE_SUPPLIERS[digest[0] % len(_FAKE_SUPPLIERS)]
	currency = _FAKE_CURRENCIES[digest[1] % len(_FAKE_CURRENCIES)]
	invoice_no = "INV-{0}".format(digest.hex()[:8].upper())
	# Days back from a fixed reference epoch so dates are stable but realistic.
	days_back = digest[2] + digest[3]
	invoice_date = date(2026, 1, 1) - timedelta(days=days_back)
	# Two-decimal amount derived from the digest; bounded for sane test values.
	cents = int.from_bytes(digest[4:8], "big") % 1_000_000
	total_amount = round(cents / 100.0, 2)

	return {
		"supplier": supplier,
		"supplier_invoice_no": invoice_no,
		"invoice_date": invoice_date.isoformat(),
		"total_amount": total_amount,
		"currency": currency,
	}


def _seed_for_capture(capture: "APInvoiceCapture") -> str:
	# Use both filename and URL so two captures of literally the same artifact
	# yield the same proposal, but two different sources don't collide.
	return "|".join(
		[
			capture.source_filename or "",
			capture.source_file_url or "",
			capture.source_file or "",
		]
	)


def _detect_simulation_markers(filename: str) -> tuple[set[str], set[str]]:
	"""Inspect filename tokens for deterministic missing/ambiguous simulation.

	Filenames containing ``missing_<field>`` cause that mandatory field to be
	dropped from the proposal. Filenames containing ``ambiguous_<field>`` or
	a bare ``ambiguous`` token flag fields as low-confidence (still proposed).
	"""

	lower = (filename or "").lower()
	logical_names = [name for name, _, _ in MANDATORY_HEADER_FIELDS]

	missing: set[str] = set()
	ambiguous: set[str] = set()

	for name in logical_names:
		if f"missing_{name}" in lower:
			missing.add(name)
		if f"ambiguous_{name}" in lower:
			ambiguous.add(name)

	if "ambiguous" in lower and not ambiguous:
		# Bare 'ambiguous' marker flags every mandatory field.
		ambiguous.update(logical_names)

	return missing, ambiguous


def run_fake_extraction(
	capture: "APInvoiceCapture | str",
	*,
	simulate_missing: list[str] | tuple[str, ...] | None = None,
	simulate_ambiguous: list[str] | tuple[str, ...] | None = None,
	save: bool = True,
) -> "APInvoiceCapture":
	"""Run deterministic fake OCR against a capture and persist the proposal.

	The proposal lives only in ``proposed_*`` fields plus ``ocr_*`` metadata
	— it is non-authoritative. ``final_*`` fields are intentionally left
	untouched so downstream consumers cannot mistake an unconfirmed proposal
	for an AP-reviewed value.

	``simulate_missing`` / ``simulate_ambiguous`` override / extend any
	filename-based simulation markers and are intended for explicit test
	cases. They accept the logical field names declared in
	``MANDATORY_HEADER_FIELDS``.
	"""

	if isinstance(capture, str):
		capture = frappe.get_doc("AP Invoice Capture", capture)

	if not capture.is_supported_format:
		raise OCRExtractionError(
			_("Cannot run extraction on an unsupported source format.")
		)

	filename_missing, filename_ambiguous = _detect_simulation_markers(
		capture.source_filename or ""
	)
	missing_fields: set[str] = set(filename_missing)
	ambiguous_fields: set[str] = set(filename_ambiguous)
	if simulate_missing:
		missing_fields.update(simulate_missing)
	if simulate_ambiguous:
		ambiguous_fields.update(simulate_ambiguous)

	proposal = _propose_for_seed(_seed_for_capture(capture))
	# Strip values for any field the caller / filename marks as missing.
	for logical_name in missing_fields:
		if logical_name in proposal:
			proposal[logical_name] = None

	now = now_datetime()
	capture.ocr_provider = FAKE_OCR_PROVIDER
	capture.ocr_extracted_at = now
	capture.ocr_status = OCR_STATUS_PROPOSED

	# Persist proposal into proposed_* fields. final_* stays untouched.
	capture.proposed_supplier = proposal.get("supplier")
	capture.proposed_supplier_invoice_no = proposal.get("supplier_invoice_no")
	capture.proposed_invoice_date = (
		getdate(proposal["invoice_date"]) if proposal.get("invoice_date") else None
	)
	capture.proposed_total_amount = proposal.get("total_amount") or 0.0
	capture.proposed_currency = proposal.get("currency")
	capture.proposed_missing_fields = (
		", ".join(sorted(missing_fields)) if missing_fields else None
	)
	capture.proposed_ambiguous_fields = (
		", ".join(sorted(ambiguous_fields)) if ambiguous_fields else None
	)
	capture.ocr_raw_response = json.dumps(
		{
			"provider": FAKE_OCR_PROVIDER,
			"extracted_at": now.isoformat() if hasattr(now, "isoformat") else str(now),
			"proposal": proposal,
			"missing_fields": sorted(missing_fields),
			"ambiguous_fields": sorted(ambiguous_fields),
		},
		default=str,
		sort_keys=True,
	)

	# Overall capture status moves to Proposed; AP review is still required.
	capture.status = STATUS_PROPOSED
	capture.action_required = 1
	capture.action_required_reason = _("AP review of OCR proposal required")

	if save:
		capture.save()
	return capture


# ---------------------------------------------------------------------------
# AP Clerk review / confirm / correct
# ---------------------------------------------------------------------------


_CORRECTION_FIELDNAMES = {
	"supplier": "final_supplier",
	"supplier_invoice_no": "final_supplier_invoice_no",
	"invoice_date": "final_invoice_date",
	"total_amount": "final_total_amount",
	"currency": "final_currency",
}


def _coerce_correction(logical_name: str, value):
	if value is None or value == "":
		return None
	if logical_name == "invoice_date":
		return getdate(value)
	if logical_name == "total_amount":
		return float(value)
	return value


def confirm_extracted_fields(
	capture: "APInvoiceCapture | str",
	corrections: dict | None = None,
	reviewer: str | None = None,
	notes: str | None = None,
	save: bool = True,
) -> "APInvoiceCapture":
	"""Record an AP clerk's review of an OCR proposal.

	Behavior:
	* Proposed values are copied into ``final_*`` fields, overridden by any
	  ``corrections`` supplied (keyed by logical field name).
	* Reviewer + timestamp are recorded.
	* If any mandatory header field is still empty in ``final_*`` after the
	  merge, the capture is parked at ``status = Needs Correction`` with
	  ``action_required = 1`` so it cannot silently progress.
	* Otherwise the capture is marked ``Confirmed`` and ``action_required``
	  is cleared.
	"""

	if isinstance(capture, str):
		capture = frappe.get_doc("AP Invoice Capture", capture)

	if capture.ocr_status == OCR_STATUS_NOT_EXTRACTED:
		raise OCRExtractionError(
			_("Cannot confirm extracted fields before extraction has run.")
		)

	corrections = corrections or {}

	# Merge proposal -> corrections into final_* fields.
	for logical_name, proposed_field, final_field in MANDATORY_HEADER_FIELDS:
		if logical_name in corrections:
			value = _coerce_correction(logical_name, corrections[logical_name])
		else:
			value = capture.get(proposed_field)
		capture.set(final_field, value)

	# Identify mandatory fields still missing after the merge.
	missing: list[str] = []
	for logical_name, _proposed_field, final_field in MANDATORY_HEADER_FIELDS:
		value = capture.get(final_field)
		if value in (None, "", 0, 0.0):
			missing.append(logical_name)

	capture.reviewed_by = reviewer or frappe.session.user
	capture.reviewed_at = now_datetime()
	if notes is not None:
		capture.review_notes = notes

	if missing:
		# Block silent progression.
		capture.ocr_status = OCR_STATUS_NEEDS_CORRECTION
		capture.status = STATUS_NEEDS_CORRECTION
		capture.action_required = 1
		capture.action_required_reason = _(
			"Mandatory fields missing after review: {0}"
		).format(", ".join(missing))
	else:
		capture.ocr_status = OCR_STATUS_CONFIRMED
		capture.status = STATUS_CONFIRMED
		capture.action_required = 0
		capture.action_required_reason = None

	if save:
		capture.save()
	return capture


@frappe.whitelist()
def run_fake_extraction_for(capture: str) -> str:
	"""Whitelisted helper to trigger fake OCR on an existing capture."""

	doc = run_fake_extraction(capture)
	return doc.name


@frappe.whitelist()
def confirm_extracted_fields_for(
	capture: str,
	corrections: str | dict | None = None,
	notes: str | None = None,
) -> str:
	"""Whitelisted entrypoint for the AP clerk review action.

	``corrections`` may be passed as a JSON string from the client.
	"""

	parsed: dict | None
	if isinstance(corrections, str) and corrections:
		parsed = json.loads(corrections)
	else:
		parsed = corrections or None
	doc = confirm_extracted_fields(capture, corrections=parsed, notes=notes)
	return doc.name
