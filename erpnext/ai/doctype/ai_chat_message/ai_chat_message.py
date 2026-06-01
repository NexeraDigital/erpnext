# Copyright (c) 2026, NexeraDigital and contributors
# For license information, please see license.txt

"""AI Chat Message.

One turn in a conversation — a ``User`` prompt or an ``Assistant`` reply. These
rows are the human-readable audit trail of the chat panel: who asked what,
against which record (``context_*``), which tools ran (``tools_invoked``), and
the per-turn token/latency telemetry. Per-tool-call enforcement detail still
lives in ``MCP Audit Log``; this is the conversation-level view.

Owner-scoped like ``AI Chat Conversation``. ``content`` is stored verbatim but
is always treated as data, never instructions, when replayed to the model.
"""

from __future__ import annotations

from frappe.model.document import Document


class AIChatMessage(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		content: DF.LongText | None
		context_doctype: DF.Data | None
		context_name: DF.Data | None
		conversation: DF.Link
		error: DF.SmallText | None
		input_tokens: DF.Int
		latency_ms: DF.Int
		model: DF.Data | None
		output_tokens: DF.Int
		role: DF.Literal["User", "Assistant"]
		tools_invoked: DF.Code | None
	# end: auto-generated types

	pass
