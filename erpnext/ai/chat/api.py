# Copyright (c) 2026, NexeraDigital and contributors
# For license information, please see license.txt

"""Whitelisted HTTP surface for the AI chat panel.

Every endpoint is ``@frappe.whitelist()`` with the framework default
``allow_guest=False`` — Guest is rejected before the function runs
(https://docs.frappe.io/framework/v15/user/en/api/rest, whitelist decorator at
frappe/__init__.py:1263). We additionally assert a real signed-in user as
defence-in-depth.

``start_turn`` validates, persists the user's message, and enqueues the Claude
loop as the calling user (``frappe.enqueue(..., user=...)``) — the turn never runs
on the web worker (no held-open request; see plan §2 D1). The browser is handed a
``conversation`` id and subscribes to ``ai_chat:<conversation>`` realtime events.
"""

from __future__ import annotations

import time

import frappe
from frappe import _

# Per-user turn budget: a single user cannot fan out more than this many turns per
# minute (the model itself fans out tool calls, which MCP rate-limits separately).
_TURNS_PER_MINUTE = 20
_RATE_WINDOW_SECONDS = 60


def _assert_logged_in() -> str:
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("You must be signed in to use the AI chat."), frappe.AuthenticationError)
	return user


def _rate_limit(user: str) -> None:
	window = int(time.time()) // _RATE_WINDOW_SECONDS
	key = frappe.cache.make_key(f"ai-chat-rl:{user}:{window}")
	count = frappe.cache.incrby(key, 1)
	if count == 1:
		frappe.cache.expire(key, _RATE_WINDOW_SECONDS)
	if count > _TURNS_PER_MINUTE:
		frappe.throw(
			_("You're sending messages too quickly. Please wait a moment."),
			frappe.RateLimitExceededError,
		)


def _own_conversation_or_throw(name: str, user: str):
	owner = frappe.db.get_value("AI Chat Conversation", name, "owner")
	if owner is None:
		frappe.throw(_("Conversation not found."), frappe.DoesNotExistError)
	if owner != user:
		# Don't reveal existence of another user's thread — same error as not-found.
		frappe.throw(_("Conversation not found."), frappe.PermissionError)


@frappe.whitelist(methods=["POST"])
def start_turn(message: str, conversation: str | None = None, context: str | dict | None = None) -> dict:
	"""Persist a user message and enqueue the assistant reply.

	Returns ``{"conversation": <name>}``. The reply is delivered asynchronously over
	the ``ai_chat:<conversation>`` realtime channel.
	"""
	user = _assert_logged_in()
	_rate_limit(user)

	message = (message or "").strip()
	if not message:
		frappe.throw(_("Message cannot be empty."))
	if len(message) > 8000:
		frappe.throw(_("Message is too long."))

	# The context is a client hint only; it is NOT trusted here. The agent
	# re-validates and re-fetches it server-side under the user's permissions.
	hint = frappe.parse_json(context) if isinstance(context, str) else (context or None)
	hint = hint if isinstance(hint, dict) else None

	conv = _get_or_create_conversation(conversation, user, message, hint)

	# Persist the user turn (owner = this user via if_owner perms / ignore_permissions).
	umsg = frappe.new_doc("AI Chat Message")
	umsg.conversation = conv
	umsg.role = "User"
	umsg.content = message
	if hint:
		umsg.context_doctype = (hint.get("doctype") or "").strip() or None
		umsg.context_name = (hint.get("name") or "").strip() or None
	umsg.insert(ignore_permissions=True)

	frappe.enqueue(
		"erpnext.ai.chat.agent.run_turn",
		queue="short",
		timeout=150,
		user=user,
		enqueue_after_commit=True,
		conversation=conv,
		user_message=message,
		context=hint,
	)
	return {"conversation": conv}


def _get_or_create_conversation(conversation: str | None, user: str, message: str, hint: dict | None) -> str:
	if conversation:
		_own_conversation_or_throw(conversation, user)
		return conversation
	doc = frappe.new_doc("AI Chat Conversation")
	doc.title = (message[:60] + "…") if len(message) > 60 else message
	if hint:
		doc.context_doctype = (hint.get("doctype") or "").strip() or None
		doc.context_name = (hint.get("name") or "").strip() or None
	doc.insert(ignore_permissions=True)
	return doc.name


@frappe.whitelist()
def get_conversation(conversation: str) -> dict:
	"""Return a conversation's messages (oldest first) for the owner only."""
	user = _assert_logged_in()
	_own_conversation_or_throw(conversation, user)
	messages = frappe.get_all(
		"AI Chat Message",
		filters={"conversation": conversation},
		fields=["name", "role", "content", "model", "context_doctype", "context_name", "creation", "error"],
		order_by="creation asc",
	)
	return {"conversation": conversation, "messages": messages}


@frappe.whitelist()
def list_conversations(limit: int = 30) -> list[dict]:
	"""Return the caller's recent conversations, most-recent-first."""
	user = _assert_logged_in()
	return frappe.get_all(
		"AI Chat Conversation",
		filters={"owner": user},
		fields=["name", "title", "context_doctype", "context_name", "last_active"],
		order_by="last_active desc",
		limit_page_length=int(limit or 30),
	)


@frappe.whitelist(methods=["POST"])
def clear_conversation(conversation: str) -> dict:
	"""Delete a conversation and its messages (owner only)."""
	user = _assert_logged_in()
	_own_conversation_or_throw(conversation, user)
	frappe.db.delete("AI Chat Message", {"conversation": conversation})
	frappe.delete_doc("AI Chat Conversation", conversation, ignore_permissions=True)
	return {"ok": True}
