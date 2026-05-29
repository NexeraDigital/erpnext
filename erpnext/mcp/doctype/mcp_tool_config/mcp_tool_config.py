# Copyright (c) 2026, NexeraDigital and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class MCPToolConfig(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		concurrency_cap: DF.Int
		enabled: DF.Check
		rate_limit_per_minute: DF.Int
		required_oauth_scope: DF.Data | None
		required_role: DF.Link | None
		timeout_seconds: DF.Int
		tool_name: DF.Data
	# end: auto-generated types

	def on_update(self):
		# Tool config is read on every request; bust the cache so an ops kill
		# switch takes effect immediately across workers.
		frappe.cache.delete_value("mcp_tool_config")
