# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""Tests for AP Closed Loop Settings — OCR provider selection (Phase 3).

Covers:
  * get_ocr_config() resolution (default fake; Anthropic mapping; threshold).
  * validate(): Anthropic selected without a key is rejected with a key-free
    message; out-of-range confidence is rejected.
  * run_extraction dispatches to the configured provider/model/threshold.

The dispatch tests patch the late-imported get_extractor / get_ocr_config so
no real provider is constructed and no network call is made.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils.password import remove_encrypted_password

from erpnext.accounts.ap_closed_loop.extractors.base import ExtractionResult
from erpnext.accounts.doctype.ap_closed_loop_settings.ap_closed_loop_settings import (
	get_ocr_config,
)

_AI_SETTINGS = "AI Provider Settings"
_FAKE_KEY = "sk-ant-phase3-test-" + "z" * 30


def _set_single(fieldname, value):
	frappe.db.set_single_value("AP Closed Loop Settings", fieldname, value)


class TestGetOcrConfig(IntegrationTestCase):
	# NOTE: never frappe.db.commit() in these tests — IntegrationTestCase rolls
	# back the transaction per test, which restores any real configured values
	# (including a live API key). Committing here would persist test mutations
	# and could destroy the developer's real settings.

	def test_defaults_to_fake_when_unset(self):
		_set_single("ocr_provider", None)
		cfg = get_ocr_config()
		self.assertEqual(cfg["provider"], "fake")

	def test_resolves_anthropic_label_to_registry_key(self):
		_set_single("ocr_provider", "Anthropic Claude")
		_set_single("ocr_model", "claude-sonnet-4-6")
		_set_single("ocr_confidence_threshold", 0.85)
		cfg = get_ocr_config()
		self.assertEqual(cfg["provider"], "anthropic")
		self.assertEqual(cfg["model"], "claude-sonnet-4-6")
		self.assertEqual(cfg["confidence_threshold"], 0.85)

	def test_confidence_threshold_defaults_when_blank(self):
		_set_single("ocr_provider", "Anthropic Claude")
		_set_single("ocr_confidence_threshold", 0)
		self.assertEqual(get_ocr_config()["confidence_threshold"], 0.70)


class TestSettingsValidation(IntegrationTestCase):
	# CRITICAL: do NOT frappe.db.commit() anywhere here. Key removal and any
	# settings mutation must stay inside the per-test transaction so
	# IntegrationTestCase's rollback restores the developer's real, configured
	# Anthropic key after each test. (An earlier version committed the key
	# deletion and wiped the live key — never again.)

	def setUp(self):
		# In-transaction clean slate; rolled back after the test, so a real
		# stored key survives the test run untouched.
		remove_encrypted_password(_AI_SETTINGS, _AI_SETTINGS, "anthropic_api_key")

	def test_anthropic_without_key_is_rejected(self):
		settings = frappe.get_single("AP Closed Loop Settings")
		settings.ocr_provider = "Anthropic Claude"
		with self.assertRaises(frappe.ValidationError) as ctx:
			settings.save(ignore_permissions=True)
		msg = str(ctx.exception)
		self.assertIn("AI Provider Settings", msg)
		self.assertNotIn("sk-ant", msg)  # never echo a key

	def test_anthropic_with_key_saves(self):
		ai = frappe.get_single(_AI_SETTINGS)
		ai.anthropic_api_key = _FAKE_KEY  # in-transaction; visible to validate
		ai.save(ignore_permissions=True)

		settings = frappe.get_single("AP Closed Loop Settings")
		settings.ocr_provider = "Anthropic Claude"
		settings.save(ignore_permissions=True)  # should NOT raise
		self.assertEqual(
			frappe.db.get_single_value("AP Closed Loop Settings", "ocr_provider"),
			"Anthropic Claude",
		)

	def test_out_of_range_confidence_rejected(self):
		settings = frappe.get_single("AP Closed Loop Settings")
		settings.ocr_provider = "Fake (Deterministic)"
		settings.ocr_confidence_threshold = 1.5
		with self.assertRaises(frappe.ValidationError):
			settings.save(ignore_permissions=True)


class TestRunExtractionDispatch(IntegrationTestCase):
	def _capture(self):
		c = frappe.new_doc("AP Invoice Capture")
		c.source_filename = "dispatch.pdf"
		c.file_extension = "pdf"
		c.intake_channel = "Manual ERPNext Upload"
		c.is_supported_format = 1
		c.source_file_url = "/private/files/dispatch.pdf"
		c.received_at = frappe.utils.now_datetime()
		return c

	def test_dispatches_to_configured_provider(self):
		from erpnext.accounts.doctype.ap_invoice_capture.ap_invoice_capture import (
			run_extraction,
		)

		canned = ExtractionResult(
			proposal={
				"supplier": "ACME",
				"supplier_invoice_no": "INV-1",
				"invoice_date": "2026-01-01",
				"total_amount": 10.0,
				"currency": "USD",
			},
			provider_name="anthropic",
		)
		stub = MagicMock()
		stub.extract.return_value = canned

		fake_config = {
			"provider": "anthropic",
			"model": "claude-sonnet-4-6",
			"confidence_threshold": 0.85,
			"max_file_mb": 25,
			"force_reextract": False,
		}

		# Patch the names run_extraction late-imports.
		with patch(
			"erpnext.accounts.ap_closed_loop.extractors.registry.get_extractor",
			return_value=stub,
		) as mock_get, patch(
			"erpnext.accounts.doctype.ap_closed_loop_settings.ap_closed_loop_settings.get_ocr_config",
			return_value=fake_config,
		):
			doc = run_extraction(self._capture(), save=False)

		# get_extractor called with the configured provider + model + threshold.
		args, kwargs = mock_get.call_args
		self.assertEqual(args[0], "anthropic")
		self.assertEqual(kwargs["model"], "claude-sonnet-4-6")
		self.assertEqual(kwargs["confidence_threshold"], 0.85)
		# The capture reflects the provider's result.
		self.assertEqual(doc.ocr_provider, "anthropic")
		self.assertEqual(doc.proposed_supplier, "ACME")

	def test_default_dispatches_to_fake(self):
		from erpnext.accounts.doctype.ap_invoice_capture.ap_invoice_capture import (
			run_extraction,
		)

		# No commit — in-transaction set, rolled back after the test.
		_set_single("ocr_provider", "Fake (Deterministic)")
		doc = run_extraction(self._capture(), save=False)
		self.assertEqual(doc.ocr_provider, "fake-deterministic-v1")


class TestFoundationGetters(IntegrationTestCase):
	"""Spec 01 foundation getters + threshold wiring (AC-01-11..14).

	AC-01-15 (validate rejects an out-of-range confidence threshold) is covered
	above by TestSettingsValidation.test_out_of_range_confidence_rejected.
	"""

	def tearDown(self):
		frappe.db.rollback()

	def _set(self, field, value):
		frappe.db.set_single_value("AP Closed Loop Settings", field, value)

	# AC-01-11
	def test_get_auto_post_threshold(self):
		from erpnext.accounts.doctype.ap_closed_loop_settings.ap_closed_loop_settings import (
			get_auto_post_threshold,
		)

		self._set("auto_post_amount_threshold", 2500)
		self.assertEqual(get_auto_post_threshold(), 2500.0)
		self._set("auto_post_amount_threshold", None)
		self.assertEqual(get_auto_post_threshold(), 1000.0)
		self._set("auto_post_amount_threshold", 0)
		self.assertEqual(get_auto_post_threshold(), 1000.0)  # non-positive → default

	# AC-01-12
	def test_resolve_approval_threshold_uses_settings(self):
		from erpnext.accounts.doctype.ap_invoice_capture.ap_invoice_capture import (
			_resolve_approval_threshold,
		)

		self._set("auto_post_amount_threshold", 2500)
		val, _src = _resolve_approval_threshold(None, None)
		self.assertEqual(val, 2500.0)

		self._set("auto_post_amount_threshold", None)
		val2, _src2 = _resolve_approval_threshold(None, None)
		self.assertEqual(val2, 1000.0)  # back-compat fallback

		val3, src3 = _resolve_approval_threshold(750, None)
		self.assertEqual(val3, 750.0)
		self.assertEqual(src3, "explicit-override")

	# AC-01-13
	def test_get_confidence_threshold(self):
		from erpnext.accounts.doctype.ap_closed_loop_settings.ap_closed_loop_settings import (
			get_confidence_threshold,
			get_field_threshold,
		)

		self._set("ocr_confidence_threshold", 0.8)
		self._set("field_thresholds", '{"total_amount": 0.95, "supplier": 0.6}')
		self.assertEqual(get_confidence_threshold("total_amount"), 0.95)
		self.assertEqual(get_confidence_threshold("supplier"), 0.6)
		self.assertEqual(get_confidence_threshold("invoice_date"), 0.8)  # not overridden
		self.assertEqual(get_confidence_threshold(), 0.8)  # no field → scalar
		self.assertEqual(get_field_threshold("total_amount"), 0.95)  # alias
		self._set("ocr_confidence_threshold", None)
		self._set("field_thresholds", None)
		self.assertEqual(get_confidence_threshold(), 0.70)  # blank → default
		self.assertEqual(get_confidence_threshold("anything"), 0.70)

	# AC-01-14
	def test_account_link_fields_roundtrip(self):
		self._set("credit_card_clearing_account", "Creditors - _TC")
		self._set("unmapped_card_spend_account", "Cost of Goods Sold - _TC")
		stored = frappe.db.get_singles_dict("AP Closed Loop Settings")
		self.assertEqual(stored.get("credit_card_clearing_account"), "Creditors - _TC")
		self.assertEqual(stored.get("unmapped_card_spend_account"), "Cost of Goods Sold - _TC")

	def test_get_sod_config(self):
		from erpnext.accounts.doctype.ap_closed_loop_settings.ap_closed_loop_settings import (
			get_sod_config,
		)

		self._set("enforce_sod", 1)
		self._set("sod_threshold_amount", 250)
		cfg = get_sod_config()
		self.assertTrue(cfg["enforce"])
		self.assertEqual(cfg["threshold"], 250.0)
		self._set("enforce_sod", 0)
		self.assertFalse(get_sod_config()["enforce"])

	def test_get_dedupe_window_days(self):
		from erpnext.accounts.doctype.ap_closed_loop_settings.ap_closed_loop_settings import (
			get_dedupe_window_days,
		)

		self._set("dedupe_window_days", 30)
		self.assertEqual(get_dedupe_window_days(), 30)
		self._set("dedupe_window_days", None)
		self.assertEqual(get_dedupe_window_days(), 90)

	def test_get_stream_rules(self):
		from erpnext.accounts.doctype.ap_closed_loop_settings.ap_closed_loop_settings import (
			get_stream_rules,
		)

		parent = "AP Closed Loop Settings"
		frappe.db.delete("AP Stream Rule", {"parent": parent})
		self.assertEqual(get_stream_rules(), [])  # empty on a fresh rule set

		seeds = [
			{"priority": 30, "signal": "filename", "pattern": "c_*", "assign_stream": "Receipt (R)", "enabled": 1},
			{"priority": 10, "signal": "filename", "pattern": "a_*", "assign_stream": "Invoice (I)", "enabled": 1},
			{"priority": 20, "signal": "body", "pattern": "x", "assign_stream": "Receipt (R)", "enabled": 0},
		]
		for i, r in enumerate(seeds, start=1):
			frappe.get_doc({
				"doctype": "AP Stream Rule", "parent": parent, "parenttype": parent,
				"parentfield": "stream_rules", "idx": i, **r,
			}).insert(ignore_permissions=True)

		rules = get_stream_rules()
		# excludes the disabled (enabled=0) row, ordered by priority asc
		self.assertEqual([r["pattern"] for r in rules], ["a_*", "c_*"])
