# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""Tests for OCR audit logging (Phase 5): pricing + Integration Request writes.

Pricing is pure. The audit-write and run_extraction-integration tests use the
real Integration Request DocType and a mocked Anthropic client (no API spend).
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from erpnext.accounts.ap_closed_loop.extractors.audit import (
	INTEGRATION_SERVICE,
	sanitize,
	write_integration_request,
)
from erpnext.accounts.ap_closed_loop.extractors.base import ExtractionResult
from erpnext.accounts.ap_closed_loop.extractors.pricing import estimate_cost_usd


class TestPricing(IntegrationTestCase):
	def test_known_model_cost(self):
		# Haiku: $1/Mtok in, $5/Mtok out. 1M in + 1M out = $1 + $5 = $6.
		cost, complete = estimate_cost_usd(
			[{"model": "claude-haiku-4-5-20251001", "input_tokens": 1_000_000, "output_tokens": 1_000_000}]
		)
		self.assertAlmostEqual(cost, 6.0, places=4)
		self.assertTrue(complete)

	def test_multi_call_sums(self):
		cost, complete = estimate_cost_usd(
			[
				{"model": "claude-haiku-4-5-20251001", "input_tokens": 1000, "output_tokens": 100},
				{"model": "claude-sonnet-4-6", "input_tokens": 1000, "output_tokens": 100},
			]
		)
		self.assertGreater(cost, 0)
		self.assertTrue(complete)

	def test_unknown_model_is_incomplete(self):
		cost, complete = estimate_cost_usd([{"model": "made-up", "input_tokens": 1000, "output_tokens": 1000}])
		self.assertEqual(cost, 0.0)
		self.assertFalse(complete)

	def test_prefix_match(self):
		# A dated haiku variant not enumerated still prices via prefix.
		cost, complete = estimate_cost_usd(
			[{"model": "claude-haiku-4-5-20260101", "input_tokens": 1_000_000, "output_tokens": 0}]
		)
		self.assertAlmostEqual(cost, 1.0, places=4)
		self.assertTrue(complete)


class TestSanitize(IntegrationTestCase):
	def test_redacts_key(self):
		self.assertNotIn("sk-ant-", sanitize("error using sk-ant-abc123def456 oops"))
		self.assertIn("[REDACTED]", sanitize("sk-ant-abc123def456"))

	def test_redacts_auth_header(self):
		self.assertNotIn("secretval", sanitize("x-api-key: secretval"))


class TestWriteIntegrationRequest(IntegrationTestCase):
	def _capture(self):
		c = frappe.new_doc("Document Capture")
		c.source_filename = "audit.pdf"
		c.file_extension = "pdf"
		c.intake_channel = "Manual ERPNext Upload"
		c.is_supported_format = 1
		c.source_file_url = "/private/files/audit.pdf"
		c.received_at = frappe.utils.now_datetime()
		c.insert(ignore_permissions=True)  # need a name for reference_docname
		return c

	def _result(self):
		return ExtractionResult(
			proposal={"supplier": "ACME", "currency": "USD"},
			provider_name="anthropic",
			raw_response={
				"model": "claude-haiku-4-5-20251001",
				"outcome": "primary",
				"latency_ms": 812,
				"calls": [
					{"model": "claude-haiku-4-5-20251001", "input_tokens": 1500, "output_tokens": 90}
				],
			},
		)

	def test_completed_row_has_service_reference_and_cost(self):
		cap = self._capture()
		name = write_integration_request(cap, result=self._result(), status="Completed")
		self.assertIsNotNone(name)
		ir = frappe.get_doc("Integration Request", name)
		self.assertEqual(ir.integration_request_service, INTEGRATION_SERVICE)
		self.assertEqual(ir.status, "Completed")
		self.assertEqual(ir.reference_doctype, "Document Capture")
		self.assertEqual(ir.reference_docname, cap.name)
		out = json.loads(ir.output)
		self.assertEqual(out["model"], "claude-haiku-4-5-20251001")
		self.assertEqual(out["outcome"], "primary")
		self.assertEqual(out["total_input_tokens"], 1500)
		self.assertGreater(out["cost_usd_estimate"], 0)
		self.assertEqual(out["latency_ms"], 812)

	def test_failed_row_stores_sanitized_error(self):
		cap = self._capture()
		name = write_integration_request(
			cap, status="Failed", error="boom with sk-ant-leakedkey123 in it"
		)
		ir = frappe.get_doc("Integration Request", name)
		self.assertEqual(ir.status, "Failed")
		self.assertNotIn("sk-ant-leakedkey123", ir.error)
		self.assertIn("[REDACTED]", ir.error)

	def test_no_api_key_anywhere_in_row(self):
		cap = self._capture()
		name = write_integration_request(cap, result=self._result(), status="Completed")
		ir = frappe.get_doc("Integration Request", name)
		blob = " ".join(str(x) for x in [ir.data, ir.output, ir.error, ir.request_headers])
		self.assertNotIn("sk-ant", blob)


class TestRunExtractionAuditIntegration(IntegrationTestCase):
	"""run_extraction must create an Integration Request for the real provider
	and must NOT for the fake provider. Network client mocked."""

	def _set(self, **f):
		for k, v in f.items():
			frappe.db.set_single_value("AP Closed Loop Settings", k, v)

	def _store_key(self):
		ai = frappe.get_single("AI Provider Settings")
		ai.anthropic_api_key = "sk-ant-audit-" + "k" * 30
		ai.save(ignore_permissions=True)

	def _capture(self):
		c = frappe.new_doc("Document Capture")
		c.source_filename = "audit_int.png"
		c.file_extension = "png"
		c.intake_channel = "Manual ERPNext Upload"
		c.is_supported_format = 1
		c.source_file_url = "/private/files/audit_int.png"
		c.received_at = frappe.utils.now_datetime()
		c.insert(ignore_permissions=True)
		return c

	def _count_ir(self, capture_name):
		return frappe.db.count(
			"Integration Request",
			{"reference_doctype": "Document Capture", "reference_docname": capture_name},
		)

	def test_anthropic_run_logs_completed_integration_request(self):
		from erpnext.accounts.doctype.document_capture.document_capture import run_extraction

		self._store_key()
		self._set(ocr_provider="Anthropic Claude", ocr_model="claude-haiku-4-5-20251001")
		cap = self._capture()
		resp = SimpleNamespace(
			content=[SimpleNamespace(type="tool_use", name="extract_invoice_fields", input={
				"supplier_name": "ACME", "supplier_invoice_no": "INV-1",
				"invoice_date": "2026-01-01", "total_amount": 10.0, "currency": "USD",
				"confidence_per_field": {k: 0.95 for k in ("supplier_name", "supplier_invoice_no", "invoice_date", "total_amount", "currency")},
			})],
			usage=SimpleNamespace(input_tokens=1200, output_tokens=80),
		)
		mock_client = MagicMock()
		mock_client.messages.create.return_value = resp
		ex = MagicMock()
		# Patch the extractor to use our mocked client but real logic:
		from erpnext.accounts.ap_closed_loop.extractors.anthropic import AnthropicExtractor

		real = AnthropicExtractor(client=mock_client, model="claude-haiku-4-5-20251001")
		real._read_source = lambda capture: (b"img", "image/png")
		real._prepare_image = lambda b, m: (b, m)
		with patch(
			"erpnext.accounts.ap_closed_loop.extractors.registry.get_extractor",
			return_value=real,
		):
			run_extraction(cap, save=False)

		self.assertEqual(self._count_ir(cap.name), 1)
		ir_name = frappe.db.get_value(
			"Integration Request",
			{"reference_docname": cap.name, "integration_request_service": "anthropic"},
			"name",
		)
		ir = frappe.get_doc("Integration Request", ir_name)
		self.assertEqual(ir.status, "Completed")
		self.assertIn("claude-haiku", ir.output)

	def test_fake_provider_logs_nothing(self):
		from erpnext.accounts.doctype.document_capture.document_capture import run_extraction

		self._set(ocr_provider="Fake (Deterministic)")
		cap = self._capture()
		run_extraction(cap, save=False)
		self.assertEqual(self._count_ir(cap.name), 0)
