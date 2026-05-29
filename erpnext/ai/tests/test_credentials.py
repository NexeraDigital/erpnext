# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""Tests for erpnext.ai.credentials.

Covers the four properties the helper must guarantee:
  1. Returns the stored key after one is saved (round trip works).
  2. Raises AICredentialsNotConfigured when no key is set.
  3. The exception message does not contain any key value, partial or full.
  4. Unknown providers raise a clear ValueError.

The DocType-level permission boundary (System Manager only) is tested via
its own permission test that does not call the helper — keeping concerns
separate so a permission regression doesn't masquerade as a helper bug.
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils.password import remove_encrypted_password

from erpnext.ai.credentials import (
	SETTINGS_DOCTYPE,
	AICredentials,
	AICredentialsNotConfigured,
	get_ai_credentials,
)

_FAKE_KEY = "sk-ant-test-" + "x" * 40  # plausible-looking shape, obviously fake
_FAKE_OPENAI_KEY = "sk-openai-test-" + "y" * 40


class TestAICredentialsHelper(IntegrationTestCase):
	"""End-to-end behavior of get_ai_credentials against a real (test) site."""

	def setUp(self) -> None:
		# Wipe any previously-stored passwords so each test starts clean.
		remove_encrypted_password(SETTINGS_DOCTYPE, SETTINGS_DOCTYPE, "anthropic_api_key")
		remove_encrypted_password(SETTINGS_DOCTYPE, SETTINGS_DOCTYPE, "openai_api_key")
		frappe.db.commit()

	def tearDown(self) -> None:
		remove_encrypted_password(SETTINGS_DOCTYPE, SETTINGS_DOCTYPE, "anthropic_api_key")
		remove_encrypted_password(SETTINGS_DOCTYPE, SETTINGS_DOCTYPE, "openai_api_key")
		frappe.db.commit()

	def test_round_trip_anthropic_key(self) -> None:
		# Arrange: save a key via the document (so encryption happens via the
		# real Password-field write path, not by manually inserting into __Auth).
		settings = frappe.get_single(SETTINGS_DOCTYPE)
		settings.anthropic_api_key = _FAKE_KEY
		settings.anthropic_default_model = "claude-haiku-4-5-20251001"
		settings.anthropic_zdr_enabled = 1
		settings.save(ignore_permissions=True)
		frappe.db.commit()

		# Act
		creds = get_ai_credentials("anthropic")

		# Assert
		self.assertIsInstance(creds, AICredentials)
		self.assertEqual(creds.provider, "anthropic")
		self.assertEqual(creds.api_key, _FAKE_KEY)
		self.assertEqual(creds.default_model, "claude-haiku-4-5-20251001")
		self.assertTrue(creds.zdr_enabled)

	def test_raises_when_anthropic_key_not_set(self) -> None:
		# setUp already cleared the key.
		with self.assertRaises(AICredentialsNotConfigured) as ctx:
			get_ai_credentials("anthropic")

		msg = str(ctx.exception)
		# Message must name the provider and point at the right form.
		self.assertIn("anthropic", msg.lower())
		self.assertIn("AI Provider Settings", msg)

	def test_exception_message_never_contains_key_substrings(self) -> None:
		"""Even when a key IS set for one provider, asking for an unset one
		must produce a message that does not leak the other provider's key
		(or anything that looks like one). Defensive against future code
		changes that might attempt to be 'helpful' in the error."""

		settings = frappe.get_single(SETTINGS_DOCTYPE)
		settings.anthropic_api_key = _FAKE_KEY  # stored
		# openai_api_key intentionally left empty
		settings.save(ignore_permissions=True)
		frappe.db.commit()

		with self.assertRaises(AICredentialsNotConfigured) as ctx:
			get_ai_credentials("openai")

		msg = str(ctx.exception)
		# Must not contain either fake key, in whole or in suspicious prefix.
		self.assertNotIn(_FAKE_KEY, msg)
		self.assertNotIn(_FAKE_KEY[:16], msg)
		self.assertNotIn("sk-ant-", msg)
		self.assertNotIn("sk-openai-", msg)

	def test_unknown_provider_raises_value_error(self) -> None:
		with self.assertRaises(ValueError) as ctx:
			get_ai_credentials("not-a-real-provider")

		msg = str(ctx.exception)
		self.assertIn("not-a-real-provider", msg)
		# The error should list supported providers so the caller can fix it.
		self.assertIn("anthropic", msg)
		self.assertIn("openai", msg)

	def test_default_model_falls_back_to_none_when_empty(self) -> None:
		settings = frappe.get_single(SETTINGS_DOCTYPE)
		settings.anthropic_api_key = _FAKE_KEY
		settings.anthropic_default_model = ""  # explicitly blank
		settings.save(ignore_permissions=True)
		frappe.db.commit()

		creds = get_ai_credentials("anthropic")
		self.assertIsNone(creds.default_model)

	def test_zdr_only_applies_to_anthropic(self) -> None:
		"""ZDR is currently an Anthropic-specific concept. Asking for OpenAI
		credentials with OpenAI key set must return zdr_enabled=False even
		if Anthropic's ZDR is on."""

		settings = frappe.get_single(SETTINGS_DOCTYPE)
		settings.anthropic_api_key = _FAKE_KEY
		settings.anthropic_zdr_enabled = 1
		settings.openai_api_key = _FAKE_OPENAI_KEY
		settings.save(ignore_permissions=True)
		frappe.db.commit()

		openai_creds = get_ai_credentials("openai")
		self.assertEqual(openai_creds.api_key, _FAKE_OPENAI_KEY)
		self.assertFalse(openai_creds.zdr_enabled)
