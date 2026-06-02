# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""AP Supplier Coding Profile — per-supplier GL auto-coding master (spec 06).

Layers default expense account / cost center / purchase-tax template / payment
terms / accounting dimensions on top of native Party Account + Supplier.payment_
terms + tax_category. One row per Supplier (autoname ``field:supplier``, unique),
so the resolver is a single ``frappe.db.exists`` / ``get_doc`` keyed on the
matched supplier. Single-company pilot scope (decision D1) — company comes from
``AP Closed Loop Settings.default_company`` and the payable account stays native.
"""

from __future__ import annotations

from frappe.model.document import Document


class APSupplierCodingProfile(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from erpnext.accounts.doctype.ap_supplier_coding_dimension.ap_supplier_coding_dimension import (
			APSupplierCodingDimension,
		)

		coding_notes: DF.SmallText | None
		default_accounting_dimensions: DF.Table[APSupplierCodingDimension]
		default_cost_center: DF.Link | None
		default_expense_account: DF.Link | None
		default_payment_terms_template: DF.Link | None
		default_purchase_tax_template: DF.Link | None
		qty_tolerance_pct: DF.Float
		amount_tolerance_pct: DF.Float
		anomaly_multiple: DF.Float
		anomaly_sigma: DF.Float
		anomaly_min_sample: DF.Int
		supplier: DF.Link
	# end: auto-generated types

	pass
