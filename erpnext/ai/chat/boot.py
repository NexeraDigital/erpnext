# Copyright (c) 2026, NexeraDigital and contributors
# For license information, please see license.txt

"""``extend_bootinfo`` handler: expose ``frappe.boot.ai_chat_enabled`` to the desk.

The global launcher (added in the front-end slice) only renders when this flag is
true, so the panel never appears for guests, on sites where the MCP server is
disabled, or before the feature is switched on. Cheap, read-mostly: it reads the
cached MCP Settings Single and never touches the API key.
"""

from __future__ import annotations

import frappe


def boot_session(bootinfo) -> None:
	user = getattr(frappe.session, "user", None)
	if not user or user == "Guest":
		bootinfo.ai_chat_enabled = False
		return
	bootinfo.ai_chat_enabled = _is_enabled()


def _is_enabled() -> bool:
	"""Enabled when the MCP server (the tool surface the chat consumes) is on.

	Key-presence is intentionally NOT checked here (it would decrypt on every boot);
	if the Anthropic key is missing, the first turn returns a clear, key-free error
	from ``get_ai_credentials``.
	"""
	try:
		from erpnext.mcp import config as mcp_config

		return bool(mcp_config.is_enabled())
	except Exception:
		return False
