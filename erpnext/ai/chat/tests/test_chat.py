# Copyright (c) 2026, NexeraDigital and contributors
# For license information, please see license.txt

"""Tests for the AI chat panel backend (plan §5.1).

Covers the security-critical paths:
- auth rejection (Guest),
- RBAC scoping (low-priv user -> tool denied + PermissionDenied audit row, run as
  the session user, never leaked rows),
- context re-validation / forged-context rejection,
- unknown-tool path,
- secret hygiene (API key never persisted or published),
- enqueue identity (turn enqueued as the calling user).

The Anthropic network call is mocked at the single seam ``agent._create_message``;
credentials are mocked at ``agent.get_ai_credentials`` so no real key/network is used.
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from erpnext.ai.chat import agent, api
from erpnext.ai.chat import context as chat_context
from erpnext.ai.credentials import AICredentials

_FAKE_KEY = "sk-ant-TESTKEY-should-never-be-persisted-or-published-0001"


# --------------------------------------------------------------------------- #
# Fake Anthropic SDK response objects                                          #
# --------------------------------------------------------------------------- #


class _Block:
	def __init__(self, type, text=None, id=None, name=None, input=None):
		self.type = type
		self.text = text
		self.id = id
		self.name = name
		self.input = input or {}


class _Usage:
	def __init__(self, i=10, o=5):
		self.input_tokens = i
		self.output_tokens = o


class _Resp:
	def __init__(self, content, stop_reason="end_turn"):
		self.content = content
		self.stop_reason = stop_reason
		self.usage = _Usage()


def _text_response(text):
	return _Resp([_Block("text", text=text)])


def _tool_then_text(tool_name, tool_input, final_text):
	"""A scripted two-step exchange: first a tool_use, then a text answer."""
	first = _Resp(
		[_Block("tool_use", id="tu_1", name=tool_name, input=tool_input)],
		stop_reason="tool_use",
	)
	second = _text_response(final_text)
	return [first, second]


# --------------------------------------------------------------------------- #
# Test case                                                                    #
# --------------------------------------------------------------------------- #


class TestAIChat(IntegrationTestCase):
	def setUp(self):
		self._orig_user = frappe.session.user
		# Capture realtime publishes instead of hitting Socket.IO.
		self.events = []
		self._orig_publish = frappe.publish_realtime
		frappe.publish_realtime = lambda *a, **k: self.events.append((a, k))
		# Stub credentials + the model call so no key/network is needed.
		self._orig_creds = agent.get_ai_credentials
		agent.get_ai_credentials = lambda provider: AICredentials(
			provider="anthropic",
			api_key=_FAKE_KEY,
			default_model="claude-haiku-4-5-20251001",
			zdr_enabled=False,
		)
		self._orig_get_client = agent._get_client
		agent._get_client = lambda api_key: object()
		self._orig_create = agent._create_message
		self._scripted = []  # list of responses popped per model call
		agent._create_message = lambda client, params: self._scripted.pop(0)

	def tearDown(self):
		frappe.publish_realtime = self._orig_publish
		agent.get_ai_credentials = self._orig_creds
		agent._get_client = self._orig_get_client
		agent._create_message = self._orig_create
		frappe.set_user(self._orig_user)
		frappe.db.rollback()

	# ----- helpers -----

	def _make_user(self, email, roles=None):
		if not frappe.db.exists("User", email):
			u = frappe.new_doc("User")
			u.email = email
			u.first_name = email.split("@")[0]
			u.send_welcome_email = 0
			u.insert(ignore_permissions=True)
		user = frappe.get_doc("User", email)
		if roles:
			user.add_roles(*roles)
		return email

	def _new_conversation(self, user):
		frappe.set_user(user)
		doc = frappe.new_doc("AI Chat Conversation")
		doc.title = "t"
		doc.insert(ignore_permissions=True)
		return doc.name

	# ----- auth -----

	def test_guest_cannot_start_turn(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.AuthenticationError):
			api.start_turn(message="hello")

	# ----- happy path (run as session user) -----

	def test_turn_persists_assistant_reply_and_streams(self):
		user = self._make_user("ai_chat_admin@example.com", roles=["System Manager"])
		conv = self._new_conversation(user)
		# persist the user message the way start_turn would
		m = frappe.new_doc("AI Chat Message")
		m.conversation = conv
		m.role = "User"
		m.content = "hi"
		m.insert(ignore_permissions=True)

		self._scripted = [_text_response("Hello, how can I help?")]
		agent.run_turn(conversation=conv, user_message="hi", context=None, user=user)

		replies = frappe.get_all(
			"AI Chat Message",
			filters={"conversation": conv, "role": "Assistant"},
			fields=["content", "model"],
		)
		self.assertEqual(len(replies), 1)
		self.assertEqual(replies[0].content, "Hello, how can I help?")
		# a 'done' event was published to the user
		kinds = [k[0][1].get("type") for k in self.events if k[0] and isinstance(k[0][1], dict)]
		self.assertIn("done", kinds)

	def test_tool_call_runs_through_mcp_and_is_recorded(self):
		user = self._make_user("ai_chat_admin@example.com", roles=["System Manager"])
		conv = self._new_conversation(user)
		self._scripted = _tool_then_text("list_ap_invoices", {"limit": 5}, "You have no open invoices.")
		agent.run_turn(conversation=conv, user_message="any overdue invoices?", context=None, user=user)

		reply = frappe.get_all(
			"AI Chat Message",
			filters={"conversation": conv, "role": "Assistant"},
			fields=["content", "tools_invoked"],
		)[0]
		self.assertIn("invoices", reply.content)
		self.assertIn("list_ap_invoices", reply.tools_invoked or "")

	# ----- RBAC scoping -----

	def test_low_priv_tool_call_is_denied_and_audited(self):
		user = self._make_user("ai_chat_lowpriv@example.com", roles=[])
		frappe.set_user(user)
		ctx = agent.build_auth_context(user)
		visible = agent.visible_tools(ctx)
		# Dispatch a real read tool as a user without Purchase Invoice read.
		outcome = agent._dispatch_tool(ctx, visible, "list_ap_invoices", {"limit": 5})
		self.assertFalse(outcome["ok"])  # denied, never leaked rows
		# safe_execute recorded a PermissionDenied audit row for this user.
		rows = frappe.get_all(
			"MCP Audit Log",
			filters={"user": user, "tool": "list_ap_invoices"},
			fields=["result_status"],
		)
		self.assertTrue(rows)
		self.assertEqual(rows[-1].result_status, "PermissionDenied")

	def test_unknown_tool_is_rejected(self):
		user = self._make_user("ai_chat_admin@example.com", roles=["System Manager"])
		frappe.set_user(user)
		ctx = agent.build_auth_context(user)
		visible = agent.visible_tools(ctx)
		outcome = agent._dispatch_tool(ctx, visible, "definitely_not_a_tool", {})
		self.assertFalse(outcome["ok"])
		self.assertIn("Unknown", outcome["content"])

	# ----- context re-validation / forged context -----

	def test_forged_context_is_rejected(self):
		# A low-priv user claims context on a System-Manager-only Single.
		user = self._make_user("ai_chat_lowpriv@example.com", roles=[])
		frappe.set_user(user)
		with self.assertRaises(frappe.PermissionError):
			chat_context.resolve_context(
				{"doctype": "AI Provider Settings", "name": "AI Provider Settings"}
			)

	def test_unknown_context_doctype_is_ignored(self):
		user = self._make_user("ai_chat_admin@example.com", roles=["System Manager"])
		frappe.set_user(user)
		self.assertIsNone(
			chat_context.resolve_context({"doctype": "No Such DocType 9000", "name": "x"})
		)

	# ----- secret hygiene -----

	def test_api_key_never_persisted_or_published(self):
		user = self._make_user("ai_chat_admin@example.com", roles=["System Manager"])
		conv = self._new_conversation(user)
		self._scripted = [_text_response("ok")]
		agent.run_turn(conversation=conv, user_message="hi", context=None, user=user)

		# Not in any stored chat message field.
		for row in frappe.get_all(
			"AI Chat Message", filters={"conversation": conv}, fields=["content", "error", "tools_invoked"]
		):
			for value in row.values():
				self.assertNotIn(_FAKE_KEY, value or "")
		# Not in any published realtime payload.
		self.assertNotIn(_FAKE_KEY, repr(self.events))

	# ----- enqueue identity -----

	def test_start_turn_enqueues_as_calling_user(self):
		user = self._make_user("ai_chat_admin@example.com", roles=["System Manager"])
		frappe.set_user(user)
		captured = {}
		orig_enqueue = frappe.enqueue

		def fake_enqueue(method, **kwargs):
			captured["method"] = method
			captured["user"] = kwargs.get("user")
			captured["conversation"] = kwargs.get("conversation")
			return None

		frappe.enqueue = fake_enqueue
		try:
			result = api.start_turn(message="hello there", context=None)
		finally:
			frappe.enqueue = orig_enqueue

		self.assertEqual(captured["method"], "erpnext.ai.chat.agent.run_turn")
		self.assertEqual(captured["user"], user)
		# A conversation + user message were persisted under this user.
		self.assertEqual(captured["conversation"], result["conversation"])
		umsgs = frappe.get_all(
			"AI Chat Message",
			filters={"conversation": result["conversation"], "role": "User"},
			fields=["content", "owner"],
		)
		self.assertEqual(len(umsgs), 1)
		self.assertEqual(umsgs[0].owner, user)

	# ----- credentials-not-configured surfaces cleanly -----

	def test_missing_credentials_surfaces_friendly_error(self):
		from erpnext.ai.credentials import AICredentialsNotConfigured

		user = self._make_user("ai_chat_admin@example.com", roles=["System Manager"])
		conv = self._new_conversation(user)

		def raise_missing(provider):
			raise AICredentialsNotConfigured("No API key configured for AI provider 'anthropic'.")

		agent.get_ai_credentials = raise_missing
		agent.run_turn(conversation=conv, user_message="hi", context=None, user=user)

		reply = frappe.get_all(
			"AI Chat Message",
			filters={"conversation": conv, "role": "Assistant"},
			fields=["content", "error"],
		)[0]
		self.assertIn("not configured", reply.content.lower())
		self.assertNotIn(_FAKE_KEY, reply.content)
