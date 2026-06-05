# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""AP Invoice Capture Item — extracted invoice line item.

Child rows of ``AP Invoice Capture.line_items``. Mirrors the narrow shape of
Purchase Invoice Item (description / qty / rate / amount / expense_account /
cost_center / purchase_order / purchase_receipt) so ``promote_to_purchase_invoice``
can map one capture line → one PI item row (Stream I), and the Stream-R Journal
Entry path ([[07-classification-doctype-branching]]) can read the same rows.
See docs/spec/04-extraction-confidence-line-items.md §5.1.
"""

from __future__ import annotations

from frappe.model.document import Document


class APInvoiceCaptureItem(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		amount: DF.Currency
		confidence_summary: DF.SmallText | None
		cost_center: DF.Link | None
		currency: DF.Data | None
		description: DF.TextEditor | None
		expense_account: DF.Link | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		po_reference: DF.Link | None
		pr_reference: DF.Link | None
		qty: DF.Float
		rate: DF.Currency
		tax_amount: DF.Currency
	# end: auto-generated types
	pass
