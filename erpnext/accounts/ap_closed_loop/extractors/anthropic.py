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
import time
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


def _classify_exception(exc) -> tuple[bool, float | None]:
	"""Classify an exception from ``messages.create`` for retry purposes.

	Returns ``(retryable, retry_after_seconds)``. Retryable = transient provider
	conditions worth a second attempt: rate limits (429), server errors (5xx),
	timeouts, and connection failures. Anything else (400 bad request, 401 auth,
	404) is fatal — a retry would fail identically.

	The ``anthropic`` exception classes are imported lazily so this module (and
	its unit tests, which inject a mock client) never require the SDK at import
	time. If the SDK is absent we fall back to a conservative, status-code-based
	heuristic.
	"""
	try:
		import anthropic
	except Exception:  # pragma: no cover — SDK always present in the bench
		status = getattr(exc, "status_code", None)
		return (status is None or status == 429 or status >= 500), None

	# Connection-level failures (includes APITimeoutError) — retry.
	if isinstance(exc, anthropic.APIConnectionError):
		return True, None
	# HTTP responses with a status code.
	if isinstance(exc, anthropic.APIStatusError):
		status = getattr(exc, "status_code", None)
		retry_after = _parse_retry_after(exc)
		if status == 429:
			return True, retry_after
		if status is not None and status >= 500:
			return True, retry_after
		return False, None  # 400/401/403/404 etc — fatal
	return False, None


def _backoff_seconds(attempt: int, retry_after) -> float:
	"""Exponential backoff (1s, 2s, 4s…), but never less than a server-sent
	Retry-After. Deterministic — no jitter — so tests can assert on it."""
	base = float(2 ** (attempt - 1))
	if retry_after is not None:
		try:
			return max(base, float(retry_after))
		except (TypeError, ValueError):
			return base
	return base


def _parse_retry_after(exc) -> float | None:
	"""Pull a Retry-After (seconds) from a 429 response if the server sent one."""
	response = getattr(exc, "response", None)
	headers = getattr(response, "headers", None)
	if not headers:
		return None
	try:
		raw = headers.get("retry-after")
	except AttributeError:
		return None
	if raw is None:
		return None
	try:
		return float(raw)
	except (TypeError, ValueError):
		return None  # HTTP-date form — fall back to exponential backoff

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
				"description": (
					"ISO 4217 3-letter code (e.g. USD, EUR, INR). Set this ONLY when a "
					"currency symbol (e.g. $, €, £) or an explicit code is printed on the "
					"invoice. If amounts are bare numbers with no currency shown, return "
					"null — do NOT infer or default a currency."
				),
			},
			"subtotal": {
				"type": ["number", "null"],
				"description": "Pre-tax subtotal if printed.",
			},
			"tax_total": {
				"type": ["number", "null"],
				"description": "Total tax amount if printed.",
			},
			"po_reference": {
				"type": ["string", "null"],
				"description": "Visible purchase-order number on the document, if any.",
			},
			"line_items": {
				"type": "array",
				"description": (
					"One object per invoice line. Omit or return [] for a receipt with "
					"no itemization. Do not invent lines."
				),
				"items": {
					"type": "object",
					"properties": {
						"description": {"type": ["string", "null"]},
						"qty": {"type": ["number", "null"]},
						"rate": {"type": ["number", "null"]},
						"amount": {"type": ["number", "null"]},
						"tax_amount": {"type": ["number", "null"]},
						"expense_account": {"type": ["string", "null"]},
						"cost_center": {"type": ["string", "null"]},
						"po_reference": {"type": ["string", "null"]},
						"confidence": {
							"type": "object",
							"description": "Per-field certainty for this line (0..1), same scale as confidence_per_field.",
						},
					},
				},
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
	"Use null for any field you cannot read confidently. Do not infer or default "
	"a currency that is not explicitly printed on the invoice — return null for "
	"currency in that case so it can be reviewed."
)


class AnthropicExtractor(OCRProvider):
	"""OCR provider backed by Anthropic Claude with forced tool use."""

	def __init__(
		self,
		client=None,
		model: str | None = None,
		confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
		fallback_model: str | None = None,
		max_retries: int = 1,
		breaker=None,
		sleep=None,
	):
		self._client = client
		self._model = model
		self._confidence_threshold = confidence_threshold
		# Phase 4: when the primary (e.g. Haiku) pass leaves a required field
		# missing/ambiguous, retry once with this stronger model. Empty/None
		# disables fallback.
		self._fallback_model = fallback_model or None
		# Phase 6 hardening: transient-failure retry + circuit breaker.
		self._max_retries = max_retries
		if breaker is None:
			from erpnext.accounts.ap_closed_loop.extractors.circuit import shared_breaker

			breaker = shared_breaker()
		self._breaker = breaker
		self._sleep = sleep if sleep is not None else time.sleep

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
		import time

		file_bytes, media_type = self._read_source(capture)
		file_bytes, media_type = self._prepare_image(file_bytes, media_type)
		client = self._get_client()
		content = self._build_content(file_bytes, media_type)

		# Accumulate per-call telemetry across primary + any fallback so cost and
		# token usage in the audit log reflect EVERY call, not just the last one.
		calls: list[dict] = []
		t0 = time.monotonic()

		primary_model = self._resolve_model()
		tool_input, response = self._call_model(client, content, primary_model)
		calls.append(self._call_usage(primary_model, response))
		result = self._to_extraction_result(
			tool_input, response, model=primary_model, outcome="primary"
		)

		# Phase 4 fallback: if the primary pass couldn't confidently read every
		# required field, retry ONCE with the configured fallback model.
		fb = self._fallback_model
		needs_fallback = bool(result.missing_fields or result.ambiguous_fields)
		if fb and fb != primary_model and needs_fallback:
			tool_input, response = self._call_model(client, content, fb)
			calls.append(self._call_usage(fb, response))
			result = self._to_extraction_result(
				tool_input, response, model=fb, outcome="fallback_invoked"
			)

		# Per-call breakdown + total latency for the audit log (Phase 5).
		result.raw_response["calls"] = calls
		result.raw_response["latency_ms"] = int((time.monotonic() - t0) * 1000)
		return result

	@staticmethod
	def _call_usage(model: str, response) -> dict:
		usage = getattr(response, "usage", None)
		return {
			"model": model,
			"input_tokens": getattr(usage, "input_tokens", None) if usage else None,
			"output_tokens": getattr(usage, "output_tokens", None) if usage else None,
		}

	def _call_model(self, client, content, model):
		"""One forced-tool extraction call. Returns (tool_input, response).

		Phase 6 hardening: a process-local circuit breaker fails fast when the
		provider has been flapping, and transient failures (429 / 5xx / timeout /
		connection) are retried with exponential backoff (honouring Retry-After
		on 429). Client errors (400 bad request, auth, not-found) are NOT retried
		— they will fail identically on a second attempt.
		"""
		self._breaker.check()
		attempt = 0
		while True:
			try:
				response = client.messages.create(
					model=model,
					max_tokens=MAX_TOKENS,
					tools=[INVOICE_EXTRACTION_TOOL],
					tool_choice={"type": "tool", "name": "extract_invoice_fields"},
					messages=[{"role": "user", "content": content}],
				)
			except Exception as exc:  # noqa: BLE001 — classified below
				retryable, retry_after = _classify_exception(exc)
				if not retryable:
					# Client-side error: don't retry, don't trip the breaker
					# (the provider is healthy — our request is the problem).
					raise
				attempt += 1
				if attempt > self._max_retries:
					self._breaker.record_failure()
					raise
				self._sleep(_backoff_seconds(attempt, retry_after))
				continue
			self._breaker.record_success()
			return self._parse_tool_use(response), response

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

	def _to_extraction_result(
		self, tool_input: dict, response=None, *, model: str | None = None, outcome: str | None = None
	) -> ExtractionResult:
		confidences = tool_input.get("confidence_per_field") or {}
		proposal: dict = {}
		missing: set[str] = set()
		ambiguous: set[str] = set()
		confidence: dict[str, float] = {}
		score_sources: dict[str, str] = {}

		for tool_key, logical in _TOOL_TO_LOGICAL.items():
			value = tool_input.get(tool_key)
			proposal[logical] = value
			raw_conf = confidences.get(tool_key)
			if raw_conf is not None:
				# Real model score (spec 04): keep the number, tag it Model.
				try:
					conf = float(raw_conf)
				except (TypeError, ValueError):
					conf = 0.0
				score_sources[logical] = "Model"
				if value not in (None, "") and conf < self._confidence_threshold:
					ambiguous.add(logical)
			else:
				# Mapping fallback: no per-field number for this field, derive one
				# from clarity (present -> 0.95, absent -> 0.0) and tag Derived-Mapping
				# so routing (spec 09) does not over-trust a stand-in.
				conf = 0.0 if value in (None, "") else 0.95
				score_sources[logical] = "Derived-Mapping"
			confidence[logical] = conf
			if value in (None, ""):
				missing.add(logical)

		# Header surfaces (spec 04): carry subtotal / tax / visible PO under logical
		# proposal keys the controller reads on write-back.
		proposal["subtotal"] = tool_input.get("subtotal")
		proposal["tax"] = tool_input.get("tax_total")
		proposal["po_reference"] = tool_input.get("po_reference")

		# Line items (spec 04): one dict per line, plus per-line confidence emitted
		# into confidence["line_<i>_<field>"]. A line that carries a numeric score
		# is tagged Model; a present-but-unscored field falls back to 0.95 Derived.
		lines: list[dict] = []
		for i, line in enumerate(tool_input.get("line_items") or []):
			if not isinstance(line, dict):
				continue
			line_conf = line.get("confidence") or {}
			lines.append(
				{
					"description": line.get("description"),
					"qty": line.get("qty"),
					"rate": line.get("rate"),
					"amount": line.get("amount"),
					"tax_amount": line.get("tax_amount"),
					"expense_account": line.get("expense_account"),
					"cost_center": line.get("cost_center"),
					"po_reference": line.get("po_reference"),
					"confidence": line_conf,
				}
			)
			for fkey in ("description", "qty", "rate", "amount", "po_reference"):
				key = f"line_{i}_{fkey}"
				raw_lc = line_conf.get(fkey)
				if raw_lc is not None:
					try:
						confidence[key] = float(raw_lc)
					except (TypeError, ValueError):
						confidence[key] = 0.0
					score_sources[key] = "Model"
				elif line.get(fkey) not in (None, ""):
					confidence[key] = 0.95
					score_sources[key] = "Derived-Mapping"

		raw = {"tool_input": tool_input}
		usage = getattr(response, "usage", None)
		if usage is not None:
			raw["usage"] = {
				"input_tokens": getattr(usage, "input_tokens", None),
				"output_tokens": getattr(usage, "output_tokens", None),
			}
		raw["model"] = model or self._resolve_model()
		if outcome:
			raw["outcome"] = outcome

		return ExtractionResult(
			proposal=proposal,
			missing_fields=missing,
			ambiguous_fields=ambiguous,
			provider_name=PROVIDER_NAME,
			raw_response=raw,
			confidence=confidence,
			lines=lines,
			score_sources=score_sources,
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
