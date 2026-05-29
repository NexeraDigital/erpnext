# Copyright (c) 2026, NexeraDigital and contributors
# For license information, please see license.txt

"""JSON-RPC dispatch tests (plan §7.1 #8) exercised against the vendored MCP.

Confirms the vendored transport returns spec-correct JSON-RPC error codes, so our
endpoint can rely on it for ``-32601/-32602/-32700``.
"""

import json
import unittest

from frappe.tests import IntegrationTestCase
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request, Response

import erpnext.mcp  # noqa: F401  (puts _vendor on sys.path)


def _post(mcp, payload):
	builder = EnvironBuilder(method="POST", json=payload)
	request = Request(builder.get_environ())
	return mcp.handle(request, Response())


def _body(resp):
	return json.loads(resp.get_data(as_text=True))


class TestDispatcher(IntegrationTestCase):
	def _mcp(self):
		from frappe_mcp import MCP

		mcp = MCP(name="erpnext-mcp-test")
		mcp.add_tool(
			{
				"name": "echo",
				"description": "echo",
				"input_schema": {"type": "object", "properties": {}},
				"output_schema": None,
				"annotations": None,
				"fn": lambda **kw: {"ok": True},
			}
		)
		return mcp

	def test_ping_returns_empty_result(self):
		resp = _post(self._mcp(), {"jsonrpc": "2.0", "id": 1, "method": "ping"})
		self.assertEqual(resp.status_code, 200)
		self.assertEqual(_body(resp)["result"], {})

	def test_unknown_method_is_method_not_found(self):
		resp = _post(self._mcp(), {"jsonrpc": "2.0", "id": 2, "method": "does/not/exist"})
		self.assertEqual(_body(resp)["error"]["code"], -32601)

	def test_tools_list_includes_registered_tool(self):
		resp = _post(self._mcp(), {"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
		names = [t["name"] for t in _body(resp)["result"]["tools"]]
		self.assertIn("echo", names)

	def test_tools_call_roundtrip(self):
		resp = _post(
			self._mcp(),
			{"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "echo"}},
		)
		result = _body(resp)["result"]
		self.assertEqual(result["structuredContent"], {"ok": True})
		self.assertNotEqual(result.get("isError"), True)

	def test_tools_call_unknown_tool_is_error_content(self):
		resp = _post(
			self._mcp(),
			{"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "nope"}},
		)
		# MCP-correct: tool-not-found is isError content, not a JSON-RPC error.
		self.assertTrue(_body(resp)["result"]["isError"])

	def test_get_method_rejected(self):
		from frappe_mcp import MCP

		builder = EnvironBuilder(method="GET")
		request = Request(builder.get_environ())
		resp = MCP(name="t").handle(request, Response())
		self.assertEqual(resp.status_code, 405)
