# Copyright (c) 2026, NexeraDigital and contributors
# For license information, please see license.txt

"""The ONE auth utility (plan L2/L3, §4.6).

Validate a v16 OAuth Bearer token, bind its audience (RFC 8707), and map it to a
Frappe user via ``frappe.set_user``. There is exactly one auth entry point —
``authenticate`` — to avoid the multi-path drift the plan flags in FAC (§3.4).

No token passthrough: the bearer token is NEVER forwarded to any ERPNext API.
``frappe.set_user`` is the only credential propagation.

References (frappe version-16):
- frappe/integrations/doctype/oauth_bearer_token/oauth_bearer_token.py (token fields)
- frappe/oauth.py:validate_bearer_token (status/expiry pattern), get_url_delimiter
"""

from dataclasses import dataclass, field

import frappe
from frappe.oauth import get_url_delimiter
from frappe.utils import now_datetime

from erpnext.mcp import audience
from erpnext.mcp.exceptions import MCPAuthError


@dataclass
class AuthContext:
	"""Per-request authenticated identity + correlation metadata."""

	user: str
	scopes: list[str] = field(default_factory=list)
	client_id: str | None = None
	session_id: str | None = None
	protocol_version: str | None = None
	ip_address: str | None = None


def _extract_bearer_token(request) -> str:
	"""Return the bearer token from the Authorization header.

	MCP MUST: ``Authorization: Bearer`` only; tokens in query strings are rejected.
	"""
	# Reject tokens smuggled in the query string (plan §3.6).
	if request.args.get("access_token") or request.args.get("token"):
		raise MCPAuthError("Access tokens must not be passed in the query string.")

	header = request.headers.get("Authorization") or ""
	if not header:
		raise MCPAuthError("Missing Authorization header.")

	parts = header.split(" ", 1)
	if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
		raise MCPAuthError("Authorization header must be 'Bearer <token>'.")

	return parts[1].strip()


def _load_token(access_token: str):
	"""Fetch and validate the OAuth Bearer Token (status + expiry)."""
	token = frappe.db.get_value(
		"OAuth Bearer Token",
		{"access_token": access_token},
		["name", "user", "client", "scopes", "status", "expiration_time"],
		as_dict=True,
	)
	if not token:
		raise MCPAuthError("Invalid access token.")
	if token.status != "Active":
		raise MCPAuthError("Access token is not active.")
	if not token.expiration_time or now_datetime() >= token.expiration_time:
		raise MCPAuthError("Access token has expired.")
	return token


def _parse_scopes(raw: str | None) -> list[str]:
	if not raw:
		return []
	delimiter = get_url_delimiter()
	return [s for s in (raw.split(delimiter) if delimiter else raw.split()) if s]


def authenticate(request, protocol_version: str | None = None) -> AuthContext:
	"""Validate the bearer token, bind audience, set the Frappe user, return context.

	Raises ``MCPAuthError`` / ``MCPAudienceError`` (both HTTP 401) on any failure.
	On success, ``frappe.session.user`` is the token's user for the rest of the
	request.
	"""
	access_token = _extract_bearer_token(request)
	token = _load_token(access_token)
	scopes = _parse_scopes(token.scopes)

	# L2: RFC 8707 audience binding (the gap v16 leaves).
	audience.validate_audience(scopes)

	# L3: map OAuth user -> Frappe user. No service-account fallback.
	frappe.set_user(token.user)

	return AuthContext(
		user=token.user,
		scopes=scopes,
		client_id=token.client,
		session_id=request.headers.get("Mcp-Session-Id"),
		protocol_version=protocol_version,
		ip_address=getattr(frappe.local, "request_ip", None),
	)
