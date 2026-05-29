# Copyright (c) 2026, NexeraDigital and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class MCPAuditLog(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		args_json: DF.Code | None
		client_id: DF.Data | None
		error_message: DF.SmallText | None
		error_type: DF.Data | None
		ip_address: DF.Data | None
		latency_ms: DF.Int
		protocol_version: DF.Data | None
		result_bytes: DF.Int
		result_status: DF.Literal["Success", "Error", "Timeout", "PermissionDenied"]
		result_truncated: DF.Check
		session_id: DF.Data | None
		timestamp: DF.Datetime | None
		tool: DF.Data | None
		user: DF.Link | None
	# end: auto-generated types

	pass


def get_permission_query_conditions(user: str | None = None) -> str:
	"""Row-level filter for the MCP Audit Log list view.

	System Manager and Auditor see every row; everyone else sees only their own
	calls. Mirrors the API-side scoping so the Desk list cannot leak other users'
	activity. Wired via ``permission_query_conditions`` in ``hooks.py``.
	"""
	if not user:
		user = frappe.session.user

	roles = frappe.get_roles(user)
	if "System Manager" in roles or "Auditor" in roles or user == "Administrator":
		return ""

	return f"""(`tabMCP Audit Log`.`user` = {frappe.db.escape(user)})"""
