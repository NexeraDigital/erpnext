# Copyright (c) 2026, NexeraDigital and contributors
# For license information, please see license.txt

"""RFC 8707 audience binding — the one OAuth check Frappe v16 does NOT do natively.

v16 serves RFC 9728 protected-resource metadata and advertises
``authorization_servers``, but it does not bind an issued access token to a
specific resource ``aud``. So a token minted for another resource on the same
Frappe AS could otherwise be replayed here. We close that gap by comparing the
token's recorded audience/scope against this server's canonical resource URI from
``MCP Settings.oauth_resource_uri``.

See plan §3.6 (RFC 8707) and §4.6 step 5.
"""

from erpnext.mcp import config
from erpnext.mcp.exceptions import MCPAudienceError


def validate_audience(token_scopes: list[str], token_audience: str | None = None) -> None:
	"""Raise ``MCPAudienceError`` unless the token is intended for this resource.

	The configured ``oauth_resource_uri`` is treated as the canonical audience.
	A token is accepted when either:
	  * its explicit ``aud`` (``token_audience``) equals the resource URI, or
	  * the resource URI appears among the token's granted scopes (Frappe stores
	    resource indicators in the scope string for the authorization-code flow).

	If no resource URI is configured, audience checking is skipped (dev mode) — the
	plan flags configuring it as required before production.
	"""
	resource = config.oauth_resource_uri()
	if not resource:
		# Not configured — skip (documented dev-only behavior).
		return

	if token_audience and token_audience == resource:
		return

	if resource in (token_scopes or []):
		return

	raise MCPAudienceError(
		f"Token audience does not match this resource server ({resource})."
	)
