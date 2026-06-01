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

DESTRUCTIVE-TEST GUARD (do not re-introduce ``frappe.db.commit()``):
  AI Provider Settings holds the operator's REAL Anthropic/OpenAI API keys on a
  live/dev site. These tests mutate and clear those password fields. They run
  entirely inside the IntegrationTestCase transaction and **never commit**, so
  every mutation is rolled back in ``tearDown`` and a pre-existing, committed key
  is restored untouched. Committing here would PERMANENTLY ERASE the operator's
  key (this happened — see git history). ``get_ai_credentials`` reads ``__Auth``
  on the same DB connection, so it sees uncommitted writes within the test — no
  commit is needed for the round-trip assertions to pass.
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


def _clear_keys_in_txn() -> None:
	"""Clear both provider keys WITHIN the test transaction (never committed).

	Gives each test a clean slate; ``tearDown``'s rollback restores whatever the
	site really had (including a live key) because nothing here is committed.
	"""
	remove_encrypted_password(SETTINGS_DOCTYPE, SETTINGS_DOCTYPE, "anthropic_api_key")
	remove_encrypted_password(SETTINGS_DOCTYPE, SETTINGS_DOCTYPE, "openai_api_key")


class TestAICredentialsHelper(IntegrationTestCase):
	"""End-to-end behavior of get_ai_credentials against a real (test) site."""

	def setUp(self) -> None:
		_clear_keys_in_txn()

	def tearDown(self) -> None:
		# Roll back the whole transaction — restores any real, committed key and
		# discards every mutation this test made. NEVER commit in this suite.
		frappe.db.rollback()

	def test_round_trip_anthropic_key(self) -> None:
		# Arrange: save a key via the document (so encryption happens via the
		# real Password-field write path, not by manually inserting into __Auth).
		settings = frappe.get_single(SETTINGS_DOCTYPE)
		settings.anthropic_api_key = _FAKE_KEY
		settings.anthropic_default_model = "claude-haiku-4-5-20251001"
		settings.anthropic_zdr_enabled = 1
		settings.save(ignore_permissions=True)

		# Act
		creds = get_ai_credentials("anthropic")

		# Assert
		self.assertIsInstance(creds, AICredentials)
		self.assertEqual(creds.provider, "anthropic")
		self.assertEqual(creds.api_key, _FAKE_KEY)
		self.assertEqual(creds.default_model, "claude-haiku-4-5-20251001")
		self.assertTrue(creds.zdr_enabled)

	def test_raises_when_anthropic_key_not_set(self) -> None:
		# setUp already cleared the key (within the transaction).
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

		openai_creds = get_ai_credentials("openai")
		self.assertEqual(openai_creds.api_key, _FAKE_OPENAI_KEY)
		self.assertFalse(openai_creds.zdr_enabled)


class TestPasswordPlaceholderProtection(IntegrationTestCase):
	"""Regression tests for the desk-form bug where a no-change save echoes
	the masked-asterisks placeholder back as the field value, which the
	framework would otherwise persist verbatim — silently replacing any
	real stored key with raw asterisks."""

	def setUp(self) -> None:
		_clear_keys_in_txn()

	def tearDown(self) -> None:
		frappe.db.rollback()

	def test_placeholder_save_with_no_prior_key_does_not_store_anything(self) -> None:
		"""User opens the form, clicks Save without typing. Frontend echoes
		back asterisks. After save, the field should remain empty."""

		settings = frappe.get_single(SETTINGS_DOCTYPE)
		settings.anthropic_api_key = "*" * 30  # simulates desk frontend placeholder
		settings.save(ignore_permissions=True)

		with self.assertRaises(AICredentialsNotConfigured):
			get_ai_credentials("anthropic")

	def test_placeholder_save_with_existing_key_preserves_the_key(self) -> None:
		"""User has a real key stored. They open the form to toggle some
		other field (e.g., ZDR) and save. Frontend echoes back asterisks for
		the password field. The real key must survive."""

		# Step 1: store a real key
		settings = frappe.get_single(SETTINGS_DOCTYPE)
		settings.anthropic_api_key = _FAKE_KEY
		settings.save(ignore_permissions=True)

		# Step 2: re-fetch the doc and simulate a no-change save where the
		# frontend has substituted asterisks for the password field
		settings = frappe.get_single(SETTINGS_DOCTYPE)
		settings.anthropic_api_key = "*" * 30
		settings.anthropic_zdr_enabled = 1  # the field the user actually intended to change
		settings.save(ignore_permissions=True)

		# Step 3: the real key must still be retrievable
		creds = get_ai_credentials("anthropic")
		self.assertEqual(creds.api_key, _FAKE_KEY)
		self.assertTrue(creds.zdr_enabled)

	def test_real_value_with_only_some_asterisks_is_stored_as_typed(self) -> None:
		"""Defensive: if a key happens to contain asterisks among other
		characters (mixed input), it should still be stored as-typed —
		only pure-placeholder values are restored."""

		mixed_value = "sk-ant-real***key***xyz"
		settings = frappe.get_single(SETTINGS_DOCTYPE)
		settings.anthropic_api_key = mixed_value
		settings.save(ignore_permissions=True)

		creds = get_ai_credentials("anthropic")
		self.assertEqual(creds.api_key, mixed_value)

	def test_bullet_placeholder_also_protected(self) -> None:
		"""Some Frappe versions render the masked placeholder with bullet
		characters (•) instead of asterisks. Both must be detected."""

		settings = frappe.get_single(SETTINGS_DOCTYPE)
		settings.anthropic_api_key = "•" * 12
		settings.save(ignore_permissions=True)

		with self.assertRaises(AICredentialsNotConfigured):
			get_ai_credentials("anthropic")
