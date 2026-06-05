# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""BAML receipt/invoice reader (Phase B).

Wraps the generated ``baml_client`` behind the ``OCRProvider`` interface so the
cascade can read receipts with a cheap-model BAML call selected via
``AP Closed Loop Settings.ocr_provider``. One ``ReadReceipt`` call returns the
header fields, line items (with per-line tax), AND the document kind + payment
state — so this provider both extracts and (via the stashed kind/payment in
``raw_response``) feeds classification. The state machine / field-writing in
``ap_invoice_capture.py`` is unchanged; it consumes the ``ExtractionResult``.

The Anthropic key is fetched lazily from AI Provider Settings (never logged) and
exported as ``ANTHROPIC_API_KEY`` for the BAML client's ``env`` reference.
"""

from __future__ import annotations

import base64
import os
from typing import TYPE_CHECKING

import frappe

from erpnext.accounts.ap_closed_loop.extractors.base import ExtractionResult, OCRProvider

if TYPE_CHECKING:
	from erpnext.accounts.doctype.ap_invoice_capture.ap_invoice_capture import (
		APInvoiceCapture,
	)

PROVIDER_NAME = "baml-receipt-v1"

_MEDIA_TYPE_BY_EXT = {
	"pdf": "application/pdf",
	"png": "image/png",
	"jpg": "image/jpeg",
	"jpeg": "image/jpeg",
}

# BAML DocKind -> the capture's document_type taxonomy (consumed by classification).
_KIND_TO_DOCTYPE = {
	"Receipt": "Already Paid",
	"Invoice": "Unpaid Bill",
}


class BamlReceiptProvider(OCRProvider):
	"""OCRProvider backed by the BAML ``ReadReceipt`` function (cheap vision model)."""

	def __init__(self, **kwargs) -> None:
		# confidence_threshold mirrors the other providers' signature; below it a
		# header field is flagged ambiguous for human attention (spec 04/09).
		self._threshold = float(kwargs.get("confidence_threshold") or 0.7)

	def name(self) -> str:
		return PROVIDER_NAME

	# -- source bytes ------------------------------------------------------
	def _read_source(self, capture: "APInvoiceCapture") -> tuple[bytes, str]:
		from erpnext.accounts.doctype.ap_invoice_capture.ap_invoice_capture import (
			AmbiguousSourceError,
			OCRExtractionError,
		)

		ext = (capture.file_extension or "").lower().lstrip(".")
		media_type = _MEDIA_TYPE_BY_EXT.get(ext)
		if not media_type:
			raise OCRExtractionError(
				frappe._("Unsupported source format for BAML extraction: {0}").format(ext or "?")
			)
		file_doc = None
		if capture.source_file:
			file_doc = frappe.get_doc("File", capture.source_file)
		elif capture.source_file_url:
			name = frappe.db.get_value("File", {"file_url": capture.source_file_url}, "name")
			if name:
				file_doc = frappe.get_doc("File", name)
		if not file_doc:
			raise AmbiguousSourceError(
				frappe._("Capture has no resolvable source file for extraction.")
			)
		content = file_doc.get_content()
		if isinstance(content, str):
			content = content.encode("latin-1", errors="ignore")
		return content, media_type

	# -- BAML call ---------------------------------------------------------
	def _read(self, file_bytes: bytes, media_type: str):
		"""Invoke the BAML reader; returns a baml_client Receipt."""
		from erpnext.ai.credentials import get_ai_credentials

		creds = get_ai_credentials("anthropic")
		# BAML's CheapVision client references env.ANTHROPIC_API_KEY.
		os.environ["ANTHROPIC_API_KEY"] = creds.api_key

		from baml_py import Image, Pdf

		from erpnext.accounts.ap_closed_loop.baml_client.sync_client import b

		b64 = base64.standard_b64encode(file_bytes).decode("ascii")
		if media_type == "application/pdf":
			return b.ReadReceiptPdf(Pdf.from_base64(b64))
		return b.ReadReceipt(Image.from_base64(media_type, b64))

	# -- public API --------------------------------------------------------
	def extract(
		self,
		capture: "APInvoiceCapture",
		*,
		simulate_missing=None,  # noqa: ARG002 — real provider ignores test affordances
		simulate_ambiguous=None,  # noqa: ARG002
	) -> ExtractionResult:
		file_bytes, media_type = self._read_source(capture)
		r = self._read(file_bytes, media_type)

		proposal = {
			"supplier": (r.merchant or None),
			"supplier_invoice_no": (r.doc_number or None),
			"invoice_date": (r.date or None),
			"total_amount": r.total,
			"currency": (r.currency or None),
		}
		missing = {k for k, v in proposal.items() if v in (None, "")}

		conf = float(r.confidence or 0.0)
		# One model-level confidence applied to every populated header field; below
		# the threshold the field is flagged ambiguous (still proposed).
		confidence = {k: conf for k, v in proposal.items() if v not in (None, "")}
		score_sources = {k: "Model" for k in confidence}
		ambiguous = {k for k, c in confidence.items() if c < self._threshold}

		lines = []
		for i, li in enumerate(r.line_items or []):
			lines.append(
				{
					"description": li.description,
					"qty": li.quantity,
					"rate": li.unit_price,
					"amount": li.amount,
					"tax_amount": li.tax_amount,
					"confidence": {"amount": conf},
				}
			)

		kind = getattr(r.kind, "value", str(r.kind))
		payment = getattr(r.payment_state, "value", str(r.payment_state))
		raw_response = {
			"provider": PROVIDER_NAME,
			"kind": kind,
			"payment_state": payment,
			"document_type": _KIND_TO_DOCTYPE.get(kind, ""),
			"merchant_ref": r.merchant_ref,
			"card_last4": r.card_last4,
			"subtotal": r.subtotal,
			"tax": r.tax,
			"confidence": conf,
		}

		return ExtractionResult(
			proposal=proposal,
			missing_fields=missing,
			ambiguous_fields=ambiguous,
			provider_name=PROVIDER_NAME,
			raw_response=raw_response,
			confidence=confidence,
			lines=lines,
			score_sources=score_sources,
		)
