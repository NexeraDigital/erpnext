# Copyright (c) 2026, NexeraDigital and contributors
# For license information, please see license.txt

"""Tool-layer unit tests (plan §7.1 #2): schema, validation, output sanitization."""

import unittest

from pydantic import ValidationError

from erpnext.mcp.tools import get_catalogue
from erpnext.mcp.tools.ap_invoices import ListAPInvoices
from erpnext.mcp.tools.base import _strip_controls


class TestInputValidation(unittest.TestCase):
	def test_limit_upper_bound_enforced(self):
		with self.assertRaises(ValidationError):
			ListAPInvoices.input_model(limit=999)

	def test_limit_lower_bound_enforced(self):
		with self.assertRaises(ValidationError):
			ListAPInvoices.input_model(limit=0)

	def test_negative_min_grand_total_rejected(self):
		with self.assertRaises(ValidationError):
			ListAPInvoices.input_model(min_grand_total=-1)

	def test_valid_input_accepted(self):
		m = ListAPInvoices.input_model(supplier="ACME", limit=10)
		self.assertEqual(m.limit, 10)


class TestSchemaGeneration(unittest.TestCase):
	def test_input_schema_is_object_and_keeps_constraints(self):
		schema = ListAPInvoices.input_schema()
		self.assertEqual(schema.get("type"), "object")
		limit = schema["properties"]["limit"]
		# The constraint the FAC/frappe-mcp signature-inference would silently drop.
		self.assertEqual(limit.get("maximum"), 200)
		self.assertEqual(limit.get("minimum"), 1)

	def test_list_tool_output_schema_wraps_results(self):
		schema = ListAPInvoices.output_schema()
		self.assertEqual(schema["type"], "object")
		self.assertIn("results", schema["properties"])
		self.assertEqual(schema["properties"]["results"]["type"], "array")

	def test_every_tool_declares_scope_and_schema(self):
		for name, cls in get_catalogue().items():
			self.assertTrue(cls.required_scope, f"{name} missing required_scope")
			self.assertIsNotNone(cls.input_model, f"{name} missing input_model")
			self.assertEqual(cls.input_schema().get("type"), "object")
			self.assertTrue(cls.annotations.get("readOnlyHint"), f"{name} not readOnly")


class TestOutputSanitization(unittest.TestCase):
	def test_strip_control_chars_in_strings(self):
		self.assertEqual(_strip_controls("ab\x00c\x1bd"), "abcd")

	def test_strip_preserves_whitespace(self):
		self.assertEqual(_strip_controls("a\tb\nc"), "a\tb\nc")

	def test_strip_recurses_into_containers(self):
		out = _strip_controls({"k": ["x\x07y", {"z": "p\x00q"}]})
		self.assertEqual(out["k"][0], "xy")
		self.assertEqual(out["k"][1]["z"], "pq")
