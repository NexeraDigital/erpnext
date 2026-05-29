# Copyright (c) 2026, NexeraDigital and contributors
# For license information, please see license.txt

"""Accessors for MCP Settings (Single) and MCP Tool Config rows.

All reads go through Frappe's document cache; Tool Config is additionally cached
in a small dict keyed by tool name and invalidated on save (see
``MCPToolConfig.on_update``), so the per-request hot path does not hit the DB for
every tool.
"""

import json

import frappe

# Defaults mirror the field defaults in mcp_settings.json so code paths work even
# before the Single is first saved.
_DEFAULT_ALLOWED_ORIGINS = ["http://localhost", "http://127.0.0.1"]
_DEFAULT_PROTOCOL_VERSIONS = ["2025-11-25", "2025-06-18", "2025-03-26"]
_DEFAULT_RETENTION_DAYS = 180
_DEFAULT_OUTPUT_MAX_BYTES = 51200


def get_settings():
	"""Return the MCP Settings Single (cached document)."""
	return frappe.get_cached_doc("MCP Settings")


def is_enabled() -> bool:
	return bool(get_settings().enabled)


def _json_list(raw: str | None, default: list[str]) -> list[str]:
	if not raw:
		return list(default)
	try:
		value = json.loads(raw)
	except (ValueError, TypeError):
		return list(default)
	if isinstance(value, list):
		return [str(v) for v in value]
	return list(default)


def allowed_origins() -> list[str]:
	return _json_list(get_settings().allowed_origins, _DEFAULT_ALLOWED_ORIGINS)


def allowed_protocol_versions() -> list[str]:
	return _json_list(get_settings().allowed_protocol_versions, _DEFAULT_PROTOCOL_VERSIONS)


def audit_retention_days() -> int:
	return int(get_settings().audit_retention_days or _DEFAULT_RETENTION_DAYS)


def audit_output_max_bytes() -> int:
	return int(get_settings().audit_output_max_bytes or _DEFAULT_OUTPUT_MAX_BYTES)


def oauth_resource_uri() -> str | None:
	return (get_settings().oauth_resource_uri or "").strip() or None


def require_tls() -> bool:
	return bool(get_settings().require_tls)


def get_tool_config_map() -> dict[str, dict]:
	"""Return ``{tool_name: config_dict}`` for all MCP Tool Config rows, cached."""

	def _load():
		rows = frappe.get_all(
			"MCP Tool Config",
			fields=[
				"tool_name",
				"enabled",
				"required_role",
				"required_oauth_scope",
				"rate_limit_per_minute",
				"concurrency_cap",
				"timeout_seconds",
			],
		)
		return {r["tool_name"]: r for r in rows}

	# ``get_all`` here reads framework-internal config rows (not user data), so the
	# implicit ignore_permissions is acceptable — see plan §7.2 canary note.
	return frappe.cache.get_value("mcp_tool_config", generator=_load) or {}


def get_tool_config(tool_name: str) -> dict | None:
	return get_tool_config_map().get(tool_name)
