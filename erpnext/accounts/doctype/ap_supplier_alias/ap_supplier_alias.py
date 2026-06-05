# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""AP Supplier Alias — Tier-1 deterministic resolver entry (spec 05).

Master data curated by Accounts Managers. Maps a vendor-string pattern
(``exact`` / ``glob`` / ``regex``) to a canonical ``Supplier``. The resolver in
``document_capture._resolve_supplier`` reads only ``is_active=1`` rows and
applies precedence ``exact > glob > regex``, then ``priority`` asc, then ``name``.

A bad ``regex`` pattern must NEVER block validation: it is caught and skipped at
match time (see ``_resolve_supplier``), so this controller does not hard-reject a
malformed regex on save — a manager may legitimately save a work-in-progress
pattern. We only normalise whitespace and surface a non-blocking warning.
"""

from __future__ import annotations

import re

import frappe
from frappe import _
from frappe.model.document import Document


class APSupplierAlias(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		alias_pattern: DF.Data
		canonical_supplier: DF.Link
		is_active: DF.Check
		match_type: DF.Literal["exact", "glob", "regex"]
		notes: DF.SmallText | None
		priority: DF.Int
		source_capture: DF.Link | None
	# end: auto-generated types

	def validate(self) -> None:
		self.alias_pattern = (self.alias_pattern or "").strip()
		if not self.alias_pattern:
			frappe.throw(_("Alias Pattern is required."))
		# A malformed regex is non-blocking (skipped at match time), but warn the
		# author at save so a typo is visible rather than silently never matching.
		if self.match_type == "regex":
			try:
				re.compile(self.alias_pattern)
			except re.error as exc:
				frappe.msgprint(
					_("Regex pattern does not compile and will be skipped at match time: {0}").format(
						str(exc)
					),
					indicator="orange",
					alert=True,
				)
