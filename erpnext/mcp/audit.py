# Copyright (c) 2026, NexeraDigital and contributors
# For license information, please see license.txt

"""The single audit funnel (plan L12/L13, §3.3).

Every ``tools/call`` runs through ``safe_execute``: rate-limit + concurrency cap,
then run the tool, then write exactly one ``MCP Audit Log`` row (success OR error),
with arguments sanitized. Centralizing this makes it impossible to "forget" audit
and keeps timing/error mapping consistent.
"""

import json
import time

import frappe
from frappe.utils import now_datetime

from erpnext.mcp import config
from erpnext.mcp.exceptions import MCPRateLimitError

# L13: two-layer redaction. Arg keys whose values are never logged.
_SENSITIVE_KEYS = {
	"password",
	"passwd",
	"pwd",
	"secret",
	"api_key",
	"api_secret",
	"apikey",
	"token",
	"access_token",
	"refresh_token",
	"authorization",
	"auth",
	"private_key",
	"otp",
	"pin",
}
_REDACTED = "***redacted***"

_RATE_WINDOW_SECONDS = 60


def sanitize_args(args: dict | None) -> dict:
	"""Redact sensitive values from tool arguments before they are logged."""
	if not args or not isinstance(args, dict):
		return {}
	out = {}
	for key, value in args.items():
		if key.lower() in _SENSITIVE_KEYS:
			out[key] = _REDACTED
		elif isinstance(value, dict):
			out[key] = sanitize_args(value)
		else:
			out[key] = value
	return out


def _rl_key(user: str, tool: str, window_number: int) -> str:
	return frappe.cache.make_key(f"mcp-rl:{user}:{tool}:{window_number}")


def _cc_key(user: str, tool: str) -> str:
	return frappe.cache.make_key(f"mcp-cc:{user}:{tool}")


def _check_rate_limit(user: str, tool: str, cfg: dict | None) -> None:
	"""Per-(user, tool) requests-per-minute. 0/absent disables.

	Uses ``frappe.cache`` INCR counters keyed by a 60s window — the same approach
	as ``frappe.rate_limiter.RateLimiter``, but keyed per (user, tool) rather than
	globally per window (which that class does not support).
	"""
	limit = int((cfg or {}).get("rate_limit_per_minute") or 0)
	if limit <= 0:
		return
	window_number = int(time.time()) // _RATE_WINDOW_SECONDS
	key = _rl_key(user, tool, window_number)
	count = frappe.cache.incrby(key, 1)
	if count == 1:
		frappe.cache.expire(key, _RATE_WINDOW_SECONDS)
	if count > limit:
		raise MCPRateLimitError(f"Rate limit exceeded for tool '{tool}' ({limit}/min).")


def _enter_concurrency(user: str, tool: str, cfg: dict | None) -> str | None:
	"""Increment the per-(user, tool) in-flight counter; raise if over cap.

	Returns the cache key to release in ``_exit_concurrency`` (None if disabled).
	"""
	cap = int((cfg or {}).get("concurrency_cap") or 0)
	if cap <= 0:
		return None
	key = _cc_key(user, tool)
	count = frappe.cache.incrby(key, 1)
	# Safety expiry so a crashed request cannot leak a slot forever.
	frappe.cache.expire(key, 300)
	if count > cap:
		frappe.cache.incrby(key, -1)
		raise MCPRateLimitError(f"Concurrency cap exceeded for tool '{tool}' ({cap}).")
	return key


def _exit_concurrency(key: str | None) -> None:
	if key:
		frappe.cache.incrby(key, -1)


def _classify(exc: Exception) -> tuple[str, str]:
	"""Map an exception to (result_status, error_type)."""
	from erpnext.mcp.exceptions import MCPScopeError

	if isinstance(exc, (frappe.PermissionError, MCPScopeError)):
		return "PermissionDenied", type(exc).__name__
	return "Error", type(exc).__name__


def write_audit(
	*,
	tool: str,
	ctx,
	args: dict | None,
	result_status: str,
	result_bytes: int = 0,
	result_truncated: bool = False,
	error_type: str | None = None,
	error_message: str | None = None,
	latency_ms: int = 0,
) -> None:
	"""Insert one immutable MCP Audit Log row. Never raises into the caller."""
	try:
		doc = frappe.new_doc("MCP Audit Log")
		doc.timestamp = now_datetime()
		doc.user = getattr(ctx, "user", None) or frappe.session.user
		doc.tool = tool
		doc.result_status = result_status
		doc.result_bytes = result_bytes
		doc.result_truncated = 1 if result_truncated else 0
		doc.error_type = error_type
		doc.error_message = (error_message or "")[:1000] or None
		doc.latency_ms = latency_ms
		# L13: defensive re-sanitize at the sink, independent of the tool layer.
		doc.args_json = json.dumps(sanitize_args(args), default=str)
		doc.client_id = getattr(ctx, "client_id", None)
		doc.session_id = getattr(ctx, "session_id", None)
		doc.protocol_version = getattr(ctx, "protocol_version", None)
		doc.ip_address = getattr(ctx, "ip_address", None)
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
	except Exception:
		# Audit must never break the request; log to the error log instead.
		frappe.log_error(title="MCP audit write failed", message=frappe.get_traceback())


def safe_execute(tool: str, ctx, cfg: dict | None, run_callable, raw_args: dict | None):
	"""Run a tool with rate-limit/concurrency guards and guaranteed audit.

	``run_callable`` is a zero-arg function that performs the tool's permission
	checks + query and returns a JSON-serializable result. Exceptions propagate to
	the caller (the vendored ``handle_call_tool`` renders them as MCP ``isError``
	content) AFTER an audit row is written.
	"""
	start = time.time()
	max_bytes = config.audit_output_max_bytes()
	cc_key = None
	try:
		_check_rate_limit(ctx.user, tool, cfg)
		cc_key = _enter_concurrency(ctx.user, tool, cfg)

		result = run_callable()

		# Measure (but do not store) result size for the audit row.
		try:
			encoded = json.dumps(result, default=str).encode("utf-8")
			result_bytes = len(encoded)
		except (TypeError, ValueError):
			result_bytes = 0
		latency_ms = int((time.time() - start) * 1000)
		write_audit(
			tool=tool,
			ctx=ctx,
			args=raw_args,
			result_status="Success",
			result_bytes=result_bytes,
			result_truncated=result_bytes > max_bytes,
			latency_ms=latency_ms,
		)
		return result
	except Exception as exc:
		status, error_type = _classify(exc)
		latency_ms = int((time.time() - start) * 1000)
		write_audit(
			tool=tool,
			ctx=ctx,
			args=raw_args,
			result_status=status,
			error_type=error_type,
			error_message=str(exc),
			latency_ms=latency_ms,
		)
		raise
	finally:
		_exit_concurrency(cc_key)
