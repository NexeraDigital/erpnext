# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""AP Supplier Coding Dimension — child of AP Supplier Coding Profile (spec 06)."""

from __future__ import annotations

from frappe.model.document import Document


class APSupplierCodingDimension(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		dimension: DF.Link
		dimension_doctype: DF.Data | None
		dimension_value: DF.DynamicLink
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
	# end: auto-generated types

	pass
