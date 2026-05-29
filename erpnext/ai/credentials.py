# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""Credentials helper for AI providers.

Single entry point used by every AI-powered feature in this app to fetch
provider credentials. Resolves API keys from the ``AI Provider Settings``
Single DocType (where they are stored as Frappe ``Password`` fields,
encrypted at rest in the ``__Auth`` table per Frappe convention).

Never logs or echoes the API key. ``AICredentialsNotConfigured`` exception
messages are deliberately key-free so a stack trace surfaced to a user does
not leak the secret.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import frappe
from frappe.utils.password import get_decrypted_password

SETTINGS_DOCTYPE = "AI Provider Settings"

# Providers currently recognised by the helper. Extend this tuple AND add
# the matching pair of fields to ``ai_provider_settings.json`` to register
# a new provider — the lookup tables below are keyed by these strings.
SUPPORTED_PROVIDERS = ("anthropic", "openai")
Provider = Literal["anthropic", "openai"]

_API_KEY_FIELD = {
	"anthropic": "anthropic_api_key",
	"openai": "openai_api_key",
}

_DEFAULT_MODEL_FIELD = {
	"anthropic": "anthropic_default_model",
	"openai": "openai_default_model",
}

# ZDR (Zero Data Retention) is an Anthropic-specific contract flag. Other
# providers may have analogous flags later; keyed lookup leaves room.
_ZDR_FIELD = {
	"anthropic": "anthropic_zdr_enabled",
}


class AICredentialsNotConfigured(frappe.ValidationError):
	"""Raised when ``get_ai_credentials`` is called for a provider that has
	no API key stored. Inherits ``ValidationError`` so the desk / API
	surfaces it as a 4xx rather than a 500. The message names the provider
	and points the operator at the right form — it does NOT echo the key
	(there is no key to echo, but the convention matters for the OpenAI
	case where a partial value might otherwise tempt a log line)."""


@dataclass(frozen=True)
class AICredentials:
	provider: str
	api_key: str
	default_model: str | None
	zdr_enabled: bool


def get_ai_credentials(provider: str) -> AICredentials:
	"""Return decrypted credentials for the named provider.

	Raises ``ValueError`` if the provider is not recognised.
	Raises ``AICredentialsNotConfigured`` if recognised but no API key set.
	"""

	if provider not in SUPPORTED_PROVIDERS:
		raise ValueError(
			f"Unknown AI provider {provider!r}. Supported: {', '.join(SUPPORTED_PROVIDERS)}."
		)

	api_key_field = _API_KEY_FIELD[provider]
	api_key = get_decrypted_password(
		SETTINGS_DOCTYPE, SETTINGS_DOCTYPE, api_key_field, raise_exception=False
	)

	if not api_key:
		raise AICredentialsNotConfigured(
			f"No API key configured for AI provider '{provider}'. "
			f"Set it in AI Provider Settings (/app/ai-provider-settings) "
			f"as a System Manager."
		)

	default_model = frappe.db.get_single_value(
		SETTINGS_DOCTYPE, _DEFAULT_MODEL_FIELD[provider]
	)

	zdr_field = _ZDR_FIELD.get(provider)
	zdr_enabled = bool(frappe.db.get_single_value(SETTINGS_DOCTYPE, zdr_field)) if zdr_field else False

	return AICredentials(
		provider=provider,
		api_key=api_key,
		default_model=default_model or None,
		zdr_enabled=zdr_enabled,
	)
