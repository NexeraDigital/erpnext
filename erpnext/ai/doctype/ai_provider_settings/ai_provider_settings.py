# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""AI Provider Settings.

Single DocType. System Manager only. Holds API keys and shared configuration
for AI providers (Anthropic, OpenAI, etc.) so every AI-powered feature in
this app reads credentials from one place.

This DocType deliberately does NOT hold feature-specific tuning (which model
the AP OCR uses, what confidence threshold triggers a fallback, etc.). Those
live on per-feature settings DocTypes such as ``AP Closed Loop Settings``.
The split lets AP Managers configure how AP uses AI without giving them
visibility into the underlying credentials.

Reads go through ``erpnext.ai.credentials.get_ai_credentials(provider)``,
which handles the Password-field decryption and raises a clear, key-free
exception when a provider is not configured.
"""

from __future__ import annotations

import frappe
from frappe.model.document import Document


class AIProviderSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		anthropic_api_key: DF.Password | None
		anthropic_default_model: DF.Data | None
		anthropic_zdr_enabled: DF.Check
		openai_api_key: DF.Password | None
		openai_default_model: DF.Data | None
	# end: auto-generated types

	def validate(self) -> None:
		"""Trim whitespace on API key fields so a stray newline or trailing
		space in a copy-paste doesn't silently produce a 401 from the
		provider. Do NOT validate the key by calling the provider here —
		that belongs in a separate "test connection" action if we ever
		want one."""

		for fieldname in ("anthropic_api_key", "openai_api_key"):
			value = self.get(fieldname)
			if value and isinstance(value, str):
				stripped = value.strip()
				if stripped != value:
					self.set(fieldname, stripped)
