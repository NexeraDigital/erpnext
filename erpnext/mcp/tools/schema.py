# Copyright (c) 2026, NexeraDigital and contributors
# For license information, please see license.txt

"""Schema introspection tool: get_doctype_meta (plan §5).

Allowlisted DocTypes only — per §3.7 rule 10, DocType identifiers from tool input
are never trusted without an allowlist (qb/meta parameterize values, not
identifiers).
"""

from __future__ import annotations

from typing import Literal, Optional

import frappe
from pydantic import BaseModel, Field

from erpnext.mcp.permissions import ensure_can_read
from erpnext.mcp.tools.base import BaseTool

# The only DocTypes this tool will introspect.
_ALLOWLIST = ("Purchase Invoice", "Purchase Invoice Item", "Supplier")


class GetDoctypeMetaInput(BaseModel):
	doctype: Literal["Purchase Invoice", "Purchase Invoice Item", "Supplier"] = Field(
		..., description="DocType to introspect (allowlisted)"
	)


class FieldMeta(BaseModel):
	fieldname: str
	label: Optional[str] = None
	fieldtype: Optional[str] = None
	options: Optional[str] = None
	reqd: Optional[int] = None


class DoctypeMeta(BaseModel):
	doctype: str
	fields: list[FieldMeta] = []


class GetDoctypeMeta(BaseTool):
	name = "get_doctype_meta"
	title = "Get DocType Schema"
	description = (
		"Return the field schema (name, label, type, options) for an allowlisted "
		"DocType so a client can construct valid filters. Allowlist: Purchase "
		"Invoice, Purchase Invoice Item, Supplier."
	)
	required_scope = "erpnext:schema:read"
	annotations = {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False}
	input_model = GetDoctypeMetaInput
	output_model = DoctypeMeta
	output_is_list = False

	def execute(self, args: GetDoctypeMetaInput) -> dict:
		# Defense-in-depth: Pydantic Literal already enforces the allowlist, but
		# re-check so a future input-model change cannot silently widen access.
		if args.doctype not in _ALLOWLIST:
			frappe.throw(frappe._("DocType not permitted for introspection."), frappe.PermissionError)

		# The caller must be able to read the DocType to see its schema.
		ensure_can_read(args.doctype)

		meta = frappe.get_meta(args.doctype)
		fields = [
			{
				"fieldname": df.fieldname,
				"label": df.label,
				"fieldtype": df.fieldtype,
				"options": df.options,
				"reqd": df.reqd,
			}
			for df in meta.fields
			if df.fieldtype not in ("Section Break", "Column Break", "Tab Break", "HTML")
		]
		return {"doctype": args.doctype, "fields": fields}
