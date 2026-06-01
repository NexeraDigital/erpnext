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

import fnmatch
import hashlib
import json
import os
import re
from datetime import date, timedelta

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_to_date, flt, getdate, now_datetime, today

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({"pdf", "png", "jpg", "jpeg"})

STATUS_PENDING_REVIEW = "Pending Review"
STATUS_UNSUPPORTED = "Unsupported"
STATUS_REJECTED = "Rejected"
STATUS_PROPOSED = "Proposed"
STATUS_NEEDS_CORRECTION = "Needs Correction"
STATUS_CONFIRMED = "Confirmed"
STATUS_DUPLICATE = "Duplicate"

OCR_STATUS_NOT_EXTRACTED = "Not Extracted"
OCR_STATUS_PROPOSED = "Proposed"
OCR_STATUS_CONFIRMED = "Confirmed"
OCR_STATUS_NEEDS_CORRECTION = "Needs Correction"

SUPPLIER_MATCH_NOT_VALIDATED = "Not Validated"
SUPPLIER_MATCH_MATCHED = "Matched"
SUPPLIER_MATCH_UNKNOWN = "Unknown"
SUPPLIER_MATCH_AMBIGUOUS = "Ambiguous"

PURCHASE_REF_NOT_VALIDATED = "Not Validated"
PURCHASE_REF_NON_PO = "Non-PO / Not Applicable"
PURCHASE_REF_PURCHASE_ORDER = "Purchase Order"
PURCHASE_REF_PURCHASE_RECEIPT = "Purchase Receipt"

VALIDATION_STATUS_NOT_VALIDATED = "Not Validated"
VALIDATION_STATUS_VALIDATED = "Validated"
VALIDATION_STATUS_BLOCKED = "Blocked"

PROMOTION_STATUS_NOT_PROMOTED = "Not Promoted"
PROMOTION_STATUS_PROMOTED = "Promoted"

VALIDATION_SOURCE_DEFAULT = "ap-validation-v1"

APPROVAL_STATUS_NOT_REQUIRED = "Not Required"
APPROVAL_STATUS_AUTO_APPROVED = "Auto Approved"
APPROVAL_STATUS_PENDING_MANAGER = "Pending Manager"
APPROVAL_STATUS_MANAGER_APPROVED = "Manager Approved"
APPROVAL_STATUS_REJECTED = "Rejected"

PAYMENT_READINESS_NOT_READY = "Not Ready"
PAYMENT_READINESS_READY = "Ready for Payment"
PAYMENT_READINESS_BLOCKED = "Blocked"

APPROVAL_SOURCE_DEFAULT = "ap-approval-v1"
AUTO_APPROVAL_THRESHOLD_DEFAULT = 1000.0
MANAGER_APPROVAL_ROLE_DEFAULT = "Accounts Manager"

MOCK_PAYMENT_PROVIDER = "mock_payment_provider"
MOCK_PAYMENT_PREFIX = "MOCK-PAY"
MOCK_CLEARING_ACCOUNT_DEFAULT = "_Test Bank - _TC"
MOCK_PAYMENT_REMARK = (
	"MOCK PAYMENT - AP Closed Loop pilot. Not bank reconciled. No real banking integration."
)

PAYMENT_LIFECYCLE_NOT_REQUESTED = "Not Requested"
PAYMENT_LIFECYCLE_CONFIRMED = "Confirmed"
PAYMENT_LIFECYCLE_CLOSED = "Closed"
PAYMENT_LIFECYCLE_BLOCKED = "Blocked"

INTAKE_MANUAL_UPLOAD = "Manual ERPNext Upload"
INTAKE_EMAIL_INBOUND = "Email Inbound"
INTAKE_MOBILE_UPLOAD = "Mobile Upload"
INTAKE_PORTAL_PULL = "Vendor Portal Pull"

# Stream tag (spec 02). Self-describing parenthesized labels, matching the
# "Fake (Deterministic)" style; the persisted value reads clearly in reports.
STREAM_RECEIPT = "Receipt (R)"
STREAM_INVOICE = "Invoice (I)"
STREAM_UNCLASSIFIED = "Unclassified"
STREAM_DEFAULT_SOURCE = "default"

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


class CaptureValidationError(frappe.ValidationError):
	"""Raised when AP-reviewed capture cannot enter the validation step."""


class CapturePromotionError(frappe.ValidationError):
	"""Raised when a capture cannot be promoted to a Purchase Invoice."""


class CaptureApprovalError(frappe.ValidationError):
	"""Raised when approval routing or decision recording is invalid."""


class CapturePaymentError(frappe.ValidationError):
	"""Raised when mock payment issuance is invalid."""


class APInvoiceCapture(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		action_required: DF.Check
		action_required_reason: DF.Data | None
		content_hash: DF.Data | None
		perceptual_hash: DF.Data | None
		duplicate_of: DF.Link | None
		duplicate_detected_at: DF.Datetime | None
		file_extension: DF.Data | None
		final_currency: DF.Data | None
		final_invoice_date: DF.Date | None
		final_supplier: DF.Data | None
		final_supplier_invoice_no: DF.Data | None
		final_total_amount: DF.Float
		intake_channel: DF.Literal["Manual ERPNext Upload", "Email Inbound", "Mobile Upload", "Vendor Portal Pull"]
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
		stream: DF.Literal["Receipt (R)", "Invoice (I)", "Unclassified"]
		stream_provisional_source: DF.Data | None
		stream_revised_from: DF.Data | None
		sla_due_at: DF.Datetime | None
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
			"Duplicate",
		]
		validation_message: DF.SmallText | None
		matched_supplier: DF.Link | None
		supplier_match_status: DF.Literal[
			"Not Validated", "Matched", "Unknown", "Ambiguous"
		]
		purchase_order_reference: DF.Link | None
		purchase_receipt_reference: DF.Link | None
		purchase_reference_status: DF.Literal[
			"Not Validated",
			"Non-PO / Not Applicable",
			"Purchase Order",
			"Purchase Receipt",
		]
		validation_status: DF.Literal["Not Validated", "Validated", "Blocked"]
		validation_result: DF.SmallText | None
		validated_by: DF.Link | None
		validated_at: DF.Datetime | None
		validation_source: DF.Data | None
		purchase_invoice: DF.Link | None
		promotion_status: DF.Literal["Not Promoted", "Promoted"]
		approval_status: DF.Literal[
			"Not Required",
			"Auto Approved",
			"Pending Manager",
			"Manager Approved",
			"Rejected",
		]
		approval_threshold: DF.Float
		approval_threshold_source: DF.Data | None
		routing_reason: DF.SmallText | None
		assigned_approver_role: DF.Data | None
		decision_by: DF.Link | None
		decision_at: DF.Datetime | None
		decision_notes: DF.SmallText | None
		payment_readiness: DF.Literal["Not Ready", "Ready for Payment", "Blocked"]
		payment_entry: DF.Link | None
		mock_payment_provider: DF.Data | None
		mock_payment_reference: DF.Data | None
		mock_payment_status: DF.Data | None
		mock_payment_amount: DF.Float
		mock_payment_issued_at: DF.Datetime | None
		mock_payment_response: DF.LongText | None
		payment_lifecycle_status: DF.Literal[
			"Not Requested", "Confirmed", "Closed", "Blocked"
		]
	# end: auto-generated types

	def validate(self):
		if not self.received_at:
			self.received_at = now_datetime()

		self._hydrate_from_linked_file()
		self._require_source_reference()
		self._apply_stream_tag()

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

	def after_insert(self):
		"""Kick off auto-progression once a capture lands.

		Cascade lives in `_kick_next_step` (also called from the whitelisted
		action wrappers). `after_insert` is just the entry point for the
		first hop — intake → OCR — for captures with a supported file
		attached.
		"""

		self._kick_next_step()

	def _kick_next_step(self) -> None:
		"""Enqueue the next automatable step, if any.

		Pauses (returns without enqueueing) at human-decision points:
		* Proposed → human OCR review and field correction
		* Validated → manual promote (defaults required, not yet wired)
		* Pending Manager → human approval decision

		Test integration:
		* In tests (`frappe.flags.in_test`) the cascade is OPT-IN — set
		  `frappe.flags.ap_auto_progress_enabled = True` to exercise it.
		  This keeps single-step tests deterministic without modifying them.
		* In all contexts, `frappe.flags.skip_ap_auto_progress = True`
		  short-circuits the cascade entirely.
		"""

		if frappe.flags.get("skip_ap_auto_progress"):
			return
		if frappe.flags.get("in_test") and not frappe.flags.get(
			"ap_auto_progress_enabled"
		):
			return

		decision = self._determine_next_step()
		if not decision:
			return
		method_name, reason = decision
		self._enqueue_next(method_name, reason)

	def _determine_next_step(self) -> "tuple[str, str] | None":
		"""Return ``(method_name, reason)`` for the next auto-step, or None.

		Each branch checks the precondition the corresponding pure function
		would otherwise raise on, so the cascade only enqueues steps that
		will succeed.
		"""

		# Step 0: Fresh, supported intake → pre-extraction dedupe (BEFORE OCR).
		# A duplicate must be caught before any billable extractor runs (spec 03).
		# Guarded by _dedupe_checked so the hop runs exactly once; the get_dedupe_config
		# read is last (after the cheap attribute checks short-circuit) and is skipped
		# entirely when dedupe is disabled, so the cascade falls straight through to OCR.
		if (
			self.status == STATUS_PENDING_REVIEW
			and self.is_supported_format
			and self.source_file
			and not self._dedupe_checked()
		):
			from erpnext.accounts.doctype.ap_closed_loop_settings.ap_closed_loop_settings import (
				get_dedupe_config,
			)

			if get_dedupe_config()["enabled"]:
				return ("run_dedupe_for", "auto: pre-extraction dedupe")

		# Step 1: Fresh, supported intake → run OCR
		if (
			self.status == STATUS_PENDING_REVIEW
			and self.ocr_status in (None, OCR_STATUS_NOT_EXTRACTED)
			and self.is_supported_format
			and self.source_file
		):
			return ("run_fake_extraction_for", "auto: post-intake OCR")

		# Step 2: Confirmed OCR → run validation
		if (
			self.ocr_status == OCR_STATUS_CONFIRMED
			and self.validation_status in (None, VALIDATION_STATUS_NOT_VALIDATED)
		):
			return ("validate_for_purchase_invoice_for", "auto: post-confirm validation")

		# Manual seam: validated captures wait for a clerk to click Promote
		# (defaults like company / item_code are required by the PI schema
		# and have no source on the capture record itself).

		# Step 3: Promoted with no approval yet → route approval
		if (
			self.promotion_status == PROMOTION_STATUS_PROMOTED
			and self.purchase_invoice
			and self.approval_status in (None, APPROVAL_STATUS_NOT_REQUIRED)
		):
			return ("request_approval_for", "auto: post-promotion approval routing")

		# Step 4: Approved (auto or by manager) and Ready → issue mock payment
		if (
			self.approval_status
			in (APPROVAL_STATUS_AUTO_APPROVED, APPROVAL_STATUS_MANAGER_APPROVED)
			and self.payment_readiness == PAYMENT_READINESS_READY
			and not self.payment_entry
		):
			return ("issue_mock_payment_for", "auto: post-approval payment issuance")

		return None

	def _enqueue_next(self, method_name: str, reason: str) -> None:
		"""Schedule the next auto-step via the AP Closed Loop async runner.

		Delegates queue selection, retry classification, and dead-letter
		surfacing to ``async_runner.enqueue_step`` (spec 01). ``job_id``-based
		dedup and the test-mode handling (``now`` in tests, ``enqueue_after_commit``
		in production) are preserved inside the runner; only the routing moved
		out of this controller.
		"""

		from erpnext.accounts.ap_closed_loop import async_runner

		async_runner.enqueue_step(self.name, method_name, reason=reason)

	def _hydrate_from_linked_file(self) -> None:
		"""Pull filename / url off the linked File record when available."""

		if not self.source_file:
			return

		file_row = frappe.db.get_value(
			"File",
			self.source_file,
			["file_name", "file_url", "content_hash"],
			as_dict=True,
		)
		if not file_row:
			return

		if not self.source_filename and file_row.file_name:
			self.source_filename = file_row.file_name
		if not self.source_file_url and file_row.file_url:
			self.source_file_url = file_row.file_url
		# Copy the File's exact-bytes MD5 (Frappe core computes it on save) for the
		# pre-extraction dedupe firewall (spec 03). NEVER recomputed here. May be
		# blank if the File's hash hasn't flushed yet — detect_duplicates_for
		# re-reads it from the File at dedupe time (the cascade hop runs post-commit).
		if not self.content_hash and file_row.content_hash:
			self.content_hash = file_row.content_hash

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

	def _apply_stream_tag(self) -> None:
		"""Set the provisional Receipt/Invoice stream + 72h SLA (spec 02 §5.3.2).

		Derive ``stream`` / ``stream_provisional_source`` ONLY when never
		classified (guard on an empty ``stream_provisional_source``) so spec 07's
		Step-6 revisions and manual overrides survive every re-save. ``sla_due_at``
		is recomputed from the current ``stream`` on every save, so a revision
		R<->I correctly sets/clears the 72h deadline.
		"""

		if not self.stream_provisional_source:
			stream_value, source = classify_stream_at_intake(
				self.source_filename,
				getattr(self, "_sender_domain", None),
				self.intake_channel,
				getattr(self, "_body_text", None),
			)
			self.stream = stream_value
			self.stream_provisional_source = source

		self.sla_due_at = (
			add_to_date(self.received_at, hours=72)
			if self.stream == STREAM_RECEIPT
			else None
		)

	def _dedupe_checked(self) -> bool:
		"""True once the pre-extraction dedupe hop has run for this capture.

		``duplicate_detected_at`` is the single unambiguous "already deduped" flag
		(spec 03 D5): ``detect_duplicates_for`` stamps it on every run — clean,
		suspect, or duplicate — so the Step-0 cascade guard fires exactly once and
		never loops (a clean capture legitimately has a ``content_hash`` but may
		have no ``perceptual_hash``, so neither hash alone is a reliable signal).
		"""

		return self.duplicate_detected_at is not None


def _run_cascade_step(capture: str, method_name: str):
	"""Back-compat alias → ``async_runner._dispatch_step`` (spec 01 §5.3-E / D4).

	Retained for one release so any in-flight RQ jobs enqueued under the old
	wrapper path still resolve. New enqueues go straight to ``_dispatch_step``
	via ``async_runner.enqueue_step``; the dispatcher now owns queue selection,
	retry classification, and the dead-letter surfacing (``action_required`` +
	Error Log) this function used to perform.
	"""

	from erpnext.accounts.ap_closed_loop import async_runner

	async_runner._dispatch_step(capture, method_name)


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


def classify_stream_at_intake(
	filename: str | None,
	sender_domain: str | None,
	intake_channel: str | None,
	body_text: str | None,
	rules: list[dict] | None = None,
) -> tuple[str, str]:
	"""Return ``(stream_value, provisional_source)`` — pure, side-effect free.

	``rules=None`` loads via ``AP Closed Loop Settings.get_stream_rules()``;
	inject ``rules`` in tests to avoid the DB. Iterates rules by priority; the
	first match wins; no match -> ``("Unclassified", "default")``. Never raises
	on empty inputs, and skips (logging once) any rule whose ``signal`` is
	unknown or whose ``body`` regex is malformed, so a tuning typo in the rule
	table can never block intake.
	"""

	if rules is None:
		from erpnext.accounts.doctype.ap_closed_loop_settings.ap_closed_loop_settings import (
			get_stream_rules,
		)

		rules = get_stream_rules()

	fname = (filename or "").lower()
	domain = (sender_domain or "").lower()
	channel = (intake_channel or "").lower()
	body = body_text or ""

	for rule in rules:
		signal = rule.get("signal")
		pattern = rule.get("pattern") or ""
		assign = rule.get("assign_stream")
		if not pattern or not assign:
			continue
		try:
			if signal == "filename":
				if fnmatch.fnmatch(fname, pattern.lower()):
					return assign, f"filename:{pattern}"
			elif signal == "sender_domain":
				if pattern.lower() in domain:
					return assign, "sender_domain"
			elif signal == "label":
				if pattern.lower() in channel:
					return assign, "label"
			elif signal == "body":
				if re.search(pattern, body, re.IGNORECASE):
					return assign, f"body:{pattern}"
			else:
				frappe.log_error(
					title="AP Stream Rule: unknown signal",
					message=f"Skipping stream rule with unrecognized signal {signal!r}.",
				)
		except re.error:
			frappe.log_error(
				title="AP Stream Rule: invalid pattern",
				message=f"Skipping stream rule {pattern!r} for signal {signal!r} (bad regex).",
			)

	return STREAM_UNCLASSIFIED, STREAM_DEFAULT_SOURCE


def create_capture_from_file(
	file_doc=None,
	file_name: str | None = None,
	file_url: str | None = None,
	source_context: str | None = None,
	intake_channel: str = INTAKE_MANUAL_UPLOAD,
	received_at=None,
	sender_domain: str | None = None,
	body_text: str | None = None,
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
	# Transient classifier inputs — set on the in-memory doc so validate()'s
	# stream tagger can read them; NEVER persisted (privacy; spec 02 OD-4).
	if sender_domain:
		capture._sender_domain = sender_domain
	if body_text:
		capture._body_text = body_text
	capture.insert()
	return capture


@frappe.whitelist()
def create_capture_from_uploaded_file(
	file_name: str,
	source_context: str | None = None,
	intake_channel: str = INTAKE_MANUAL_UPLOAD,
):
	"""Whitelisted entrypoint for the manual ERPNext upload (and mobile) flow.

	``file_name`` is the ``name`` of an existing Frappe ``File`` record (the one
	created when the user uploads through the ERPNext UI / mobile app). The
	mobile client passes ``intake_channel="Mobile Upload"`` (spec 02 §5.3.4).
	"""

	return create_capture_from_file(
		file_doc=file_name,
		source_context=source_context,
		intake_channel=intake_channel,
	).name


# ---------------------------------------------------------------------------
# Email-in intake adapter (spec 02 §5.3.3)
# ---------------------------------------------------------------------------


def _email_domain(sender: str | None) -> str | None:
	"""Extract the lowercased domain from an email sender address."""

	if not sender or "@" not in sender:
		return None
	domain = sender.rsplit("@", 1)[-1].strip().strip(">").lower()
	return domain or None


def _email_body_snippet(content: str | None, limit: int = 2000) -> str | None:
	"""A bounded, HTML-stripped snippet of the email body for classification.

	Used transiently by the stream classifier and NEVER persisted (privacy;
	spec 02 OD-4)."""

	if not content:
		return None
	text = re.sub(r"<[^>]+>", " ", content)
	text = re.sub(r"\s+", " ", text).strip()
	return text[:limit] or None


@frappe.whitelist()
def create_capture_from_email(communication: str) -> list:
	"""Create one AP Invoice Capture per supported attachment of a Communication.

	Iterates the inbound email's attached Files, skipping unsupported
	attachments (signatures/logos/.txt — spec 02 OD-7). Stream is classified from
	the sender domain + filename (+ a bounded body snippet, never persisted).
	Idempotent on a re-fired hook via a per-``source_file`` existence guard
	(OD-5). Returns the list of created capture names (possibly empty).
	"""

	comm = frappe.get_doc("Communication", communication)
	sender_domain = _email_domain(comm.sender)
	body_snippet = _email_body_snippet(comm.content)
	context = f"Email: {comm.subject}" if comm.subject else None

	files = frappe.get_all(
		"File",
		filters={
			"attached_to_doctype": "Communication",
			"attached_to_name": comm.name,
		},
		fields=["name", "file_name", "file_url"],
	)

	created = []
	for file_row in files:
		extension = _normalize_extension(file_row.file_name or file_row.file_url or "")
		if extension not in SUPPORTED_EXTENSIONS:
			continue
		# Don't double-create from a re-fired hook / re-delivery (OD-5). The real
		# content-level dedupe firewall is spec 03.
		if frappe.db.exists("AP Invoice Capture", {"source_file": file_row.name}):
			continue
		capture = create_capture_from_file(
			file_doc=file_row.name,
			source_context=context,
			intake_channel=INTAKE_EMAIL_INBOUND,
			received_at=comm.communication_date,  # the true receipt time, not now()
			sender_domain=sender_domain,
			body_text=body_snippet,
		)
		created.append(capture.name)
	return created


def handle_inbound_ap_communication(doc, method=None) -> None:
	"""``Communication.after_insert`` hook target (spec 02 §5.3.3).

	No-op unless this is an inbound email on the configured AP intake Email
	Account (``AP Closed Loop Settings.ap_intake_email_account``). OFF by default:
	if that setting is empty, this does nothing. Never raises — an inbound-mail
	hook must not break mail sync.
	"""

	try:
		if getattr(doc, "communication_type", None) != "Communication":
			return
		if getattr(doc, "sent_or_received", None) != "Received":
			return
		configured = frappe.db.get_single_value(
			"AP Closed Loop Settings", "ap_intake_email_account"
		)
		if not configured or getattr(doc, "email_account", None) != configured:
			return
		create_capture_from_email(doc.name)
	except Exception:
		frappe.log_error(
			title="AP intake: inbound Communication handler failed",
			message=frappe.get_traceback(),
		)


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


def _source_file_size_bytes(capture: "APInvoiceCapture") -> int | None:
	"""Best-effort size (bytes) of the capture's source File, or None if unknown.

	Uses the File DocType's stored ``file_size`` so we don't have to read the
	whole file just to size it. Returns None when the file can't be resolved —
	the guard then defers to the provider's own limits rather than blocking.
	"""
	name = None
	if capture.source_file:
		name = capture.source_file
	elif capture.source_file_url:
		name = frappe.db.get_value("File", {"file_url": capture.source_file_url}, "name")
	if not name:
		return None
	size = frappe.db.get_value("File", name, "file_size")
	try:
		return int(size) if size is not None else None
	except (TypeError, ValueError):
		return None


def run_extraction(
	capture: "APInvoiceCapture | str",
	*,
	simulate_missing: list[str] | tuple[str, ...] | None = None,
	simulate_ambiguous: list[str] | tuple[str, ...] | None = None,
	save: bool = True,
) -> "APInvoiceCapture":
	"""Run OCR against a capture and persist the proposal.

	Provider-agnostic entry point: the proposal is produced by the configured
	``OCRProvider`` (Phase 1 ships only the deterministic ``fake`` provider;
	later phases select a real provider via ``AP Closed Loop Settings``). The
	proposal lives only in ``proposed_*`` fields plus ``ocr_*`` metadata — it
	is non-authoritative. ``final_*`` fields are intentionally left untouched
	so downstream consumers cannot mistake an unconfirmed proposal for an
	AP-reviewed value.

	``simulate_missing`` / ``simulate_ambiguous`` override / extend any
	filename-based simulation markers and are intended for explicit test
	cases (honoured by the fake provider). They accept the logical field names
	declared in ``MANDATORY_HEADER_FIELDS``.
	"""

	# Late import keeps the module load cycle-free (registry -> fake -> base,
	# none of which import this module at load time).
	from erpnext.accounts.ap_closed_loop.extractors.registry import get_extractor
	from erpnext.accounts.doctype.ap_closed_loop_settings.ap_closed_loop_settings import (
		get_ocr_config,
	)

	if isinstance(capture, str):
		capture = frappe.get_doc("AP Invoice Capture", capture)

	if not capture.is_supported_format:
		raise OCRExtractionError(
			_("Cannot run extraction on an unsupported source format.")
		)

	# Phase 3: provider, model, and confidence threshold come from
	# AP Closed Loop Settings, defaulting to the deterministic fake provider
	# when unconfigured (so a fresh site makes no real API calls).
	ocr_config = get_ocr_config()
	provider = ocr_config["provider"]
	# Phase 5: real-provider calls are audited via Integration Request. The fake
	# provider makes no API call and has no cost, so it is not logged.
	audit = provider != "fake"

	# Phase 6: enforce the configured file-size ceiling BEFORE sending anything
	# to the provider, so an oversized scan fails fast (no API call, no cost) and
	# is surfaced for a human instead of being silently rejected by the API. The
	# fake provider reads nothing, so the guard applies only to real providers.
	if audit:
		max_mb = ocr_config.get("max_file_mb")
		size_bytes = _source_file_size_bytes(capture)
		if max_mb and size_bytes is not None and size_bytes > max_mb * 1024 * 1024:
			reason = _(
				"Source file is {0:.1f} MB, over the {1} MB OCR limit. "
				"Reduce/split the file or enter the invoice manually."
			).format(size_bytes / (1024 * 1024), max_mb)
			capture.action_required = 1
			capture.action_required_reason = reason
			from erpnext.accounts.ap_closed_loop.extractors.audit import (
				write_integration_request,
			)

			write_integration_request(capture, status="Failed", error=reason)
			if save:
				capture.save()
			raise OCRExtractionError(reason)

	try:
		result = get_extractor(
			provider,
			model=ocr_config["model"],
			confidence_threshold=ocr_config["confidence_threshold"],
			fallback_model=ocr_config.get("fallback_model"),
		).extract(
			capture,
			simulate_missing=simulate_missing,
			simulate_ambiguous=simulate_ambiguous,
		)
	except Exception as exc:
		if audit:
			from erpnext.accounts.ap_closed_loop.extractors.audit import (
				write_integration_request,
			)

			write_integration_request(capture, status="Failed", error=str(exc))
		# Phase 6: never fail silently. Surface the failure on the capture itself
		# (action_required + human reason) so a clerk sees it and can act, rather
		# than the capture stalling with no visible cause. We mutate the object
		# in place (callers holding the reference see it) and persist when saving,
		# then re-raise so the cascade/job records the error too.
		capture.action_required = 1
		capture.action_required_reason = _(
			"OCR extraction failed ({0}). Retry later or enter the invoice manually."
		).format(type(exc).__name__)
		if save:
			try:
				capture.save()
			except Exception:
				frappe.log_error(
					title="AP capture: failed to persist OCR failure state",
					message=frappe.get_traceback(),
				)
		raise

	if audit:
		from erpnext.accounts.ap_closed_loop.extractors.audit import (
			write_integration_request,
		)

		write_integration_request(capture, result=result, status="Completed")

	proposal = result.proposal
	missing_fields = result.missing_fields
	ambiguous_fields = result.ambiguous_fields

	now = now_datetime()
	capture.ocr_provider = result.provider_name
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
	# Carry the provider's own metadata (model used, outcome, token usage) into
	# the persisted record so the audit trail reflects what actually happened
	# — e.g. whether a low-confidence fallback fired and which model produced
	# the final result. Fake provider has none of these (empty raw_response).
	provider_raw = result.raw_response or {}
	capture.ocr_raw_response = json.dumps(
		{
			"provider": result.provider_name,
			"extracted_at": now.isoformat() if hasattr(now, "isoformat") else str(now),
			"proposal": proposal,
			"missing_fields": sorted(missing_fields),
			"ambiguous_fields": sorted(ambiguous_fields),
			"model": provider_raw.get("model"),
			"outcome": provider_raw.get("outcome"),
			"usage": provider_raw.get("usage"),
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


# Backward-compatible alias. The pilot's test suite and the cascade call this
# by name; ``run_extraction`` is the forward-looking provider-agnostic name.
run_fake_extraction = run_extraction


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
	# OCR completes at status=Proposed; the cascade pauses there for human
	# review. _kick_next_step is a no-op at that state, but we call it
	# uniformly so failure paths (e.g. extraction left the capture in an
	# unexpected state) get a chance to advance.
	doc._kick_next_step()
	return doc.name


# ---------------------------------------------------------------------------
# Pre-extraction deduplication (spec 03 §5.2/5.3)
# ---------------------------------------------------------------------------


def detect_duplicates_for(
	capture: "APInvoiceCapture | str",
	save: bool = True,
) -> dict:
	"""Run exact + perceptual dedupe against the last ``dedupe_window_days``.

	The firewall against double-booking: an exact MD5 ``content_hash`` re-upload
	terminates the capture (``status = Duplicate``, cascade stops, no OCR cost); a
	near-duplicate (pHash within ``dedupe_phash_max_distance``) is flagged
	``action_required`` for a human but left at ``Pending Review`` so it still gets
	extracted (spec 03 D1=(b)). Stream-agnostic — keys only on bytes/pixels +
	``received_at``, never on a ``stream`` field.

	Resolves ``capture`` (str -> get_doc). Never raises out for a benign
	"no duplicate" / "poppler missing" case. Returns::

	    {"status": "skipped"|"clean"|"duplicate"|"suspected",
	     "kind": "exact"|"perceptual"|None,
	     "original": <capture name>|None}
	"""

	if isinstance(capture, str):
		capture = frappe.get_doc("AP Invoice Capture", capture)

	from erpnext.accounts.doctype.ap_closed_loop_settings.ap_closed_loop_settings import (
		get_dedupe_config,
	)

	cfg = get_dedupe_config()
	if not cfg["enabled"]:
		# Kill switch: no mutation (AC-03-9). Step 0 also short-circuits on this
		# flag, so a disabled site never enqueues run_dedupe_for in the first place.
		return {"status": "skipped", "kind": None, "original": None}

	cutoff = add_to_date(now_datetime(), days=-cfg["window_days"])

	# Stamp the "deduped" marker on every (non-skipped) run so the Step-0 cascade
	# guard (_dedupe_checked) trips exactly once, clean or not (spec 03 D5).
	capture.duplicate_detected_at = now_datetime()

	# ---- EXACT pass: MD5 content_hash (copied from the File) ----
	content_hash = capture.content_hash or (
		frappe.db.get_value("File", capture.source_file, "content_hash")
		if capture.source_file
		else None
	)
	if content_hash:
		capture.content_hash = content_hash
		hits = frappe.db.get_all(
			"AP Invoice Capture",
			filters={
				"content_hash": content_hash,
				"received_at": [">=", cutoff],
				"name": ["!=", capture.name],
				"status": ["!=", STATUS_DUPLICATE],
			},
			fields=["name"],
			order_by="received_at asc",
			limit=1,
		)
		if hits:
			# Oldest matching capture is the original to keep (asc + limit 1).
			original = hits[0].name
			capture.status = STATUS_DUPLICATE
			capture.duplicate_of = original
			capture.action_required = 1
			capture.action_required_reason = _("Exact duplicate of {0}").format(original)
			if save:
				capture.save()
			return {"status": "duplicate", "kind": "exact", "original": original}

	# ---- PERCEPTUAL pass: pHash of the rasterized first page ----
	# Guard the compute call itself so a _compute_phash that escapes its own
	# try/except (or a monkeypatched raiser, AC-03-8) degrades to exact-only
	# rather than blocking intake.
	try:
		capture.perceptual_hash = _compute_phash(capture)
	except Exception:
		capture.perceptual_hash = None
		frappe.log_error(
			title="AP dedupe: perceptual pass error",
			message=frappe.get_traceback(),
		)

	if capture.perceptual_hash:
		candidates = frappe.db.get_all(
			"AP Invoice Capture",
			filters={
				"received_at": [">=", cutoff],
				"name": ["!=", capture.name],
				"status": ["!=", STATUS_DUPLICATE],
				"perceptual_hash": ["is", "set"],
			},
			fields=["name", "perceptual_hash"],
			order_by="received_at asc",
		)
		best_name = None
		best_distance = None
		max_distance = cfg["phash_max_distance"]
		for cand in candidates:
			distance = _phash_distance(capture.perceptual_hash, cand.perceptual_hash)
			if distance is None:
				continue
			if distance <= max_distance and (best_distance is None or distance < best_distance):
				best_name = cand.name
				best_distance = distance
		if best_name is not None:
			# SUSPECT only — never set STATUS_DUPLICATE / duplicate_of automatically;
			# a human (and the follow-on body-text fingerprint, D2) confirms. The
			# capture stays Pending Review so the cascade still runs OCR (D1=(b)).
			capture.action_required = 1
			capture.action_required_reason = _(
				"Suspected near-duplicate of {0} (visual match)"
			).format(best_name)
			if save:
				capture.save()
			return {"status": "suspected", "kind": "perceptual", "original": best_name}

	# ---- CLEAN ----
	if save:
		capture.save()
	return {"status": "clean", "kind": None, "original": None}


def _phash_distance(a: "str | None", b: "str | None") -> "int | None":
	"""Hamming distance between two equal-length pHash hex strings, or None.

	Computed on the hex representation directly (XOR + popcount) so the
	fuzzy-distance logic never depends on ``imagehash`` being installed — this
	matches ``imagehash.hex_to_hash(a) - imagehash.hex_to_hash(b)`` for the
	16-hex-char (64-bit) hashes ``_compute_phash`` produces.
	"""

	if not a or not b:
		return None
	try:
		return bin(int(a, 16) ^ int(b, 16)).count("1")
	except (TypeError, ValueError):
		return None


def _compute_phash(capture: "APInvoiceCapture") -> "str | None":
	"""pHash hex of the rasterized first page, or None on ANY failure.

	None when poppler/imagehash is absent, the file is unreadable, or the type is
	unsupported. NEVER raises — a failed pHash degrades dedupe to exact-only, it
	does not block intake. First-page-only at 150 DPI (spec 03 D7).
	"""

	# Late import: keeps module load cycle-free and lets the app load on a host
	# without these deps (same discipline as run_extraction's late imports).
	try:
		import imagehash
		from PIL import Image
	except ImportError:
		return None

	try:
		path = None
		if capture.source_file:
			try:
				path = frappe.get_doc("File", capture.source_file).get_full_path()
			except Exception:
				path = None
		if not path or not os.path.exists(path):
			return None

		extension = (capture.file_extension or "").lower()
		if extension == "pdf":
			try:
				from pdf2image import convert_from_path
			except ImportError:
				return None
			pages = convert_from_path(path, first_page=1, last_page=1, dpi=150)
			if not pages:
				return None
			image = pages[0]
		elif extension in ("png", "jpg", "jpeg"):
			image = Image.open(path)
		else:
			return None

		return str(imagehash.phash(image))
	except Exception:
		# poppler binary absent (PDFInfoNotInstalledError), unreadable bytes, etc.
		frappe.log_error(
			title="AP dedupe: perceptual hash failed",
			message=frappe.get_traceback(),
		)
		return None


@frappe.whitelist()
def run_dedupe_for(capture: str) -> str:
	"""Whitelisted cascade wrapper: run pre-extraction dedupe, then advance.

	Same shape as ``run_fake_extraction_for``. On an exact hit the capture lands
	in ``STATUS_DUPLICATE`` and the next ``_kick_next_step`` is a no-op (the
	Step-1 status guard stops the cascade — terminal); on a clean/suspect result
	the cascade falls through to OCR. Routing dedupe through the cascade rail
	gives it the dead-letter error surface for free.
	"""

	detect_duplicates_for(capture)
	doc = frappe.get_doc("AP Invoice Capture", capture)
	doc._kick_next_step()
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
	doc._kick_next_step()
	return doc.name


# ---------------------------------------------------------------------------
# Validation against existing ERPNext records + Purchase Invoice promotion
# ---------------------------------------------------------------------------


def _match_supplier(supplier_name: str | None) -> tuple[str | None, str]:
	"""Match an AP-reviewed supplier name against existing Supplier records.

	Returns ``(matched_name, status)``. Suppliers are never auto-created;
	an unknown name yields ``(None, Unknown)`` so AP correction is required.
	"""

	if not supplier_name:
		return None, SUPPLIER_MATCH_UNKNOWN

	candidate = supplier_name.strip()
	if not candidate:
		return None, SUPPLIER_MATCH_UNKNOWN

	if frappe.db.exists("Supplier", candidate):
		return candidate, SUPPLIER_MATCH_MATCHED

	by_supplier_name = frappe.get_all(
		"Supplier",
		filters={"supplier_name": candidate},
		pluck="name",
	)
	if len(by_supplier_name) == 1:
		return by_supplier_name[0], SUPPLIER_MATCH_MATCHED
	if len(by_supplier_name) > 1:
		return None, SUPPLIER_MATCH_AMBIGUOUS

	return None, SUPPLIER_MATCH_UNKNOWN


def _classify_purchase_reference(po_ref: str | None, pr_ref: str | None) -> str:
	"""Explicit classification of purchase reference handling for AC-V3.

	A Purchase Receipt reference dominates a Purchase Order reference because
	a PR already implies an upstream PO in ERPNext; both being absent is
	explicitly recorded as Non-PO so it cannot be silently inferred.
	"""

	if pr_ref:
		return PURCHASE_REF_PURCHASE_RECEIPT
	if po_ref:
		return PURCHASE_REF_PURCHASE_ORDER
	return PURCHASE_REF_NON_PO


def validate_for_purchase_invoice(
	capture: "APInvoiceCapture | str",
	actor: str | None = None,
	source: str | None = None,
	save: bool = True,
) -> "APInvoiceCapture":
	"""Validate an AP-reviewed capture against existing ERPNext records.

	Behavior:
	* Requires AP-reviewed/final fields confirmed (status == Confirmed).
	* Matches ``final_supplier`` to an existing Supplier by ``name`` or
	  ``supplier_name``. Unknown suppliers are flagged, never auto-created.
	* Classifies purchase reference handling explicitly (PO / PR / Non-PO).
	* Records auditable outcome: ``validation_status``, ``validation_result``,
	  ``validated_by``, ``validated_at``, ``validation_source``.
	* Does NOT create a Purchase Invoice; that is a separate promotion call.
	"""

	if isinstance(capture, str):
		capture = frappe.get_doc("AP Invoice Capture", capture)

	if capture.status != STATUS_CONFIRMED:
		raise CaptureValidationError(
			_(
				"AP Invoice Capture must be AP-reviewed (status Confirmed) before validation; "
				"current status is {0}."
			).format(capture.status)
		)

	final_supplier_value = (capture.final_supplier or "").strip() or None
	matched_supplier, match_status = _match_supplier(final_supplier_value)
	capture.matched_supplier = matched_supplier
	capture.supplier_match_status = match_status

	purchase_ref_status = _classify_purchase_reference(
		capture.purchase_order_reference, capture.purchase_receipt_reference
	)
	capture.purchase_reference_status = purchase_ref_status

	issues: list[str] = []

	for logical_name, _proposed_field, final_field in MANDATORY_HEADER_FIELDS:
		value = capture.get(final_field)
		if value in (None, "", 0, 0.0):
			issues.append(_("Missing reviewed {0}").format(logical_name))

	if match_status == SUPPLIER_MATCH_UNKNOWN:
		issues.append(
			_("Supplier '{0}' is unknown — AP correction required (no auto-create).").format(
				final_supplier_value or ""
			)
		)
	elif match_status == SUPPLIER_MATCH_AMBIGUOUS:
		issues.append(
			_("Supplier '{0}' is ambiguous — multiple existing Suppliers share this name.").format(
				final_supplier_value or ""
			)
		)

	capture.validated_by = actor or frappe.session.user
	capture.validated_at = now_datetime()
	capture.validation_source = source or VALIDATION_SOURCE_DEFAULT

	if issues:
		capture.validation_status = VALIDATION_STATUS_BLOCKED
		capture.validation_result = "; ".join(issues)
		capture.action_required = 1
		capture.action_required_reason = _("Validation blocked: {0}").format(
			capture.validation_result
		)
	else:
		capture.validation_status = VALIDATION_STATUS_VALIDATED
		capture.validation_result = _(
			"Supplier matched: {0}. Purchase reference: {1}."
		).format(matched_supplier, purchase_ref_status)
		# Confirmed -> Validated does NOT clear action_required by itself;
		# the next required action is promotion to Purchase Invoice.
		capture.action_required = 1
		capture.action_required_reason = _("Ready for promotion to Purchase Invoice")

	if save:
		capture.save()
	return capture


_PROMOTE_DEFAULT_KEYS = (
	"company",
	"item_code",
	"qty",
	"uom",
	"warehouse",
	"expense_account",
	"cost_center",
)


def _coalesce_defaults(defaults: dict | None) -> dict:
	"""Resolve promote-time defaults for ``promote_to_purchase_invoice``.

	Precedence (highest wins):
	1. Caller-supplied ``defaults`` dict (tests, UI dialog overrides).
	2. Site-wide values from the ``AP Closed Loop Settings`` Single doctype.

	Tests pass explicit ``_PROMOTION_DEFAULTS`` and continue to work unchanged.
	Production flows can leave ``defaults=None`` and rely entirely on the
	settings doctype, which is what the form-based Promote button does.
	"""

	merged: dict = {}

	try:
		from erpnext.accounts.doctype.ap_closed_loop_settings.ap_closed_loop_settings import (
			get_promote_defaults,
		)
		merged.update(get_promote_defaults())
	except Exception:
		# Settings doctype may not be installed yet (early test runs against
		# stale sites). Falling back to caller-supplied defaults is fine.
		pass

	if defaults:
		for k, v in defaults.items():
			if v is not None:
				merged[k] = v

	return {k: v for k, v in merged.items() if k in _PROMOTE_DEFAULT_KEYS}


def promote_to_purchase_invoice(
	capture: "APInvoiceCapture | str",
	actor: str | None = None,
	defaults: dict | None = None,
	save: bool = True,
) -> "Document":
	"""Promote a validated capture into the native Purchase Invoice lifecycle.

	Preconditions:
	* ``validation_status`` must be ``Validated``.
	* ``matched_supplier`` must be set (unknown suppliers cannot promote).
	* Capture must not already be promoted.

	A draft Purchase Invoice is created with a single header-level item row
	(deterministic default item / cost center / warehouse). Any explicit
	purchase reference remains on the capture for Phase 1 auditability;
	line-level PO/PR matching is out of scope for this slice.
	"""

	if isinstance(capture, str):
		capture = frappe.get_doc("AP Invoice Capture", capture)

	if capture.validation_status != VALIDATION_STATUS_VALIDATED:
		raise CapturePromotionError(
			_(
				"Capture must be successfully validated before promotion; "
				"current validation_status is {0}."
			).format(capture.validation_status or VALIDATION_STATUS_NOT_VALIDATED)
		)
	if not capture.matched_supplier:
		raise CapturePromotionError(
			_("Capture cannot be promoted without a matched Supplier.")
		)
	if capture.promotion_status == PROMOTION_STATUS_PROMOTED and capture.purchase_invoice:
		raise CapturePromotionError(
			_("Capture has already been promoted to Purchase Invoice {0}.").format(
				capture.purchase_invoice
			)
		)

	d = _coalesce_defaults(defaults)

	pi = frappe.new_doc("Purchase Invoice")
	pi.supplier = capture.matched_supplier
	pi.bill_no = capture.final_supplier_invoice_no
	pi.bill_date = capture.final_invoice_date.isoformat() if capture.final_invoice_date else None
	pi.posting_date = capture.final_invoice_date.isoformat() if capture.final_invoice_date else today()
	if capture.final_currency:
		pi.currency = capture.final_currency
	pi.conversion_rate = 1.0
	if d.get("company"):
		pi.company = d["company"]

	rate = float(capture.final_total_amount or 0.0)
	qty = float(d.get("qty", 1) or 1)
	item_row: dict = {
		"item_code": d.get("item_code", "_Test Item"),
		"qty": qty,
		"rate": rate,
	}
	if d.get("uom"):
		item_row["uom"] = d["uom"]
		item_row["stock_uom"] = d["uom"]
	if d.get("warehouse"):
		item_row["warehouse"] = d["warehouse"]
	if d.get("expense_account"):
		item_row["expense_account"] = d["expense_account"]
	if d.get("cost_center"):
		item_row["cost_center"] = d["cost_center"]
	# Phase 1 deliberately does NOT attach the capture's PO/PR reference onto
	# the Purchase Invoice item row — line-level PO/PR matching is out of scope
	# for this slice. The references remain auditable on the capture itself.
	pi.append("items", item_row)

	pi.insert(ignore_permissions=True)

	capture.purchase_invoice = pi.name
	capture.promotion_status = PROMOTION_STATUS_PROMOTED
	# Promotion clears action-required: the capture has now handed off to
	# the native Purchase Invoice lifecycle. Approval/payment is out of scope.
	capture.action_required = 0
	capture.action_required_reason = None
	if actor:
		capture.validated_by = actor

	if save:
		capture.save()
	return pi


# ---------------------------------------------------------------------------
# Approval routing / manager decision
# ---------------------------------------------------------------------------


def _resolve_approval_threshold(threshold: float | None, source: str | None) -> tuple[float, str]:
	if threshold is None:
		# Settings-driven (spec 01): get_auto_post_threshold() returns the
		# AP Closed Loop Settings value, falling back to AUTO_APPROVAL_THRESHOLD_DEFAULT
		# (1000.0) when blank so empty-settings sites are byte-for-byte unchanged.
		from erpnext.accounts.doctype.ap_closed_loop_settings.ap_closed_loop_settings import (
			get_auto_post_threshold,
		)

		return get_auto_post_threshold(), source or APPROVAL_SOURCE_DEFAULT
	return float(threshold), source or "explicit-override"


def request_approval(
	capture: "APInvoiceCapture | str",
	threshold: float | None = None,
	source: str | None = None,
	actor: str | None = None,
	approver_role: str | None = None,
	save: bool = True,
) -> "APInvoiceCapture":
	"""Route a promoted capture through Phase 1 approval controls.

	Auto-approval is allowed when the AP-reviewed total is at or below the
	threshold. Larger captures route to manager approval with a visible reason.
	No payment artifact is created here.
	"""

	if isinstance(capture, str):
		capture = frappe.get_doc("AP Invoice Capture", capture)

	if capture.validation_status != VALIDATION_STATUS_VALIDATED:
		raise CaptureApprovalError(
			_(
				"Capture must be Validated before approval routing; "
				"current validation_status is {0}."
			).format(capture.validation_status or VALIDATION_STATUS_NOT_VALIDATED)
		)
	if capture.promotion_status != PROMOTION_STATUS_PROMOTED or not capture.purchase_invoice:
		raise CaptureApprovalError(
			_("Capture must be promoted to a Purchase Invoice before approval routing.")
		)
	if capture.approval_status and capture.approval_status != APPROVAL_STATUS_NOT_REQUIRED:
		raise CaptureApprovalError(
			_("Approval routing already recorded for this capture (current status: {0}).").format(
				capture.approval_status
			)
		)

	resolved_threshold, resolved_source = _resolve_approval_threshold(threshold, source)
	amount = float(capture.final_total_amount or 0.0)

	capture.approval_threshold = resolved_threshold
	capture.approval_threshold_source = resolved_source

	if amount <= resolved_threshold:
		capture.approval_status = APPROVAL_STATUS_AUTO_APPROVED
		capture.routing_reason = _(
			"Auto-approved: final_total_amount {0:.2f} <= threshold {1:.2f}"
		).format(amount, resolved_threshold)
		capture.assigned_approver_role = None
		capture.decision_by = actor or frappe.session.user
		capture.decision_at = now_datetime()
		capture.decision_notes = None
		capture.payment_readiness = PAYMENT_READINESS_READY
		capture.action_required = 0
		capture.action_required_reason = None
	else:
		capture.approval_status = APPROVAL_STATUS_PENDING_MANAGER
		capture.routing_reason = _(
			"Manager approval required: final_total_amount {0:.2f} > threshold {1:.2f}"
		).format(amount, resolved_threshold)
		capture.assigned_approver_role = approver_role or MANAGER_APPROVAL_ROLE_DEFAULT
		capture.decision_by = None
		capture.decision_at = None
		capture.decision_notes = None
		capture.payment_readiness = PAYMENT_READINESS_NOT_READY
		capture.action_required = 1
		capture.action_required_reason = _("Manager approval required")

	if save:
		capture.save()
	return capture


def record_manager_decision(
	capture: "APInvoiceCapture | str",
	approve: bool,
	actor: str | None = None,
	notes: str | None = None,
	save: bool = True,
) -> "APInvoiceCapture":
	"""Record manager approval or rejection for a routed capture."""

	if isinstance(capture, str):
		capture = frappe.get_doc("AP Invoice Capture", capture)

	# The DocType grants write to both Accounts User and Accounts Manager,
	# so without this gate any AP clerk could approve their own over-threshold
	# capture. Enforce the role that was recorded when approval was routed.
	frappe.only_for(capture.assigned_approver_role or MANAGER_APPROVAL_ROLE_DEFAULT)

	if capture.approval_status != APPROVAL_STATUS_PENDING_MANAGER:
		raise CaptureApprovalError(
			_("Manager decision requires approval_status Pending Manager; current is {0}.").format(
				capture.approval_status or APPROVAL_STATUS_NOT_REQUIRED
			)
		)

	capture.decision_by = actor or frappe.session.user
	capture.decision_at = now_datetime()
	capture.decision_notes = notes

	if approve:
		capture.approval_status = APPROVAL_STATUS_MANAGER_APPROVED
		capture.payment_readiness = PAYMENT_READINESS_READY
		capture.action_required = 0
		capture.action_required_reason = None
	else:
		capture.approval_status = APPROVAL_STATUS_REJECTED
		capture.payment_readiness = PAYMENT_READINESS_BLOCKED
		capture.action_required = 1
		capture.action_required_reason = _("Approval rejected — capture blocked from payment")

	if save:
		capture.save()
	return capture


def is_ready_for_payment(capture: "APInvoiceCapture | str") -> bool:
	"""Predicate used by downstream mock-payment issuance code."""

	if isinstance(capture, str):
		capture = frappe.get_doc("AP Invoice Capture", capture)

	return (
		capture.approval_status
		in (APPROVAL_STATUS_AUTO_APPROVED, APPROVAL_STATUS_MANAGER_APPROVED)
		and capture.payment_readiness == PAYMENT_READINESS_READY
	)


def is_payment_blocked(capture: "APInvoiceCapture | str") -> bool:
	if isinstance(capture, str):
		capture = frappe.get_doc("AP Invoice Capture", capture)

	return (
		capture.approval_status == APPROVAL_STATUS_REJECTED
		or capture.payment_readiness == PAYMENT_READINESS_BLOCKED
	)


# ---------------------------------------------------------------------------
# Mock payment issuance / Payment Entry writeback
# ---------------------------------------------------------------------------


def _bank_transaction_count_for_payment_entry(payment_entry: str | None) -> int:
	if not payment_entry or not frappe.db.exists("DocType", "Bank Transaction"):
		return 0
	return frappe.db.count(
		"Bank Transaction Payments",
		filters={"payment_document": "Payment Entry", "payment_entry": payment_entry},
	)


def _derive_payment_lifecycle_status(capture: "APInvoiceCapture") -> str:
	if is_payment_blocked(capture):
		return PAYMENT_LIFECYCLE_BLOCKED
	if not capture.payment_entry:
		return PAYMENT_LIFECYCLE_NOT_REQUESTED

	pi_state = frappe.db.get_value(
		"Purchase Invoice",
		capture.purchase_invoice,
		["docstatus", "status", "outstanding_amount"],
		as_dict=True,
	)
	pe_docstatus = frappe.db.get_value("Payment Entry", capture.payment_entry, "docstatus")
	if (
		pi_state
		and int(pi_state.docstatus) == 1
		and int(pe_docstatus or 0) == 1
		and flt(pi_state.outstanding_amount) == 0
		and pi_state.status == "Paid"
	):
		return PAYMENT_LIFECYCLE_CLOSED
	return PAYMENT_LIFECYCLE_CONFIRMED


def issue_mock_payment(
	capture: "APInvoiceCapture | str",
	actor: str | None = None,
	paid_from: str | None = None,
	save: bool = True,
) -> "Document":
	"""Issue a deterministic mock Payment Entry for an approved capture."""

	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	if isinstance(capture, str):
		capture = frappe.get_doc("AP Invoice Capture", capture)

	# Payment issuance is a manager-level action — the approval gate above is
	# state-only and would otherwise let any AP clerk trigger a Payment Entry.
	frappe.only_for(MANAGER_APPROVAL_ROLE_DEFAULT)

	if not is_ready_for_payment(capture):
		raise CapturePaymentError(
			_("Capture is not approved and ready for mock payment issuance.")
		)
	if not capture.purchase_invoice:
		raise CapturePaymentError(_("Capture has no Purchase Invoice to pay."))
	if capture.payment_entry:
		raise CapturePaymentError(
			_("Capture already has mock Payment Entry {0}.").format(capture.payment_entry)
		)

	pi = frappe.get_doc("Purchase Invoice", capture.purchase_invoice)
	if pi.docstatus == 0:
		pi.submit()
	elif pi.docstatus != 1:
		raise CapturePaymentError(
			_("Purchase Invoice {0} must be draft or submitted before mock payment.").format(
				pi.name
			)
		)

	mock_account = paid_from or MOCK_CLEARING_ACCOUNT_DEFAULT
	pe = get_payment_entry("Purchase Invoice", pi.name, bank_account=mock_account)
	pe.paid_from = mock_account
	pe.reference_no = f"{MOCK_PAYMENT_PREFIX}-{capture.name}"
	pe.reference_date = today()
	pe.custom_remarks = 1
	pe.remarks = MOCK_PAYMENT_REMARK
	# The Accounts Manager role check above is the authorization boundary for
	# payment issuance; Payment Entry's own create-permission is bypassed so
	# AP-flow approvals don't require separate PE create rights per user.
	pe.insert(ignore_permissions=True)
	pe.submit()

	issued_at = now_datetime()
	response = {
		"provider": MOCK_PAYMENT_PROVIDER,
		"reference": pe.reference_no,
		"status": "confirmed-mock",
		"amount": flt(pe.paid_amount),
		"issued_at": issued_at.isoformat() if hasattr(issued_at, "isoformat") else str(issued_at),
		"is_mock": True,
		"payment_entry": pe.name,
		"purchase_invoice": pi.name,
		"bank_transaction_count": _bank_transaction_count_for_payment_entry(pe.name),
		"issued_by": actor or frappe.session.user,
	}

	capture.payment_entry = pe.name
	capture.mock_payment_provider = MOCK_PAYMENT_PROVIDER
	capture.mock_payment_reference = pe.reference_no
	capture.mock_payment_status = response["status"]
	capture.mock_payment_amount = response["amount"]
	capture.mock_payment_issued_at = issued_at
	capture.mock_payment_response = json.dumps(response, sort_keys=True, default=str)
	capture.payment_lifecycle_status = _derive_payment_lifecycle_status(capture)
	capture.action_required = 0
	capture.action_required_reason = None

	if save:
		capture.save()
	return pe


# ---------------------------------------------------------------------------
# Closure evidence / lifecycle visibility
# ---------------------------------------------------------------------------


def _gl_entries_for_vouchers(voucher_names: list[str]) -> list[dict]:
	if not voucher_names:
		return []
	return frappe.db.get_all(
		"GL Entry",
		filters={"voucher_no": ["in", voucher_names], "is_cancelled": 0},
		fields=["voucher_type", "voucher_no", "account", "debit", "credit"],
		order_by="voucher_no, account",
	)


def build_closure_evidence(capture: "APInvoiceCapture | str") -> dict:
	"""Build audit evidence for a capture from ERPNext-native state."""

	if isinstance(capture, str):
		capture = frappe.get_doc("AP Invoice Capture", capture)

	pi_state = None
	pe_state = None
	if capture.purchase_invoice:
		pi_state = frappe.db.get_value(
			"Purchase Invoice",
			capture.purchase_invoice,
			["name", "docstatus", "status", "grand_total", "outstanding_amount"],
			as_dict=True,
		)
	if capture.payment_entry:
		pe_state = frappe.db.get_value(
			"Payment Entry",
			capture.payment_entry,
			["name", "docstatus", "paid_amount", "reference_no", "remarks"],
			as_dict=True,
		)

	voucher_names = [
		name for name in (capture.purchase_invoice, capture.payment_entry) if name
	]
	gl_entries = _gl_entries_for_vouchers(voucher_names)
	bank_transaction_count = _bank_transaction_count_for_payment_entry(capture.payment_entry)
	closed = bool(
		pi_state
		and pe_state
		and int(pi_state.docstatus) == 1
		and int(pe_state.docstatus) == 1
		and flt(pi_state.outstanding_amount) == 0
		and pi_state.status == "Paid"
	)

	return {
		"capture": {
			"name": capture.name,
			"source_file": capture.source_file,
			"source_file_url": capture.source_file_url,
			"source_filename": capture.source_filename,
			"received_at": capture.received_at,
			"status": capture.status,
			"action_required": capture.action_required,
			"action_required_reason": capture.action_required_reason,
		},
		"ocr": {
			"provider": capture.ocr_provider,
			"status": capture.ocr_status,
			"extracted_at": capture.ocr_extracted_at,
			"proposal": {
				"supplier": capture.proposed_supplier,
				"supplier_invoice_no": capture.proposed_supplier_invoice_no,
				"invoice_date": capture.proposed_invoice_date,
				"total_amount": capture.proposed_total_amount,
				"currency": capture.proposed_currency,
			},
			"final": {
				"supplier": capture.final_supplier,
				"supplier_invoice_no": capture.final_supplier_invoice_no,
				"invoice_date": capture.final_invoice_date,
				"total_amount": capture.final_total_amount,
				"currency": capture.final_currency,
			},
		},
		"validation": {
			"status": capture.validation_status,
			"result": capture.validation_result,
			"matched_supplier": capture.matched_supplier,
			"purchase_reference_status": capture.purchase_reference_status,
			"validated_by": capture.validated_by,
			"validated_at": capture.validated_at,
			"source": capture.validation_source,
		},
		"approval": {
			"status": capture.approval_status,
			"routing_reason": capture.routing_reason,
			"assigned_approver_role": capture.assigned_approver_role,
			"decision_by": capture.decision_by,
			"decision_at": capture.decision_at,
			"decision_notes": capture.decision_notes,
			"payment_readiness": capture.payment_readiness,
		},
		"payment": {
			"entry": capture.payment_entry,
			"provider": capture.mock_payment_provider,
			"reference": capture.mock_payment_reference,
			"status": capture.mock_payment_status,
			"amount": capture.mock_payment_amount,
			"issued_at": capture.mock_payment_issued_at,
			"lifecycle_status": _derive_payment_lifecycle_status(capture),
			"response": json.loads(capture.mock_payment_response or "{}"),
		},
		"native": {
			"purchase_invoice": dict(pi_state or {}),
			"payment_entry": dict(pe_state or {}),
			"gl_entries": gl_entries,
			"gl_entry_count": len(gl_entries),
			"bank_transaction_count": bank_transaction_count,
		},
		"closed": closed,
		"closure_basis": (
			"Closed is derived from native ERPNext state: submitted Purchase Invoice, "
			"submitted Payment Entry, Purchase Invoice outstanding_amount=0, and status Paid. "
			"No custom closed flag is stored; Bank Transaction count must remain 0."
		),
	}


def get_ap_lifecycle_rows() -> list[dict]:
	"""List AP captures with the fields AP clerks need for next action visibility."""

	return frappe.get_all(
		"AP Invoice Capture",
		fields=[
			"name",
			"source_filename",
			"status",
			"action_required",
			"action_required_reason",
			"validation_status",
			"approval_status",
			"payment_readiness",
			"payment_lifecycle_status",
			"purchase_invoice",
			"payment_entry",
			"modified",
		],
		order_by="modified desc",
	)


def get_manager_approval_queue() -> list[dict]:
	"""Return only captures currently waiting for manager approval."""

	return frappe.get_all(
		"AP Invoice Capture",
		filters={"approval_status": APPROVAL_STATUS_PENDING_MANAGER},
		fields=[
			"name",
			"source_filename",
			"final_supplier",
			"final_total_amount",
			"final_currency",
			"routing_reason",
			"assigned_approver_role",
			"purchase_invoice",
		],
		order_by="modified asc",
	)


@frappe.whitelist()
def validate_for_purchase_invoice_for(capture: str, source: str | None = None) -> str:
	"""Whitelisted entrypoint for the validation step."""

	doc = validate_for_purchase_invoice(capture, source=source)
	doc._kick_next_step()
	return doc.name


@frappe.whitelist()
def promote_to_purchase_invoice_for(
	capture: str, defaults: str | dict | None = None
) -> str:
	"""Whitelisted entrypoint for promotion to Purchase Invoice."""

	parsed: dict | None
	if isinstance(defaults, str) and defaults:
		parsed = json.loads(defaults)
	else:
		parsed = defaults or None
	pi = promote_to_purchase_invoice(capture, defaults=parsed)
	# `promote` returns the PI, not the capture — reload the capture to
	# resume the cascade (next hop is approval routing).
	cap = frappe.get_doc("AP Invoice Capture", capture if isinstance(capture, str) else capture.name)
	cap._kick_next_step()
	return pi.name


@frappe.whitelist()
def request_approval_for(
	capture: str,
	threshold: float | str | None = None,
	source: str | None = None,
) -> str:
	"""Whitelisted entrypoint for approval routing."""

	parsed_threshold = float(threshold) if threshold not in (None, "") else None
	doc = request_approval(capture, threshold=parsed_threshold, source=source)
	doc._kick_next_step()
	return doc.name


@frappe.whitelist()
def record_manager_decision_for(
	capture: str,
	approve: bool | int | str,
	notes: str | None = None,
) -> str:
	"""Whitelisted entrypoint for manager approval / rejection."""

	if isinstance(approve, str):
		approve = approve.strip().lower() in ("1", "true", "yes", "approve", "approved")
	doc = record_manager_decision(capture, approve=bool(approve), notes=notes)
	doc._kick_next_step()
	return doc.name


@frappe.whitelist()
def issue_mock_payment_for(capture: str, paid_from: str | None = None) -> str:
	"""Whitelisted entrypoint for deterministic mock payment issuance."""

	pe = issue_mock_payment(capture, paid_from=paid_from)
	# Mock payment is terminal — _kick_next_step is a no-op at Closed/Confirmed
	# but we call it for symmetry and so any future hop (e.g. closure-evidence
	# auto-generation) plugs in without changing the wrapper.
	cap = frappe.get_doc("AP Invoice Capture", capture if isinstance(capture, str) else capture.name)
	cap._kick_next_step()
	return pe.name


@frappe.whitelist()
def build_closure_evidence_for(capture: str) -> dict:
	return build_closure_evidence(capture)


@frappe.whitelist()
def get_ap_lifecycle_rows_for() -> list[dict]:
	return get_ap_lifecycle_rows()


@frappe.whitelist()
def get_manager_approval_queue_for() -> list[dict]:
	return get_manager_approval_queue()
