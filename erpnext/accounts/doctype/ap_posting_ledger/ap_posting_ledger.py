# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""AP Posting Ledger controller.

Append-only DOCUMENT-level idempotency ledger. One row per (capture, step)
document-creating operation; the UNIQUE ``idempotency_key`` index is the
double-post guard. Rows are written server-side by
``erpnext.accounts.ap_closed_loop.idempotency.with_idempotency`` and are not
meant to be created or edited by hand. See
docs/spec/01-foundations-settings-async-idempotency.md.
"""

from __future__ import annotations

from frappe.model.document import Document


class APPostingLedger(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		capture: DF.Link
		idempotency_key: DF.Data
		posted_at: DF.Datetime | None
		result_doctype: DF.Data | None
		result_name: DF.Data | None
		step: DF.Data | None
	# end: auto-generated types

	pass
