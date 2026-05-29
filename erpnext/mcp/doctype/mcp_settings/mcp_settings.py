# Copyright (c) 2026, NexeraDigital and contributors
# For license information, please see license.txt

import json

import frappe
from frappe.model.document import Document


class MCPSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		allowed_origins: DF.Code | None
		allowed_protocol_versions: DF.Code | None
		audit_output_max_bytes: DF.Int
		audit_retention_days: DF.Int
		enabled: DF.Check
		oauth_resource_uri: DF.Data | None
		require_tls: DF.Check
	# end: auto-generated types

	def validate(self):
		self._validate_json_list("allowed_origins")
		self._validate_json_list("allowed_protocol_versions")

	def _validate_json_list(self, fieldname: str):
		raw = self.get(fieldname)
		if not raw:
			return
		try:
			value = json.loads(raw)
		except (ValueError, TypeError):
			frappe.throw(frappe._("{0} must be valid JSON").format(self.meta.get_label(fieldname)))
		if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
			frappe.throw(frappe._("{0} must be a JSON list of strings").format(self.meta.get_label(fieldname)))
