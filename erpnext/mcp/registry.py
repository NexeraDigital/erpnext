# Copyright (c) 2026, NexeraDigital and contributors
# For license information, please see license.txt

"""Per-request tool registry (plan §3.4 reject: NO module-level singleton).

For each request we build a fresh ``MCP`` instance and register only the tools
the authenticated caller may see (enabled + role + scope). Each registered
function wraps the tool's ``run`` in ``audit.safe_execute`` so rate-limiting,
concurrency, and audit apply uniformly. This is race-free under multi-worker
gunicorn because nothing is shared between requests.
"""

import frappe

from erpnext.mcp import audit, config
from erpnext.mcp.exceptions import MCPScopeError
from erpnext.mcp.tools import _scope, get_catalogue


def _make_fn(tool_cls, cfg, ctx):
	"""Build the callable the vendored dispatcher invokes for ``tools/call``."""

	def fn(**arguments):
		tool = tool_cls()
		return audit.safe_execute(
			tool_cls.name,
			ctx,
			cfg,
			lambda: tool.run(arguments),
			arguments,
		)

	return fn


def _tool_dict(tool_cls, cfg, ctx) -> dict:
	annotations = dict(getattr(tool_cls, "annotations", {}) or {})
	if tool_cls.title and "title" not in annotations:
		annotations["title"] = tool_cls.title
	return {
		"name": tool_cls.name,
		"description": tool_cls.description,
		"input_schema": tool_cls.input_schema(),
		"output_schema": tool_cls.output_schema(),
		"annotations": annotations or None,
		"fn": _make_fn(tool_cls, cfg, ctx),
	}


def build_mcp(ctx):
	"""Return a per-request ``MCP`` instance with the caller's visible tools."""
	# Import here so ``erpnext.mcp.__init__`` has already put _vendor on sys.path.
	from frappe_mcp import MCP

	mcp = MCP(name="erpnext-mcp")
	cfg_map = config.get_tool_config_map()
	for tool_cls in get_catalogue().values():
		cfg = cfg_map.get(tool_cls.name)
		if _scope.is_visible(ctx, tool_cls, cfg):
			mcp.add_tool(_tool_dict(tool_cls, cfg, ctx))
	return mcp


def assert_can_call(ctx, tool_name: str) -> None:
	"""Pre-dispatch gate for ``tools/call`` (plan L4).

	Raises ``MCPScopeError`` (HTTP 403, ``insufficient_scope``) when the named tool
	exists in the catalogue but the caller lacks its scope/role, or it is disabled.
	Unknown tool names are left to the dispatcher (which returns an MCP isError).
	"""
	tool_cls = get_catalogue().get(tool_name)
	if tool_cls is None:
		return
	cfg = config.get_tool_config(tool_name)
	if not _scope.is_enabled(cfg):
		raise MCPScopeError(f"Tool '{tool_name}' is disabled.")
	if not _scope.has_required_role(ctx, cfg):
		raise MCPScopeError(f"Caller lacks the role required for tool '{tool_name}'.")
	if not _scope.has_required_scope(ctx, tool_cls, cfg):
		needed = _scope.required_scope(tool_cls, cfg)
		raise MCPScopeError(f"insufficient_scope: tool '{tool_name}' requires '{needed}'.")
