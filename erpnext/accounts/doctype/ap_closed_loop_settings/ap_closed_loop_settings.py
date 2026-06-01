# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""AP Closed Loop Settings.

Single DocType holding site-wide defaults used by the AP Invoice Capture
promote step. The four "required" defaults (company, item_code, expense_
account, cost_center) fill in values that are not on the invoice image and
that the Purchase Invoice schema requires to post. The two "optional"
defaults (warehouse, uom) extend the Item line when applicable.

Reads typically go through ``frappe.db.get_single_value`` for cheap
single-field lookups; ``promote_to_purchase_invoice`` calls a helper that
gathers all six in one round trip via ``frappe.get_single``.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.model.document import Document

# Maps the human-readable ocr_provider select option to the registry key used
# by erpnext.accounts.ap_closed_loop.extractors.registry.get_extractor.
OCR_PROVIDER_REGISTRY_KEY = {
	"Fake (Deterministic)": "fake",
	"Anthropic Claude": "anthropic",
}
DEFAULT_OCR_CONFIDENCE_THRESHOLD = 0.70
DEFAULT_AUTO_POST_THRESHOLD = 1000.0
DEFAULT_DEDUPE_WINDOW_DAYS = 90


class APClosedLoopSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from erpnext.accounts.doctype.ap_stream_rule.ap_stream_rule import APStreamRule

		ap_intake_email_account: DF.Link | None
		default_company: DF.Link | None
		default_cost_center: DF.Link | None
		default_expense_account: DF.Link | None
		default_item_code: DF.Link | None
		default_uom: DF.Link | None
		default_warehouse: DF.Link | None
		ocr_provider: DF.Literal["Fake (Deterministic)", "Anthropic Claude"]
		ocr_model: DF.Literal["claude-haiku-4-5-20251001", "claude-sonnet-4-6"]
		ocr_fallback_model: DF.Literal["", "claude-sonnet-4-6"]
		ocr_confidence_threshold: DF.Float
		ocr_max_file_mb: DF.Int
		ocr_force_reextract: DF.Check
		auto_post_amount_threshold: DF.Float
		credit_card_clearing_account: DF.Link | None
		dedupe_window_days: DF.Int
		enforce_sod: DF.Check
		field_thresholds: DF.JSON | None
		sod_threshold_amount: DF.Float
		stream_rules: DF.Table[APStreamRule]
		unmapped_card_spend_account: DF.Link | None
	# end: auto-generated types

	def validate(self) -> None:
		self._validate_ocr_provider_has_credentials()
		self._validate_confidence_threshold()

	def _validate_ocr_provider_has_credentials(self) -> None:
		"""If the live provider is selected, the Anthropic key must be set on
		AI Provider Settings. We check via the credentials helper so the error
		message points the operator at the right form and never echoes a key."""

		if self.ocr_provider != "Anthropic Claude":
			return
		from erpnext.ai.credentials import AICredentialsNotConfigured, get_ai_credentials

		try:
			get_ai_credentials("anthropic")
		except AICredentialsNotConfigured:
			frappe.throw(
				_(
					"OCR Provider is set to Anthropic Claude, but no Anthropic API key "
					"is configured. Set it in AI Provider Settings "
					"(/app/ai-provider-settings) as a System Manager, then save again."
				)
			)

	def _validate_confidence_threshold(self) -> None:
		threshold = self.ocr_confidence_threshold
		if threshold and not (0.0 <= threshold <= 1.0):
			frappe.throw(_("OCR Confidence Threshold must be between 0 and 1."))


def get_promote_defaults() -> dict:
	"""Return a flat dict of promote defaults derived from this Single.

	Reads the raw stored values via ``frappe.db.get_singles_dict`` rather
	than ``frappe.get_single`` because the latter runs ``set_missing_values``
	and auto-populates empty Link fields from the user's session defaults
	— which is a footgun here: an unconfigured ``default_warehouse`` would
	come back as "the user's default warehouse" (e.g. "Stores - TQC") and
	end up applied across captures whose target Company can't see it.

	Empty values are omitted so a caller's explicit ``defaults`` dict
	always wins on a per-field basis (settings only fill gaps).
	"""

	stored = frappe.db.get_singles_dict("AP Closed Loop Settings") or {}
	candidate = {
		"company": stored.get("default_company"),
		"item_code": stored.get("default_item_code"),
		"expense_account": stored.get("default_expense_account"),
		"cost_center": stored.get("default_cost_center"),
		"warehouse": stored.get("default_warehouse"),
		"uom": stored.get("default_uom"),
	}
	return {k: v for k, v in candidate.items() if v}


def get_ocr_config() -> dict:
	"""Return the OCR provider configuration for run_extraction.

	Reads raw stored values (``get_singles_dict``) and resolves the
	human-readable provider option to a registry key. Falls back to the
	deterministic fake provider when unset, so a fresh/empty site keeps the
	pre-Phase-3 behaviour (no real API calls until explicitly configured).
	"""

	stored = frappe.db.get_singles_dict("AP Closed Loop Settings") or {}
	provider_label = stored.get("ocr_provider") or "Fake (Deterministic)"
	provider_key = OCR_PROVIDER_REGISTRY_KEY.get(provider_label, "fake")

	# Singles store values as text, so a stored 0 arrives as "0.0" (truthy).
	# Convert first, then treat blank / non-positive as "use the default" — a
	# zero threshold would flag nothing ambiguous, which is never intended.
	raw_threshold = stored.get("ocr_confidence_threshold")
	try:
		threshold = float(raw_threshold) if raw_threshold not in (None, "") else 0.0
	except (TypeError, ValueError):
		threshold = 0.0
	if threshold <= 0:
		threshold = DEFAULT_OCR_CONFIDENCE_THRESHOLD

	max_mb = stored.get("ocr_max_file_mb")
	try:
		max_mb = int(max_mb) if max_mb else 25
	except (TypeError, ValueError):
		max_mb = 25

	return {
		"provider": provider_key,
		"model": stored.get("ocr_model") or None,
		"fallback_model": stored.get("ocr_fallback_model") or None,
		"confidence_threshold": threshold,
		"max_file_mb": max_mb,
		"force_reextract": bool(stored.get("ocr_force_reextract")),
	}


def _settings() -> dict:
	"""Raw stored Single values (text), via get_singles_dict — never get_single
	(which auto-populates empty Links from session defaults; see
	get_promote_defaults)."""

	return frappe.db.get_singles_dict("AP Closed Loop Settings") or {}


def get_auto_post_threshold() -> float:
	"""Stream-I auto-post / auto-approval amount threshold.

	Falls back to DEFAULT_AUTO_POST_THRESHOLD (1000.0) when blank / non-positive
	so empty-settings sites keep the pre-foundation behaviour. Replaces the
	hard-coded AUTO_APPROVAL_THRESHOLD_DEFAULT in ap_invoice_capture."""

	raw = _settings().get("auto_post_amount_threshold")
	try:
		value = float(raw) if raw not in (None, "") else 0.0
	except (TypeError, ValueError):
		value = 0.0
	return value if value > 0 else DEFAULT_AUTO_POST_THRESHOLD


def get_dedupe_window_days() -> int:
	"""Cross-capture dedupe horizon in days (consumed by the dedup step).

	Falls back to DEFAULT_DEDUPE_WINDOW_DAYS (90) when blank / non-positive."""

	raw = _settings().get("dedupe_window_days")
	try:
		value = int(float(raw)) if raw not in (None, "") else 0
	except (TypeError, ValueError):
		value = 0
	return value if value > 0 else DEFAULT_DEDUPE_WINDOW_DAYS


def get_confidence_threshold(field: str | None = None) -> float:
	"""Per-field confidence floor. Resolution order:

	1. a per-field override in the field_thresholds JSON (when ``field`` given),
	2. the canonical ocr_confidence_threshold scalar,
	3. DEFAULT_OCR_CONFIDENCE_THRESHOLD (0.70).

	D1: ocr_confidence_threshold stays the single canonical stored scalar — no
	separate per_field_confidence_threshold field is added."""

	stored = _settings()

	if field:
		overrides = _coerce_field_thresholds(stored.get("field_thresholds"))
		if field in overrides:
			try:
				return float(overrides[field])
			except (TypeError, ValueError):
				pass

	raw = stored.get("ocr_confidence_threshold")
	try:
		value = float(raw) if raw not in (None, "") else 0.0
	except (TypeError, ValueError):
		value = 0.0
	return value if value > 0 else DEFAULT_OCR_CONFIDENCE_THRESHOLD


def get_field_threshold(field: str) -> float:
	"""Thin alias for get_confidence_threshold(field)."""

	return get_confidence_threshold(field)


def get_sod_config() -> dict:
	"""Segregation-of-duties config consumed by the approval step (spec 11).

	``enforce`` defaults ON when unset."""

	stored = _settings()
	raw_enforce = stored.get("enforce_sod")
	if raw_enforce in (None, ""):
		enforce = True
	else:
		try:
			enforce = bool(int(float(raw_enforce)))
		except (TypeError, ValueError):
			enforce = True
	try:
		threshold = float(stored.get("sod_threshold_amount") or 0)
	except (TypeError, ValueError):
		threshold = 0.0
	return {"enforce": enforce, "threshold": threshold}


def _coerce_field_thresholds(raw) -> dict:
	"""Parse the field_thresholds JSON Single value (stored as text) into a dict."""

	if not raw:
		return {}
	if isinstance(raw, dict):
		return raw
	try:
		parsed = json.loads(raw)
	except (TypeError, ValueError):
		return {}
	return parsed if isinstance(parsed, dict) else {}


def get_stream_rules() -> list[dict]:
	"""Enabled stream-tagging rules ordered by priority (spec 02 §5.1.3).

	Child rows don't round-trip through get_singles_dict, so read them directly
	via get_all. Returns [] on a fresh site (no rules -> everything Unclassified,
	which is the correct fallthrough)."""

	return frappe.get_all(
		"AP Stream Rule",
		filters={"parent": "AP Closed Loop Settings", "enabled": 1},
		fields=["priority", "signal", "pattern", "assign_stream"],
		order_by="priority asc",
	)


@frappe.whitelist()
def get_promote_defaults_for_ui() -> dict:
	"""Whitelisted wrapper so the form's Promote dialog can prefill without
	going through ``frappe.client.get_doc`` (which triggers the same
	set_missing_values auto-population we deliberately skip on the server)."""

	defaults = get_promote_defaults()
	return {f"default_{k}": v for k, v in defaults.items()}
