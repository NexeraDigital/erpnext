# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""Document Capture Confidence — numeric per-field extraction confidence.

Child rows of ``Document Capture.field_confidences``. Each row is one logical
field (header key, or ``line_<i>_<field>`` for line rows) with the numeric score
the OCR provider returned (spec 04). ``is_above_threshold`` is derived at write
time against the per-field threshold so confidence routing ([[09-confidence-routing]])
can filter on a real, indexable column rather than parsing ``ocr_raw_response``.
See docs/spec/04-extraction-confidence-line-items.md §5.1.
"""

from __future__ import annotations

from frappe.model.document import Document


class DocumentCaptureConfidence(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		confidence: DF.Float
		field_name: DF.Data
		is_above_threshold: DF.Check
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		score_source: DF.Literal["Model", "Derived-Mapping"]
	# end: auto-generated types
	pass
