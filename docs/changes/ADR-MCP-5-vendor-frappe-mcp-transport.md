# ADR-MCP-5 — Vendor `frappe/mcp`'s MIT transport layer (v16 hybrid)

> **Status:** Accepted — 2026-05-28.
> **Supersedes:** the v15-era reading of decision **L5** in `docs/planning/mcp-server-plan.md` ("depend on neither `frappe/mcp` nor FAC; vendor no code").
> **Context doc:** `docs/planning/mcp-server-plan.md` §0.1, §3.5.
> **Decision owner:** Russ (via working session 2026-05-28).

## Context

The MCP server plan was drafted against Frappe **v15**, where:
- `frappe/mcp`'s OAuth depended on `frappe/frappe#33188`, which was absent from v15 → `/.well-known/oauth-protected-resource` 404'd. The transport was therefore unusable out of the box, so L5 chose to build the JSON-RPC dispatcher from scratch and "vendor no code."
- The "vendor no code" stance was also coloured by **`Frappe_Assistant_Core` (FAC)** being **AGPL-3.0** — shipping a derivative of FAC would be a licensing problem.

The fork is now on Frappe **16.18.3**. Two facts change the calculus (verified in local source, §0.1 of the plan):

1. **v16 ships the OAuth metadata natively.** `frappe/integrations/oauth2.py` provides RFC 9728 protected-resource metadata, RFC 8414 auth-server metadata, native PKCE, dynamic client registration (RFC 7591), and token introspection (RFC 7662); `frappe/app.py` emits the `WWW-Authenticate: Bearer resource_metadata=…` header. So `frappe/mcp`'s OAuth — which piggybacks on exactly these core updates — **works on v16**.
2. **`frappe/mcp` is MIT-licensed**, not AGPL. The licensing rationale that argued against vendoring FAC does **not** apply to it.

## Decision

**Vendor `frappe/mcp`'s transport layer** into `erpnext/mcp/_vendor/frappe_mcp/`, pinned to a specific commit SHA, and build all security, schema, tool, and DocType code on top of it ourselves. **Do not** take a live git/pip dependency. **Continue to reject FAC** as a dependency (AGPL) — mine its patterns only.

### Pinned provenance

- **Source:** https://github.com/frappe/mcp
- **License:** MIT (`Copyright (c) 2025 Alan <me@18alan.space>`)
- **Pinned commit:** `0ea7d0ebfb4ff7244a1ee1b3d6b37ffdfa0f2611` (dated 2025-11-06, "fix test")
- **What we vendor:** the Streamable-HTTP transport + JSON-RPC dispatch for `initialize` / `ping` / `tools/list` / `tools/call` (`frappe_mcp/server/server.py`, `server/handlers.py`, `server/tools/handlers.py`, `server/types.py`). We strip the example tools and the signature-based schema inference (`tools/tool_schema.py`) since we replace it.

### What we keep vs. build

| Vendored from `frappe/mcp` | Built by us (our value) |
|---|---|
| HTTP route + Streamable HTTP framing | `BaseTool` + Pydantic input/output models |
| JSON-RPC dispatch (`initialize`/`ping`/`tools/list`/`tools/call`) | `_safe_execute`: rate-limit → `has_permission` → `permitted_names` → `qb` → field-mask → audit |
| `@frappe.whitelist`-as-transport bridge + OAuth-on-v16-core handshake | `auth.py` + `audience.py` (RFC 8707, the one gap v16 leaves) |
| `Tool` registry + `CallToolResult`/`structuredContent` serialization | 5 AP tools + `MCP Audit Log` / `MCP Tool Config` / `MCP Settings` DocTypes |

### Three seams we patch (the vendored transport does NOT cover them)

1. **Schema.** `frappe/mcp` hand-rolls JSON Schema from `inspect.signature` (the §3.4 anti-pattern: drops `enum`/`min`/`max`/`format`). We register tools into its `OrderedDict` registry with `PydanticModel.model_json_schema()` as the `inputSchema`, bypassing its inference.
2. **JSON-RPC errors.** Its `handle_call_tool` swallows all exceptions into `isError=True` text content (an in-code `TODO: proper JSON-RPC error`). Our `endpoint.py` maps to real `-32601/-32602/-32603` codes.
3. **Transport L1.** Origin allowlist + `MCP-Protocol-Version` validation are absent; we add them in `endpoint.py`.

## Consequences

**Positive**
- Drops `endpoint.py`'s from-scratch dispatcher, the whole v15 `oauth/` subpackage, and the Basic-auth/PKCE/discovery shims — roughly a day of plumbing.
- The vendored code is small, MIT, and reviewed at vendor time; pinning to a SHA means upstream's "breaks without notice" warning cannot reach us unexpectedly.
- Our security surface (the part that matters) is unchanged and entirely ours.

**Negative / risks**
- We own the vendored code's maintenance. Re-syncing to a newer upstream SHA (e.g. if it fills its `NotImplementedError` stubs for resources/prompts) is a deliberate, reviewed merge — see the Risks table in the plan.
- The vendored tree is excluded from the §7.2 permission canaries (it is third-party code, not our tool surface); we accept this and gate it with a one-time vendor review instead.

## Revisit when

- Frappe ships a **native** MCP server in core ([frappe/frappe#33170](https://github.com/frappe/frappe/issues/33170)) — at which point we re-evaluate dropping the vendored transport for the core one.
- We need resources/prompts/SSE, which the pinned `frappe/mcp` stubs out — triggers either a re-sync or our own implementation.
