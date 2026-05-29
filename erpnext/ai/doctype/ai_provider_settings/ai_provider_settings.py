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
from frappe.utils.password import get_decrypted_password

# Characters Frappe's desk-form frontend may render as the masked placeholder
# for a Password field. When the user saves the form without re-typing the
# field, the POST body can echo back a string composed entirely of these
# characters — which the framework would otherwise persist verbatim (in the
# raw ``tabSingles`` row, NOT in the encrypted ``__Auth`` table — i.e., a
# silent destruction of the real key). We detect that case in ``validate``
# and restore the previously-stored value instead.
_PASSWORD_PLACEHOLDER_CHARS = frozenset("*•·●")


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
		"""Two guards on the Password fields:

		1. Trim whitespace so a stray newline or trailing space in a
		   copy-paste doesn't silently produce a 401 from the provider.
		2. Detect the desk's masked-placeholder echo (all asterisks/bullets)
		   and restore the previously-stored value, so a no-change save
		   does NOT replace a real encrypted key with raw asterisks.

		Do NOT validate the key by calling the provider here — that belongs
		in a separate "test connection" action if we ever want one.
		"""

		for fieldname in ("anthropic_api_key", "openai_api_key"):
			self._trim_password(fieldname)
			self._restore_password_if_placeholder(fieldname)

	def _trim_password(self, fieldname: str) -> None:
		value = self.get(fieldname)
		if value and isinstance(value, str):
			stripped = value.strip()
			if stripped != value:
				self.set(fieldname, stripped)

	def _restore_password_if_placeholder(self, fieldname: str) -> None:
		value = self.get(fieldname)
		if not value or not isinstance(value, str):
			return
		if not set(value).issubset(_PASSWORD_PLACEHOLDER_CHARS):
			return
		# The submitted value is the frontend's masked placeholder, not a
		# real key. Restore whatever was previously stored (None if nothing
		# was stored — which leaves the field empty, the safe outcome).
		previous = get_decrypted_password(
			self.doctype, self.name, fieldname, raise_exception=False
		)
		self.set(fieldname, previous)
