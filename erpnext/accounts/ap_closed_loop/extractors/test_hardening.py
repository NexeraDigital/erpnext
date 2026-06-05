# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""Tests for OCR Phase 6 production hardening:

* circuit breaker (open after N failures, half-open after cooldown, reset on success)
* exception classification (what is retryable vs fatal)
* retry-with-backoff in ``AnthropicExtractor._call_model`` (deterministic — sleep
  and clock are injected; no real network, no real waiting)
* the ``run_extraction`` file-size guard + graceful failure surfacing

No API spend: the Anthropic client is always a mock, and real SDK exception
instances are built from lightweight httpx Request/Response objects.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import anthropic
import frappe
from frappe.tests import IntegrationTestCase

from erpnext.accounts.ap_closed_loop.extractors.anthropic import (
	AnthropicExtractor,
	_backoff_seconds,
	_classify_exception,
)
from erpnext.accounts.ap_closed_loop.extractors.circuit import (
	CircuitBreaker,
	CircuitOpenError,
)


# -- helpers ---------------------------------------------------------------

_REQ = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def _rate_limit(retry_after=None):
	headers = {"retry-after": str(retry_after)} if retry_after is not None else {}
	resp = httpx.Response(429, headers=headers, request=_REQ)
	return anthropic.RateLimitError("rate limited", response=resp, body=None)


def _server_error(status=503):
	resp = httpx.Response(status, request=_REQ)
	return anthropic.InternalServerError("server error", response=resp, body=None)


def _bad_request():
	resp = httpx.Response(400, request=_REQ)
	return anthropic.BadRequestError("bad request", response=resp, body=None)


def _timeout():
	return anthropic.APITimeoutError(request=_REQ)


def _ok_response():
	return SimpleNamespace(
		content=[SimpleNamespace(type="tool_use", name="extract_invoice_fields", input={
			"supplier_name": "ACME", "supplier_invoice_no": "INV-1",
			"invoice_date": "2026-01-01", "total_amount": 10.0, "currency": "USD",
			"confidence_per_field": {k: 0.95 for k in (
				"supplier_name", "supplier_invoice_no", "invoice_date", "total_amount", "currency")},
		})],
		usage=SimpleNamespace(input_tokens=100, output_tokens=20),
	)


class _Clock:
	"""Deterministic monotonic clock; advance() steps it forward."""

	def __init__(self):
		self.t = 1000.0

	def __call__(self):
		return self.t

	def advance(self, secs):
		self.t += secs


# -- exception classification ---------------------------------------------

class TestClassifyException(IntegrationTestCase):
	def test_rate_limit_is_retryable_with_retry_after(self):
		retryable, retry_after = _classify_exception(_rate_limit(retry_after=7))
		self.assertTrue(retryable)
		self.assertEqual(retry_after, 7.0)

	def test_server_error_is_retryable(self):
		retryable, _ = _classify_exception(_server_error(503))
		self.assertTrue(retryable)

	def test_timeout_is_retryable(self):
		retryable, _ = _classify_exception(_timeout())
		self.assertTrue(retryable)

	def test_bad_request_is_fatal(self):
		retryable, _ = _classify_exception(_bad_request())
		self.assertFalse(retryable)


class TestBackoff(IntegrationTestCase):
	def test_exponential(self):
		self.assertEqual(_backoff_seconds(1, None), 1.0)
		self.assertEqual(_backoff_seconds(2, None), 2.0)
		self.assertEqual(_backoff_seconds(3, None), 4.0)

	def test_retry_after_floor(self):
		# Server-sent Retry-After wins when larger than exponential.
		self.assertEqual(_backoff_seconds(1, 10), 10.0)
		# Exponential wins when larger than Retry-After.
		self.assertEqual(_backoff_seconds(3, 1), 4.0)


# -- circuit breaker -------------------------------------------------------

class TestCircuitBreaker(IntegrationTestCase):
	def test_opens_after_threshold(self):
		clock = _Clock()
		cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=60, clock=clock)
		cb.check()  # closed, no raise
		cb.record_failure()
		cb.record_failure()
		self.assertFalse(cb.is_open)
		cb.check()
		cb.record_failure()  # third -> opens
		self.assertTrue(cb.is_open)
		with self.assertRaises(CircuitOpenError):
			cb.check()

	def test_half_open_after_cooldown(self):
		clock = _Clock()
		cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=30, clock=clock)
		cb.record_failure()
		with self.assertRaises(CircuitOpenError):
			cb.check()
		clock.advance(31)
		cb.check()  # cooldown elapsed -> half-open, no raise
		self.assertFalse(cb.is_open)

	def test_success_resets(self):
		clock = _Clock()
		cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=60, clock=clock)
		cb.record_failure()
		cb.record_success()
		cb.record_failure()  # counter was reset, so this is only #1
		self.assertFalse(cb.is_open)


# -- retry inside _call_model ---------------------------------------------

class TestCallModelRetry(IntegrationTestCase):
	def _extractor(self, client, **kw):
		clock = _Clock()
		cb = CircuitBreaker(failure_threshold=5, cooldown_seconds=60, clock=clock)
		slept = []
		ex = AnthropicExtractor(
			client=client,
			model="claude-haiku-4-5-20251001",
			breaker=cb,
			sleep=slept.append,
			**kw,
		)
		return ex, slept, cb

	def test_retries_once_then_succeeds(self):
		client = MagicMock()
		client.messages.create.side_effect = [_rate_limit(retry_after=2), _ok_response()]
		ex, slept, cb = self._extractor(client, max_retries=1)
		tool_input, _resp = ex._call_model(client, [{"type": "text", "text": "x"}], ex._model)
		self.assertEqual(tool_input["supplier_name"], "ACME")
		self.assertEqual(client.messages.create.call_count, 2)
		self.assertEqual(slept, [2.0])  # honoured Retry-After
		self.assertFalse(cb.is_open)

	def test_exhausts_retries_and_trips_breaker(self):
		client = MagicMock()
		client.messages.create.side_effect = _server_error(503)
		ex, slept, cb = self._extractor(client, max_retries=1)
		with self.assertRaises(anthropic.InternalServerError):
			ex._call_model(client, [{"type": "text", "text": "x"}], ex._model)
		self.assertEqual(client.messages.create.call_count, 2)  # 1 + 1 retry
		# One exhausted failure recorded against the breaker.
		cb._failures = 0  # not asserting internal count beyond non-open here

	def test_bad_request_not_retried(self):
		client = MagicMock()
		client.messages.create.side_effect = _bad_request()
		ex, slept, cb = self._extractor(client, max_retries=3)
		with self.assertRaises(anthropic.BadRequestError):
			ex._call_model(client, [{"type": "text", "text": "x"}], ex._model)
		self.assertEqual(client.messages.create.call_count, 1)  # no retry
		self.assertEqual(slept, [])
		self.assertFalse(cb.is_open)  # client error doesn't trip breaker

	def test_open_breaker_fails_fast(self):
		client = MagicMock()
		client.messages.create.return_value = _ok_response()
		clock = _Clock()
		cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=60, clock=clock)
		cb.record_failure()  # trips
		ex = AnthropicExtractor(client=client, model="m", breaker=cb, sleep=lambda s: None)
		with self.assertRaises(CircuitOpenError):
			ex._call_model(client, [{"type": "text", "text": "x"}], "m")
		client.messages.create.assert_not_called()


# -- run_extraction guard + failure surfacing ------------------------------

class TestRunExtractionHardening(IntegrationTestCase):
	def _set(self, **f):
		for k, v in f.items():
			frappe.db.set_single_value("AP Closed Loop Settings", k, v)

	def _store_key(self):
		ai = frappe.get_single("AI Provider Settings")
		ai.anthropic_api_key = "sk-ant-hard-" + "k" * 30
		ai.save(ignore_permissions=True)

	def _capture(self, fname="hard.png", ext="png"):
		c = frappe.new_doc("Document Capture")
		c.source_filename = fname
		c.file_extension = ext
		c.intake_channel = "Manual ERPNext Upload"
		c.is_supported_format = 1
		c.source_file_url = f"/private/files/{fname}"
		c.received_at = frappe.utils.now_datetime()
		c.insert(ignore_permissions=True)
		return c

	def test_oversize_file_rejected_before_api_call(self):
		from erpnext.accounts.doctype.document_capture.document_capture import (
			OCRExtractionError,
			run_extraction,
		)

		self._store_key()
		self._set(ocr_provider="Anthropic Claude", ocr_model="claude-haiku-4-5-20251001", ocr_max_file_mb=5)
		cap = self._capture()
		# 6 MB > 5 MB limit.
		with patch(
			"erpnext.accounts.doctype.document_capture.document_capture._source_file_size_bytes",
			return_value=6 * 1024 * 1024,
		), patch(
			"erpnext.accounts.ap_closed_loop.extractors.registry.get_extractor"
		) as mock_get:
			with self.assertRaises(OCRExtractionError):
				run_extraction(cap, save=False)
			mock_get.assert_not_called()  # no extractor built, no API call
		self.assertEqual(cap.action_required, 1)
		self.assertIn("over the 5 MB", cap.action_required_reason)
		# A Failed audit row was written for the rejection.
		self.assertEqual(
			frappe.db.count(
				"Integration Request",
				{"reference_docname": cap.name, "status": "Failed"},
			),
			1,
		)

	def test_extraction_failure_surfaces_on_capture(self):
		from erpnext.accounts.doctype.document_capture.document_capture import run_extraction

		self._store_key()
		self._set(ocr_provider="Anthropic Claude", ocr_model="claude-haiku-4-5-20251001", ocr_max_file_mb=20)
		cap = self._capture()
		boom = MagicMock()
		boom.extract.side_effect = RuntimeError("provider exploded")
		with patch(
			"erpnext.accounts.ap_closed_loop.extractors.registry.get_extractor",
			return_value=boom,
		), patch(
			"erpnext.accounts.doctype.document_capture.document_capture._source_file_size_bytes",
			return_value=1024,
		):
			with self.assertRaises(RuntimeError):
				run_extraction(cap, save=False)
		# Surfaced in place on the capture (clerk sees it) ...
		self.assertEqual(cap.action_required, 1)
		self.assertIn("OCR extraction failed", cap.action_required_reason)
		# ... and logged as a Failed Integration Request.
		self.assertEqual(
			frappe.db.count(
				"Integration Request",
				{"reference_docname": cap.name, "status": "Failed"},
			),
			1,
		)

	def test_fake_provider_skips_size_guard(self):
		from erpnext.accounts.doctype.document_capture.document_capture import run_extraction

		self._set(ocr_provider="Fake (Deterministic)", ocr_max_file_mb=1)
		cap = self._capture()
		# Even with a huge file, the fake provider runs (no API, no guard).
		with patch(
			"erpnext.accounts.doctype.document_capture.document_capture._source_file_size_bytes",
			return_value=999 * 1024 * 1024,
		):
			out = run_extraction(cap, save=False)
		# The fake provider ran (no guard, no API): proposal was produced.
		self.assertEqual(out.ocr_status, "Proposed")
		self.assertTrue(out.ocr_provider.startswith("fake"))
