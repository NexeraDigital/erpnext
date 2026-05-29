# Copyright (c) 2026, NexeraDigital and contributors
# For license information, please see license.txt

"""Per-tool authorization resolution: enabled / role / OAuth scope.

A tool declares a default ``required_scope`` in code; an ``MCP Tool Config`` row
may override the scope and add a ``required_role`` and an enable/disable switch.
This module is the single place those are combined into a visibility decision,
used both for ``tools/list`` filtering and the ``tools/call`` pre-dispatch gate.
"""

import frappe


def required_scope(tool_cls, cfg: dict | None) -> str:
	"""Effective OAuth scope for a tool (Tool Config override wins)."""
	if cfg and cfg.get("required_oauth_scope"):
		return cfg["required_oauth_scope"]
	return getattr(tool_cls, "required_scope", "") or ""


def is_enabled(cfg: dict | None) -> bool:
	"""Tools default to enabled when no config row exists."""
	if cfg is None:
		return True
	return bool(cfg.get("enabled", 1))


def has_required_role(ctx, cfg: dict | None) -> bool:
	role = (cfg or {}).get("required_role")
	if not role:
		return True
	return role in frappe.get_roles(ctx.user)


def has_required_scope(ctx, tool_cls, cfg: dict | None) -> bool:
	scope = required_scope(tool_cls, cfg)
	if not scope:
		return True
	return scope in (ctx.scopes or [])


def is_visible(ctx, tool_cls, cfg: dict | None) -> bool:
	"""True if the caller may both see (tools/list) and call this tool."""
	return is_enabled(cfg) and has_required_role(ctx, cfg) and has_required_scope(ctx, tool_cls, cfg)
