# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""AP Capture Rejection Log — reject/reopen audit child rows (spec 10)."""

from __future__ import annotations

from frappe.model.document import Document


class APCaptureRejectionLog(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		action: DF.Literal["Rejected", "Reopened"]
		actor: DF.Link | None
		from_status: DF.Data | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		reason: DF.SmallText | None
		timestamp: DF.Datetime | None
		to_status: DF.Data | None
	# end: auto-generated types

	pass
