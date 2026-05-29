# Copyright (c) 2026, NexeraDigital and contributors
# For license information, please see license.txt

"""Permission-bypass canaries (plan §7.2).

Pure static greps over our own MCP source (the vendored ``_vendor/`` tree is
excluded — it is reviewed third-party MIT code, not our tool surface). These
fail the build if a permission-bypass pattern slips into a tool.
"""

import os
import re
import unittest

_MCP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_VENDOR = os.path.join(_MCP_DIR, "_vendor")
_TESTS = os.path.dirname(os.path.abspath(__file__))

# Canaries scan production source only. The vendored tree is reviewed third-party
# code, and the tests themselves reference the forbidden patterns by design.
_SKIP_DIRS = (_VENDOR, _TESTS)


def _py_files(root: str):
	for dirpath, _dirs, files in os.walk(root):
		if any(dirpath == d or dirpath.startswith(d + os.sep) for d in _SKIP_DIRS):
			continue
		for f in files:
			if f.endswith(".py"):
				yield os.path.join(dirpath, f)


def _read(path: str) -> str:
	with open(path, encoding="utf-8") as fh:
		return fh.read()


class TestCanaries(unittest.TestCase):
	def test_no_ignore_permissions_true_in_tools(self):
		tools_dir = os.path.join(_MCP_DIR, "tools")
		offenders = [p for p in _py_files(tools_dir) if "ignore_permissions=True" in _read(p)]
		self.assertEqual(offenders, [], f"ignore_permissions=True found in tools/: {offenders}")

	def test_no_get_all_in_tools(self):
		tools_dir = os.path.join(_MCP_DIR, "tools")
		offenders = [p for p in _py_files(tools_dir) if re.search(r"\bget_all\(", _read(p))]
		self.assertEqual(offenders, [], f"get_all( found in tools/: {offenders}")

	def test_no_interpolated_sql(self):
		# frappe.db.sql with an f-string or %-interpolated query is forbidden.
		pat = re.compile(r"frappe\.db\.sql\(\s*(f[\"']|[\"'][^\"']*%[^\"']*[\"']\s*%)")
		offenders = [p for p in _py_files(_MCP_DIR) if pat.search(_read(p))]
		self.assertEqual(offenders, [], f"interpolated frappe.db.sql found: {offenders}")

	def test_no_sampling_references(self):
		offenders = [p for p in _py_files(_MCP_DIR) if "sampling/" in _read(p)]
		self.assertEqual(offenders, [], f"sampling/ reference found: {offenders}")
