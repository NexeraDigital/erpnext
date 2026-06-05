# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""AP Stream Rule — a data-driven intake-classification rule.

Child rows of ``AP Closed Loop Settings.stream_rules``. Each row maps a signal
(filename / sender_domain / body / label) + pattern to a stream (Receipt/Invoice)
so non-engineers can tune Receipt-vs-Invoice tagging with no code change. Read
back via ``ap_closed_loop_settings.get_stream_rules()`` and consumed by
``document_capture.classify_stream_at_intake``. See
docs/spec/02-intake-stream-tagging.md §5.1.2.
"""

from __future__ import annotations

from frappe.model.document import Document


class APStreamRule(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		assign_stream: DF.Literal["Receipt (R)", "Invoice (I)"]
		enabled: DF.Check
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		pattern: DF.Data
		priority: DF.Int
		signal: DF.Literal["filename", "sender_domain", "body", "label"]
	# end: auto-generated types
	pass
