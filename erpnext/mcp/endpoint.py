# Copyright (c) 2026, NexeraDigital and contributors
# For license information, please see license.txt

"""The ONLY HTTP route for the MCP server (plan §4.1, §4.5).

Reachable at ``/api/method/erpnext.mcp.endpoint.handle_mcp``. This wraps the
vendored ``frappe/mcp`` transport with the layers it does not provide:

  L1  transport — Origin allowlist, MCP-Protocol-Version validation, TLS guard
  L2/L3 auth    — OAuth bearer + audience -> frappe.set_user
  L4  scope     — pre-dispatch tools/call gate (403 insufficient_scope)

then hands the request to the vendored ``MCP.handle`` (which already returns
spec-correct JSON-RPC ``-32601/-32602/-32700`` errors). Tool-execution rate-limit,
permission checks, and audit live deeper, in ``audit.safe_execute`` / the tools.
"""

import json

import frappe
from werkzeug.wrappers import Response

from erpnext.mcp import auth, config, registry
from erpnext.mcp.exceptions import (
	MCPAuthError,
	MCPDisabledError,
	MCPError,
	MCPProtocolVersionError,
	MCPTransportError,
)

_DEFAULT_PROTOCOL_VERSION = "2025-03-26"  # MCP default when header absent (§3.6)
_LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "[::1]")


def _json_error(status: int, message: str, www_authenticate: str | None = None) -> Response:
	resp = Response(
		json.dumps({"error": message}),
		status=status,
		mimetype="application/json",
	)
	if www_authenticate:
		resp.headers["WWW-Authenticate"] = www_authenticate
	return resp


def _resource_metadata_url(request) -> str:
	base = (config.oauth_resource_uri() or request.host_url).rstrip("/")
	return f"{base}/.well-known/oauth-protected-resource"


def _check_origin(request) -> None:
	"""L1: DNS-rebinding defense. Browser clients send Origin; CLI clients don't."""
	origin = request.headers.get("Origin")
	if not origin:
		return
	allowed = config.allowed_origins()
	if not any(origin == a or origin.startswith(a) for a in allowed):
		raise MCPTransportError(f"Origin '{origin}' is not allowed.")


def _resolve_protocol_version(request) -> str:
	"""L1: honor MCP-Protocol-Version; default when absent; 400 on unsupported."""
	version = request.headers.get("MCP-Protocol-Version") or _DEFAULT_PROTOCOL_VERSION
	if version not in config.allowed_protocol_versions():
		raise MCPProtocolVersionError(f"Unsupported MCP-Protocol-Version '{version}'.")
	return version


def _check_tls(request) -> None:
	"""L1: refuse plaintext for non-loopback hosts when require_tls is set."""
	if not config.require_tls():
		return
	scheme = request.headers.get("X-Forwarded-Proto") or request.scheme
	host = (request.host or "").split(":")[0]
	if scheme != "https" and host not in _LOOPBACK_HOSTS:
		raise MCPTransportError("TLS is required for non-loopback requests.")


def _peek_method(request) -> tuple[str | None, dict]:
	"""Parse the JSON-RPC body once for the pre-dispatch scope gate."""
	try:
		data = request.get_json(force=True, silent=True) or {}
	except Exception:
		return None, {}
	if not isinstance(data, dict):
		return None, {}
	return data.get("method"), (data.get("params") or {})


@frappe.whitelist(allow_guest=True, methods=["POST"])
def handle_mcp():
	request = frappe.request
	try:
		# Master switch.
		if not config.is_enabled():
			raise MCPDisabledError("MCP server is disabled.")

		# L1 — transport.
		_check_tls(request)
		_check_origin(request)
		protocol_version = _resolve_protocol_version(request)

		# L2/L3 — auth (sets frappe.session.user). 401 on failure.
		try:
			ctx = auth.authenticate(request, protocol_version=protocol_version)
		except MCPAuthError as e:
			return _json_error(
				e.http_status,
				str(e),
				www_authenticate=f'Bearer resource_metadata="{_resource_metadata_url(request)}"',
			)

		# L4 — pre-dispatch scope gate for tools/call (403 insufficient_scope).
		method, params = _peek_method(request)
		if method == "tools/call":
			tool_name = params.get("name")
			if tool_name:
				try:
					registry.assert_can_call(ctx, tool_name)
				except MCPError as e:
					return _json_error(
						e.http_status,
						str(e),
						www_authenticate=(
							f'Bearer resource_metadata="{_resource_metadata_url(request)}", '
							f'error="insufficient_scope"'
							if e.http_status == 403
							else None
						),
					)

		# Dispatch via the vendored transport (handles JSON-RPC error codes).
		mcp = registry.build_mcp(ctx)
		return mcp.handle(request, Response())

	except MCPTransportError as e:
		return _json_error(e.http_status, str(e))
	except MCPError as e:
		return _json_error(e.http_status, str(e))
	except Exception:
		frappe.log_error(title="MCP endpoint error", message=frappe.get_traceback())
		return _json_error(500, "Internal server error.")
