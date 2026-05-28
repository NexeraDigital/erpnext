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

	Empty values are omitted so a caller's explicit ``defaults`` dict
	always wins on a per-field basis (settings only fill gaps).
	"""

	doc = frappe.get_single("AP Closed Loop Settings")
	candidate = {
		"company": doc.default_company,
		"item_code": doc.default_item_code,
		"expense_account": doc.default_expense_account,
		"cost_center": doc.default_cost_center,
		"warehouse": doc.default_warehouse,
		"uom": doc.default_uom,
	}
	return {k: v for k, v in candidate.items() if v}
