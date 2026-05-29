# Copyright (c) 2026, NexeraDigital and contributors
# For license information, please see license.txt

"""Scheduled tasks for the MCP server."""

import frappe
from frappe.query_builder import Interval
from frappe.query_builder.functions import Now

from erpnext.mcp import config


def prune_audit_logs():
	"""Daily: delete MCP Audit Log rows older than ``audit_retention_days``.

	Wired via ``scheduler_events['daily']`` in hooks.py.
	"""
	days = config.audit_retention_days()
	if days <= 0:
		return
	table = frappe.qb.DocType("MCP Audit Log")
	frappe.db.delete(table, filters=(table.timestamp < (Now() - Interval(days=days))))
	frappe.db.commit()
