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

import frappe
from frappe.model.document import Document


class APClosedLoopSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		default_company: DF.Link | None
		default_cost_center: DF.Link | None
		default_expense_account: DF.Link | None
		default_item_code: DF.Link | None
		default_uom: DF.Link | None
		default_warehouse: DF.Link | None
	# end: auto-generated types

	pass


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


@frappe.whitelist()
def get_promote_defaults_for_ui() -> dict:
	"""Whitelisted wrapper so the form's Promote dialog can prefill without
	going through ``frappe.client.get_doc`` (which triggers the same
	set_missing_values auto-population we deliberately skip on the server)."""

	defaults = get_promote_defaults()
	return {f"default_{k}": v for k, v in defaults.items()}
