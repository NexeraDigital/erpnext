# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""Anthropic Claude OCR provider (Phase 2).

Reads an uploaded invoice (PDF / PNG / JPG) from the capture's linked File and
asks Claude to extract the header fields, using the Messages API with a forced
tool call so the response is structured JSON rather than free text.

Phase 2 scope: single model (no Sonnet fallback — that is Phase 4), no audit
logging (Phase 5), not yet wired into the live cascade via settings (Phase 3).
The model is invoked directly; callers reach it through ``get_extractor`` or a
bench smoke test.

Design notes:
* The Anthropic client is injectable (``client=`` ctor arg) so unit tests can
  pass a mock and never hit the network.
* The API key is fetched lazily from ``AI Provider Settings`` via
  ``get_ai_credentials`` — never logged, held only for the call.
* Document block (PDF) vs image block (PNG/JPG) is chosen by media type, and
  the document/image block is placed BEFORE the text block per Anthropic's
  vision/PDF guidance (https://platform.claude.com/docs/en/build-with-claude/pdf-support).
"""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING

import frappe

from erpnext.accounts.ap_closed_loop.extractors.base import ExtractionResult, OCRProvider

if TYPE_CHECKING:
	from erpnext.accounts.doctype.ap_invoice_capture.ap_invoice_capture import (
		APInvoiceCapture,
	)

PROVIDER_NAME = "anthropic"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_CONFIDENCE_THRESHOLD = 0.70
MAX_TOKENS = 2048

# Anthropic recommends a max long edge of ~1568px for images (optimal
# quality/cost) and enforces a hard ~5MB-per-image limit. Real scanned invoices
# are large and noisy (a noisy PNG can be 6MB+), so we downscale + re-encode
# before sending. See https://platform.claude.com/docs/en/build-with-claude/vision
MAX_IMAGE_EDGE = 1568
IMAGE_REENCODE_THRESHOLD_BYTES = 4_000_000

_MEDIA_TYPE_BY_EXT = {
	"pdf": "application/pdf",
	"png": "image/png",
	"jpg": "image/jpeg",
	"jpeg": "image/jpeg",
}

# Forced tool call — the schema IS the output contract. Nullable fields let the
# model return null for anything it cannot read confidently rather than guess.
INVOICE_EXTRACTION_TOOL = {
	"name": "extract_invoice_fields",
	"description": (
		"Extract structured header fields from a supplier invoice document. "
		"Return null for any field you cannot read confidently. Do not guess. "
		"confidence_per_field reflects certainty: 1.0 = unambiguous, "
		"0.7 = legible but unverified, 0.4 = partial/ambiguous, 0.0 = absent."
	),
	"input_schema": {
		"type": "object",
		"properties": {
			"supplier_name": {"type": ["string", "null"]},
			"supplier_invoice_no": {"type": ["string", "null"]},
			"invoice_date": {
				"type": ["string", "null"],
				"description": "ISO 8601 date (YYYY-MM-DD) if determinable.",
			},
			"total_amount": {"type": ["number", "null"]},
			"currency": {
				"type": ["string", "null"],
				"description": "ISO 4217 3-letter code (e.g. USD, EUR, INR).",
			},
			"confidence_per_field": {
				"type": "object",
				"properties": {
					"supplier_name": {"type": "number"},
					"supplier_invoice_no": {"type": "number"},
					"invoice_date": {"type": "number"},
					"total_amount": {"type": "number"},
					"currency": {"type": "number"},
				},
			},
		},
		"required": ["confidence_per_field"],
	},
}

# Map the tool's field names to ExtractionResult.proposal logical keys.
_TOOL_TO_LOGICAL = {
	"supplier_name": "supplier",
	"supplier_invoice_no": "supplier_invoice_no",
	"invoice_date": "invoice_date",
	"total_amount": "total_amount",
	"currency": "currency",
}

_PROMPT = (
	"Extract the invoice header fields using the extract_invoice_fields tool. "
	"Use null for any field you cannot read confidently."
)


class AnthropicExtractor(OCRProvider):
	"""OCR provider backed by Anthropic Claude with forced tool use."""

	def __init__(
		self,
		client=None,
		model: str | None = None,
		confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
	):
		self._client = client
		self._model = model
		self._confidence_threshold = confidence_threshold

	def name(self) -> str:
		return PROVIDER_NAME

	# -- client / model resolution -----------------------------------------

	def _get_client(self):
		if self._client is not None:
			return self._client
		import anthropic

		from erpnext.ai.credentials import get_ai_credentials

		creds = get_ai_credentials("anthropic")
		self._client = anthropic.Anthropic(api_key=creds.api_key)
		# Prefer an explicit ctor model, else the org default, else the pin.
		if not self._model:
			self._model = creds.default_model or DEFAULT_MODEL
		return self._client

	def _resolve_model(self) -> str:
		return self._model or DEFAULT_MODEL

	# -- public API --------------------------------------------------------

	def extract(
		self,
		capture: "APInvoiceCapture",
		*,
		simulate_missing=None,  # noqa: ARG002 - real provider ignores test affordances
		simulate_ambiguous=None,  # noqa: ARG002
	) -> ExtractionResult:
		file_bytes, media_type = self._read_source(capture)
		file_bytes, media_type = self._prepare_image(file_bytes, media_type)
		client = self._get_client()
		response = client.messages.create(
			model=self._resolve_model(),
			max_tokens=MAX_TOKENS,
			tools=[INVOICE_EXTRACTION_TOOL],
			tool_choice={"type": "tool", "name": "extract_invoice_fields"},
			messages=[{"role": "user", "content": self._build_content(file_bytes, media_type)}],
		)
		tool_input = self._parse_tool_use(response)
		return self._to_extraction_result(tool_input, response)

	# -- helpers (each independently testable) -----------------------------

	def _prepare_image(self, file_bytes: bytes, media_type: str) -> tuple[bytes, str]:
		"""Downscale + re-encode oversized images before sending.

		Real scanned invoices are large and noisy; a noisy PNG easily exceeds
		Anthropic's ~5MB-per-image limit (and is wastefully large even when it
		doesn't). PDFs are left untouched (handled as documents). For images
		that are either over the long-edge guidance or over the byte threshold,
		downscale to MAX_IMAGE_EDGE and re-encode as JPEG (q85) to keep the
		payload small and within limits.
		"""
		if media_type == "application/pdf":
			return file_bytes, media_type
		try:
			import io

			from PIL import Image

			img = Image.open(io.BytesIO(file_bytes))
			long_edge = max(img.size)
			oversize = long_edge > MAX_IMAGE_EDGE or len(file_bytes) > IMAGE_REENCODE_THRESHOLD_BYTES
			if not oversize:
				return file_bytes, media_type
			if long_edge > MAX_IMAGE_EDGE:
				scale = MAX_IMAGE_EDGE / long_edge
				img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))))
			buf = io.BytesIO()
			img.convert("RGB").save(buf, format="JPEG", quality=85)
			return buf.getvalue(), "image/jpeg"
		except Exception:
			# If anything goes wrong preparing the image, fall back to the
			# original bytes — the API call may still succeed for small files.
			return file_bytes, media_type

	def _read_source(self, capture: "APInvoiceCapture") -> tuple[bytes, str]:
		"""Return (raw bytes, media_type) for the capture's source file."""
		ext = (capture.file_extension or "").lower().lstrip(".")
		media_type = _MEDIA_TYPE_BY_EXT.get(ext)
		if not media_type:
			from erpnext.accounts.doctype.ap_invoice_capture.ap_invoice_capture import (
				OCRExtractionError,
			)

			raise OCRExtractionError(
				frappe._("Unsupported source format for extraction: {0}").format(ext or "?")
			)

		file_doc = None
		if capture.source_file:
			file_doc = frappe.get_doc("File", capture.source_file)
		elif capture.source_file_url:
			name = frappe.db.get_value("File", {"file_url": capture.source_file_url}, "name")
			if name:
				file_doc = frappe.get_doc("File", name)
		if not file_doc:
			from erpnext.accounts.doctype.ap_invoice_capture.ap_invoice_capture import (
				AmbiguousSourceError,
			)

			raise AmbiguousSourceError(
				frappe._("Capture has no resolvable source file for extraction.")
			)

		content = file_doc.get_content()
		if isinstance(content, str):
			content = content.encode("latin-1", errors="ignore")
		return content, media_type

	def _build_content(self, file_bytes: bytes, media_type: str) -> list:
		"""Document/image block first, then the instruction text."""
		b64 = base64.standard_b64encode(file_bytes).decode("ascii")
		block_type = "document" if media_type == "application/pdf" else "image"
		return [
			{
				"type": block_type,
				"source": {"type": "base64", "media_type": media_type, "data": b64},
			},
			{"type": "text", "text": _PROMPT},
		]

	def _parse_tool_use(self, response) -> dict:
		"""Pull the single tool_use block's input out of the response."""
		for block in getattr(response, "content", []) or []:
			if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "extract_invoice_fields":
				return dict(block.input or {})
		from erpnext.accounts.doctype.ap_invoice_capture.ap_invoice_capture import (
			OCRExtractionError,
		)

		raise OCRExtractionError(
			frappe._("Claude did not return a structured invoice extraction.")
		)

	def _to_extraction_result(self, tool_input: dict, response=None) -> ExtractionResult:
		confidences = tool_input.get("confidence_per_field") or {}
		proposal: dict = {}
		missing: set[str] = set()
		ambiguous: set[str] = set()

		for tool_key, logical in _TOOL_TO_LOGICAL.items():
			value = tool_input.get(tool_key)
			proposal[logical] = value
			if value in (None, ""):
				missing.add(logical)
				continue
			conf = confidences.get(tool_key)
			if conf is not None and conf < self._confidence_threshold:
				ambiguous.add(logical)

		raw = {"tool_input": tool_input}
		usage = getattr(response, "usage", None)
		if usage is not None:
			raw["usage"] = {
				"input_tokens": getattr(usage, "input_tokens", None),
				"output_tokens": getattr(usage, "output_tokens", None),
			}
		raw["model"] = self._resolve_model()

		return ExtractionResult(
			proposal=proposal,
			missing_fields=missing,
			ambiguous_fields=ambiguous,
			provider_name=PROVIDER_NAME,
			raw_response=raw,
		)


def smoke_test(file_name: str | None = None) -> dict:
	"""Bench-executable smoke test: extract a real fixture against the live key.

	Usage:
	    bench --site <site> execute \\
	        erpnext.accounts.ap_closed_loop.extractors.anthropic.smoke_test \\
	        --kwargs '{"file_name": "<File docname>"}'

	If file_name is omitted, picks the most recent PDF File on the site.
	"""
	if not file_name:
		file_name = frappe.db.get_value(
			"File", {"file_name": ["like", "%.pdf"]}, "name", order_by="creation desc"
		)
	if not file_name:
		return {"error": "No PDF File found; pass file_name=<File docname>."}

	file_doc = frappe.get_doc("File", file_name)
	ext = (file_doc.file_name or "").rsplit(".", 1)[-1].lower()

	# Build a throwaway in-memory capture pointing at the file.
	cap = frappe.new_doc("AP Invoice Capture")
	cap.source_filename = file_doc.file_name
	cap.file_extension = ext
	cap.intake_channel = "Manual ERPNext Upload"
	cap.is_supported_format = 1
	cap.source_file = file_doc.name
	cap.received_at = frappe.utils.now_datetime()

	result = AnthropicExtractor().extract(cap)
	return {
		"provider": result.provider_name,
		"proposal": result.proposal,
		"missing_fields": sorted(result.missing_fields),
		"ambiguous_fields": sorted(result.ambiguous_fields),
		"usage": result.raw_response.get("usage"),
		"model": result.raw_response.get("model"),
	}
