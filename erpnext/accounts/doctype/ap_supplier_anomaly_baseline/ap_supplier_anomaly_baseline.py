# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""AP Supplier Anomaly Baseline — per-supplier rolling mean/stddev cache (spec 08)."""

from __future__ import annotations

from frappe.model.document import Document


class APSupplierAnomalyBaseline(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		computed_at: DF.Datetime | None
		mean_grand_total: DF.Float
		sample_count: DF.Int
		stddev_grand_total: DF.Float
		supplier: DF.Link
		window_months: DF.Int
	# end: auto-generated types

	pass
