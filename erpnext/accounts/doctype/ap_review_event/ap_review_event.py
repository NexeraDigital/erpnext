# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""AP Review Event — append-only step-9 instrumentation log (spec 10).

One row per clerk/system review action, carrying a fixed-vocabulary root-cause tag
so the weekly 'Top step-9 root causes' report can ``GROUP BY root_cause_tag``. Rows
are written exclusively by ``emit_review_event`` in the AP Invoice Capture
controller; the DocType is clerk-read-only (append-only telemetry).
"""

from __future__ import annotations

from frappe.model.document import Document


class APReviewEvent(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		action_taken: DF.Literal[
			"field_corrected",
			"supplier_created",
			"rejected",
			"classified_other",
			"coding_completed",
		]
		capture: DF.Link
		clerk: DF.Link | None
		created: DF.Datetime | None
		exception_reason_code: DF.Data | None
		fields_changed: DF.SmallText | None
		note: DF.SmallText | None
		root_cause_tag: DF.Literal[
			"",
			"extraction_miss",
			"supplier_unmapped",
			"confidence_threshold_too_tight",
			"stream_mistag",
			"policy_violation",
			"vendor_error",
			"missing_po",
			"other",
		]
		time_to_resolve_seconds: DF.Int
	# end: auto-generated types

	pass
