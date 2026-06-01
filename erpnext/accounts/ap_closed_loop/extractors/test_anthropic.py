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


class TestAnthropicConfidenceAndLines(IntegrationTestCase):
	"""Spec 04 — keep the numeric scores + extract line items."""

	def setUp(self):
		self.extractor = AnthropicExtractor(client=MagicMock())

	# AC-04-2
	def test_confidence_per_field_kept_as_numbers(self):
		result = self.extractor._to_extraction_result(_GOOD_INPUT)
		self.assertEqual(result.confidence["supplier"], 0.98)
		self.assertEqual(result.confidence["total_amount"], 0.97)
		self.assertEqual(result.confidence["currency"], 0.99)
		self.assertEqual(result.score_sources["supplier"], "Model")
		# Missing/ambiguous derivation is unchanged (all scores clear here).
		self.assertEqual(result.missing_fields, set())
		self.assertEqual(result.ambiguous_fields, set())

	# AC-04-3
	def test_line_items_populate_lines_and_line_confidence_keys(self):
		data = dict(_GOOD_INPUT)
		data["line_items"] = [
			{
				"description": "Widgets",
				"qty": 2,
				"rate": 100.0,
				"amount": 200.0,
				"confidence": {"description": 0.9, "amount": 0.85},
			},
			{"description": "Freight", "qty": 1, "rate": 10.55, "amount": 10.55,
			 "confidence": {"amount": 0.6}},
		]
		result = self.extractor._to_extraction_result(data)
		self.assertEqual(len(result.lines), 2)
		self.assertEqual(result.lines[0]["description"], "Widgets")
		self.assertEqual(result.confidence["line_0_description"], 0.9)
		self.assertEqual(result.confidence["line_0_amount"], 0.85)
		self.assertEqual(result.confidence["line_1_amount"], 0.6)
		self.assertEqual(result.score_sources["line_0_amount"], "Model")

	# AC-04-4
	def test_mapping_fallback_when_no_confidence_per_field(self):
		data = {
			"supplier_name": "Globex Logistics",
			"supplier_invoice_no": "INV-9931",
			"invoice_date": None,  # absent
			"total_amount": 4210.55,
			"currency": "USD",
			"confidence_per_field": {},  # model emitted no numeric scores
		}
		result = self.extractor._to_extraction_result(data)
		self.assertEqual(result.confidence["supplier"], 0.95)  # present
		self.assertEqual(result.confidence["invoice_date"], 0.0)  # absent
		self.assertEqual(result.score_sources["supplier"], "Derived-Mapping")
		self.assertEqual(result.score_sources["invoice_date"], "Derived-Mapping")
		# Header surfaces carried under proposal keys.
		self.assertIn("subtotal", result.proposal)
		self.assertIn("po_reference", result.proposal)


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


class TestAnthropicImagePrep(IntegrationTestCase):
	"""Oversized/noisy images must be downscaled + re-encoded before sending,
	to stay under Anthropic's per-image size limit (regression for the corpus
	finding where 6MB+ scanned PNGs returned HTTP 400)."""

	def setUp(self):
		self.extractor = AnthropicExtractor(client=MagicMock())

	def _noisy_png(self, w, h):
		import io

		import numpy as np
		from PIL import Image

		arr = (np.random.default_rng(1).integers(0, 256, (h, w, 3))).astype("uint8")
		buf = io.BytesIO()
		Image.fromarray(arr).save(buf, format="PNG")
		return buf.getvalue()

	def test_pdf_passes_through_untouched(self):
		raw = b"%PDF-1.4 not really"
		out, mt = self.extractor._prepare_image(raw, "application/pdf")
		self.assertEqual(out, raw)
		self.assertEqual(mt, "application/pdf")

	def test_small_image_untouched(self):
		import io

		from PIL import Image

		buf = io.BytesIO()
		Image.new("RGB", (400, 300), "white").save(buf, format="PNG")
		raw = buf.getvalue()
		out, mt = self.extractor._prepare_image(raw, "image/png")
		self.assertEqual(out, raw)
		self.assertEqual(mt, "image/png")

	def test_oversize_noisy_png_downscaled_and_reencoded(self):
		import io

		from PIL import Image

		raw = self._noisy_png(1700, 2380)  # mimics a 6MB+ scanned PNG
		self.assertGreater(len(raw), 4_000_000)
		out, mt = self.extractor._prepare_image(raw, "image/png")
		self.assertEqual(mt, "image/jpeg")  # re-encoded
		self.assertLess(len(out), 5_000_000)  # under Anthropic's limit
		self.assertLessEqual(max(Image.open(io.BytesIO(out)).size), 1568)  # long edge capped

	def test_large_dimension_clean_image_downscaled(self):
		import io

		from PIL import Image

		buf = io.BytesIO()
		Image.new("RGB", (3000, 2000), "white").save(buf, format="PNG")
		out, mt = self.extractor._prepare_image(buf.getvalue(), "image/png")
		self.assertEqual(mt, "image/jpeg")
		self.assertLessEqual(max(Image.open(io.BytesIO(out)).size), 1568)


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


class TestAnthropicFallback(IntegrationTestCase):
	"""Phase 4: low-confidence/missing primary result triggers exactly one
	retry with the configured fallback model."""

	def _low_conf_input(self):
		data = dict(_GOOD_INPUT)
		data["confidence_per_field"] = dict(data["confidence_per_field"])
		data["confidence_per_field"]["invoice_date"] = 0.30  # below threshold
		return data

	def _extractor(self, client, fallback="claude-sonnet-4-6"):
		ex = AnthropicExtractor(
			client=client, model="claude-haiku-4-5-20251001", fallback_model=fallback
		)
		ex._read_source = lambda capture: (b"img", "image/png")
		ex._prepare_image = lambda b, m: (b, m)
		return ex

	def _cap(self):
		c = frappe.new_doc("AP Invoice Capture")
		c.source_filename = "fb.png"
		c.file_extension = "png"
		c.intake_channel = "Manual ERPNext Upload"
		c.is_supported_format = 1
		return c

	def test_low_confidence_triggers_single_fallback(self):
		client = MagicMock()
		# 1st (Haiku) low-confidence, 2nd (Sonnet) clean.
		client.messages.create.side_effect = [
			_response([_tool_use_block(self._low_conf_input())]),
			_response([_tool_use_block(_GOOD_INPUT)]),
		]
		result = self._extractor(client).extract(self._cap())
		self.assertEqual(client.messages.create.call_count, 2)
		# second call used the fallback model
		self.assertEqual(client.messages.create.call_args_list[1].kwargs["model"], "claude-sonnet-4-6")
		self.assertEqual(result.raw_response["outcome"], "fallback_invoked")
		self.assertEqual(result.raw_response["model"], "claude-sonnet-4-6")
		self.assertEqual(result.ambiguous_fields, set())  # resolved by fallback

	def test_high_confidence_no_fallback(self):
		client = MagicMock()
		client.messages.create.side_effect = [_response([_tool_use_block(_GOOD_INPUT)])]
		result = self._extractor(client).extract(self._cap())
		self.assertEqual(client.messages.create.call_count, 1)
		self.assertEqual(result.raw_response["outcome"], "primary")

	def test_no_fallback_model_means_no_retry(self):
		client = MagicMock()
		client.messages.create.side_effect = [_response([_tool_use_block(self._low_conf_input())])]
		result = self._extractor(client, fallback=None).extract(self._cap())
		self.assertEqual(client.messages.create.call_count, 1)  # no retry despite low conf
		self.assertIn("invoice_date", result.ambiguous_fields)

	def test_fallback_equal_to_primary_skips_retry(self):
		client = MagicMock()
		client.messages.create.side_effect = [_response([_tool_use_block(self._low_conf_input())])]
		ex = self._extractor(client, fallback="claude-haiku-4-5-20251001")  # same as primary
		result = ex.extract(self._cap())
		self.assertEqual(client.messages.create.call_count, 1)
		self.assertEqual(result.raw_response["outcome"], "primary")

	def test_fallback_fires_once_only_even_if_still_low(self):
		client = MagicMock()
		# both passes low-confidence; must NOT loop — exactly 2 calls total.
		client.messages.create.side_effect = [
			_response([_tool_use_block(self._low_conf_input())]),
			_response([_tool_use_block(self._low_conf_input())]),
		]
		result = self._extractor(client).extract(self._cap())
		self.assertEqual(client.messages.create.call_count, 2)
		self.assertEqual(result.raw_response["outcome"], "fallback_invoked")
		self.assertIn("invoice_date", result.ambiguous_fields)  # still flagged for human


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
