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
from collections import Counter, namedtuple
from datetime import date, timedelta

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_to_date, flt, get_datetime, getdate, now_datetime, today

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
SUPPLIER_MATCH_ALIAS = "Alias"
SUPPLIER_MATCH_UNKNOWN = "Unknown"
SUPPLIER_MATCH_AMBIGUOUS = "Ambiguous"

# Resolver tier labels (spec 05 §5.1) — which tier produced a match.
SUPPLIER_TIER_NONE = "None"
SUPPLIER_TIER_ALIAS = "Alias"
SUPPLIER_TIER_FUZZY = "Fuzzy"
SUPPLIER_TIER_EXACT = "Exact"

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

# Validation gates: 3WM / anomaly / bank-change (spec 08)
THREE_WAY_MATCH_NOT_CHECKED = "Not Checked"
THREE_WAY_MATCH_NOT_APPLICABLE = "Not Applicable"
THREE_WAY_MATCH_MATCHED = "Matched"
THREE_WAY_MATCH_EXCEPTION = "Exception"
THREE_WAY_MATCH_OVERRIDE = "Matched (Override)"
ANOMALY_NOT_CHECKED = "Not Checked"
ANOMALY_NORMAL = "Normal"
ANOMALY_ANOMALOUS = "Anomalous"
ANOMALY_INSUFFICIENT_HISTORY = "Insufficient History"

# Document-type classification & branching (spec 07)
DOCUMENT_TYPE_UNPAID_BILL = "Unpaid Bill"
DOCUMENT_TYPE_ALREADY_PAID = "Already Paid"
DOCUMENT_TYPE_EMPLOYEE_REIMBURSEMENT = "Employee Reimbursement"
DOCUMENT_TYPE_MANUAL_REVIEW = "Manual Review"
STATUS_MANUAL_REVIEW = "Manual Review"
CLASSIFIED_STREAM_I = "I"
CLASSIFIED_STREAM_R = "R"
CLASSIFIED_STREAM_R_EMPLOYEE = "R-employee"
STREAM_AGREEMENT_AGREE = "Agree"
STREAM_AGREEMENT_DISAGREE = "Disagree"
STREAM_AGREEMENT_UNCONFIRMED = "Unconfirmed"
CLASSIFICATION_SOURCE_DEFAULT = "ap-classify-v1"
CLASSIFICATION_SOURCE_OVERRIDE = "clerk-override"

# GL coding (spec 06)
CODING_STATUS_PENDING = "Pending"
CODING_STATUS_CODED = "Coded"
CODING_STATUS_AMBIGUOUS = "Ambiguous"
CODING_STATUS_FLAGGED = "Flagged"
CODING_SOURCE_DEFAULT = "ap-coding-v1"
# Tax-validation tolerance (D3): absorb extractor rounding without hiding real mismatches.
CODING_TAX_TOLERANCE = 0.01

APPROVAL_STATUS_NOT_REQUIRED = "Not Required"
APPROVAL_STATUS_AUTO_APPROVED = "Auto Approved"
APPROVAL_STATUS_PENDING_MANAGER = "Pending Manager"
APPROVAL_STATUS_MANAGER_APPROVED = "Manager Approved"
APPROVAL_STATUS_REJECTED = "Rejected"
# Spec 09: a capture that cleared validation + promotion but failed the
# confidence or flag axis of confidence-based routing parks here (not an auto
# state) until a clerk fixes it and a sanctioned re-route runs.
APPROVAL_STATUS_NEEDS_REVIEW = "Needs Review"

# Spec 09 — axes the combined-signal routing evaluator reports on.
ROUTING_AXIS_CONFIDENCE = "confidence"
ROUTING_AXIS_VALIDATION_FLAG = "validation_flag"

# Spec 10 — AP Review Event instrumentation vocabularies (fixed; mirror the
# AP Review Event Select options).
REVIEW_ACTION_FIELD_CORRECTED = "field_corrected"
REVIEW_ACTION_SUPPLIER_CREATED = "supplier_created"
REVIEW_ACTION_REJECTED = "rejected"
REVIEW_ACTION_CLASSIFIED_OTHER = "classified_other"
REVIEW_ACTION_CODING_COMPLETED = "coding_completed"
REVIEW_ACTION_TAKEN_VALUES = (
	REVIEW_ACTION_FIELD_CORRECTED,
	REVIEW_ACTION_SUPPLIER_CREATED,
	REVIEW_ACTION_REJECTED,
	REVIEW_ACTION_CLASSIFIED_OTHER,
	REVIEW_ACTION_CODING_COMPLETED,
)
ROOT_CAUSE_EXTRACTION_MISS = "extraction_miss"
ROOT_CAUSE_SUPPLIER_UNMAPPED = "supplier_unmapped"
ROOT_CAUSE_CONFIDENCE_TOO_TIGHT = "confidence_threshold_too_tight"
ROOT_CAUSE_STREAM_MISTAG = "stream_mistag"
ROOT_CAUSE_POLICY_VIOLATION = "policy_violation"
ROOT_CAUSE_VENDOR_ERROR = "vendor_error"
ROOT_CAUSE_MISSING_PO = "missing_po"
ROOT_CAUSE_OTHER = "other"
ROOT_CAUSE_TAG_VALUES = (
	ROOT_CAUSE_EXTRACTION_MISS,
	ROOT_CAUSE_SUPPLIER_UNMAPPED,
	ROOT_CAUSE_CONFIDENCE_TOO_TIGHT,
	ROOT_CAUSE_STREAM_MISTAG,
	ROOT_CAUSE_POLICY_VIOLATION,
	ROOT_CAUSE_VENDOR_ERROR,
	ROOT_CAUSE_MISSING_PO,
	ROOT_CAUSE_OTHER,
)
# Reject/reopen child-table actions (AP Capture Rejection Log).
REJECTION_ACTION_REJECTED = "Rejected"
REJECTION_ACTION_REOPENED = "Reopened"

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

		from erpnext.accounts.doctype.ap_capture_rejection_log.ap_capture_rejection_log import (
			APCaptureRejectionLog,
		)
		from erpnext.accounts.doctype.ap_invoice_capture_confidence.ap_invoice_capture_confidence import (
			APInvoiceCaptureConfidence,
		)
		from erpnext.accounts.doctype.ap_invoice_capture_item.ap_invoice_capture_item import (
			APInvoiceCaptureItem,
		)

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
		proposed_supplier_confidence: DF.Float
		proposed_supplier_invoice_no: DF.Data | None
		proposed_total_amount: DF.Float
		subtotal_amount: DF.Currency
		tax_amount: DF.Currency
		line_items: DF.Table[APInvoiceCaptureItem]
		field_confidences: DF.Table[APInvoiceCaptureConfidence]
		rejection_log: DF.Table[APCaptureRejectionLog]
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
			"Manual Review",
		]
		document_type: DF.Literal[
			"", "Unpaid Bill", "Already Paid", "Employee Reimbursement", "Manual Review"
		]
		classification_override: DF.Literal[
			"", "Unpaid Bill", "Already Paid", "Employee Reimbursement", "Manual Review"
		]
		classified_stream: DF.Literal["", "I", "R", "R-employee"]
		stream_tag_agreement: DF.Literal["Agree", "Disagree", "Unconfirmed"]
		card_charge_marker: DF.Data | None
		detected_last4: DF.Data | None
		expense_claim: DF.Data | None
		classified_at: DF.Datetime | None
		classified_by: DF.Link | None
		classification_source: DF.Data | None
		three_way_match_status: DF.Literal[
			"Not Checked", "Not Applicable", "Matched", "Exception", "Matched (Override)"
		]
		three_way_match_result: DF.LongText | None
		three_way_match_checked_at: DF.Datetime | None
		three_way_match_override_by: DF.Link | None
		three_way_match_override_at: DF.Datetime | None
		three_way_match_override_notes: DF.SmallText | None
		anomaly_status: DF.Literal[
			"Not Checked", "Normal", "Anomalous", "Insufficient History"
		]
		anomaly_result: DF.SmallText | None
		anomaly_checked_at: DF.Datetime | None
		vendor_bank_change_detected: DF.Check
		vendor_bank_change_result: DF.SmallText | None
		vendor_bank_change_checked_at: DF.Datetime | None
		validation_message: DF.SmallText | None
		matched_supplier: DF.Link | None
		supplier_match_status: DF.Literal[
			"Not Validated", "Matched", "Alias", "Unknown", "Ambiguous"
		]
		supplier_match_tier: DF.Literal["None", "Alias", "Fuzzy", "Exact"]
		supplier_match_confidence: DF.Float
		supplier_change_request: DF.Link | None
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
		coding_status: DF.Literal["Pending", "Coded", "Ambiguous", "Flagged"]
		applied_expense_account: DF.Link | None
		applied_cost_center: DF.Link | None
		applied_tax_template: DF.Link | None
		applied_payment_terms_template: DF.Link | None
		coding_review_reason: DF.SmallText | None
		card_last4: DF.Data | None
		receipt_location: DF.Data | None
		coding_source: DF.Data | None
		purchase_invoice: DF.Link | None
		promotion_status: DF.Literal["Not Promoted", "Promoted"]
		approval_status: DF.Literal[
			"Not Required",
			"Auto Approved",
			"Pending Manager",
			"Manager Approved",
			"Rejected",
			"Needs Review",
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

		# A clerk-rejected capture is terminal-quiet (spec 10): never re-derive its
		# status / action_required on a later save, or the Rejected state would be
		# clobbered back to an in-progress value (the highest-risk integration point).
		if self.status == STATUS_REJECTED:
			return

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

		# Spec 10: a clerk-rejected capture is terminal — never auto-advance it
		# (it waits for an explicit reopen). The positive branches below would all
		# miss anyway, but make the exclusion explicit and future-proof.
		if self.status == STATUS_REJECTED:
			return None

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

		# Step 1a (spec 04/09 §5.6, T-015): confidence-gated auto-confirm. A freshly
		# extracted capture normally pauses at Proposed for a human to confirm the OCR
		# proposal. When auto-confirm is opted in AND every mandatory header field
		# cleared its confidence threshold AND no validation flag is open, skip that
		# pause and auto-confirm — escalate only the doubtful. Gated last so the
		# settings read is skipped entirely when the cheap state checks miss.
		if (
			self.status == STATUS_PROPOSED
			and self.ocr_status == OCR_STATUS_PROPOSED
		):
			from erpnext.accounts.doctype.ap_closed_loop_settings.ap_closed_loop_settings import (
				is_auto_confirm_enabled,
			)

			if is_auto_confirm_enabled():
				decision = _evaluate_confirm_signals(self)
				if decision.fields_ok and decision.flags_ok:
					return (
						"auto_confirm_extracted_fields_for",
						"auto: confidence-gated auto-confirm",
					)

		# Step 1b (spec 07): Confirmed OCR, not yet classified → Step-6 classification.
		# Runs before validation so the doctype fork is decided first. A clerk override
		# is honoured (re-classify supersedes); an Employee/Manual-Review outcome parks
		# the capture (status -> Manual Review) and the steps below won't match.
		if (
			self.ocr_status == OCR_STATUS_CONFIRMED
			and not self.document_type
			and self.status == STATUS_CONFIRMED
		):
			return ("classify_document_type_for", "auto: post-confirm Step-6 classification")

		# Step 2: Confirmed OCR → run validation (Stream-I Unpaid Bill, or Already
		# Paid which still needs supplier resolution; unclassified back-compat too).
		if (
			self.ocr_status == OCR_STATUS_CONFIRMED
			and self.status == STATUS_CONFIRMED
			and self.document_type in (None, "", DOCUMENT_TYPE_UNPAID_BILL, DOCUMENT_TYPE_ALREADY_PAID)
			and self.validation_status in (None, VALIDATION_STATUS_NOT_VALIDATED)
		):
			return ("validate_for_purchase_invoice_for", "auto: post-confirm validation")

		# Step 2a (spec 07): Already Paid, validated, supplier resolved → post the
		# is-paid Purchase Invoice (Stream R; no approval/payment). Only auto-fires when
		# the paid-from account is configured; otherwise it parks at a manual seam.
		if (
			self.document_type == DOCUMENT_TYPE_ALREADY_PAID
			and self.validation_status == VALIDATION_STATUS_VALIDATED
			and self.matched_supplier
			and not self.purchase_invoice
		):
			from erpnext.accounts.doctype.ap_closed_loop_settings.ap_closed_loop_settings import (
				get_already_paid_config,
			)

			if get_already_paid_config().get("paid_from_account"):
				return ("promote_already_paid_for", "auto: Stream-R already-paid posting")

		# Step 2b: Validated → GL coding (spec 06). Only auto-fires when coding is
		# actually configured for this capture (a supplier coding profile exists, or
		# the Stream-R catch-all account is set) — so an unconfigured site flows
		# straight to the promote seam exactly as before (graceful degrade). Coding
		# that lands Ambiguous/Flagged parks here (coding_status leaves Pending).
		if (
			self.validation_status == VALIDATION_STATUS_VALIDATED
			and self.coding_status in (None, CODING_STATUS_PENDING)
			and (self.matched_supplier or self.stream == STREAM_RECEIPT)
			and self._coding_configured()
		):
			return ("apply_coding_profile_for_ui", "auto: post-validation GL coding")

		# Manual seam: validated captures wait for a clerk to click Promote
		# (defaults like company / item_code are required by the PI schema
		# and have no source on the capture record itself).

		# Step 3: Promoted with no approval yet → route approval. Already-Paid (Stream
		# R) PIs skip approval/payment entirely — the money already moved (spec 07).
		if (
			self.promotion_status == PROMOTION_STATUS_PROMOTED
			and self.purchase_invoice
			and self.document_type != DOCUMENT_TYPE_ALREADY_PAID
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

	def _coding_configured(self) -> bool:
		"""True when GL coding (spec 06) has something to do for this capture:
		a supplier coding profile exists, or (Stream R) the catch-all account is set.
		Keeps the coding cascade hop dormant on unconfigured sites."""

		if self.matched_supplier and frappe.db.exists(
			"AP Supplier Coding Profile", self.matched_supplier
		):
			return True
		# Coding bootstrap from history (spec 06 §5.3.1, T-016): no profile, but the
		# supplier has enough posted-PI history to self-code → the coding hop fires so
		# _derive_coding_from_history gets a chance (cheap count guard).
		if self.matched_supplier:
			from erpnext.accounts.doctype.ap_closed_loop_settings.ap_closed_loop_settings import (
				get_coding_history_config,
			)

			hist = get_coding_history_config()
			if hist["enabled"]:
				filters = {"supplier": self.matched_supplier, "docstatus": 1}
				if hist["company"]:
					filters["company"] = hist["company"]
				if frappe.db.count("Purchase Invoice", filters) >= hist["min_samples"]:
					return True
		if self.stream == STREAM_RECEIPT:
			from erpnext.accounts.doctype.ap_closed_loop_settings.ap_closed_loop_settings import (
				get_coding_settings,
			)

			return bool(get_coding_settings().get("unmapped_card_spend_account"))
		return False

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

	# Spec 04: persist numeric per-field confidence + extracted line items as
	# child rows, and surface subtotal / tax / a resolved PO header ref. This is a
	# clear-and-replace rebuild, so a re-extraction is idempotent.
	_write_extraction_detail(capture, result, ocr_config)

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
			# Spec 04: audit copy-of-record of the numeric scores + lines. No
			# credentials here (the proposal/confidence/lines carry no key; the API
			# key is fetched lazily and never serialized).
			"confidence": result.confidence,
			"lines": result.lines,
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
# Spec 04 — per-field confidence + line-item write-back
# ---------------------------------------------------------------------------

# Logical line-field base names a "line_<i>_<field>" key strips to (for threshold
# resolution and the confidence_summary blurb).
_LINE_KEY_RE = re.compile(r"^line_\d+_(.+)$")


def _base_field(field_name: str) -> str:
	"""``line_0_amount`` -> ``amount``; header keys pass through unchanged."""

	m = _LINE_KEY_RE.match(field_name or "")
	return m.group(1) if m else (field_name or "")


def _resolve_above(field_name: str, conf: float, cfg: dict) -> bool:
	"""Whether ``conf`` clears the per-field threshold (spec 04 §5.3.5).

	Two-tier resolution (locked decision #4 — no second scalar): a per-field
	override in ``cfg["field_thresholds"]`` keyed by the base field, else the
	canonical ``cfg["confidence_threshold"]`` (the existing ``ocr_confidence_threshold``).
	Pure + idempotent.
	"""

	default = cfg.get("confidence_threshold", 0.70)
	thresholds = cfg.get("field_thresholds") or {}
	base = _base_field(field_name)
	threshold = default
	if base in thresholds:
		try:
			threshold = float(thresholds[base])
		except (TypeError, ValueError):
			threshold = default
	try:
		return float(conf) >= float(threshold)
	except (TypeError, ValueError):
		return False


def _to_float(value, default: float = 0.0) -> float:
	"""Defensive numeric coercion — a malformed extracted value never raises
	mid-write-back (it surfaces later at promote reconciliation, spec 04 §5.3.6)."""

	if value in (None, ""):
		return default
	try:
		return float(value)
	except (TypeError, ValueError):
		return default


def _existing_link(doctype: str, value) -> "str | None":
	"""Return ``value`` only if it names an existing ``doctype`` record, else None.

	Guards Link writes so a hallucinated OCR string (PO/PR/account/cost-center)
	never creates a dangling Link that would fail validation on save (spec 04
	§5.3.3 / AC-04-10)."""

	if value and frappe.db.exists(doctype, value):
		return value
	return None


def _line_confidence_summary(line_conf: dict) -> "str | None":
	"""Compact per-line blurb like ``desc 0.95 / amount 0.88 / po 0.40`` from a
	line's confidence dict. Authoritative numbers live in field_confidences."""

	abbr = {"description": "desc", "po_reference": "po"}
	parts = []
	for fkey in ("description", "qty", "rate", "amount", "po_reference"):
		val = (line_conf or {}).get(fkey)
		if val is not None:
			try:
				parts.append(f"{abbr.get(fkey, fkey)} {float(val):.2f}")
			except (TypeError, ValueError):
				continue
	return " / ".join(parts) or None


def _write_extraction_detail(
	capture: "APInvoiceCapture", result, cfg: dict
) -> None:
	"""Rebuild ``field_confidences`` + ``line_items`` and set header surfaces.

	Clear-and-replace (idempotent across re-extraction). Never raises on a
	malformed line — values are coerced defensively; a bad line is caught at
	promote reconciliation, not here.
	"""

	# (1) field_confidences — one row per header key AND per line_<i>_<field> key.
	conf_rows = []
	for field_name, conf in (getattr(result, "confidence", None) or {}).items():
		conf_val = _to_float(conf)
		conf_rows.append(
			{
				"field_name": field_name,
				"confidence": conf_val,
				"is_above_threshold": 1 if _resolve_above(field_name, conf_val, cfg) else 0,
				"score_source": (getattr(result, "score_sources", None) or {}).get(
					field_name
				)
				or "Model",
			}
		)
	capture.set("field_confidences", conf_rows)

	# (2) line_items — one AP Invoice Capture Item per extracted line.
	currency = capture.final_currency or capture.proposed_currency
	line_rows = []
	for line in getattr(result, "lines", None) or []:
		qty = _to_float(line.get("qty"), default=1.0)
		rate = _to_float(line.get("rate"))
		amount = line.get("amount")
		amount = _to_float(amount) if amount not in (None, "") else round(qty * rate, 2)
		line_rows.append(
			{
				"description": line.get("description"),
				"qty": qty,
				"rate": rate,
				"amount": amount,
				"tax_amount": _to_float(line.get("tax_amount")),
				"expense_account": _existing_link("Account", line.get("expense_account")),
				"cost_center": _existing_link("Cost Center", line.get("cost_center")),
				"po_reference": _existing_link("Purchase Order", line.get("po_reference")),
				"pr_reference": _existing_link("Purchase Receipt", line.get("pr_reference")),
				"currency": currency,
				"confidence_summary": _line_confidence_summary(line.get("confidence")),
			}
		)
	capture.set("line_items", line_rows)

	# (3) Header surfaces — subtotal / tax / resolved PO. A non-existent PO string
	# is NOT written to the Link (no dangling ref); the raw value already rides in
	# ocr_raw_response under proposal["po_reference"] for review.
	proposal = getattr(result, "proposal", None) or {}
	capture.subtotal_amount = _to_float(proposal.get("subtotal"))
	capture.tax_amount = _to_float(proposal.get("tax"))
	resolved_po = _existing_link("Purchase Order", proposal.get("po_reference"))
	if resolved_po:
		capture.purchase_order_reference = resolved_po

	# (4) Derive the single supplier-name confidence scalar the spec-05 Tier-3 gate
	# reads (OD-05-4: spec 04 owns the full confidence child table; this is the one
	# derived float). The extractor keys it as "supplier_name" or "supplier".
	conf_map = getattr(result, "confidence", None) or {}
	supplier_conf = conf_map.get("supplier_name", conf_map.get("supplier"))
	capture.proposed_supplier_confidence = _to_float(supplier_conf)


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
	emit_event: bool = True,
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

	# Spec 10 instrumentation: snapshot final_* before the merge so we can record
	# which header fields the clerk actually changed (fields_changed) and pick the
	# action class (field_corrected vs coding_completed).
	_final_before = {
		logical_name: capture.get(final_field)
		for logical_name, _proposed_field, final_field in MANDATORY_HEADER_FIELDS
	}

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

	# Spec 10 instrumentation: one AP Review Event per HUMAN confirm action. Header
	# field change → field_corrected; clerk-supplied GL coding with no header change →
	# coding_completed (decision D-7). Telemetry never blocks the action. Suppressed on
	# the confidence-gated auto-confirm path (emit_event=False) — an auto-confirm is the
	# opposite of an escalation (no human acted), so it must not pollute the spec-10
	# root-cause report that measures avoidable human work.
	if emit_event:
		_changed = {
			logical: {"from": _final_before.get(logical), "to": capture.get(final_field)}
			for logical, _proposed, final_field in MANDATORY_HEADER_FIELDS
			if _final_before.get(logical) != capture.get(final_field)
		}
		_coding_supplied = any(k in corrections for k in ("cost_center", "expense_account"))
		_action = (
			REVIEW_ACTION_CODING_COMPLETED
			if (_coding_supplied and not _changed)
			else REVIEW_ACTION_FIELD_CORRECTED
		)
		_safe_emit_review_event(
			capture,
			action_taken=_action,
			root_cause_tag=ROOT_CAUSE_EXTRACTION_MISS,
			exception_reason_code="ocr_review",
			fields_changed=_changed or None,
			note=notes,
			clerk=reviewer or frappe.session.user,
		)

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


@frappe.whitelist()
def auto_confirm_extracted_fields_for(capture: str) -> str:
	"""Cascade entrypoint for confidence-gated auto-confirm (spec 04/09 §5.6, T-015).

	Promotes the OCR proposal to final with NO corrections and NO human, when the
	confirm-seam gate has already passed in ``_determine_next_step``. Re-checks the
	gate defensively (a concurrent edit could have changed state) and falls back to
	the human pause if it no longer holds. Suppresses the spec-10 AP Review Event —
	an auto-confirm is not an escalation. Resumes the cascade."""

	doc = frappe.get_doc("AP Invoice Capture", capture)
	decision = _evaluate_confirm_signals(doc)
	if not (decision.fields_ok and decision.flags_ok):
		# Lost the gate since enqueue — leave it at the human pause; do not auto-confirm.
		return doc.name
	doc = confirm_extracted_fields(
		doc, notes=_("Auto-confirmed (confidence-gated, T-015)"), emit_event=False
	)
	doc._kick_next_step()
	return doc.name


# ---------------------------------------------------------------------------
# Validation against existing ERPNext records + Purchase Invoice promotion
# ---------------------------------------------------------------------------


_ALIAS_TYPE_PRECEDENCE = {"exact": 0, "glob": 1, "regex": 2}


def _resolve_supplier(supplier_name: str | None, *, stream: str | None = None) -> dict:
	"""Three-tier supplier resolver (spec 05 §5.3). NEVER auto-creates a Supplier.

	Returns ``{matched_supplier, match_status, confidence, tier, alias_id, competing}``.
	Tier 1 = deterministic alias table (exact > glob > regex); Tier 2 = exact PK /
	unique supplier_name, then rapidfuzz token_set_ratio; Tier 3 (the gated create
	request) is fired by the caller ``validate_for_purchase_invoice``, never here.
	``stream`` is accepted for signature symmetry; branching lives in the caller.
	"""

	result = {
		"matched_supplier": None,
		"match_status": SUPPLIER_MATCH_UNKNOWN,
		"confidence": 0.0,
		"tier": SUPPLIER_TIER_NONE,
		"alias_id": None,
		"competing": [],
	}

	candidate = (supplier_name or "").strip() or None
	if not candidate:
		return result

	# Tier 1 — alias (deterministic, highest precedence).
	alias_hit = _resolve_alias(candidate)
	if alias_hit is not None:
		return alias_hit

	# Tier 2a — preserve current exact behaviour (PK then unique supplier_name).
	if frappe.db.exists("Supplier", candidate):
		result.update(
			matched_supplier=candidate,
			match_status=SUPPLIER_MATCH_MATCHED,
			confidence=100.0,
			tier=SUPPLIER_TIER_EXACT,
		)
		return result

	by_supplier_name = frappe.get_all(
		"Supplier", filters={"supplier_name": candidate}, pluck="name"
	)
	if len(by_supplier_name) == 1:
		result.update(
			matched_supplier=by_supplier_name[0],
			match_status=SUPPLIER_MATCH_MATCHED,
			confidence=100.0,
			tier=SUPPLIER_TIER_EXACT,
		)
		return result
	if len(by_supplier_name) > 1:
		result.update(
			match_status=SUPPLIER_MATCH_AMBIGUOUS,
			confidence=100.0,
			competing=by_supplier_name,
		)
		return result

	# Tier 2b — fuzzy (only if exact found nothing).
	return _resolve_fuzzy(candidate, result)


def _resolve_alias(candidate: str) -> "dict | None":
	"""Tier 1: match ``candidate`` against active AP Supplier Alias rows.

	Precedence exact > glob > regex, then ``priority`` asc, then ``name`` asc. A bad
	regex is caught + logged + skipped (never raises into validation; AC-05-4).
	Aliases pointing at a disabled Supplier are ignored. Returns a resolution dict
	(Alias / Ambiguous) or ``None`` to fall through to Tier 2.
	"""

	aliases = frappe.get_all(
		"AP Supplier Alias",
		filters={"is_active": 1},
		fields=["name", "canonical_supplier", "alias_pattern", "match_type", "priority"],
		order_by="priority asc, name asc",
	)
	if not aliases:
		return None

	matches: list[tuple] = []  # (type_precedence, priority, name, canonical_supplier)
	disabled_cache: dict[str, bool] = {}
	for a in aliases:
		mt = a.match_type or "glob"
		pattern = a.alias_pattern or ""
		if not pattern:
			continue
		try:
			if mt == "exact":
				hit = pattern == candidate
			elif mt == "regex":
				hit = re.fullmatch(pattern, candidate) is not None
			else:  # glob (default)
				hit = fnmatch.fnmatchcase(candidate, pattern)
		except re.error:
			# A malformed regex must never block validation — skip + log.
			frappe.log_error(
				title="AP Supplier Alias bad regex",
				message=f"Skipping alias {a.name} with uncompilable regex {pattern!r}.",
			)
			continue

		if not hit:
			continue

		canonical = a.canonical_supplier
		if canonical not in disabled_cache:
			disabled_cache[canonical] = bool(
				frappe.db.get_value("Supplier", canonical, "disabled")
			)
		if disabled_cache[canonical]:
			continue  # alias points at a disabled Supplier — ignore it

		matches.append((_ALIAS_TYPE_PRECEDENCE.get(mt, 9), a.priority or 0, a.name, canonical))

	if not matches:
		return None

	distinct_suppliers = {m[3] for m in matches}
	if len(distinct_suppliers) == 1:
		matches.sort(key=lambda m: (m[0], m[1], m[2]))
		best = matches[0]
		return {
			"matched_supplier": best[3],
			"match_status": SUPPLIER_MATCH_ALIAS,
			"confidence": 100.0,
			"tier": SUPPLIER_TIER_ALIAS,
			"alias_id": best[2],
			"competing": [],
		}

	# Two active aliases point at different suppliers — ambiguous, do not guess.
	return {
		"matched_supplier": None,
		"match_status": SUPPLIER_MATCH_AMBIGUOUS,
		"confidence": 100.0,
		"tier": SUPPLIER_TIER_ALIAS,
		"alias_id": None,
		"competing": sorted(distinct_suppliers),
	}


def _resolve_fuzzy(candidate: str, result: dict) -> dict:
	"""Tier 2b: rapidfuzz ``token_set_ratio`` over active Suppliers (spec 05 §5.3).

	Mutates and returns ``result``. A candidate shorter than the settings
	``supplier_fuzzy_min_length`` floor is left Unknown (OD-05-2 short-name guard).
	"""

	from erpnext.accounts.doctype.ap_closed_loop_settings.ap_closed_loop_settings import (
		get_supplier_resolution_settings,
	)

	cfg = get_supplier_resolution_settings()
	threshold = cfg["supplier_fuzzy_threshold"]
	min_length = cfg["supplier_fuzzy_min_length"]

	if len(candidate) < min_length:
		return result  # too short for reliable fuzzy — stays Unknown, confidence 0

	from rapidfuzz import fuzz

	suppliers = frappe.get_all(
		"Supplier", filters={"disabled": 0}, fields=["name", "supplier_name"]
	)

	best_score = 0.0
	hits: list[tuple[float, str]] = []
	for s in suppliers:
		target = s.supplier_name or s.name
		score = float(fuzz.token_set_ratio(candidate, target))
		if score > best_score:
			best_score = score
		if score >= threshold:
			hits.append((score, s.name))

	if len(hits) == 1:
		result.update(
			matched_supplier=hits[0][1],
			match_status=SUPPLIER_MATCH_MATCHED,
			confidence=hits[0][0],
			tier=SUPPLIER_TIER_FUZZY,
		)
		return result

	if len(hits) > 1:
		hits.sort(reverse=True)
		result.update(
			match_status=SUPPLIER_MATCH_AMBIGUOUS,
			confidence=hits[0][0],
			competing=[name for _score, name in hits],
		)
		return result

	# Zero ≥ threshold — Unknown, but surface the best score seen for observability.
	result.update(match_status=SUPPLIER_MATCH_UNKNOWN, confidence=best_score)
	return result


def _match_supplier(supplier_name: str | None) -> tuple[str | None, str]:
	"""Back-compat shim over ``_resolve_supplier`` (spec 05 §5.2).

	Returns the legacy ``(matched_name, status)`` tuple so pre-spec-05 callers and
	tests stay green. A Tier-1 ``Alias`` hit folds into the legacy ``Matched`` value
	(legacy callers only know Matched / Unknown / Ambiguous). Suppliers are still
	never auto-created. Mirrors the ``run_fake_extraction = run_extraction`` alias.
	"""

	resolution = _resolve_supplier(supplier_name)
	status = resolution["match_status"]
	if status == SUPPLIER_MATCH_ALIAS:
		status = SUPPLIER_MATCH_MATCHED
	return resolution["matched_supplier"], status


def queue_supplier_create_request(
	capture: "APInvoiceCapture | str", candidate: str, payload: dict | None = None
) -> str:
	"""Tier 3: create a Draft Supplier Master Change Request. NEVER creates a Supplier.

	Idempotent on ``(evidence_capture, change_type=Create, open)`` — a second call
	for a capture that already has an open create-request returns the existing one.
	Returns the request name.
	"""

	capture_name = capture if isinstance(capture, str) else capture.name

	existing = frappe.get_all(
		"Supplier Master Change Request",
		filters={
			"evidence_capture": capture_name,
			"change_type": "Create",
			"workflow_state": ["in", ["Draft", "Pending Approval", "Approved"]],
		},
		pluck="name",
		limit=1,
	)
	if existing:
		req_name = existing[0]
	else:
		payload = payload or {"supplier_name": candidate, "supplier_type": "Company"}
		req = frappe.get_doc(
			{
				"doctype": "Supplier Master Change Request",
				"change_type": "Create",
				"requested_supplier_name": candidate,
				"evidence_capture": capture_name,
				"proposed_payload": json.dumps(payload),
			}
		)
		req.insert(ignore_permissions=True)
		req_name = req.name

	# Link the request back onto the capture (spec 05 §5.2). When handed a doc, set
	# the attribute so the caller's pending save persists it; when handed a name,
	# write directly (the capture isn't in-flight here).
	if isinstance(capture, str):
		frappe.db.set_value(
			"AP Invoice Capture", capture_name, "supplier_change_request", req_name
		)
	else:
		capture.supplier_change_request = req_name
	return req_name


def _maybe_queue_supplier_create(capture: "APInvoiceCapture", candidate: str | None) -> None:
	"""Fire Tier-3 iff the gate is on AND OCR supplier confidence clears the bar AND
	no open create-request already exists for this capture (spec 05 §5.3-Tier-3).

	Passes the in-memory doc so the back-link is set on it (persisted by the
	validate save that follows), not written behind the pending save."""

	if not candidate or capture.supplier_change_request:
		return

	from erpnext.accounts.doctype.ap_closed_loop_settings.ap_closed_loop_settings import (
		get_supplier_resolution_settings,
	)

	cfg = get_supplier_resolution_settings()
	if not cfg["enable_gated_supplier_creation"]:
		return
	confidence = capture.proposed_supplier_confidence or 0.0
	if confidence < cfg["supplier_autocreate_confidence_threshold"]:
		return

	payload = {"supplier_name": candidate, "supplier_type": "Company"}
	queue_supplier_create_request(capture, candidate, payload)


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


# ---------------------------------------------------------------------------
# Validation gates: three-way match, amount anomaly, vendor bank change (spec 08)
# ---------------------------------------------------------------------------
#
# All three gates run inside ``validate_for_purchase_invoice`` (save=False) and
# record their verdict on the capture. They are *stream-aware* exactly like the
# supplier gate: on Stream I (or unset/Unclassified — the stricter D7 fallback) a
# failing gate is BLOCKING; on Stream R (already-paid card spend) the verdict is
# recorded but never blocks. The bank-change gate additionally re-asserts itself
# at promotion time (an approved Update-Bank-Details request lifts it).


def _is_stream_i(capture: "APInvoiceCapture") -> bool:
	"""True when the gates should block on failure.

	Stream R (Receipt) short-circuits to non-blocking; Invoice / Unclassified /
	unset all resolve to Stream I (D7: absent stream ⇒ treat as the stricter I).
	"""

	return capture.stream != STREAM_RECEIPT


def _resolve_gate_config(capture: "APInvoiceCapture") -> dict:
	"""Effective gate parameters: site settings, with per-supplier profile overrides.

	A non-zero ``AP Supplier Coding Profile`` override replaces the corresponding
	site default (a Frappe Float can't be NULL, so 0 means "no override / use
	settings"; the strict-0 floor already lives in settings). When
	``respect_over_billing_allowance`` is on, the amount tolerance is widened to at
	least the native ``Accounts Settings.over_billing_allowance`` so 3WM never
	blocks what ERPNext itself would permit (D2).
	"""

	from erpnext.accounts.doctype.ap_closed_loop_settings.ap_closed_loop_settings import (
		get_validation_gate_config,
	)

	cfg = dict(get_validation_gate_config())

	supplier = capture.matched_supplier
	if supplier and frappe.db.exists("AP Supplier Coding Profile", supplier):
		profile = frappe.get_doc("AP Supplier Coding Profile", supplier)
		for field in (
			"qty_tolerance_pct",
			"amount_tolerance_pct",
			"anomaly_multiple",
			"anomaly_sigma",
			"anomaly_min_sample",
		):
			override = profile.get(field)
			try:
				if override not in (None, "") and float(override) != 0:
					cfg[field] = float(override)
			except (TypeError, ValueError):
				pass

	if cfg.get("respect_over_billing_allowance"):
		try:
			allowance = float(
				frappe.db.get_single_value("Accounts Settings", "over_billing_allowance") or 0
			)
			cfg["amount_tolerance_pct"] = max(cfg["amount_tolerance_pct"], allowance)
		except Exception:
			pass

	return cfg


def three_way_match_for(capture: "APInvoiceCapture | str", save: bool = True) -> "APInvoiceCapture":
	"""Three-way match the capture against its referenced Purchase Order(s).

	PO-level match (pilot scope): OCR resolves a PO reference at header / line
	granularity but does not produce a ``po_detail`` row mapping, so the cumulative
	PO authority (sum of received_qty and ordered amount across the referenced POs)
	is compared against the invoiced qty/amount. Honors D1 (cumulative received_qty,
	not per-delivery) and the qty/amount tolerances.

	* Stream R → ``Not Applicable`` (receipts are already paid; no PO control).
	* An existing ``Matched (Override)`` is left untouched — an AP override stands
	  and must not be silently recomputed back to ``Exception``.
	* No PO referenced → ``Not Applicable``, unless ``require_po_for_invoices`` is on
	  (then a Stream-I invoice with no PO is itself an ``Exception``).
	"""

	if isinstance(capture, str):
		capture = frappe.get_doc("AP Invoice Capture", capture)

	capture.three_way_match_checked_at = now_datetime()

	if capture.three_way_match_status == THREE_WAY_MATCH_OVERRIDE:
		# An AP override is authoritative; never recompute over it.
		if save:
			capture.save()
		return capture

	if not _is_stream_i(capture):
		capture.three_way_match_status = THREE_WAY_MATCH_NOT_APPLICABLE
		capture.three_way_match_result = json.dumps({"reason": "Stream R — no PO control"})
		if save:
			capture.save()
		return capture

	cfg = _resolve_gate_config(capture)

	po_refs: set[str] = set()
	for line in capture.get("line_items") or []:
		if line.get("po_reference"):
			po_refs.add(line.po_reference)
	if not po_refs and capture.purchase_order_reference:
		po_refs.add(capture.purchase_order_reference)

	if not po_refs:
		if cfg.get("require_po_for_invoices"):
			capture.three_way_match_status = THREE_WAY_MATCH_EXCEPTION
			capture.three_way_match_result = json.dumps(
				{"reason": "PO reference required by policy but none present"}
			)
		else:
			capture.three_way_match_status = THREE_WAY_MATCH_NOT_APPLICABLE
			capture.three_way_match_result = json.dumps({"reason": "No PO referenced (PO-less invoice)"})
		if save:
			capture.save()
		return capture

	po_received_qty = 0.0
	po_ordered_amount = 0.0
	for po in sorted(po_refs):
		for item in frappe.get_all(
			"Purchase Order Item",
			filters={"parent": po},
			fields=["qty", "rate", "received_qty"],
		):
			po_received_qty += flt(item.received_qty)
			po_ordered_amount += flt(item.qty) * flt(item.rate)

	invoiced_amount = flt(capture.final_total_amount)
	line_qtys = [flt(line.qty) for line in (capture.get("line_items") or []) if line.get("qty")]
	invoiced_qty = sum(line_qtys) if line_qtys else None

	qty_ok = True
	qty_diff_pct = 0.0
	if invoiced_qty is not None:
		if po_received_qty > 0:
			qty_diff_pct = (invoiced_qty - po_received_qty) / po_received_qty * 100
			qty_ok = qty_diff_pct <= cfg["qty_tolerance_pct"]
		elif invoiced_qty > 0:
			# Billing for goods with zero cumulative receipt is always an exception.
			qty_ok = False
			qty_diff_pct = 100.0

	amount_ok = True
	amount_diff_pct = 0.0
	if po_ordered_amount > 0:
		amount_diff_pct = (invoiced_amount - po_ordered_amount) / po_ordered_amount * 100
		amount_ok = amount_diff_pct <= cfg["amount_tolerance_pct"]

	within_tolerance = qty_ok and amount_ok
	capture.three_way_match_status = (
		THREE_WAY_MATCH_MATCHED if within_tolerance else THREE_WAY_MATCH_EXCEPTION
	)
	capture.three_way_match_result = json.dumps(
		{
			"purchase_orders": sorted(po_refs),
			"po_received_qty": po_received_qty,
			"po_ordered_amount": round(po_ordered_amount, 2),
			"invoiced_qty": invoiced_qty,
			"invoiced_amount": invoiced_amount,
			"qty_tolerance_pct": cfg["qty_tolerance_pct"],
			"amount_tolerance_pct": cfg["amount_tolerance_pct"],
			"qty_diff_pct": round(qty_diff_pct, 2),
			"amount_diff_pct": round(amount_diff_pct, 2),
			"within_tolerance": within_tolerance,
		}
	)
	if save:
		capture.save()
	return capture


def _anomaly_baseline(supplier: str, cfg: dict) -> tuple[int, float, float]:
	"""Return ``(sample_count, mean, population_stddev)`` of the supplier's recent PIs.

	Uses the ``AP Supplier Anomaly Baseline`` cache when it is fresh (computed today
	for the same window); otherwise recomputes inline from submitted Purchase
	Invoices in the lookback window. Population stddev (denominator N) so a single
	outlier in a small sample still moves sigma sensibly.
	"""

	lookback = int(cfg["anomaly_lookback_months"])

	cached = frappe.db.get_value(
		"AP Supplier Anomaly Baseline",
		supplier,
		["sample_count", "mean_grand_total", "stddev_grand_total", "computed_at", "window_months"],
		as_dict=True,
	)
	if (
		cached
		and cached.computed_at
		and getdate(cached.computed_at) == getdate(today())
		and int(cached.window_months or 0) == lookback
	):
		return int(cached.sample_count or 0), flt(cached.mean_grand_total), flt(cached.stddev_grand_total)

	totals = frappe.get_all(
		"Purchase Invoice",
		filters={
			"supplier": supplier,
			"docstatus": 1,
			"posting_date": [">=", add_to_date(today(), months=-lookback)],
		},
		pluck="grand_total",
	)
	values = [flt(t) for t in totals]
	n = len(values)
	if n == 0:
		return 0, 0.0, 0.0
	mean = sum(values) / n
	variance = sum((v - mean) ** 2 for v in values) / n
	return n, mean, variance ** 0.5


def detect_amount_anomaly_for(
	capture: "APInvoiceCapture | str", save: bool = True
) -> "APInvoiceCapture":
	"""Flag a capture whose total is an outlier vs the supplier's recent history.

	Anomalous when the total exceeds either rule: ``> anomaly_multiple × mean`` OR
	``> anomaly_sigma × stddev`` from the mean. Below ``anomaly_min_sample`` prior
	PIs → ``Insufficient History`` (recorded, never blocking — D8). No matched
	supplier → also ``Insufficient History``.
	"""

	if isinstance(capture, str):
		capture = frappe.get_doc("AP Invoice Capture", capture)

	capture.anomaly_checked_at = now_datetime()
	supplier = capture.matched_supplier

	if not supplier:
		capture.anomaly_status = ANOMALY_INSUFFICIENT_HISTORY
		capture.anomaly_result = "No matched supplier — anomaly baseline unavailable."
		if save:
			capture.save()
		return capture

	cfg = _resolve_gate_config(capture)
	n, mean, stddev = _anomaly_baseline(supplier, cfg)
	min_sample = int(cfg["anomaly_min_sample"])

	if n < min_sample:
		capture.anomaly_status = ANOMALY_INSUFFICIENT_HISTORY
		capture.anomaly_result = "Only {0} prior invoice(s) in the last {1} months (min {2}).".format(
			n, int(cfg["anomaly_lookback_months"]), min_sample
		)
		if save:
			capture.save()
		return capture

	total = flt(capture.final_total_amount)
	multiple_hit = mean > 0 and total > cfg["anomaly_multiple"] * mean
	sigma_hit = stddev > 0 and abs(total - mean) > cfg["anomaly_sigma"] * stddev
	anomalous = multiple_hit or sigma_hit
	z_score = (total - mean) / stddev if stddev > 0 else 0.0

	capture.anomaly_status = ANOMALY_ANOMALOUS if anomalous else ANOMALY_NORMAL
	capture.anomaly_result = (
		"Total {0:,.2f} vs {1}-mo mean {2:,.2f} ± {3:,.2f} (n={4}, z={5:.1f}); "
		"rules: >{6}×mean={7}, >{8}σ={9}."
	).format(
		total,
		int(cfg["anomaly_lookback_months"]),
		mean,
		stddev,
		n,
		z_score,
		cfg["anomaly_multiple"],
		multiple_hit,
		cfg["anomaly_sigma"],
		sigma_hit,
	)
	if save:
		capture.save()
	return capture


# Vendor master fields whose change since the last payment is treated as a
# bank-detail change (social-engineering-fraud defence).
_BANK_ACCOUNT_WATCH_FIELDS = {"iban", "bank_account_no", "branch_code"}
_BANK_WATCH_FIELDS = {"swift_number", "bank_name"}
_SUPPLIER_WATCH_FIELDS = {"default_bank_account"}


def detect_vendor_bank_change_for(
	capture: "APInvoiceCapture | str", save: bool = True
) -> "APInvoiceCapture":
	"""Detect a watched vendor bank-detail change since the supplier's last payment.

	Anchors on the most recent *submitted* Payment Entry to the supplier and scans
	``Version`` history (Frappe's native ``track_changes`` audit) of the supplier's
	default Bank Account, its Bank, and the Supplier's ``default_bank_account`` link
	created after that anchor. No prior payment → not detected (soft baseline, D8a).
	"""

	if isinstance(capture, str):
		capture = frappe.get_doc("AP Invoice Capture", capture)

	capture.vendor_bank_change_checked_at = now_datetime()
	supplier = capture.matched_supplier

	if not supplier:
		capture.vendor_bank_change_detected = 0
		capture.vendor_bank_change_result = "No matched supplier."
		if save:
			capture.save()
		return capture

	last_pe = frappe.get_all(
		"Payment Entry",
		filters={"party_type": "Supplier", "party": supplier, "docstatus": 1},
		fields=["name", "creation"],
		order_by="creation desc",
		limit=1,
	)
	if not last_pe:
		capture.vendor_bank_change_detected = 0
		capture.vendor_bank_change_result = (
			"No prior payment to this supplier — bank-change baseline not yet established."
		)
		if save:
			capture.save()
		return capture

	anchor = last_pe[0].creation
	default_bank_account = frappe.db.get_value("Supplier", supplier, "default_bank_account")
	bank = (
		frappe.db.get_value("Bank Account", default_bank_account, "bank")
		if default_bank_account
		else None
	)

	watch: list[tuple[str, str, set[str]]] = [("Supplier", supplier, _SUPPLIER_WATCH_FIELDS)]
	if default_bank_account:
		watch.append(("Bank Account", default_bank_account, _BANK_ACCOUNT_WATCH_FIELDS))
	if bank:
		watch.append(("Bank", bank, _BANK_WATCH_FIELDS))

	change_msg = None
	for ref_dt, dn, fields in watch:
		rows = frappe.get_all(
			"Version",
			filters={"ref_doctype": ref_dt, "docname": dn, "creation": [">", anchor]},
			fields=["data", "creation"],
			order_by="creation desc",
		)
		for row in rows:
			try:
				changed = (json.loads(row.data or "{}")).get("changed", [])
			except (ValueError, TypeError):
				continue
			for entry in changed:
				if entry and entry[0] in fields:
					change_msg = "{0}.{1} changed at {2} (after last payment {3}).".format(
						ref_dt, entry[0], row.creation, anchor
					)
					break
			if change_msg:
				break
		if change_msg:
			break

	capture.vendor_bank_change_detected = 1 if change_msg else 0
	capture.vendor_bank_change_result = (
		change_msg or "No watched bank field changed since the last payment."
	)
	if save:
		capture.save()
	return capture


def has_approved_bank_change(supplier: str | None) -> bool:
	"""True when a Posted Update-Bank-Details request lifts the bank-change block.

	Conservative backstop (D10): a ``Supplier Master Change Request`` of type
	``Update Bank Details`` for this supplier that reached ``Posted`` and was decided
	by someone other than the requester (the spec-05 SoD rule). The full
	Treasury-Approver / non-AP-approver role rule is owned by spec 11 (see TODO).
	"""

	if not supplier:
		return False
	if not frappe.db.exists("DocType", "Supplier Master Change Request"):
		return False
	for req in frappe.get_all(
		"Supplier Master Change Request",
		filters={
			"target_supplier": supplier,
			"change_type": "Update Bank Details",
			"workflow_state": "Posted",
		},
		fields=["requested_by", "decision_by"],
	):
		# T-012 (spec 11): the lift requires a dedicated **Treasury Approver** who is
		# NOT the requester — an AP clerk must not be able to lift a bank-change block
		# even by deciding someone else's request. Both conditions must hold.
		if (
			req.decision_by
			and req.decision_by != req.requested_by
			and "Treasury Approver" in frappe.get_roles(req.decision_by)
		):
			return True
	return False


def override_three_way_match(
	capture: "APInvoiceCapture | str",
	notes: str,
	actor: str | None = None,
	save: bool = True,
) -> "APInvoiceCapture":
	"""AP override of a 3WM Exception into ``Matched (Override)``, then re-validate.

	Dedicated override fields (D6) keep the override audit separate from the
	approval-decision audit. Requires non-empty notes and an existing Exception.
	Re-runs ``validate_for_purchase_invoice`` so the capture can leave Blocked if
	3WM was its only outstanding issue — ``three_way_match_for`` will not recompute
	over the override.
	"""

	frappe.only_for(("Accounts User", "Accounts Manager", "System Manager"))

	if isinstance(capture, str):
		capture = frappe.get_doc("AP Invoice Capture", capture)

	if capture.three_way_match_status != THREE_WAY_MATCH_EXCEPTION:
		raise CaptureValidationError(
			_("Only a three-way-match Exception can be overridden; current status is {0}.").format(
				capture.three_way_match_status
			)
		)

	clean_notes = (notes or "").strip()
	if not clean_notes:
		raise CaptureValidationError(_("Override notes are required to override a 3WM Exception."))

	capture.three_way_match_status = THREE_WAY_MATCH_OVERRIDE
	capture.three_way_match_override_by = actor or frappe.session.user
	capture.three_way_match_override_at = now_datetime()
	capture.three_way_match_override_notes = clean_notes
	capture.save()

	# Re-validate so a now-cleared 3WM lets the capture leave Blocked.
	validate_for_purchase_invoice(capture, save=save)
	return capture


def refresh_anomaly_baselines() -> int:
	"""Daily scheduler: recompute the per-supplier anomaly baseline cache.

	Returns the number of supplier baselines written. Idempotent (upserts one row
	per supplier with at least one submitted PI in the lookback window).
	"""

	from erpnext.accounts.doctype.ap_closed_loop_settings.ap_closed_loop_settings import (
		get_validation_gate_config,
	)

	cfg = get_validation_gate_config()
	lookback = int(cfg["anomaly_lookback_months"])
	since = add_to_date(today(), months=-lookback)

	suppliers = frappe.get_all(
		"Purchase Invoice",
		filters={"docstatus": 1, "posting_date": [">=", since], "supplier": ["is", "set"]},
		distinct=True,
		pluck="supplier",
	)

	written = 0
	for supplier in suppliers:
		totals = frappe.get_all(
			"Purchase Invoice",
			filters={"supplier": supplier, "docstatus": 1, "posting_date": [">=", since]},
			pluck="grand_total",
		)
		values = [flt(t) for t in totals]
		if not values:
			continue
		n = len(values)
		mean = sum(values) / n
		variance = sum((v - mean) ** 2 for v in values) / n
		_upsert_anomaly_baseline(supplier, n, mean, variance ** 0.5, lookback)
		written += 1
	return written


def _upsert_anomaly_baseline(
	supplier: str, sample_count: int, mean: float, stddev: float, window_months: int
) -> None:
	"""Insert/update the single baseline row for ``supplier``."""

	if frappe.db.exists("AP Supplier Anomaly Baseline", supplier):
		doc = frappe.get_doc("AP Supplier Anomaly Baseline", supplier)
	else:
		doc = frappe.new_doc("AP Supplier Anomaly Baseline")
		doc.supplier = supplier
	doc.sample_count = sample_count
	doc.mean_grand_total = mean
	doc.stddev_grand_total = stddev
	doc.window_months = window_months
	doc.computed_at = now_datetime()
	doc.flags.ignore_permissions = True
	doc.save()


def validate_for_purchase_invoice(
	capture: "APInvoiceCapture | str",
	actor: str | None = None,
	source: str | None = None,
	save: bool = True,
) -> "APInvoiceCapture":
	"""Validate an AP-reviewed capture against existing ERPNext records.

	Behavior:
	* Requires AP-reviewed/final fields confirmed (status == Confirmed).
	* Resolves ``final_supplier`` via the 3-tier resolver (alias → exact → fuzzy);
	  records the chosen tier + confidence. Suppliers are never auto-created.
	* **Stream-aware (spec 05 §5.3):** on Stream I (or unset) an Unknown/Ambiguous
	  supplier is BLOCKING (no payable against an unknown vendor); on Stream R
	  (already-paid card spend) it is a SOFT flag — validation still passes, the raw
	  vendor string is preserved verbatim for the downstream Unmapped-Card-Spend JE.
	* **Tier 3 (gated creation):** an Unknown supplier on the blocking path may queue
	  a Draft ``Supplier Master Change Request`` when the gate is on and OCR supplier
	  confidence clears the bar — still never creating a Supplier inline.
	* Classifies purchase reference handling explicitly (PO / PR / Non-PO).
	* Records auditable outcome; does NOT create a Purchase Invoice.
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
	resolution = _resolve_supplier(final_supplier_value, stream=capture.stream)
	match_status = resolution["match_status"]
	capture.matched_supplier = resolution["matched_supplier"]
	capture.supplier_match_status = match_status
	capture.supplier_match_tier = resolution["tier"]
	capture.supplier_match_confidence = resolution["confidence"]

	purchase_ref_status = _classify_purchase_reference(
		capture.purchase_order_reference, capture.purchase_receipt_reference
	)
	capture.purchase_reference_status = purchase_ref_status

	issues: list[str] = []

	for logical_name, _proposed_field, final_field in MANDATORY_HEADER_FIELDS:
		value = capture.get(final_field)
		if value in (None, "", 0, 0.0):
			issues.append(_("Missing reviewed {0}").format(logical_name))

	# Stream-aware supplier branching (spec 05 §5.3). On Stream R an unresolved
	# supplier is SOFT (OD-05-5: Ambiguous treated like Unknown); everywhere else it
	# BLOCKS, exactly as the pre-spec-05 behaviour did.
	supplier_unresolved = match_status in (SUPPLIER_MATCH_UNKNOWN, SUPPLIER_MATCH_AMBIGUOUS)
	soft_supplier = capture.stream == STREAM_RECEIPT and supplier_unresolved
	competing = resolution.get("competing") or []

	if supplier_unresolved and not soft_supplier:
		if match_status == SUPPLIER_MATCH_UNKNOWN:
			issues.append(
				_("Supplier '{0}' is unknown — AP correction required (no auto-create).").format(
					final_supplier_value or ""
				)
			)
			# Tier 3 — may queue a gated create request (never creates a Supplier).
			_maybe_queue_supplier_create(capture, final_supplier_value)
		else:  # Ambiguous
			detail = (": " + ", ".join(competing)) if competing else ""
			issues.append(
				_(
					"Supplier '{0}' is ambiguous — multiple existing Suppliers share this name{1}."
				).format(final_supplier_value or "", detail)
			)

	# Validation gates (spec 08). Each gate records its verdict on the capture
	# (save=False — this function owns the single save below). On Stream I a failing
	# gate is appended to ``issues`` and blocks; on Stream R the verdict is recorded
	# but never blocks. The bank-change gate re-asserts at promotion time.
	three_way_match_for(capture, save=False)
	detect_amount_anomaly_for(capture, save=False)
	detect_vendor_bank_change_for(capture, save=False)

	if _is_stream_i(capture):
		if capture.three_way_match_status == THREE_WAY_MATCH_EXCEPTION:
			issues.append(
				_("Three-way match exception — invoice does not reconcile to its Purchase Order (override required).")
			)
		if capture.anomaly_status == ANOMALY_ANOMALOUS:
			# Keep the issue line short (action_required_reason is a 140-char field);
			# the full mean/stddev/z evidence lives on the anomaly_result field.
			issues.append(
				_("Amount anomaly — total is an outlier vs this supplier's recent history.")
			)
		if capture.vendor_bank_change_detected and not has_approved_bank_change(capture.matched_supplier):
			issues.append(
				_("Vendor bank details changed since last payment — an approved Update-Bank-Details request is required.")
			)

	capture.validated_by = actor or frappe.session.user
	capture.validated_at = now_datetime()
	capture.validation_source = source or VALIDATION_SOURCE_DEFAULT

	if issues:
		capture.validation_status = VALIDATION_STATUS_BLOCKED
		capture.validation_result = "; ".join(issues)
		capture.action_required = 1
		if capture.supplier_change_request:
			capture.action_required_reason = _("Pending supplier approval (request {0})").format(
				capture.supplier_change_request
			)
		else:
			# action_required_reason is a 140-char Data field; the full multi-issue
			# detail stays on validation_result (Small Text). Truncate defensively so
			# stacked gate issues (3WM + anomaly + bank-change) never raise.
			reason = _("Validation blocked: {0}").format(capture.validation_result)
			capture.action_required_reason = reason[:137] + "…" if len(reason) > 140 else reason
	else:
		capture.validation_status = VALIDATION_STATUS_VALIDATED
		if soft_supplier:
			# Stream-R soft path: preserve the raw vendor string verbatim (left on
			# final_supplier/proposed_supplier) for the Unmapped-Card-Spend JE memo
			# owned by spec 07; record the warning rather than a matched supplier.
			capture.validation_result = _(
				"Unmapped card spend — vendor '{0}' preserved as memo; posting to Unmapped Card Spend."
			).format(final_supplier_value or "")
		else:
			capture.validation_result = _(
				"Supplier matched: {0}. Purchase reference: {1}."
			).format(capture.matched_supplier, purchase_ref_status)
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


# ---------------------------------------------------------------------------
# GL Coding, Cost Center & Tax Assignment (spec 06)
# ---------------------------------------------------------------------------


def _resolve_supplier_coding(matched_supplier: "str | None") -> dict:
	"""Layer-1: the per-supplier `AP Supplier Coding Profile`, or ``{}`` if none.

	Raw reads only (no set_missing_values); empty fields are omitted so the caller
	merges them cleanly over Layer 0 / under Layer 2.
	"""

	if not matched_supplier:
		return {}
	if not frappe.db.exists("AP Supplier Coding Profile", matched_supplier):
		return {}
	p = frappe.get_doc("AP Supplier Coding Profile", matched_supplier)
	out: dict = {}
	if p.default_expense_account:
		out["expense_account"] = p.default_expense_account
	if p.default_cost_center:
		out["cost_center"] = p.default_cost_center
	if p.default_purchase_tax_template:
		out["purchase_tax_template"] = p.default_purchase_tax_template
	if p.default_payment_terms_template:
		out["payment_terms_template"] = p.default_payment_terms_template
	dims = [
		{"dimension": r.dimension, "dimension_value": r.dimension_value}
		for r in (p.default_accounting_dimensions or [])
		if r.dimension and r.dimension_value
	]
	if dims:
		out["accounting_dimensions"] = dims
	return out


def _derive_coding_from_history(
	matched_supplier: "str | None", company: "str | None" = None
) -> "tuple[dict, dict]":
	"""Layer-1.5 (spec 06 §5.3.1 / T-016): derive coding from posted-PI history.

	Inspects the supplier's most-recent **submitted** Purchase Invoices and, for each
	codable field independently (``expense_account`` / ``cost_center`` /
	``purchase_tax_template``), returns the value only when a single value covers
	``>= consensus`` of the non-empty observations AND there are ``>= min_samples`` of
	them. Returns ``(derived, ambiguous)``: ``derived`` = confidently-consistent field
	values; ``ambiguous`` = field → competing-values reason for fields whose history is
	split. Thin history (below min_samples) derives nothing and is not ambiguous (falls
	through). Pure read; no writes. Disabled / no supplier / no history → ``({}, {})``.
	"""

	if not matched_supplier:
		return {}, {}
	from erpnext.accounts.doctype.ap_closed_loop_settings.ap_closed_loop_settings import (
		get_coding_history_config,
	)

	cfg = get_coding_history_config()
	if not cfg["enabled"]:
		return {}, {}

	filters = {"supplier": matched_supplier, "docstatus": 1}
	if company or cfg["company"]:
		filters["company"] = company or cfg["company"]
	pis = frappe.get_all(
		"Purchase Invoice",
		filters=filters,
		fields=["name", "taxes_and_charges"],
		order_by="posting_date desc, creation desc",
		limit=cfg["lookback"],
	)
	if not pis:
		return {}, {}

	pi_names = [p.name for p in pis]
	items = frappe.get_all(
		"Purchase Invoice Item",
		filters={"parent": ["in", pi_names]},
		fields=["expense_account", "cost_center"],
	)
	observations = {
		"expense_account": [it.expense_account for it in items if it.expense_account],
		"cost_center": [it.cost_center for it in items if it.cost_center],
		"purchase_tax_template": [p.taxes_and_charges for p in pis if p.taxes_and_charges],
	}

	derived: dict = {}
	ambiguous: dict = {}
	for field, values in observations.items():
		if len(values) < cfg["min_samples"]:
			continue  # thin history → derive nothing (no auto-post on shaky evidence)
		counts = Counter(values)
		top_value, top_n = counts.most_common(1)[0]
		if top_n / len(values) >= cfg["consensus"]:
			derived[field] = top_value
		else:
			detail = ", ".join("{0} ({1})".format(v, n) for v, n in counts.most_common())
			ambiguous[field] = _("history split for {0}: {1}").format(field, detail)
	return derived, ambiguous


# Cost-center inference signal resolvers — pilot stubs (decision D2). The
# location→CC and card→CC maps don't exist as data yet (the Location doctype is
# not installed; there's no card registry), so these return None and the profile
# signal governs (graceful degrade). They are module-level so tests can monkeypatch
# them to exercise the multi-signal agree/conflict logic.
def _location_cost_center(receipt_location: "str | None") -> "str | None":
	return None


def _card_cost_center(card_last4: "str | None") -> "str | None":
	return None


def _infer_cost_center(
	capture: "APInvoiceCapture", supplier_profile: dict
) -> "tuple[str | None, str | None]":
	"""Return ``(cost_center, ambiguity_reason)`` (spec 06 §5.3 step 5).

	Priority of signals: receipt_location > card_last4 > profile.default_cost_center.
	A single signal, or several that AGREE, resolves to that cost center. Two+
	signals resolving to DIFFERENT cost centers is AMBIGUOUS → return
	``(None, reason)`` and write nothing (must NOT silently fall back to the
	profile default on a conflict).
	"""

	signals: list[tuple[str, str]] = []  # (label, cost_center), highest priority first
	loc_cc = _location_cost_center(capture.receipt_location) if capture.receipt_location else None
	if loc_cc:
		signals.append(("location", loc_cc))
	card_cc = _card_cost_center(capture.card_last4) if capture.card_last4 else None
	if card_cc:
		signals.append(("card", card_cc))
	profile_cc = supplier_profile.get("cost_center")
	if profile_cc:
		signals.append(("profile", profile_cc))

	if not signals:
		return None, None
	distinct = {cc for _label, cc in signals}
	if len(distinct) == 1:
		return signals[0][1], None  # all agree; highest-priority signal wins ordering
	detail = ", ".join(f"{label}={cc}" for label, cc in signals)
	return None, _("Cost-center conflict: {0}").format(detail)


def _validate_coding_tax(capture: "APInvoiceCapture", tax_template: str) -> "tuple[bool, str | None]":
	"""Validate the extracted tax against the template's computed tax (spec 06 §5.3 step 7).

	Computes expected tax as ``subtotal × Σ(template rates)`` and compares to the
	extracted ``tax_amount`` within ``CODING_TAX_TOLERANCE`` (decision D3). When
	there's no subtotal or the template can't be read, validation passes (nothing
	to check against) — absence of a checkable signal is "validated".
	"""

	subtotal = float(capture.subtotal_amount or 0.0)
	if not subtotal:
		return True, None
	try:
		tmpl = frappe.get_doc("Purchase Taxes and Charges Template", tax_template)
	except Exception:
		return True, None
	total_rate = sum(float(r.rate or 0.0) for r in (tmpl.taxes or []))
	if total_rate <= 0:
		return True, None
	expected = round(subtotal * total_rate / 100.0, 2)
	extracted = round(float(capture.tax_amount or 0.0), 2)
	if abs(expected - extracted) <= CODING_TAX_TOLERANCE:
		return True, None
	return False, _("Extracted tax {0} != template-computed tax {1}.").format(extracted, expected)


def _apply_dimensions_to_row(row, dims: "list[dict] | None") -> None:
	"""Write profile accounting dimensions onto a PI item row, guarded by has_field.

	The dimension's PI-Item custom field is created by a background job (C3) and may
	be absent on a fresh site — skip silently when the field doesn't exist (R6).
	"""

	if not dims:
		return
	for d in dims:
		ad = d.get("dimension")
		value = d.get("dimension_value")
		if not ad or not value:
			continue
		fieldname = frappe.db.get_value("Accounting Dimension", ad, "fieldname")
		if fieldname and row.meta.has_field(fieldname):
			row.set(fieldname, value)


def apply_coding_profile_for(
	capture: "APInvoiceCapture | str",
	defaults: dict | None = None,
	save: bool = True,
) -> "APInvoiceCapture":
	"""Three-layer GL-coding merge + cost-center inference + tax (spec 06 §5.3).

	Re-runnable; refuses to mutate a *submitted* Purchase Invoice. Resolves expense
	account / cost center / tax template / payment terms across Layer 0 (Settings),
	Layer 1 (the supplier's coding profile), Layer 2 (caller ``defaults``); infers a
	cost center (routing conflicts to review); validates tax; and stamps
	``coding_status`` + the ``applied_*`` audit fields. Writes coding onto an existing
	draft PI when one is present, else stages the resolved values on the capture for
	a subsequent ``promote_to_purchase_invoice`` to consume.
	"""

	if isinstance(capture, str):
		capture = frappe.get_doc("AP Invoice Capture", capture)

	# (2) Submitted-PI guard (highest severity, R3) — coding only ever mutates a draft.
	if capture.purchase_invoice:
		pi_docstatus = frappe.db.get_value("Purchase Invoice", capture.purchase_invoice, "docstatus")
		if pi_docstatus == 1:
			raise CapturePromotionError(
				_("Cannot re-code a submitted Purchase Invoice {0}.").format(capture.purchase_invoice)
			)

	# (3) Resolve the three default layers (lowest → highest).
	from erpnext.accounts.doctype.ap_closed_loop_settings.ap_closed_loop_settings import (
		get_coding_settings,
		get_promote_defaults,
	)

	merged: dict = {}
	try:
		merged.update(get_promote_defaults())  # Layer 0a: item defaults (expense/cost_center/...)
		coding_settings = get_coding_settings()
		merged["purchase_tax_template"] = coding_settings.get("purchase_tax_template")
	except Exception:
		coding_settings = {"unmapped_card_spend_account": None, "purchase_tax_template": None}
	# Layer 1.5 (spec 06 §5.3.1, T-016): the supplier's own posted-PI history — below
	# the profile + caller (they override), above Settings. Confidently-consistent
	# fields fill what no human has pinned; split fields escalate (handled below).
	history_derived, history_ambiguous = _derive_coding_from_history(capture.matched_supplier)
	for k, v in history_derived.items():
		if v is not None:
			merged[k] = v
	layer1 = _resolve_supplier_coding(capture.matched_supplier)
	for k, v in layer1.items():  # Layer 1: supplier profile
		if v is not None:
			merged[k] = v
	if defaults:  # Layer 2: caller override
		for k, v in defaults.items():
			if v is not None:
				merged[k] = v

	reasons: list[str] = []
	coding_status = CODING_STATUS_CODED

	# (4) Expense resolution (stream-aware Stream-R catch-all).
	expense = merged.get("expense_account")
	if not expense and not capture.matched_supplier and not layer1:
		expense = coding_settings.get("unmapped_card_spend_account")
		coding_status = CODING_STATUS_FLAGGED
		reasons.append(
			_("No supplier/profile — using Unmapped Card Spend account.")
			if expense
			else _("No expense account resolved (no profile, no Unmapped Card Spend account).")
		)
	capture.applied_expense_account = expense or None

	# (5) Cost-center inference (routes conflicts to review; never guesses).
	cost_center, ambiguity = _infer_cost_center(capture, {"cost_center": merged.get("cost_center")})
	if ambiguity:
		coding_status = CODING_STATUS_AMBIGUOUS
		reasons.append(ambiguity)
		capture.applied_cost_center = None
	else:
		capture.applied_cost_center = cost_center or None
		if not cost_center:
			if coding_status == CODING_STATUS_CODED:
				coding_status = CODING_STATUS_FLAGGED
			reasons.append(_("No cost center resolved."))

	# (6) Payment terms (profile override; native Supplier.payment_terms is the base).
	capture.applied_payment_terms_template = merged.get("payment_terms_template") or None

	# (7) Tax population + validation.
	tax_template = merged.get("purchase_tax_template")
	capture.applied_tax_template = tax_template or None
	if tax_template:
		ok, tax_reason = _validate_coding_tax(capture, tax_template)
		if not ok:
			coding_status = CODING_STATUS_FLAGGED
			reasons.append(tax_reason)

	# (8) History-ambiguity escalation (spec 06 §5.3.1, T-016). A field whose posted-PI
	# history is split (no consensus), that neither a profile nor the caller pinned and
	# that nothing else resolved, routes to Coding Review naming the competing values —
	# escalate only the doubtful; history never auto-posts on shaky evidence.
	pinned_keys = set(layer1.keys()) | set((defaults or {}).keys())
	_applied = {
		"expense_account": capture.applied_expense_account,
		"cost_center": capture.applied_cost_center,
		"purchase_tax_template": capture.applied_tax_template,
	}
	for field, reason in history_ambiguous.items():
		if field not in pinned_keys and not _applied.get(field):
			coding_status = CODING_STATUS_AMBIGUOUS
			reasons.append(reason)

	# (9) Apply onto an existing DRAFT PI, if any (re-code path).
	if capture.purchase_invoice:
		pi_docstatus = frappe.db.get_value("Purchase Invoice", capture.purchase_invoice, "docstatus")
		if pi_docstatus == 0:
			_apply_coding_to_draft_pi(capture, merged)

	# (10) Status / provenance.
	capture.coding_source = CODING_SOURCE_DEFAULT
	capture.coding_status = coding_status
	capture.coding_review_reason = "; ".join(reasons) if reasons else None
	if coding_status in (CODING_STATUS_AMBIGUOUS, CODING_STATUS_FLAGGED):
		capture.action_required = 1
		capture.action_required_reason = _("Coding review required: {0}").format(
			capture.coding_review_reason or ""
		)
	# Coded: do NOT stomp validation's own action_required (next action is promote).

	if save:
		capture.save()
	return capture


def _apply_coding_to_draft_pi(capture: "APInvoiceCapture", merged: dict) -> None:
	"""Write the resolved coding onto an existing docstatus==0 Purchase Invoice."""

	pi = frappe.get_doc("Purchase Invoice", capture.purchase_invoice)
	dims = merged.get("accounting_dimensions")
	for item in pi.items:
		if capture.applied_expense_account:
			item.expense_account = capture.applied_expense_account
		if capture.applied_cost_center:
			item.cost_center = capture.applied_cost_center
		_apply_dimensions_to_row(item, dims)
	if capture.applied_tax_template:
		pi.taxes_and_charges = capture.applied_tax_template
	if capture.applied_payment_terms_template:
		pi.payment_terms_template = capture.applied_payment_terms_template
	pi.flags.ignore_permissions = True
	pi.save()


def is_fully_coded(capture: "APInvoiceCapture | str") -> bool:
	"""Step-8 auto-post gate (spec 06 §5.3): expense + cost center (unambiguous) +
	tax (validated/absent) all resolved. "Without coding, nothing auto-posts."""

	if isinstance(capture, str):
		capture = frappe.get_doc("AP Invoice Capture", capture)
	if capture.coding_status in (CODING_STATUS_AMBIGUOUS, CODING_STATUS_FLAGGED):
		return False
	if not capture.applied_expense_account:
		return False
	if not capture.applied_cost_center:
		return False
	return True


# ---------------------------------------------------------------------------
# Document-type classification & branching (spec 07)
# ---------------------------------------------------------------------------

# last-4 card marker: "****1234", "xxxx1234", "ending in 1234"
_CARD_LAST4_RE = re.compile(r"(?:\*{2,}|x{2,}|ending\s+in\s+)(\d{4})", re.IGNORECASE)
_PAID_MARKER_RE = re.compile(r"\bpaid\b", re.IGNORECASE)

_DOC_TYPE_TO_STREAM = {
	DOCUMENT_TYPE_UNPAID_BILL: CLASSIFIED_STREAM_I,
	DOCUMENT_TYPE_ALREADY_PAID: CLASSIFIED_STREAM_R,
	DOCUMENT_TYPE_EMPLOYEE_REIMBURSEMENT: CLASSIFIED_STREAM_R_EMPLOYEE,
}


def _classification_text(capture: "APInvoiceCapture") -> str:
	"""Concatenated OCR/clerk text the classifier scans for a paid/card marker."""

	parts = [
		capture.source_context,
		capture.review_notes,
		capture.ocr_raw_response,
		capture.source_filename,
		capture.final_supplier_invoice_no,
		capture.proposed_supplier_invoice_no,
	]
	return " ".join(str(p) for p in parts if p)


def _detect_card_marker(text: str) -> "tuple[str | None, str | None]":
	"""Return (marker_string, last4) when the text shows an already-paid card charge."""

	m = _CARD_LAST4_RE.search(text)
	if m:
		return m.group(0), m.group(1)
	if "paid by" in text.lower() or _PAID_MARKER_RE.search(text):
		return "PAID", None
	return None, None


def _provisional_stream(capture: "APInvoiceCapture") -> "str | None":
	"""Map the spec-02 ``stream`` field onto the classifier's I/R space."""

	if capture.stream == STREAM_INVOICE:
		return CLASSIFIED_STREAM_I
	if capture.stream == STREAM_RECEIPT:
		return CLASSIFIED_STREAM_R
	return None  # Unclassified / unset


def _content_classification_confident(capture: "APInvoiceCapture") -> bool:
	"""Whether the content read is confident enough to trust over a weak intake tag
	(spec 07 §5.3 / T-017). A decisive paid/card marker is itself a confident content
	signal; otherwise the mandatory-header confidence (spec 04) must clear threshold."""

	if capture.get("card_charge_marker"):
		return True
	fields_ok, _failing = _confidence_fields_ok(capture)
	return fields_ok


def classify_document_type(
	capture: "APInvoiceCapture | str",
	override: str | None = None,
	actor: str | None = None,
	save: bool = True,
) -> "APInvoiceCapture":
	"""Step-6 classification (spec 07): route a confirmed capture to a document type.

	Heuristics (clerk ``override`` always wins): a paid/card marker → Already Paid;
	a matched supplier in the configured employee group → Employee Reimbursement;
	an unmatched supplier when an employee group IS configured → Manual Review
	(can't tell employee vs vendor); otherwise → Unpaid Bill. The classifier then
	**confirms/revises** the intake stream tag — a disagreement forces Manual Review
	and records the tuning signal. Employee/Manual-Review land the capture in the
	review queue (``status=Manual Review`` + ``action_required``).
	"""

	if isinstance(capture, str):
		capture = frappe.get_doc("AP Invoice Capture", capture)

	if capture.status not in (STATUS_CONFIRMED, STATUS_MANUAL_REVIEW):
		raise CaptureValidationError(
			_("Capture must be AP-reviewed (Confirmed) before classification; current status is {0}.").format(
				capture.status
			)
		)

	from erpnext.accounts.doctype.ap_closed_loop_settings.ap_closed_loop_settings import (
		get_already_paid_config,
	)

	reason: str | None = None
	eff_override = (override or capture.classification_override or "").strip() or None

	if eff_override:
		capture.document_type = eff_override
		capture.classification_override = eff_override
		capture.classified_stream = _DOC_TYPE_TO_STREAM.get(eff_override, "")
		capture.stream_tag_agreement = STREAM_AGREEMENT_UNCONFIRMED
		capture.classification_source = CLASSIFICATION_SOURCE_OVERRIDE
		return _finalize_classification(capture, actor, save, reason)

	emp_group = get_already_paid_config().get("employee_supplier_group")
	marker, last4 = _detect_card_marker(_classification_text(capture))

	if marker:
		capture.document_type = DOCUMENT_TYPE_ALREADY_PAID
		capture.classified_stream = CLASSIFIED_STREAM_R
		capture.card_charge_marker = marker
		capture.detected_last4 = last4
	elif emp_group and capture.matched_supplier and (
		frappe.db.get_value("Supplier", capture.matched_supplier, "supplier_group") == emp_group
	):
		capture.document_type = DOCUMENT_TYPE_EMPLOYEE_REIMBURSEMENT
		capture.classified_stream = CLASSIFIED_STREAM_R_EMPLOYEE
	elif emp_group and not capture.matched_supplier:
		# Employee distinction matters but the supplier is unresolved -> review (D-07-5).
		capture.document_type = DOCUMENT_TYPE_MANUAL_REVIEW
		capture.classified_stream = ""
		reason = _("Supplier unmatched — cannot determine employee vs vendor; manual classification required.")
	else:
		capture.document_type = DOCUMENT_TYPE_UNPAID_BILL
		capture.classified_stream = CLASSIFIED_STREAM_I

	capture.classification_source = CLASSIFICATION_SOURCE_DEFAULT

	# Confirm/revise the intake stream tag (spec 02). A disagreement → review.
	if capture.document_type != DOCUMENT_TYPE_MANUAL_REVIEW:
		provisional = _provisional_stream(capture)
		if provisional is None:
			capture.stream_tag_agreement = STREAM_AGREEMENT_UNCONFIRMED
		elif provisional == capture.classified_stream:
			capture.stream_tag_agreement = STREAM_AGREEMENT_AGREE
		else:
			capture.stream_tag_agreement = STREAM_AGREEMENT_DISAGREE
			# T-017 (spec 07 §5.3): content is the stronger signal. When opted in AND the
			# content read is confident, trust the content over the weak intake tag —
			# record the correction as telemetry (stream_mistag) and continue with NO
			# human. Only genuinely ambiguous content still escalates to Manual Review.
			from erpnext.accounts.doctype.ap_closed_loop_settings.ap_closed_loop_settings import (
				is_classification_trust_content_enabled,
			)

			if is_classification_trust_content_enabled() and _content_classification_confident(capture):
				_safe_emit_review_event(
					capture,
					action_taken=REVIEW_ACTION_CLASSIFIED_OTHER,
					root_cause_tag=ROOT_CAUSE_STREAM_MISTAG,
					exception_reason_code="stream_mistag",
					note="intake tagged {0}, confident content read {1} — trusted content (no halt)".format(
						provisional, capture.classified_stream
					),
				)
				# document_type / classified_stream stand; reason stays None → no halt.
			else:
				reason = _(
					"Stream conflict: intake tagged {0}, classifier read {1} ({2}) — manual classification required."
				).format(provisional, capture.classified_stream, capture.card_charge_marker or capture.document_type)
				capture.document_type = DOCUMENT_TYPE_MANUAL_REVIEW
				capture.classified_stream = ""
	else:
		capture.stream_tag_agreement = STREAM_AGREEMENT_UNCONFIRMED

	return _finalize_classification(capture, actor, save, reason)


def _finalize_classification(
	capture: "APInvoiceCapture", actor: str | None, save: bool, reason: str | None
) -> "APInvoiceCapture":
	capture.classified_at = now_datetime()
	capture.classified_by = actor or frappe.session.user
	if not capture.classification_source:
		capture.classification_source = CLASSIFICATION_SOURCE_DEFAULT

	if capture.document_type in (DOCUMENT_TYPE_MANUAL_REVIEW, DOCUMENT_TYPE_EMPLOYEE_REIMBURSEMENT):
		capture.status = STATUS_MANUAL_REVIEW
		capture.action_required = 1
		if capture.document_type == DOCUMENT_TYPE_EMPLOYEE_REIMBURSEMENT:
			capture.action_required_reason = _(
				"Employee reimbursement — the Expense Claim path needs the hrms app (not installed). Manual handling required."
			)
		else:
			capture.action_required_reason = reason or _("Manual classification required.")
	# Unpaid Bill / Already Paid: leave status Confirmed; downstream steps proceed.

	if save:
		capture.save()
	return capture


def _build_already_paid_voucher(capture: "APInvoiceCapture", defaults: dict | None) -> "Document":
	"""The SINGLE swap point for the already-paid posting mechanism (D-07-1).

	**Locked = Option C (PI is_paid=1):** build a Purchase Invoice marked paid — one
	submitted PI posts the invoice legs (DR expense / CR supplier) plus the is-paid
	payment legs (DR supplier / CR bank) via make_payment_gl_entries, netting the
	supplier to zero while keeping it visible in spend-by-supplier/AP reports, and
	reusing the existing promote_to_purchase_invoice mapping (adds only is_paid /
	cash_bank_account / paid_amount). Keep the A/B/C choice ONLY here so switching to
	a direct Journal Entry (Option A) or PI+Clearing (Option B) is a one-function
	change with no caller impact.
	"""

	return promote_to_purchase_invoice(capture, defaults=defaults, _already_paid=True)


def promote_already_paid(
	capture: "APInvoiceCapture | str",
	actor: str | None = None,
	defaults: dict | None = None,
	save: bool = True,
) -> "Document":
	"""Promote an 'Already Paid' (Stream R) capture into its posting voucher (spec 07).

	Option C builds a paid Purchase Invoice. No approval and no separate payment hop —
	the money already moved; closure is reconciliation-only (specs 13/14).
	"""

	if isinstance(capture, str):
		capture = frappe.get_doc("AP Invoice Capture", capture)

	if capture.document_type != DOCUMENT_TYPE_ALREADY_PAID:
		raise CapturePromotionError(
			_("Already-paid promotion requires document_type 'Already Paid'; current is {0}.").format(
				capture.document_type or "(unset)"
			)
		)
	if capture.promotion_status == PROMOTION_STATUS_PROMOTED and capture.purchase_invoice:
		raise CapturePromotionError(
			_("Capture has already been promoted to {0}.").format(capture.purchase_invoice)
		)

	from erpnext.accounts.doctype.ap_closed_loop_settings.ap_closed_loop_settings import (
		get_already_paid_config,
	)

	paid_from = (defaults or {}).get("paid_from_account") or get_already_paid_config().get(
		"paid_from_account"
	)
	if not paid_from:
		raise CapturePromotionError(
			_(
				"Cannot post an already-paid receipt: no paid-from (Credit Card Clearing) account "
				"is configured in AP Closed Loop Settings."
			)
		)

	return _build_already_paid_voucher(capture, defaults)


def promote_to_purchase_invoice(
	capture: "APInvoiceCapture | str",
	actor: str | None = None,
	defaults: dict | None = None,
	save: bool = True,
	_already_paid: bool = False,
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

	# Document-type guard (spec 07). The standard (Unpaid Bill) path refuses an
	# Already-Paid capture; the already-paid path (_already_paid=True, via
	# _build_already_paid_voucher) requires it. The guard only fires when
	# document_type is set, so pre-spec-07 / unclassified captures still promote.
	if not _already_paid:
		if capture.document_type and capture.document_type != DOCUMENT_TYPE_UNPAID_BILL:
			raise CapturePromotionError(
				_("Capture document_type is {0}; only 'Unpaid Bill' promotes to a standard Purchase Invoice.").format(
					capture.document_type
				)
			)
	elif capture.document_type != DOCUMENT_TYPE_ALREADY_PAID:
		raise CapturePromotionError(
			_("Already-paid promotion requires document_type 'Already Paid'; current is {0}.").format(
				capture.document_type or "(unset)"
			)
		)

	# The already-paid path skips the Stream-I validation gate (PI-specific PO/PR
	# logic); supplier resolution still runs upstream and is required below.
	if not _already_paid and capture.validation_status != VALIDATION_STATUS_VALIDATED:
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

	# Bank-change block (spec 08). Re-assert at promotion time so a bank change made
	# AFTER a clean validation is still caught (the stored flag may be stale). A
	# detected change blocks promotion on the Stream-I path until an approved
	# Update-Bank-Details request lifts it. The already-paid (Stream R) path is
	# exempt — those funds already left.
	if not _already_paid and _is_stream_i(capture):
		detect_vendor_bank_change_for(capture, save=False)
	if (
		not _already_paid
		and _is_stream_i(capture)
		and capture.vendor_bank_change_detected
		and not has_approved_bank_change(capture.matched_supplier)
	):
		raise CapturePromotionError(
			_(
				"Vendor bank details changed since the last payment to {0}; an approved "
				"Update-Bank-Details request is required before this capture can be promoted."
			).format(capture.matched_supplier)
		)

	if capture.promotion_status == PROMOTION_STATUS_PROMOTED and capture.purchase_invoice:
		raise CapturePromotionError(
			_("Capture has already been promoted to Purchase Invoice {0}.").format(
				capture.purchase_invoice
			)
		)

	d = _coalesce_defaults(defaults)

	# Spec-06 coding: values resolved by apply_coding_profile_for and staged on the
	# capture take precedence over the raw Settings defaults when present (the caller
	# `defaults` dict still wins over both, via `d`).
	coded_expense = capture.applied_expense_account or None
	coded_cost_center = capture.applied_cost_center or None
	coding_dims = _resolve_supplier_coding(capture.matched_supplier).get("accounting_dimensions")

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

	default_item = d.get("item_code", "_Test Item")
	if capture.line_items:
		# Spec 04 line-aware path: one PI item per extracted capture line, mapping
		# po_reference -> PI Item.purchase_order and pr_reference -> purchase_receipt
		# (the three-way-match join surface for spec 08). po_detail/pr_detail (the
		# specific PO/PR child rowname) are NOT set — OCR gives header-PO granularity
		# only. A line with no item identity falls back to the default item_code.
		for line in capture.line_items:
			line_qty = float(line.qty or 1) or 1.0
			# Prefer the extracted amount; fall back to qty*rate, then the rate.
			line_amount = float(line.amount or 0.0)
			line_rate = float(line.rate or 0.0)
			if not line_rate and line_amount and line_qty:
				line_rate = round(line_amount / line_qty, 2)
			item_row = {
				"item_code": default_item,
				"qty": line_qty,
				"rate": line_rate,
				"description": line.description or None,
			}
			if d.get("uom"):
				item_row["uom"] = d["uom"]
				item_row["stock_uom"] = d["uom"]
			if d.get("warehouse"):
				item_row["warehouse"] = d["warehouse"]
			# GL coding precedence (spec 06): per-line value > capture.applied_*
			# (resolved by apply_coding_profile_for) > Settings default.
			eff_expense = line.expense_account or coded_expense or d.get("expense_account")
			eff_cc = line.cost_center or coded_cost_center or d.get("cost_center")
			if eff_expense:
				item_row["expense_account"] = eff_expense
			if eff_cc:
				item_row["cost_center"] = eff_cc
			if line.po_reference:
				item_row["purchase_order"] = line.po_reference
			if line.pr_reference:
				item_row["purchase_receipt"] = line.pr_reference
			row = pi.append("items", item_row)
			_apply_dimensions_to_row(row, coding_dims)

		# Reconciliation guard (decision D1): surface a mismatch rather than
		# silently mutating the ledger. A bad line read must not create a payable.
		#
		# Tax-aware (correction found via real-Anthropic e2e on a 19%-VAT invoice):
		# invoice lines are PRE-tax and sum to the subtotal, while final_total_amount
		# is the TAX-INCLUSIVE grand total — so a naive sum(lines) == total check
		# wrongly blocks every taxed invoice. Accept EITHER convention:
		#   * tax-exclusive lines + separate tax:  sum(lines) + tax  == total
		#   * tax-inclusive lines:                 sum(lines)        == total
		# A genuine misread (lines reconcile under neither) still raises.
		line_total = round(sum(float(li.amount or 0.0) for li in capture.line_items), 2)
		tax_total = round(float(capture.tax_amount or 0.0), 2)
		final_total = round(float(capture.final_total_amount or 0.0), 2)
		reconciles = (
			abs(line_total - final_total) <= 0.01
			or abs(line_total + tax_total - final_total) <= 0.01
		)
		if not reconciles:
			capture.action_required = 1
			capture.action_required_reason = _(
				"Line items total {0} (+ tax {1}) does not reconcile to the invoice "
				"total {2}. Correct the lines before promoting."
			).format(line_total, tax_total, final_total)
			if save:
				capture.save()
			raise CapturePromotionError(
				_(
					"Cannot promote: line items sum to {0} (+ tax {1}) but the invoice "
					"total is {2} (off by more than 0.01)."
				).format(line_total, tax_total, final_total)
			)
	else:
		# Header-line fallback (UNCHANGED): a single header-level row.
		rate = float(capture.final_total_amount or 0.0)
		qty = float(d.get("qty", 1) or 1)
		item_row = {
			"item_code": default_item,
			"qty": qty,
			"rate": rate,
		}
		if d.get("uom"):
			item_row["uom"] = d["uom"]
			item_row["stock_uom"] = d["uom"]
		if d.get("warehouse"):
			item_row["warehouse"] = d["warehouse"]
		# GL coding (spec 06): capture.applied_* (resolved by apply_coding_profile_for)
		# wins over the Settings default for the single header line too.
		eff_expense = coded_expense or d.get("expense_account")
		eff_cc = coded_cost_center or d.get("cost_center")
		if eff_expense:
			item_row["expense_account"] = eff_expense
		if eff_cc:
			item_row["cost_center"] = eff_cc
		row = pi.append("items", item_row)
		_apply_dimensions_to_row(row, coding_dims)

	# Header-level coding staged by apply_coding_profile_for (spec 06): tax template
	# (triggers the native taxes fetch) and payment terms.
	if capture.applied_tax_template:
		pi.taxes_and_charges = capture.applied_tax_template
	if capture.applied_payment_terms_template:
		pi.payment_terms_template = capture.applied_payment_terms_template

	# Already-paid (Stream R, spec 07 Option C): mark the PI paid so a single
	# submitted PI books the invoice legs AND the payment legs (DR supplier / CR
	# bank via make_payment_gl_entries). The supplier nets to zero but stays visible
	# in spend-by-supplier/AP. Left DRAFT here (parity with the unpaid path).
	if _already_paid:
		from erpnext.accounts.doctype.ap_closed_loop_settings.ap_closed_loop_settings import (
			get_already_paid_config,
		)

		paid_from = (defaults or {}).get("paid_from_account") or get_already_paid_config().get(
			"paid_from_account"
		)
		pi.is_paid = 1
		pi.cash_bank_account = paid_from
		pi.paid_amount = flt(capture.final_total_amount)

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


# ---------------------------------------------------------------------------
# AP Review instrumentation + reject/reopen (spec 10)
# ---------------------------------------------------------------------------
#
# emit_review_event is the shared step-9 telemetry primitive every clerk/system
# review action calls exactly once. reject_capture / reopen_capture are the
# clerk-facing transition pair the capture previously lacked (status=Rejected is a
# declared option that nothing assigned). All three write through doc.save() /
# doc.append() so the capture's track_changes Version row captures the mutation.


def emit_review_event(
	capture: "APInvoiceCapture | str",
	*,
	action_taken: str,
	root_cause_tag: str | None = None,
	exception_reason_code: str | None = None,
	fields_changed: dict | None = None,
	time_to_resolve_seconds: int | None = None,
	note: str | None = None,
	clerk: str | None = None,
) -> str:
	"""Append one ``AP Review Event`` row (spec 10 §5.3). Returns its name.

	The shared instrumentation primitive — other specs import and call it on the
	success branch of a review action. Intentionally NOT idempotent (one event per
	action) and NOT whitelisted (internal only). ``fields_changed`` is serialised to
	a JSON string; ``time_to_resolve_seconds`` defaults to seconds since the capture
	was created (v1 — conflates queue wait with active handling, decision D-8).
	Inserted with ``ignore_permissions=True`` (D-6) so telemetry stays
	append-only-by-controller and clerks need no create grant.
	"""

	if isinstance(capture, str):
		capture = frappe.get_doc("AP Invoice Capture", capture)

	if time_to_resolve_seconds is None and capture.get("creation"):
		try:
			time_to_resolve_seconds = int(
				(now_datetime() - get_datetime(capture.creation)).total_seconds()
			)
		except Exception:
			time_to_resolve_seconds = None

	event = frappe.new_doc("AP Review Event")
	event.capture = capture.name
	event.action_taken = action_taken
	event.root_cause_tag = root_cause_tag or None
	event.exception_reason_code = exception_reason_code
	event.fields_changed = (
		json.dumps(fields_changed, default=str, sort_keys=True) if fields_changed else None
	)
	event.time_to_resolve_seconds = time_to_resolve_seconds
	event.note = note
	event.clerk = clerk or frappe.session.user
	event.created = now_datetime()
	event.insert(ignore_permissions=True)
	return event.name


def _safe_emit_review_event(capture, **kwargs) -> "str | None":
	"""Telemetry-safe wrapper for instrumenting existing flows (spec 10).

	Used at secondary call sites (confirm / manager reject) where a logging hiccup
	must never break the clerk's primary action. Guarded by the doctype's existence
	and a try/except. The dedicated reject/reopen paths call ``emit_review_event``
	directly (the event is integral to those actions)."""

	if not frappe.db.exists("DocType", "AP Review Event"):
		return None
	try:
		return emit_review_event(capture, **kwargs)
	except Exception:
		frappe.log_error(title="AP Review Event emission failed", message=frappe.get_traceback())
		return None


def reject_capture(
	capture: "APInvoiceCapture | str",
	reason: str,
	actor: str | None = None,
	root_cause_tag: str | None = None,
	save: bool = True,
) -> "APInvoiceCapture":
	"""Clerk bounce of a non-promoted capture back to the vendor (spec 10 §5.3).

	Sets ``status = Rejected`` (terminal-quiet: ``action_required = 0``), appends a
	``Rejected`` row to ``rejection_log``, and emits one ``AP Review Event``. Refuses
	a promoted capture (handed off to the PI lifecycle — that reject is spec 11's
	Workflow) and an already-rejected one (reopen first)."""

	if isinstance(capture, str):
		capture = frappe.get_doc("AP Invoice Capture", capture)

	if capture.promotion_status == PROMOTION_STATUS_PROMOTED:
		raise CaptureValidationError(
			_("A promoted capture cannot be rejected at the capture level — it is in the Purchase Invoice lifecycle.")
		)
	if capture.status == STATUS_REJECTED:
		raise CaptureValidationError(_("Capture is already Rejected; reopen it first."))

	reason = (reason or "").strip()
	if not reason:
		raise CaptureValidationError(_("A rejection reason is required."))

	from_status = capture.status
	actor = actor or frappe.session.user

	capture.status = STATUS_REJECTED
	capture.action_required = 0
	capture.action_required_reason = None
	capture.append(
		"rejection_log",
		{
			"action": REJECTION_ACTION_REJECTED,
			"reason": reason,
			"from_status": from_status,
			"to_status": STATUS_REJECTED,
			"actor": actor,
			"timestamp": now_datetime(),
		},
	)

	emit_review_event(
		capture,
		action_taken=REVIEW_ACTION_REJECTED,
		root_cause_tag=root_cause_tag,
		exception_reason_code=from_status,
		note=reason,
		clerk=actor,
	)

	if save:
		capture.save()
	return capture


def reopen_capture(
	capture: "APInvoiceCapture | str",
	reason: str,
	actor: str | None = None,
	save: bool = True,
) -> "APInvoiceCapture":
	"""Reopen a Rejected capture, restoring the stage it was rejected from (spec 10 §5.3).

	Deterministic restore: reads the most-recent ``Rejected`` row's ``from_status``
	(never hardcodes ``Pending Review``). Sets ``action_required = 1`` (a reopened
	item needs work), appends a ``Reopened`` row, and emits an ``AP Review Event``
	(``classified_other`` + a 'reopened' note — the Select has no ``reopened`` value
	by decision D-2)."""

	if isinstance(capture, str):
		capture = frappe.get_doc("AP Invoice Capture", capture)

	if capture.status != STATUS_REJECTED:
		raise CaptureValidationError(
			_("Only a Rejected capture can be reopened; current status is {0}.").format(
				capture.status
			)
		)

	reason = (reason or "").strip()
	if not reason:
		raise CaptureValidationError(_("A reopen reason is required."))

	restore_to = STATUS_PENDING_REVIEW
	for row in reversed(capture.rejection_log or []):
		if row.action == REJECTION_ACTION_REJECTED and row.from_status:
			restore_to = row.from_status
			break

	actor = actor or frappe.session.user
	capture.status = restore_to
	capture.action_required = 1
	capture.action_required_reason = _("Reopened for correction")
	capture.append(
		"rejection_log",
		{
			"action": REJECTION_ACTION_REOPENED,
			"reason": reason,
			"from_status": STATUS_REJECTED,
			"to_status": restore_to,
			"actor": actor,
			"timestamp": now_datetime(),
		},
	)

	emit_review_event(
		capture,
		action_taken=REVIEW_ACTION_CLASSIFIED_OTHER,
		note="reopened: {0}".format(reason),
		clerk=actor,
	)

	if save:
		capture.save()
	return capture


@frappe.whitelist()
def reject_capture_for(capture: str, reason: str, root_cause_tag: str | None = None) -> str:
	"""Whitelisted clerk reject (spec 10). Returns the capture name."""

	doc = reject_capture(capture, reason=reason, root_cause_tag=(root_cause_tag or None))
	return doc.name


@frappe.whitelist()
def reopen_capture_for(capture: str, reason: str) -> str:
	"""Whitelisted clerk reopen (spec 10). Resumes the cascade for the restored stage."""

	doc = reopen_capture(capture, reason=reason)
	doc._kick_next_step()
	return doc.name


@frappe.whitelist()
def get_rejection_log_for(capture: str) -> list[dict]:
	"""Whitelisted read of a capture's reject/reopen trail (spec 10)."""

	doc = frappe.get_doc("AP Invoice Capture", capture)
	return [
		{
			"action": r.action,
			"reason": r.reason,
			"from_status": r.from_status,
			"to_status": r.to_status,
			"actor": r.actor,
			"timestamp": r.timestamp,
		}
		for r in (doc.rejection_log or [])
	]


# ---------------------------------------------------------------------------
# Confidence-based routing (spec 09) — combined amount + confidence + flag signal
# ---------------------------------------------------------------------------
#
# Replaces the amount-only auto-approve decision with a three-axis evaluator. A
# clean+confident capture auto-advances (Auto Approved at/under threshold, Pending
# Manager over it, exactly as before); any low-confidence field or open validation
# flag parks it at ``Needs Review`` with the specific failing signal named and a
# (guarded) AP Review Event emitted for spec-10 observability.
#
# Stream-R reconciliation: an Already-Paid (Stream R) capture posts via spec 07's
# promote_already_paid (PI is_paid) and the cascade SKIPS approval entirely, so it
# never reaches request_approval — the spec's "Stream R auto-post, no approval" row
# is realised upstream, and this evaluator stays stream-agnostic (it only ever sees
# Stream-I / unclassified captures that promoted to a standard PI).

RoutingDecision = namedtuple(
	"RoutingDecision",
	["amount_ok", "fields_ok", "flags_ok", "resolved_threshold", "failing_field", "failing_flag"],
)


def _residual_gate_flag(capture: "APInvoiceCapture") -> "str | None":
	"""First open spec-08 gate failure on a capture, or None.

	Normally empty at routing time (a failed gate blocks validation upstream), but
	read the gate fields directly so the evaluator is self-contained and catches an
	edge state where a capture reached routing with an open flag."""

	if capture.get("three_way_match_status") == THREE_WAY_MATCH_EXCEPTION:
		return _("three-way match exception")
	if capture.get("anomaly_status") == ANOMALY_ANOMALOUS:
		return _("amount anomaly")
	if capture.get("vendor_bank_change_detected") and not has_approved_bank_change(
		capture.matched_supplier
	):
		return _("vendor bank change since last payment")
	return None


def _confidence_fields_ok(capture: "APInvoiceCapture") -> "tuple[bool, str | None]":
	"""The shared confidence axis — every mandatory header field is above threshold.

	Used by BOTH the approval seam (``_evaluate_routing_signals``) and the OCR-confirm
	seam (``_evaluate_confirm_signals``) so there is **one** copy of the gate (spec 09
	§5.6). A *populated* ``field_confidences`` table with a missing or below-threshold
	mandatory row **fails closed** (returns the field name). An **empty** table (no
	extraction confidence at all — e.g. a manually built capture) degrades to pass.
	"""

	rows = capture.get("field_confidences") or []
	if not rows:
		return True, None
	by_name = {row.field_name: row for row in rows}
	for logical_name, _proposed, _final in MANDATORY_HEADER_FIELDS:
		row = by_name.get(logical_name)
		if row is None or not row.is_above_threshold:
			return False, logical_name
	return True, None


ConfirmDecision = namedtuple("ConfirmDecision", ["fields_ok", "flags_ok", "failing_field", "failing_flag"])


def _evaluate_confirm_signals(capture: "APInvoiceCapture") -> ConfirmDecision:
	"""Pure read of the OCR-confirm seam gate (spec 04/09 §5.6, T-015). No writes.

	Whether a freshly-extracted capture is clean+confident enough to auto-confirm the
	OCR proposal and skip the human pause at ``Proposed``. Same ``fields_ok`` confidence
	logic as the approval seam (shared ``_confidence_fields_ok``) but **no amount axis**
	(there is no posting/authorization decision at confirm time) and a confirm-appropriate
	``flags_ok``: validation has not run yet at ``Proposed``, so the flag check is the
	residual spec-08 gate guard only (normally clean here; catches an edge state). Any
	failure → fall back to the human review pause (escalate only the doubtful).
	"""

	fields_ok, failing_field = _confidence_fields_ok(capture)
	failing_flag = _residual_gate_flag(capture)
	return ConfirmDecision(fields_ok, failing_flag is None, failing_field, failing_flag)


def _evaluate_routing_signals(
	capture: "APInvoiceCapture", threshold: float | None = None, source: str | None = None
) -> RoutingDecision:
	"""Pure read of the three routing axes (spec 09 §5.3). No writes.

	* ``amount_ok`` — ``final_total_amount <= resolved auto_post_amount_threshold``.
	* ``fields_ok`` — every ``MANDATORY_HEADER_FIELDS`` confidence row is above
	  threshold (spec 04's pre-computed ``is_above_threshold``; decision D-8), via the
	  shared ``_confidence_fields_ok``.
	* ``flags_ok`` — ``validation_status == Validated`` AND no residual hard spec-08
	  gate failure (``failing_flag`` names the first one).
	"""

	resolved_threshold, _src = _resolve_approval_threshold(threshold, source)
	amount = float(capture.final_total_amount or 0.0)
	amount_ok = amount <= resolved_threshold

	fields_ok, failing_field = _confidence_fields_ok(capture)

	flags_ok = capture.validation_status == VALIDATION_STATUS_VALIDATED
	failing_flag = None
	if not flags_ok:
		failing_flag = _("validation not passed ({0})").format(
			capture.validation_status or VALIDATION_STATUS_NOT_VALIDATED
		)
	else:
		residual = _residual_gate_flag(capture)
		if residual:
			flags_ok = False
			failing_flag = residual

	return RoutingDecision(
		amount_ok, fields_ok, flags_ok, resolved_threshold, failing_field, failing_flag
	)


def _emit_review_event(
	capture: "APInvoiceCapture",
	axis: str,
	failing_field: "str | None" = None,
	failing_flag: "str | None" = None,
	amount: "float | None" = None,
	threshold: "float | None" = None,
) -> "str | None":
	"""Route-to-review telemetry for spec 09, on the canonical spec-10 primitive.

	A confidence/flag park IS a surfaced exception — record it as one ``AP Review
	Event`` (``classified_other``) tagged with the mapped root cause so the spec-10
	'Top step-9 root causes' report can quantify whether to loosen a threshold. Stays
	guarded by ``frappe.db.exists`` so routing never fails if spec 10's doctype is
	absent (AC-09-14)."""

	if not frappe.db.exists("DocType", "AP Review Event"):
		return None
	root_cause = (
		ROOT_CAUSE_CONFIDENCE_TOO_TIGHT
		if axis == ROUTING_AXIS_CONFIDENCE
		else ROOT_CAUSE_POLICY_VIOLATION
	)
	try:
		return emit_review_event(
			capture,
			action_taken=REVIEW_ACTION_CLASSIFIED_OTHER,
			root_cause_tag=root_cause,
			exception_reason_code=failing_field or failing_flag,
			note="routed to review (amount {0} vs threshold {1})".format(amount, threshold),
		)
	except Exception:
		frappe.log_error(
			title="AP Review Event emission failed", message=frappe.get_traceback()
		)
		return None


def resolve_approver_role(capture: "APInvoiceCapture") -> str:
	"""The approver Role this capture routes to (spec 11 §5.2).

	Pilot: the threshold-driven default (``Accounts Manager``). The optional
	``AP Approval Matrix`` (department / cost-center / supplier-risk routing) is a
	deferred upgrade (spec 11 D-2), so this returns the default and **never raises**
	on an empty/absent matrix (AC-11-8). When the matrix lands, this resolves the
	highest-priority matching row's ``approver_role`` here."""

	return MANAGER_APPROVAL_ROLE_DEFAULT


def request_approval(
	capture: "APInvoiceCapture | str",
	threshold: float | None = None,
	source: str | None = None,
	actor: str | None = None,
	approver_role: str | None = None,
	save: bool = True,
) -> "APInvoiceCapture":
	"""Route a promoted capture through Phase 1 approval controls (spec 09).

	Combined-signal routing: a clean+confident capture at/under threshold is
	Auto Approved, over threshold goes to Pending Manager (unchanged amount lanes);
	a low-confidence field or an open validation flag parks the capture at
	``Needs Review`` with the failing signal named and a guarded AP Review Event
	emitted. No payment artifact is created here.
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

	# Spec 09 — confidence + flag axes gate WHETHER the capture can auto-advance at
	# all; the amount axis below gates WHICH auto-advance lane. A failing
	# confidence/flag axis parks at Needs Review (the formalised, named version of
	# the old silent stall) and emits a guarded AP Review Event.
	decision = _evaluate_routing_signals(capture, threshold=threshold, source=source)
	if not (decision.fields_ok and decision.flags_ok):
		if not decision.fields_ok:
			axis = ROUTING_AXIS_CONFIDENCE
			reason = _("Routed to review: low confidence on field '{0}'").format(
				decision.failing_field
			)
		else:
			axis = ROUTING_AXIS_VALIDATION_FLAG
			reason = _("Routed to review: open validation flag '{0}'").format(
				decision.failing_flag
			)
		capture.approval_status = APPROVAL_STATUS_NEEDS_REVIEW
		capture.routing_reason = reason
		capture.assigned_approver_role = None
		capture.decision_by = None
		capture.decision_at = None
		capture.decision_notes = None
		capture.payment_readiness = PAYMENT_READINESS_NOT_READY
		capture.action_required = 1
		capture.action_required_reason = reason[:140]
		_emit_review_event(
			capture,
			axis,
			failing_field=decision.failing_field,
			failing_flag=decision.failing_flag,
			amount=amount,
			threshold=resolved_threshold,
		)
		if save:
			capture.save()
		return capture

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


def reroute_after_review(
	capture: "APInvoiceCapture | str",
	actor: str | None = None,
	save: bool = True,
) -> "APInvoiceCapture":
	"""Sanctioned re-route of a Needs-Review capture once its flags are cleared (spec 09 D-4).

	The normal ``request_approval`` guard refuses a capture whose ``approval_status``
	is already set, which would block the flagged → cleared → routed two-hop. This
	distinct entrypoint (keeping that double-route protection intact for the normal
	path) re-runs the evaluator, and only when the capture is now clean+confident
	resets ``approval_status`` to ``Not Required`` and routes again. Raises
	``CaptureApprovalError`` if the capture is not in Needs Review or is still
	flagged/low-confidence."""

	if isinstance(capture, str):
		capture = frappe.get_doc("AP Invoice Capture", capture)

	if capture.approval_status != APPROVAL_STATUS_NEEDS_REVIEW:
		raise CaptureApprovalError(
			_("Re-route only applies to a capture in Needs Review; current status is {0}.").format(
				capture.approval_status or APPROVAL_STATUS_NOT_REQUIRED
			)
		)

	decision = _evaluate_routing_signals(capture)
	if not (decision.fields_ok and decision.flags_ok):
		problem = decision.failing_field or decision.failing_flag or _("unresolved flags")
		raise CaptureApprovalError(
			_("Capture not eligible for re-route: {0}").format(problem)
		)

	capture.approval_status = APPROVAL_STATUS_NOT_REQUIRED
	capture.routing_reason = None
	return request_approval(capture, actor=actor, save=save)


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

	# Segregation of duties (spec 11 — THE control this spec exists to add). A role
	# check alone can't stop a manager from approving an invoice they themselves
	# entered/coded/promoted. Block self-APPROVAL above threshold: the approver must
	# not be the recorded preparer (reviewed_by = who confirmed extraction;
	# validated_by = who validated/promoted). Administrator is the audited break-glass
	# exception (D-7 a; also the all-Administrator test harness). Self-reject is allowed.
	approver = actor or frappe.session.user
	if approve and approver != "Administrator":
		preparers = {capture.reviewed_by, capture.validated_by} - {None, ""}
		if approver in preparers:
			raise CaptureApprovalError(
				_(
					"Segregation of duties: {0} prepared this document and may not also approve it above "
					"threshold — a different approver is required."
				).format(approver)
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
		# Spec 10 instrumentation: a manager payment-reject emits one AP Review Event.
		# Stream-R gating (§5.2/AC-10-14): the already-paid receipt has no approval to
		# reject, so an approval/rejection root cause must not appear on Stream R.
		if capture.stream != STREAM_RECEIPT:
			_safe_emit_review_event(
				capture,
				action_taken=REVIEW_ACTION_REJECTED,
				root_cause_tag=ROOT_CAUSE_POLICY_VIOLATION,
				exception_reason_code="manager_reject",
				note=notes,
				clerk=actor or frappe.session.user,
			)

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
		"gates": {
			"three_way_match": {
				"status": capture.three_way_match_status,
				"result": json.loads(capture.three_way_match_result or "{}"),
				"checked_at": capture.three_way_match_checked_at,
				"override_by": capture.three_way_match_override_by,
				"override_at": capture.three_way_match_override_at,
				"override_notes": capture.three_way_match_override_notes,
			},
			"anomaly": {
				"status": capture.anomaly_status,
				"result": capture.anomaly_result,
				"checked_at": capture.anomaly_checked_at,
			},
			"vendor_bank_change": {
				"detected": bool(capture.vendor_bank_change_detected),
				"result": capture.vendor_bank_change_result,
				"checked_at": capture.vendor_bank_change_checked_at,
			},
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
def resolve_supplier_for(capture: str, stream: str | None = None) -> str:
	"""Form-button wrapper: re-run the 3-tier resolver + validation for a capture.

	``stream`` (string-normalized) overrides the capture's stored stream for this
	run when provided — letting a reviewer test the Stream-R soft path vs the
	Stream-I blocking path. Returns the capture name (spec 05 §5.2).
	"""

	doc = frappe.get_doc("AP Invoice Capture", capture)
	stream = (stream or "").strip() or None
	if stream and stream in (STREAM_RECEIPT, STREAM_INVOICE, STREAM_UNCLASSIFIED):
		doc.stream = stream
	doc = validate_for_purchase_invoice(doc)
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
def classify_document_type_for(capture: str, override: str | None = None) -> str:
	"""Whitelisted entrypoint for Step-6 document-type classification (spec 07).
	`override` (clerk) always wins. Returns capture.document_type; resumes the cascade."""

	doc = classify_document_type(capture, override=(override or None))
	doc._kick_next_step()
	return doc.document_type


@frappe.whitelist()
def promote_already_paid_for(capture: str, defaults: str | dict | None = None) -> str:
	"""Whitelisted entrypoint for the Stream-R already-paid posting (spec 07)."""

	parsed = json.loads(defaults) if isinstance(defaults, str) and defaults else (defaults or None)
	pi = promote_already_paid(capture, defaults=parsed)
	cap = frappe.get_doc("AP Invoice Capture", capture if isinstance(capture, str) else capture.name)
	cap._kick_next_step()
	return pi.name


@frappe.whitelist()
def three_way_match_for_capture(capture: str) -> str:
	"""Whitelisted re-run of the three-way-match gate (spec 08). Returns the status."""

	doc = three_way_match_for(capture)
	return doc.three_way_match_status


@frappe.whitelist()
def detect_amount_anomaly_for_capture(capture: str) -> str:
	"""Whitelisted re-run of the amount-anomaly gate (spec 08). Returns the status."""

	doc = detect_amount_anomaly_for(capture)
	return doc.anomaly_status


@frappe.whitelist()
def detect_vendor_bank_change_for_capture(capture: str) -> int:
	"""Whitelisted re-run of the vendor bank-change gate (spec 08). Returns 0/1."""

	doc = detect_vendor_bank_change_for(capture)
	return int(doc.vendor_bank_change_detected or 0)


@frappe.whitelist()
def override_three_way_match_for(capture: str, notes: str) -> str:
	"""Whitelisted AP override of a 3WM Exception (spec 08). Re-validates; returns status."""

	doc = override_three_way_match(capture, notes=notes)
	return doc.three_way_match_status


@frappe.whitelist()
def apply_coding_profile_for_ui(capture: str, defaults: str | dict | None = None) -> str:
	"""Whitelisted entrypoint for the GL coding step (spec 06). Normalizes the
	`defaults` arg (JSON string or dict), applies coding, resumes the cascade."""

	parsed = json.loads(defaults) if isinstance(defaults, str) and defaults else (defaults or None)
	doc = apply_coding_profile_for(capture, defaults=parsed)
	doc._kick_next_step()
	return doc.name


@frappe.whitelist()
def get_coding_review_queue_for() -> list[dict]:
	"""Captures parked in the coding-review queue (spec 06): Ambiguous/Flagged coding
	awaiting a human (mirrors get_manager_approval_queue_for)."""

	return frappe.get_all(
		"AP Invoice Capture",
		filters={
			"coding_status": ["in", [CODING_STATUS_AMBIGUOUS, CODING_STATUS_FLAGGED]],
			"action_required": 1,
		},
		fields=[
			"name",
			"matched_supplier",
			"coding_status",
			"coding_review_reason",
			"final_total_amount",
		],
		order_by="modified desc",
	)


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
def reroute_after_review_for(capture: str) -> str:
	"""Whitelisted entrypoint for the sanctioned post-review re-route (spec 09).

	Re-routes a Needs-Review capture once its flags/confidence are cleared; resumes
	the cascade. Raises CaptureApprovalError if not eligible."""

	doc = reroute_after_review(capture)
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
