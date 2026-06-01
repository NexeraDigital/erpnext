# Copyright (c) 2026, NexeraDigital and contributors
# For license information, please see license.txt

"""AI chat panel backend.

A thin, secure consumer of two already-built subsystems:

- ``erpnext.ai.credentials`` — the Claude API key (AI Provider Settings).
- ``erpnext.mcp`` — the permission-enforcing, audit-logged tool catalogue.

The desk session is already authenticated, so the chat runs the Claude tool loop
*in-process* as ``frappe.session.user`` (see ``agent.py``) rather than minting an
OAuth token for the browser. Every data read therefore goes through the MCP
tools' own ``has_permission`` / permitted-names enforcement, as the calling user.

See ``docs/planning/ai-chat-panel-plan.md``.
"""
