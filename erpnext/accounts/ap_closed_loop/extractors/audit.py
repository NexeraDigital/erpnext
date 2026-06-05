# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""Audit logging for OCR extraction calls.

Each real extraction (or failure) is recorded as a Frappe ``Integration
Request`` — the canonical DocType for outbound-API audit, the same one payment
gateways use. This gives operators a standard, queryable trail of every model
call: which capture, which model(s), token usage, estimated cost, latency, and
the outcome, plus a sanitized error on failure.

Nothing here ever stores an API key. The request summary is metadata only
(filename, format, size, content hash) — never the document bytes or the key —
and error text is scrubbed before storage.
"""

from __future__ import annotations

import json
import re

import frappe

from erpnext.accounts.ap_closed_loop.extractors.pricing import estimate_cost_usd

INTEGRATION_SERVICE = "anthropic"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

# Redact anything that looks like a key or auth header from logged text.
_REDACT_PATTERNS = [
	re.compile(r"sk-ant-[A-Za-z0-9_\-]+"),
	re.compile(r"(?i)(x-api-key|authorization)\s*[:=]\s*\S+"),
	re.compile(r"(?i)api[_-]?key\s*[:=]\s*\S+"),
]


def sanitize(text) -> str:
	"""Scrub key-like substrings from arbitrary text before persisting it."""
	if text is None:
		return ""
	s = str(text)
	for pat in _REDACT_PATTERNS:
		s = pat.sub("[REDACTED]", s)
	return s


def _request_summary(capture, result=None) -> dict:
	"""Metadata-only description of the request — never bytes, never a key."""
	summary = {
		"source_filename": getattr(capture, "source_filename", None),
		"file_extension": getattr(capture, "file_extension", None),
		"capture": getattr(capture, "name", None),
	}
	if result is not None:
		summary["provider"] = result.provider_name
	return summary


def write_integration_request(
	capture, *, result=None, status: str, error: str | None = None
) -> str | None:
	"""Create one Integration Request row for an extraction call.

	status: "Completed" or "Failed" (valid Integration Request states).
	On success pass ``result`` (an ExtractionResult); on failure pass ``error``.
	Logging must never break extraction, so any failure here is swallowed with a
	frappe.log_error rather than raised.
	"""
	try:
		output = {}
		if result is not None:
			raw = result.raw_response or {}
			calls = raw.get("calls") or []
			cost, cost_complete = estimate_cost_usd(calls)
			output = {
				"model": raw.get("model"),
				"outcome": raw.get("outcome"),
				"calls": calls,
				"total_input_tokens": sum((c.get("input_tokens") or 0) for c in calls),
				"total_output_tokens": sum((c.get("output_tokens") or 0) for c in calls),
				"cost_usd_estimate": cost,
				"cost_estimate_complete": cost_complete,
				"latency_ms": raw.get("latency_ms"),
				"missing_fields": sorted(result.missing_fields),
				"ambiguous_fields": sorted(result.ambiguous_fields),
			}

		doc = frappe.get_doc(
			{
				"doctype": "Integration Request",
				"integration_request_service": INTEGRATION_SERVICE,
				"status": status,
				"url": ANTHROPIC_URL,
				"reference_doctype": "Document Capture",
				"reference_docname": getattr(capture, "name", None),
				"data": json.dumps(_request_summary(capture, result), default=str),
				"output": json.dumps(output, default=str) if output else None,
				"error": sanitize(error) if error else None,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc.name
	except Exception:
		# Audit logging is best-effort; never let it break the extraction flow.
		frappe.log_error(
			title="AP OCR audit log failed",
			message=sanitize(frappe.get_traceback()),
		)
		return None
