# Copyright (c) 2026, NexeraDigital and contributors
# For license information, please see license.txt

"""The "permitted names" idiom — plan §4.4.

This is how the MCP server reconciles "powerful" (joins, aggregations) with
"secure" (no permission bypass). Every list/aggregation tool derives a
permission-gated set of document names via ``frappe.get_list(...).pluck("name")``
— which enforces role + user permissions + if_owner + permlevel — and then
constrains any ``frappe.qb`` join to ``WHERE name IN (<those names>)``.

References (frappe version-16):
- frappe/model/db_query.py (DatabaseQuery applies role/user/if_owner/permlevel)
- frappe/permissions.py (has_permission)
"""

import frappe


def ensure_can_read(doctype: str, parent_doctype: str | None = None) -> None:
	"""L6: assert the current user may read ``doctype``; raise PermissionError if not.

	``throw=True`` means the caller gets a ``frappe.PermissionError`` rather than a
	silently empty result. Pass ``parent_doctype`` for child tables.
	"""
	kwargs = {"throw": True}
	if parent_doctype:
		kwargs["parent_doctype"] = parent_doctype
	frappe.has_permission(doctype, "read", **kwargs)


def permitted_names(
	doctype: str,
	filters: dict | list | None = None,
	limit: int = 50,
	order_by: str | None = None,
) -> list[str]:
	"""Return names of ``doctype`` the current user may read, matching ``filters``.

	Wraps ``frappe.get_list`` with ``pluck="name"``. This enforces role + user
	permissions, if_owner, and permlevel — the canonical permission-safe name set
	for downstream ``qb`` joins. ``ignore_permissions`` is explicitly False.
	"""
	return frappe.get_list(
		doctype,
		filters=filters,
		pluck="name",
		limit_page_length=limit,
		order_by=order_by,
		ignore_permissions=False,
	)
