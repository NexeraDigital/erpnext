# Copyright (c) 2026, NexeraDigital and contributors
# For license information, please see license.txt

"""AI Chat Conversation.

One chat thread owned by a single desk user. Persistence + audit anchor for the
AI chat panel: messages (``AI Chat Message``) link back here, and the desk panel
restores history from these rows across reloads / route changes.

Ownership is enforced two ways: the DocType permission rule is ``if_owner`` (a
user sees only conversations whose ``owner`` is them), and the whitelisted chat
API additionally filters by ``owner = frappe.session.user`` so a forged name can
never reach another user's thread. ``user`` is set server-side to the session
user and is read-only — never trusted from the client.
"""

from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class AIChatConversation(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		context_doctype: DF.Data | None
		context_name: DF.Data | None
		last_active: DF.Datetime | None
		title: DF.Data | None
		user: DF.Link | None
	# end: auto-generated types

	def before_insert(self) -> None:
		# Bind ownership to the creating session user; do not trust any client value.
		self.user = frappe.session.user
		if not self.last_active:
			self.last_active = now_datetime()

	def touch_active(self) -> None:
		"""Bump ``last_active`` so the panel can order threads most-recent-first."""
		self.db_set("last_active", now_datetime(), update_modified=False)
