# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""Integration tests for the AP OCR pipeline (non-UI, full stack).

Two layers:

* TestOCRPipelineIntegration — repeatable, runs in normal `bench run-tests`.
  Exercises the WHOLE server path end-to-end: AP Closed Loop Settings ->
  get_ocr_config -> run_extraction -> registry -> AnthropicExtractor ->
  real File read from the DB -> real image preparation -> field writes onto the
  capture. The ONLY thing stubbed is the network client (anthropic.Anthropic),
  so no API spend and deterministic — but everything else is real wiring, not
  mocked internals.

* TestOCRPipelineLive — gated by ENABLE_LIVE_OCR_TESTS=1 + a configured key.
  Same full path but against the REAL Anthropic API, scored vs the committed
  corpus ground truth, plus a forced low-confidence case that must escalate
  Haiku -> Sonnet for real.

All settings/key mutations happen IN-TRANSACTION (no frappe.db.commit), so
IntegrationTestCase's per-test rollback restores the developer's real
configuration — including any live API key.
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

AP_SETTINGS = "AP Closed Loop Settings"
AI_SETTINGS = "AI Provider Settings"
_FAKE_KEY = "sk-ant-integration-" + "q" * 30


def _corpus_dir() -> str:
	# OCR-accuracy corpus lives under test/invoices/ocr-extraction/ (test/invoices
	# is organised by what each set tests: ocr-extraction/ vs deduplication/).
	return os.path.abspath(
		os.path.join(
			frappe.get_app_path("erpnext"), "..", "test", "invoices", "ocr-extraction"
		)
	)


def _load_corpus(basename: str):
	defn = json.load(open(os.path.join(_corpus_dir(), basename + ".json")))
	content = open(os.path.join(_corpus_dir(), defn["file"]), "rb").read()
	return defn, content


def _upload_file(fname: str, content: bytes) -> str:
	existing = frappe.db.get_value("File", {"file_name": fname}, "name")
	if existing:
		frappe.delete_doc("File", existing, force=True, ignore_permissions=True)
	fdoc = frappe.get_doc(
		{"doctype": "File", "file_name": fname, "is_private": 1, "content": content}
	).insert(ignore_permissions=True)
	return fdoc.name


def _capture_for(defn: dict, file_name: str):
	cap = frappe.new_doc("AP Invoice Capture")
	cap.source_filename = defn["file"]
	cap.file_extension = defn["format"]
	cap.intake_channel = "Manual ERPNext Upload"
	cap.is_supported_format = 1
	cap.source_file = file_name
	cap.received_at = frappe.utils.now_datetime()
	return cap


def _tool_block(inp):
	return SimpleNamespace(type="tool_use", name="extract_invoice_fields", input=inp)


def _resp(inp, in_tok=1000, out_tok=60):
	return SimpleNamespace(
		content=[_tool_block(inp)],
		usage=SimpleNamespace(input_tokens=in_tok, output_tokens=out_tok),
	)


def _good_input(defn, *, low_field=None):
	exp = defn["expected"]
	conf = {k: 0.97 for k in ("supplier_name", "supplier_invoice_no", "invoice_date", "total_amount", "currency")}
	if low_field:
		conf[low_field] = 0.30
	return {
		"supplier_name": exp["supplier"],
		"supplier_invoice_no": exp["supplier_invoice_no"],
		"invoice_date": exp["invoice_date"],
		"total_amount": exp["total_amount"],
		"currency": exp["currency"],
		"confidence_per_field": conf,
	}


class TestOCRPipelineIntegration(IntegrationTestCase):
	"""Full server path; only the network client is stubbed. No API spend."""

	def _set(self, **fields):
		for k, v in fields.items():
			frappe.db.set_single_value(AP_SETTINGS, k, v)  # in-transaction, rolled back

	def _store_key(self):
		ai = frappe.get_single(AI_SETTINGS)
		ai.anthropic_api_key = _FAKE_KEY
		ai.save(ignore_permissions=True)  # in-transaction

	def test_anthropic_primary_path_end_to_end(self):
		"""Settings -> run_extraction -> registry -> AnthropicExtractor ->
		real PDF read + real image/doc block build -> field writes."""
		from erpnext.accounts.doctype.ap_invoice_capture.ap_invoice_capture import run_extraction

		self._store_key()
		self._set(ocr_provider="Anthropic Claude", ocr_model="claude-haiku-4-5-20251001")
		defn, content = _load_corpus("invoice_01")  # clean modern PDF, EUR
		fname = _upload_file(defn["file"], content)

		mock_client = MagicMock()
		mock_client.messages.create.return_value = _resp(_good_input(defn))
		with patch("anthropic.Anthropic", return_value=mock_client):
			doc = run_extraction(_capture_for(defn, fname), save=False)

		# Real wiring produced the right writes from the (stubbed) model output.
		self.assertEqual(doc.ocr_provider, "anthropic")
		self.assertEqual(doc.ocr_status, "Proposed")
		self.assertEqual(doc.proposed_supplier, defn["expected"]["supplier"])
		self.assertEqual(doc.proposed_currency, defn["expected"]["currency"])
		raw = json.loads(doc.ocr_raw_response)
		self.assertEqual(raw["outcome"], "primary")
		# The real PDF actually went through the document-block path: the model
		# was called once with a forced tool choice.
		self.assertEqual(mock_client.messages.create.call_count, 1)
		self.assertEqual(mock_client.messages.create.call_args.kwargs["tool_choice"]["name"], "extract_invoice_fields")

	def test_fallback_path_end_to_end_via_settings(self):
		"""ocr_fallback_model in settings drives a real second call through the
		whole stack when the primary pass is low-confidence."""
		from erpnext.accounts.doctype.ap_invoice_capture.ap_invoice_capture import run_extraction

		self._store_key()
		self._set(
			ocr_provider="Anthropic Claude",
			ocr_model="claude-haiku-4-5-20251001",
			ocr_fallback_model="claude-sonnet-4-6",
		)
		defn, content = _load_corpus("invoice_02")
		fname = _upload_file(defn["file"], content)

		mock_client = MagicMock()
		mock_client.messages.create.side_effect = [
			_resp(_good_input(defn, low_field="invoice_date")),  # Haiku low-conf
			_resp(_good_input(defn)),                            # Sonnet clean
		]
		with patch("anthropic.Anthropic", return_value=mock_client):
			doc = run_extraction(_capture_for(defn, fname), save=False)

		self.assertEqual(mock_client.messages.create.call_count, 2)
		self.assertEqual(mock_client.messages.create.call_args_list[1].kwargs["model"], "claude-sonnet-4-6")
		raw = json.loads(doc.ocr_raw_response)
		self.assertEqual(raw["outcome"], "fallback_invoked")
		self.assertEqual(raw["model"], "claude-sonnet-4-6")

	def test_default_provider_makes_no_api_client(self):
		"""With the default (fake) provider, run_extraction must not construct an
		Anthropic client at all."""
		from erpnext.accounts.doctype.ap_invoice_capture.ap_invoice_capture import run_extraction

		self._set(ocr_provider="Fake (Deterministic)")
		defn, content = _load_corpus("invoice_05")
		fname = _upload_file(defn["file"], content)
		with patch("anthropic.Anthropic") as MockClient:
			doc = run_extraction(_capture_for(defn, fname), save=False)
		MockClient.assert_not_called()
		self.assertEqual(doc.ocr_provider, "fake-deterministic-v1")


class TestOCRPipelineLive(IntegrationTestCase):
	"""Real Anthropic API. Opt-in: ENABLE_LIVE_OCR_TESTS=1 + a configured key."""

	def setUp(self):
		if os.environ.get("ENABLE_LIVE_OCR_TESTS") != "1":
			self.skipTest("set ENABLE_LIVE_OCR_TESTS=1 to run live OCR integration")
		from erpnext.ai.credentials import AICredentialsNotConfigured, get_ai_credentials

		try:
			get_ai_credentials("anthropic")
		except AICredentialsNotConfigured:
			self.skipTest("no Anthropic key configured in AI Provider Settings")

	def _set(self, **fields):
		for k, v in fields.items():
			frappe.db.set_single_value(AP_SETTINGS, k, v)  # in-transaction

	def test_corpus_through_run_extraction_live(self):
		"""A few representative corpus invoices through the full settings-driven
		path against the real API, scored vs ground truth."""
		from erpnext.accounts.ap_closed_loop.extractors.benchmark import score
		from erpnext.accounts.doctype.ap_invoice_capture.ap_invoice_capture import run_extraction

		self._set(ocr_provider="Anthropic Claude", ocr_model="claude-haiku-4-5-20251001", ocr_fallback_model="")
		for basename in ("invoice_01", "invoice_08", "invoice_18"):  # clean / faxed / missing-currency
			defn, content = _load_corpus(basename)
			fname = _upload_file(defn["file"], content)
			doc = run_extraction(_capture_for(defn, fname), save=False)
			proposal = {
				"supplier": doc.proposed_supplier,
				"supplier_invoice_no": doc.proposed_supplier_invoice_no,
				"invoice_date": str(doc.proposed_invoice_date) if doc.proposed_invoice_date else None,
				"total_amount": doc.proposed_total_amount,
				"currency": doc.proposed_currency,
			}
			missing = set((doc.proposed_missing_fields or "").replace(" ", "").split(",")) - {""}
			s = score(defn, proposal, missing)
			self.assertEqual(doc.ocr_provider, "anthropic")
			self.assertGreaterEqual(s["n_ok"], 4, f"{basename}: only {s['n_ok']}/5 {s['marks']}")

	def test_fallback_escalates_live(self):
		"""Confirm a REAL Haiku -> Sonnet escalation. We trigger it
		deterministically with a genuinely-missing field rather than a
		confidence threshold (the model legitimately returns 1.0 confidence on
		clean fields, so a threshold can't force ambiguity): invoice_18 prints
		no currency, so the primary pass returns currency=null -> missing
		required field -> fallback fires. The fallback pass also can't read a
		currency that isn't there, so currency stays missing, but the run must
		record that the escalation happened."""
		from erpnext.accounts.doctype.ap_invoice_capture.ap_invoice_capture import run_extraction

		self._set(
			ocr_provider="Anthropic Claude",
			ocr_model="claude-haiku-4-5-20251001",
			ocr_fallback_model="claude-sonnet-4-6",
		)
		defn, content = _load_corpus("invoice_18")  # genuinely no currency printed
		fname = _upload_file(defn["file"], content)
		doc = run_extraction(_capture_for(defn, fname), save=False)
		raw = json.loads(doc.ocr_raw_response)
		self.assertEqual(raw["outcome"], "fallback_invoked")
		self.assertEqual(raw["model"], "claude-sonnet-4-6")
		# currency genuinely absent -> still reported missing after the retry
		self.assertIsNone(doc.proposed_currency)
