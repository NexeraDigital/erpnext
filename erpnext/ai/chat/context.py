# Copyright (c) 2026, NexeraDigital and contributors
# For license information, please see license.txt

"""Server-side re-validation and re-fetch of the client-supplied chat context.

The desk panel tells the backend what record the user is currently looking at
(``{doctype, name, view}``). That is a **convenience hint, never an authorization
input**. Before any of it becomes grounding for the model, this module:

  1. Confirms the DocType exists.
  2. Calls ``frappe.has_permission(doctype, "read", doc=name, throw=True)`` — so a
     forged/escalated context (a record the user may not read) raises
     ``frappe.PermissionError`` instead of leaking anything.
  3. Re-fetches the record server-side and applies field-level read permissions
     (``apply_fieldlevel_read_permissions``), so permlevel-masked fields never
     reach the model even if the browser "saw" them.

Field values sent from the browser are discarded — only the server's own fetch is
trusted. Nothing here writes; the chat is read-only in v1.

Grounding: ``frappe.has_permission(..., throw=True)`` and
``Document.apply_fieldlevel_read_permissions`` —
https://docs.frappe.io/framework/v15/user/en/basics/users-and-permissions and
frappe/model/document.py (version-16).
"""

from __future__ import annotations

import frappe
from frappe import _

# Document metadata / control fields that are noise as model grounding.
_SKIP_FIELDS = {
	"doctype",
	"owner",
	"modified_by",
	"docstatus",
	"idx",
	"_user_tags",
	"_comments",
	"_assign",
	"_liked_by",
	"_seen",
}

# Cap the number of scalar fields we surface so a wide DocType can't blow up the
# prompt. Child tables are omitted entirely in v1.
_MAX_CONTEXT_FIELDS = 60


def resolve_context(context: dict | None) -> dict | None:
	"""Validate + re-fetch the client context under the calling user's permissions.

	``context`` is the browser-supplied hint ``{doctype, name, view}``. Returns a
	compact, permission-checked grounding dict, or ``None`` when there is no usable
	context. Raises ``frappe.PermissionError`` if the user may not read the named
	record (the forged-context guard).
	"""
	if not context or not isinstance(context, dict):
		return None

	doctype = (context.get("doctype") or "").strip()
	if not doctype:
		return None

	if not frappe.db.exists("DocType", doctype):
		# Unknown DocType in the hint — ignore rather than error; the panel may be
		# on a non-DocType route (Workspace, Page) where there's nothing to ground.
		return None

	name = (context.get("name") or "").strip() or None
	view = (context.get("view") or "").strip() or None

	if name:
		# (2) Forged-context guard: throws PermissionError if the user can't read it.
		frappe.has_permission(doctype, "read", doc=name, throw=True)
		if not frappe.db.exists(doctype, name):
			return {"doctype": doctype, "name": name, "view": view, "exists": False}

		# (3) Re-fetch server-side; strip permlevel-masked fields.
		doc = frappe.get_doc(doctype, name)
		doc.apply_fieldlevel_read_permissions()
		return {
			"doctype": doctype,
			"name": name,
			"view": view,
			"exists": True,
			"fields": _safe_fields(doc),
		}

	# List/Report view: no single record, just the DocType the user is browsing.
	frappe.has_permission(doctype, "read", throw=True)
	return {"doctype": doctype, "view": view, "filters": _safe_filters(context.get("filters"))}


def _safe_fields(doc) -> dict:
	"""Return a trimmed, JSON-friendly dict of the doc's scalar fields.

	Child tables are omitted in v1. After ``apply_fieldlevel_read_permissions`` the
	masked fields are already ``None``; we drop control fields and empties to keep
	the grounding compact.
	"""
	out: dict = {}
	data = doc.as_dict(no_nulls=True)
	for key, value in data.items():
		if key in _SKIP_FIELDS:
			continue
		if isinstance(value, (list, dict)):
			# Skip child tables / nested structures in v1.
			continue
		if value in (None, ""):
			continue
		out[key] = value
		if len(out) >= _MAX_CONTEXT_FIELDS:
			break
	return out


def _safe_filters(filters) -> dict | None:
	"""Pass through simple list/report filters as strings only (no execution)."""
	if not filters or not isinstance(filters, dict):
		return None
	# Coerce to a shallow string map; these are descriptive grounding only and are
	# never used to query — a tool call re-derives any list under the user's perms.
	return {str(k): str(v) for k, v in list(filters.items())[:20]}


def context_summary(resolved: dict | None) -> str:
	"""One-line human/LLM-readable label, e.g. 'Purchase Invoice ACC-PINV-0001'."""
	if not resolved:
		return ""
	if resolved.get("name"):
		return _("{0} {1}").format(resolved["doctype"], resolved["name"])
	return resolved.get("doctype", "")
