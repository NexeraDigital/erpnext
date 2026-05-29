# Copyright (c) 2026, NexeraDigital and contributors
# For license information, please see license.txt

"""Typed errors for the MCP server, mapped to HTTP / JSON-RPC responses in endpoint.py."""


class MCPError(Exception):
	"""Base class for MCP server errors."""

	http_status = 400


class MCPDisabledError(MCPError):
	"""The MCP server is disabled in MCP Settings."""

	http_status = 503


class MCPTransportError(MCPError):
	"""L1 transport violation (Origin, protocol version, TLS)."""

	http_status = 403


class MCPProtocolVersionError(MCPTransportError):
	"""Unsupported MCP-Protocol-Version header."""

	http_status = 400


class MCPAuthError(MCPError):
	"""Missing/invalid/expired bearer token. Triggers a 401 + WWW-Authenticate."""

	http_status = 401


class MCPAudienceError(MCPAuthError):
	"""Token audience (RFC 8707) does not match this resource server."""

	http_status = 401


class MCPScopeError(MCPError):
	"""Caller's token lacks the OAuth scope required by the tool (insufficient_scope)."""

	http_status = 403


class MCPRateLimitError(MCPError):
	"""Per-(user, tool) rate limit or concurrency cap exceeded."""

	http_status = 429
