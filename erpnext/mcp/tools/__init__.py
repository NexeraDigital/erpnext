# Copyright (c) 2026, NexeraDigital and contributors
# For license information, please see license.txt

"""MCP tool catalogue (v1: AP, read-only).

The catalogue is a static, code-defined registry of tool classes. Per-request
visibility (enabled / role / scope) and wrapping are handled by
``erpnext.mcp.registry``.
"""

from erpnext.mcp.tools.ap_invoices import GetAPInvoice, ListAPInvoices
from erpnext.mcp.tools.base import BaseTool
from erpnext.mcp.tools.schema import GetDoctypeMeta
from erpnext.mcp.tools.vendors import GetVendorBalance, ListVendors

# Order is the order tools appear in tools/list.
CATALOGUE: list[type[BaseTool]] = [
	ListAPInvoices,
	GetAPInvoice,
	ListVendors,
	GetVendorBalance,
	GetDoctypeMeta,
]


def get_catalogue() -> dict[str, type[BaseTool]]:
	"""Return ``{tool_name: ToolClass}`` for the whole v1 catalogue."""
	return {cls.name: cls for cls in CATALOGUE}
