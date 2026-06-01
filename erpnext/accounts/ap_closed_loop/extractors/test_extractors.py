# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""Tests for the OCR provider adapter (Phase 1).

Phase 1 introduced the ``OCRProvider`` seam without changing behaviour. The
existing AP suites (test_walking_skeleton, test_ap_invoice_capture) prove the
no-behaviour-change requirement by passing unchanged. These tests cover the
NEW code paths the existing suites only exercise indirectly:

  * the registry resolves the fake provider and rejects unknown ones,
  * FakeExtractor produces a well-formed ExtractionResult,
  * determinism (same source -> same proposal),
  * the simulate_missing / simulate_ambiguous test affordances still work
    through the adapter,
  * run_extraction / run_fake_extraction alias identity.

The probes build in-memory captures with ``save=False`` so they need no
DocType fixtures beyond what import already provides.
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from erpnext.accounts.ap_closed_loop.extractors.base import (
	PROPOSAL_KEYS,
	ExtractionResult,
	OCRProvider,
)
from erpnext.accounts.ap_closed_loop.extractors.fake import FakeExtractor
from erpnext.accounts.ap_closed_loop.extractors.registry import get_extractor
from erpnext.accounts.doctype.ap_invoice_capture.ap_invoice_capture import (
	FAKE_OCR_PROVIDER,
	run_extraction,
	run_fake_extraction,
)


def _make_capture(filename: str = "phase1_test_invoice.pdf") -> "frappe.Document":
	"""Build an in-memory, unsaved capture sufficient for extraction."""
	c = frappe.new_doc("AP Invoice Capture")
	c.source_filename = filename
	c.file_extension = filename.rsplit(".", 1)[-1]
	c.intake_channel = "Manual ERPNext Upload"
	c.is_supported_format = 1
	c.source_file_url = f"/private/files/{filename}"
	c.received_at = frappe.utils.now_datetime()
	return c


class TestOCRRegistry(IntegrationTestCase):
	def test_get_extractor_returns_fake_provider(self):
		provider = get_extractor("fake")
		self.assertIsInstance(provider, OCRProvider)
		self.assertIsInstance(provider, FakeExtractor)

	def test_fake_provider_name_matches_constant(self):
		self.assertEqual(get_extractor("fake").name(), FAKE_OCR_PROVIDER)

	def test_default_provider_is_fake(self):
		# get_extractor() with no argument defaults to the fake provider.
		self.assertIsInstance(get_extractor(), FakeExtractor)

	def test_unknown_provider_raises_value_error(self):
		with self.assertRaises(ValueError) as ctx:
			get_extractor("does-not-exist")
		msg = str(ctx.exception)
		self.assertIn("does-not-exist", msg)
		# The error lists the registered providers so the caller can fix config.
		self.assertIn("fake", msg)


class TestFakeExtractor(IntegrationTestCase):
	def test_extract_returns_extraction_result_with_all_keys(self):
		result = FakeExtractor().extract(_make_capture())
		self.assertIsInstance(result, ExtractionResult)
		self.assertEqual(result.provider_name, FAKE_OCR_PROVIDER)
		# Every logical proposal key is present in the proposal dict.
		for key in PROPOSAL_KEYS:
			self.assertIn(key, result.proposal)
		# A clean capture has no missing/ambiguous fields.
		self.assertEqual(result.missing_fields, set())
		self.assertEqual(result.ambiguous_fields, set())

	def test_extract_is_deterministic(self):
		r1 = FakeExtractor().extract(_make_capture("same_source.pdf"))
		r2 = FakeExtractor().extract(_make_capture("same_source.pdf"))
		self.assertEqual(r1.proposal, r2.proposal)

	def test_different_sources_differ(self):
		r1 = FakeExtractor().extract(_make_capture("source_a.pdf"))
		r2 = FakeExtractor().extract(_make_capture("source_b.pdf"))
		# At least one field should differ between two distinct sources.
		self.assertNotEqual(r1.proposal, r2.proposal)

	def test_simulate_missing_strips_and_flags_fields(self):
		result = FakeExtractor().extract(
			_make_capture(), simulate_missing=["total_amount", "currency"]
		)
		self.assertIn("total_amount", result.missing_fields)
		self.assertIn("currency", result.missing_fields)
		self.assertIsNone(result.proposal["total_amount"])
		self.assertIsNone(result.proposal["currency"])

	def test_simulate_ambiguous_flags_without_stripping(self):
		result = FakeExtractor().extract(
			_make_capture(), simulate_ambiguous=["supplier"]
		)
		self.assertIn("supplier", result.ambiguous_fields)
		# Ambiguous fields are still proposed (not stripped).
		self.assertIsNotNone(result.proposal["supplier"])

	def test_filename_missing_marker_honored(self):
		# Filename-driven simulation marker, no explicit kwargs.
		result = FakeExtractor().extract(_make_capture("missing_currency_invoice.pdf"))
		self.assertIn("currency", result.missing_fields)
		self.assertIsNone(result.proposal["currency"])


class TestExtractionResultConfidenceDefaults(IntegrationTestCase):
	# AC-04-1: new dataclass fields default empty; existing construction stays valid.
	def test_new_fields_default_empty(self):
		r = ExtractionResult(proposal={"supplier": "X"})
		self.assertEqual(r.confidence, {})
		self.assertEqual(r.lines, [])
		self.assertEqual(r.score_sources, {})


class TestFakeExtractorConfidence(IntegrationTestCase):
	"""Spec 04 — FakeExtractor derives per-field confidence (AC-04-5)."""

	def test_default_path_all_clear_095_no_lines(self):
		result = FakeExtractor().extract(_make_capture())
		for key in PROPOSAL_KEYS:
			self.assertEqual(result.confidence[key], 0.95)
			self.assertEqual(result.score_sources[key], "Derived-Mapping")
		self.assertEqual(result.lines, [])
		# Default-path invariants unchanged.
		self.assertEqual(result.missing_fields, set())
		self.assertEqual(result.ambiguous_fields, set())

	def test_missing_and_ambiguous_map_to_zero_and_half(self):
		result = FakeExtractor().extract(
			_make_capture(),
			simulate_missing=["total_amount"],
			simulate_ambiguous=["supplier"],
		)
		self.assertEqual(result.confidence["total_amount"], 0.0)
		self.assertEqual(result.confidence["supplier"], 0.5)
		self.assertEqual(result.confidence["currency"], 0.95)

	def test_confidence_is_deterministic(self):
		r1 = FakeExtractor().extract(_make_capture("dc.pdf"))
		r2 = FakeExtractor().extract(_make_capture("dc.pdf"))
		self.assertEqual(r1.confidence, r2.confidence)


class TestRunExtractionThroughAdapter(IntegrationTestCase):
	def test_alias_identity(self):
		self.assertIs(run_fake_extraction, run_extraction)

	def test_run_extraction_populates_proposed_fields(self):
		doc = run_extraction(_make_capture(), save=False)
		self.assertEqual(doc.ocr_provider, FAKE_OCR_PROVIDER)
		self.assertEqual(doc.ocr_status, "Proposed")
		self.assertTrue(doc.proposed_supplier)
		self.assertTrue(doc.proposed_supplier_invoice_no)
		self.assertTrue(doc.proposed_currency)
		# action_required is set because review is always required post-proposal.
		self.assertEqual(doc.action_required, 1)

	def test_run_extraction_records_raw_response(self):
		import json

		doc = run_extraction(_make_capture(), save=False)
		raw = json.loads(doc.ocr_raw_response)
		self.assertEqual(raw["provider"], FAKE_OCR_PROVIDER)
		self.assertIn("proposal", raw)

	def test_run_extraction_simulate_missing_marks_fields(self):
		doc = run_extraction(
			_make_capture(), save=False, simulate_missing=["total_amount", "currency"]
		)
		self.assertIsNone(doc.proposed_currency)
		self.assertIn("currency", doc.proposed_missing_fields or "")
		self.assertIn("total_amount", doc.proposed_missing_fields or "")

	def test_run_extraction_rejects_unsupported_format(self):
		from erpnext.accounts.doctype.ap_invoice_capture.ap_invoice_capture import (
			OCRExtractionError,
		)

		cap = _make_capture("bad.gif")
		cap.is_supported_format = 0
		with self.assertRaises(OCRExtractionError):
			run_extraction(cap, save=False)
