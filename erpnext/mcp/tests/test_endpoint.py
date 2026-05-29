# Copyright (c) 2026, NexeraDigital and contributors
# For license information, please see license.txt

"""End-to-end endpoint tests (plan §7.1 #4/#5/#7, L1-L4).

Drives ``erpnext.mcp.endpoint.handle_mcp`` through a simulated ``frappe.request``
with real OAuth Bearer Tokens, covering the transport/auth/scope layers the
vendored dispatcher does not handle.
"""

import frappe
from frappe.tests import IntegrationTestCase

from erpnext.mcp.endpoint import handle_mcp
from erpnext.mcp.tests._helpers import body, enable_mcp, make_bearer_token, set_mcp_request

_AP = "erpnext:ap_invoice:read"
_VENDOR = "erpnext:vendor:read"
_SCHEMA = "erpnext:schema:read"
_ALL = [_AP, _VENDOR, _SCHEMA]


class TestEndpoint(IntegrationTestCase):
	def setUp(self):
		enable_mcp()
		frappe.set_user("Administrator")
		self.admin_token = make_bearer_token("Administrator", _ALL)

	def tearDown(self):
		frappe.set_user("Administrator")

	# ---- L0: master switch ----

	def test_disabled_returns_503(self):
		s = frappe.get_single("MCP Settings")
		s.enabled = 0
		s.save(ignore_permissions=True)
		set_mcp_request({"jsonrpc": "2.0", "id": 1, "method": "ping"}, token=self.admin_token)
		self.assertEqual(handle_mcp().status_code, 503)

	# ---- L1: transport ----

	def test_bad_origin_rejected_403(self):
		set_mcp_request(
			{"jsonrpc": "2.0", "id": 1, "method": "ping"},
			token=self.admin_token,
			origin="http://evil.example.com",
		)
		self.assertEqual(handle_mcp().status_code, 403)

	def test_unsupported_protocol_version_400(self):
		set_mcp_request(
			{"jsonrpc": "2.0", "id": 1, "method": "ping"},
			token=self.admin_token,
			protocol_version="1999-01-01",
		)
		self.assertEqual(handle_mcp().status_code, 400)

	def test_allowed_origin_passes(self):
		set_mcp_request(
			{"jsonrpc": "2.0", "id": 1, "method": "ping"},
			token=self.admin_token,
			origin="http://localhost",
		)
		self.assertEqual(handle_mcp().status_code, 200)

	# ---- L2/L3: auth ----

	def test_missing_auth_401_with_www_authenticate(self):
		set_mcp_request({"jsonrpc": "2.0", "id": 1, "method": "ping"}, token=None)
		resp = handle_mcp()
		self.assertEqual(resp.status_code, 401)
		self.assertIn("Bearer", resp.headers.get("WWW-Authenticate", ""))
		self.assertIn("resource_metadata", resp.headers.get("WWW-Authenticate", ""))

	def test_invalid_token_401(self):
		set_mcp_request({"jsonrpc": "2.0", "id": 1, "method": "ping"}, token="not-a-real-token")
		self.assertEqual(handle_mcp().status_code, 401)

	def test_token_in_query_string_401(self):
		from frappe.utils import set_request

		set_request(
			method="POST",
			json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
			query_string=f"access_token={self.admin_token}",
		)
		self.assertEqual(handle_mcp().status_code, 401)

	def test_user_is_mapped_from_token(self):
		# A token for a specific user causes the request to run as that user.
		if not frappe.db.exists("User", "mcp-endpoint-user@example.com"):
			u = frappe.new_doc("User")
			u.email = "mcp-endpoint-user@example.com"
			u.first_name = "Endpoint"
			u.send_welcome_email = 0
			u.insert(ignore_permissions=True)
		token = make_bearer_token("mcp-endpoint-user@example.com", _ALL)
		set_mcp_request({"jsonrpc": "2.0", "id": 1, "method": "ping"}, token=token)
		handle_mcp()
		self.assertEqual(frappe.session.user, "mcp-endpoint-user@example.com")

	# ---- protocol methods ----

	def test_initialize(self):
		set_mcp_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, token=self.admin_token)
		result = body(handle_mcp())["result"]
		self.assertIn("protocolVersion", result)
		self.assertIn("serverInfo", result)

	def test_ping(self):
		set_mcp_request({"jsonrpc": "2.0", "id": 1, "method": "ping"}, token=self.admin_token)
		self.assertEqual(body(handle_mcp())["result"], {})

	# ---- L4: scope-filtered tools ----

	def test_tools_list_filtered_by_scope(self):
		token = make_bearer_token("Administrator", [_AP])  # AP scope only
		set_mcp_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, token=token)
		names = {t["name"] for t in body(handle_mcp())["result"]["tools"]}
		self.assertEqual(names, {"list_ap_invoices", "get_ap_invoice"})

	def test_tools_list_full_scope_sees_all(self):
		set_mcp_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, token=self.admin_token)
		names = {t["name"] for t in body(handle_mcp())["result"]["tools"]}
		self.assertEqual(
			names,
			{"list_ap_invoices", "get_ap_invoice", "list_vendors", "get_vendor_balance", "get_doctype_meta"},
		)

	def test_tools_call_without_scope_403(self):
		token = make_bearer_token("Administrator", [_AP])  # lacks vendor scope
		set_mcp_request(
			{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
			 "params": {"name": "get_vendor_balance", "arguments": {"supplier": "X"}}},
			token=token,
		)
		resp = handle_mcp()
		self.assertEqual(resp.status_code, 403)
		self.assertIn("insufficient_scope", resp.headers.get("WWW-Authenticate", ""))

	def test_tools_call_with_scope_succeeds(self):
		set_mcp_request(
			{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
			 "params": {"name": "list_ap_invoices", "arguments": {"limit": 1}}},
			token=self.admin_token,
		)
		result = body(handle_mcp())["result"]
		self.assertIn("structuredContent", result)
		self.assertIn("results", result["structuredContent"])
		self.assertNotEqual(result.get("isError"), True)

	def test_tools_list_advertises_schemas(self):
		set_mcp_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, token=self.admin_token)
		tools = {t["name"]: t for t in body(handle_mcp())["result"]["tools"]}
		la = tools["list_ap_invoices"]
		self.assertEqual(la["inputSchema"]["type"], "object")
		self.assertEqual(la["inputSchema"]["properties"]["limit"]["maximum"], 200)
		self.assertTrue(la["annotations"]["readOnlyHint"])
