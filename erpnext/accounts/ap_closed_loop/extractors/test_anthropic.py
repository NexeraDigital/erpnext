# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""Tests for the Anthropic OCR provider (Phase 2).

Unit tests use a mocked Anthropic client and never hit the network — they
exercise the response-parsing and field-mapping logic, the error paths, and
the confidence->ambiguous derivation. An opt-in live test (gated by the
ENABLE_LIVE_OCR_TESTS env var) makes one real API call against a fixture.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import frappe
from frappe.tests import IntegrationTestCase

from erpnext.accounts.ap_closed_loop.extractors.anthropic import (
	PROVIDER_NAME,
	AnthropicExtractor,
)
from erpnext.accounts.ap_closed_loop.extractors.base import ExtractionResult
from erpnext.accounts.ap_closed_loop.extractors.registry import get_extractor
from erpnext.accounts.doctype.ap_invoice_capture.ap_invoice_capture import OCRExtractionError


def _tool_use_block(tool_input: dict):
	return SimpleNamespace(type="tool_use", name="extract_invoice_fields", input=tool_input)


def _response(blocks, input_tokens=1200, output_tokens=80):
	return SimpleNamespace(
		content=blocks,
		usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
	)


_GOOD_INPUT = {
	"supplier_name": "Globex Logistics",
	"supplier_invoice_no": "INV-9931",
	"invoice_date": "2026-04-12",
	"total_amount": 4210.55,
	"currency": "USD",
	"confidence_per_field": {
		"supplier_name": 0.98,
		"supplier_invoice_no": 0.95,
		"invoice_date": 0.93,
		"total_amount": 0.97,
		"currency": 0.99,
	},
}


class TestAnthropicResponseMapping(IntegrationTestCase):
	"""Pure parsing/mapping logic — no file, no network."""

	def setUp(self):
		self.extractor = AnthropicExtractor(client=MagicMock())

	def test_parse_tool_use_extracts_input(self):
		resp = _response([_tool_use_block(_GOOD_INPUT)])
		parsed = self.extractor._parse_tool_use(resp)
		self.assertEqual(parsed["supplier_name"], "Globex Logistics")

	def test_missing_tool_use_raises(self):
		# A response with only a text block (no tool_use) is a hard error.
		resp = _response([SimpleNamespace(type="text", text="sorry")])
		with self.assertRaises(OCRExtractionError):
			self.extractor._parse_tool_use(resp)

	def test_happy_path_maps_all_fields(self):
		result = self.extractor._to_extraction_result(_GOOD_INPUT)
		self.assertIsInstance(result, ExtractionResult)
		self.assertEqual(result.provider_name, PROVIDER_NAME)
		# supplier_name -> supplier (logical key)
		self.assertEqual(result.proposal["supplier"], "Globex Logistics")
		self.assertEqual(result.proposal["supplier_invoice_no"], "INV-9931")
		self.assertEqual(result.proposal["invoice_date"], "2026-04-12")
		self.assertEqual(result.proposal["total_amount"], 4210.55)
		self.assertEqual(result.proposal["currency"], "USD")
		self.assertEqual(result.missing_fields, set())
		self.assertEqual(result.ambiguous_fields, set())

	def test_null_fields_become_missing(self):
		data = dict(_GOOD_INPUT)
		data["total_amount"] = None
		data["currency"] = None
		result = self.extractor._to_extraction_result(data)
		self.assertIn("total_amount", result.missing_fields)
		self.assertIn("currency", result.missing_fields)
		self.assertIsNone(result.proposal["total_amount"])

	def test_low_confidence_becomes_ambiguous(self):
		data = dict(_GOOD_INPUT)
		data["confidence_per_field"] = dict(data["confidence_per_field"])
		data["confidence_per_field"]["invoice_date"] = 0.40  # below 0.70 threshold
		result = self.extractor._to_extraction_result(data)
		self.assertIn("invoice_date", result.ambiguous_fields)
		# Still proposed (not stripped) — low confidence != missing.
		self.assertEqual(result.proposal["invoice_date"], "2026-04-12")

	def test_low_confidence_threshold_is_configurable(self):
		strict = AnthropicExtractor(client=MagicMock(), confidence_threshold=0.99)
		# 0.98 supplier confidence is below a 0.99 bar -> ambiguous.
		result = strict._to_extraction_result(_GOOD_INPUT)
		self.assertIn("supplier", result.ambiguous_fields)

	def test_raw_response_carries_usage_and_model(self):
		resp = _response([_tool_use_block(_GOOD_INPUT)])
		result = self.extractor._to_extraction_result(_GOOD_INPUT, resp)
		self.assertEqual(result.raw_response["usage"]["input_tokens"], 1200)
		self.assertEqual(result.raw_response["usage"]["output_tokens"], 80)
		self.assertIn("model", result.raw_response)

	def test_missing_confidence_for_a_field_does_not_flag_ambiguous(self):
		data = dict(_GOOD_INPUT)
		data["confidence_per_field"] = {}  # model omitted confidences
		result = self.extractor._to_extraction_result(data)
		# No confidence -> not flagged ambiguous (only missing values are flagged).
		self.assertEqual(result.ambiguous_fields, set())


class TestAnthropicContentBlocks(IntegrationTestCase):
	def setUp(self):
		self.extractor = AnthropicExtractor(client=MagicMock())

	def test_pdf_uses_document_block_first(self):
		content = self.extractor._build_content(b"%PDF-1.4 fake", "application/pdf")
		self.assertEqual(content[0]["type"], "document")
		self.assertEqual(content[0]["source"]["media_type"], "application/pdf")
		self.assertEqual(content[1]["type"], "text")  # text comes after the doc

	def test_png_uses_image_block(self):
		content = self.extractor._build_content(b"\x89PNG fake", "image/png")
		self.assertEqual(content[0]["type"], "image")
		self.assertEqual(content[0]["source"]["media_type"], "image/png")

	def test_content_is_base64_encoded(self):
		content = self.extractor._build_content(b"hello", "application/pdf")
		import base64

		self.assertEqual(base64.standard_b64decode(content[0]["source"]["data"]), b"hello")


class TestAnthropicExtractEndToEnd(IntegrationTestCase):
	def test_extract_calls_model_and_maps(self):
		"""extract() with both the file read and the client mocked."""
		client = MagicMock()
		client.messages.create.return_value = _response([_tool_use_block(_GOOD_INPUT)])
		extractor = AnthropicExtractor(client=client, model="claude-haiku-4-5-20251001")
		# Bypass the real file read.
		extractor._read_source = lambda capture: (b"%PDF fake", "application/pdf")

		cap = frappe.new_doc("AP Invoice Capture")
		cap.source_filename = "e2e.pdf"
		cap.file_extension = "pdf"
		cap.intake_channel = "Manual ERPNext Upload"
		cap.is_supported_format = 1

		result = extractor.extract(cap)
		self.assertEqual(result.provider_name, PROVIDER_NAME)
		self.assertEqual(result.proposal["supplier"], "Globex Logistics")
		# The model was called with a forced tool choice.
		_, kwargs = client.messages.create.call_args
		self.assertEqual(kwargs["tool_choice"]["name"], "extract_invoice_fields")

	def test_registry_resolves_anthropic(self):
		self.assertIsInstance(get_extractor("anthropic"), AnthropicExtractor)


class TestAnthropicLive(IntegrationTestCase):
	"""Opt-in real API call. Skipped unless ENABLE_LIVE_OCR_TESTS=1 and a key
	is configured. Asserts the call succeeds and returns a schema-valid result;
	does NOT assert specific values (model output is non-deterministic)."""

	def test_live_extraction(self):
		if os.environ.get("ENABLE_LIVE_OCR_TESTS") != "1":
			self.skipTest("set ENABLE_LIVE_OCR_TESTS=1 to run the live Anthropic test")

		from erpnext.ai.credentials import AICredentialsNotConfigured, get_ai_credentials

		try:
			get_ai_credentials("anthropic")
		except AICredentialsNotConfigured:
			self.skipTest("no Anthropic key configured in AI Provider Settings")

		fixture = frappe.db.get_value(
			"File", {"file_name": ["like", "%.pdf"]}, "name", order_by="creation desc"
		)
		if not fixture:
			self.skipTest("no PDF File fixture available on the site")

		file_doc = frappe.get_doc("File", fixture)
		cap = frappe.new_doc("AP Invoice Capture")
		cap.source_filename = file_doc.file_name
		cap.file_extension = (file_doc.file_name or "").rsplit(".", 1)[-1].lower()
		cap.intake_channel = "Manual ERPNext Upload"
		cap.is_supported_format = 1
		cap.source_file = file_doc.name

		result = AnthropicExtractor().extract(cap)
		self.assertEqual(result.provider_name, PROVIDER_NAME)
		# All five logical keys are present in the proposal (value may be None).
		for key in ("supplier", "supplier_invoice_no", "invoice_date", "total_amount", "currency"):
			self.assertIn(key, result.proposal)
