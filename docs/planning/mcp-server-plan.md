# Plan — ERPNext MCP Server for In-Desk AI Chat (Powerful + Secure)

> **Status:** Planning (research complete, design locked, **re-evaluated against Frappe v16 — see §0.1**, awaiting build go-ahead).
>
> **Date drafted:** 2026-05-27. **Re-evaluated for v16:** 2026-05-28.
>
> **Branch:** `russ/migrateToV16`.
>
> **Base:** Frappe **16.18.3** / ERPNext version-16. (Originally drafted against v15 — the v16 re-evaluation in §0.1 supersedes several v15-era assumptions, chiefly around OAuth.)
>
> **Inputs:** `CLAUDE.md` (grounding rule + working rules), `docs/architecture/FORK-CHANGES.md` (current fork scope), `docs/architecture/ARCHITECTURE.md` (system topology), `docs/changes/IMPLEMENTATION-PLAN.md` (AP closed-loop phase plan — runs in parallel, this work does NOT block it).
>
> **Scope of this plan:** stand up an MCP (Model Context Protocol) server inside this ERPNext fork so an LLM-backed chat client (Claude Desktop, MCP Inspector, an in-Desk widget) can query AP data through a secure, audit-logged, permission-respecting tool surface. v1 is **AP-only, read-only**, OAuth 2.1 authenticated, with a deliberate path to broader catalogues in later phases.
>
> **Working assumption:** vertical slices, one PR per slice, each slice ends green tests + a verifiable artifact (e.g. `mcp-inspector` can list tools, `tools/call` round-trip succeeds against a low-privilege user). Cadence matches the AP pilot's existing slice rhythm.
>
> **Grounding rule (mandatory, from `CLAUDE.md`):** every claim about Frappe / MCP / OAuth behavior cites an upstream URL or a source `file:line`. Local memory is not authoritative.

---

## 0.1 v16 Re-Evaluation (2026-05-28) — what changed since the v15 draft

This plan was drafted against Frappe **v15**. The fork is now on Frappe **16.18.3**. One change is load-bearing; it collapses most of the Phase 2 OAuth work and amends decision **L5**.

**Native OAuth 2.x metadata now ships in core.** Everything the plan's `oauth/` subpackage was built to hand-roll on v15 exists natively in v16, gated behind the new **`OAuth Settings`** Single:

| v15-era plan item (now obsolete) | v16 native provision | Source (`apps/frappe`) |
|---|---|---|
| `oauth/discovery.py` — RFC 9728 `/.well-known/oauth-protected-resource` | `handle_wellknown` + `get_protected_resource_metadata` | `frappe/integrations/oauth2.py:269,280,413,426` |
| RFC 8414 auth-server metadata | `get_authorization_server_metadata` | `frappe/integrations/oauth2.py:275,286,300` |
| `oauth/token.py` — RFC 6749 §2.3.1 Basic-auth shim | `get_token` delegates to oauthlib (parses Basic auth natively) | `frappe/integrations/oauth2.py:143-160` |
| `WWW-Authenticate: Bearer resource_metadata=…` on 401 | emitted by **core** | `frappe/app.py:268,322` |
| PKCE / dynamic client registration shims | native PKCE + `register_client` (`enable_dynamic_client_registration`) | `oauth2.py:335`, `oauth_authorization_code.json` |
| Origin allowlist for browser clients (O4) | `OAuth Settings.allowed_public_client_origins` (partial) | `oauth_settings.json` |

**Still on us even in v16:** RFC 8707 audience binding — v16 advertises `authorization_servers` but does **not** bind the token to a resource `aud`, so `auth.py` must still validate audience. **No native MCP server** in core ([frappe/frappe#33170](https://github.com/frappe/frappe/issues/33170) still open), so a build is still required.

**L5 amended → hybrid (vendor frappe/mcp's transport).** `frappe/mcp` is **MIT** (not AGPL like FAC), so its v15-era "depend on neither" rationale doesn't apply to it. Its OAuth piggybacks on core's OAuth2 updates, which **are present in v16** (the `frappe#33188` dependency that 404'd on v15 is satisfied). We therefore **vendor its small MIT transport layer** (Streamable HTTP framing + JSON-RPC dispatch for `initialize`/`ping`/`tools/list`/`tools/call` + OAuth-on-core handshake) into `erpnext/mcp/_vendor/`, and build everything that is our actual value — security layers, Pydantic schemas, the AP tool catalogue, the three DocTypes — on top. See **`docs/changes/ADR-MCP-5-vendor-frappe-mcp-transport.md`**.

Three seams the vendored transport does **not** cover, which we patch:
1. **Schema:** frappe/mcp hand-rolls JSON Schema from `inspect.signature` (the §3.4 anti-pattern). We bypass it — register tools into its `OrderedDict` registry with `PydanticModel.model_json_schema()` as the `inputSchema`.
2. **JSON-RPC errors:** its `handle_call_tool` swallows all exceptions into `isError=True` text (`TODO: proper JSON-RPC error`). We map to real `-32601/-32602/-32603` codes.
3. **Transport L1:** Origin allowlist + `MCP-Protocol-Version` validation are absent; we add them in our wrapper.

---

## 0. Pre-Flight Decisions (Locked)

These were resolved via direct user input on 2026-05-27 and cannot drift without re-opening the design:

| # | Decision | Locked value | Why |
|---|---|---|---|
| L1 | **Module location** | `erpnext/mcp/` (top-level under the app) | Signals the MCP server is a general ERPNext capability, not AP-scoped. Per `CLAUDE.md` working rules, this expands the tracked fork delta — `docs/architecture/FORK-CHANGES.md` + `FORK-CHANGES-PLAIN.md` must be updated in the same commit that introduces the directory. |
| L2 | **v1 tool catalogue scope** | AP-only, read-only — ~5 tools | Smallest surface that proves the architecture end-to-end. Fastest to audit. Write tools (submit/cancel/delete) deferred to Phase 3 with elicitation flow. |
| L3 | **Authentication** | OAuth 2.1 Resource Server from day one | Spec-compliant out of the gate per MCP `2025-11-25` (https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization). Adds ~1–2 days vs. API-key-only, but means no auth rework when the catalogue grows. |
| L4 | **Write tools in v1** | No (read-only) | Defers optimistic-locking + elicitation + dry-run work to Phase 3. Read-only is the smallest surface that's still genuinely useful for an AP analyst. |
| L5 | **Dependency on `frappe/mcp` or Frappe_Assistant_Core** | **Amended for v16 (see §0.1): vendor `frappe/mcp`'s MIT transport layer; reject FAC entirely.** | `frappe/mcp` is MIT and its OAuth works on v16 — vendor its transport (`endpoint`/dispatch/OAuth-handshake) and build our own security + tools on top. FAC is AGPL-3.0 → still mine patterns only, vendor no FAC code. Original v15 value ("vendor neither") is superseded. |
| L6 | **Transport** | Streamable HTTP only (no stdio, no SSE-only legacy) | Per MCP `2025-11-25` (https://modelcontextprotocol.io/specification/2025-11-25/basic/transports). SSE-only is deprecated. Stdio adds complexity for no pilot benefit. |
| L7 | **`run_python_code`-style tool** | Out of scope for v1 (and v2+) | Even with FAC's subprocess + RLIMIT sandbox, the attack surface is large. Expose typed aggregation tools instead. |

Open follow-ups requiring product/security input *before* Phase 2:

| # | Open item | Default proposal | Lock by |
|---|---|---|---|
| O1 | ~~Which OAuth Authorization Server?~~ | **RESOLVED by v16 (§0.1):** Frappe's native AS. v16 ships RFC 9728/8414 metadata + PKCE + dynamic client registration in core — no shims, no external IdP for v1. Configure via `OAuth Settings`. | ✅ Resolved 2026-05-28 |
| O2 | Rate-limit numbers (per-user / per-tool / per-minute) | 60 calls/min/user, 30/min/tool, 5 concurrent/user; configurable in `MCP Settings` Single. | Phase 2 close |
| O3 | Audit log retention | 180 days (matches FAC default); GDPR/SOX review by Brandon. | Phase 2 close |
| O4 | Allowed `Origin` list for browser clients | Local dev only (`http://localhost:*`, `http://127.0.0.1:*`); production list deferred. | Phase 2 close |

A short ADR is appended to `docs/changes/` for each open item the moment it's resolved (one file per decision, `ADR-MCP-<n>-<slug>.md`).

---

## 1. Executive Summary

ERPNext does not ship a first-party AI assistant, and the one community GraphQL app is unmaintained on v15. The Frappe team's own direction is the Model Context Protocol (they shipped `frappe/mcp` as an "experimental" primitive in mid-2025 — https://github.com/frappe/mcp). For our pilot we will **build a from-scratch MCP server** inside this fork, mining proven patterns from `buildswithpaul/Frappe_Assistant_Core` (FAC) without depending on it, and aligning to the MCP `2025-11-25` spec.

The server hangs off a single `@frappe.whitelist()` route, dispatches JSON-RPC 2.0 over Streamable HTTP, authenticates via OAuth 2.1 against Frappe's existing `OAuth Bearer Token` DocType, and exposes a tightly-scoped catalogue of typed tools. Every tool is permission-checked at multiple layers (defense-in-depth), every call is audit-logged with sanitized args, every read scopes results through `frappe.get_list` to inherit Frappe's role + user + permlevel + if-owner enforcement (`apps/frappe/frappe/model/db_query.py:1098-1144`, `apps/frappe/frappe/permissions.py:80-102`).

Power and security are not in tension: `frappe.get_list(...).pluck("name")` for the permitted name set, then `frappe.qb` joins constrained to those names, gives us joins, aggregations, and cross-DocType queries while honoring every permission layer Frappe enforces.

**v1 deliverable:** an MCP Inspector–verifiable AP assistant with five read tools (`list_ap_invoices`, `get_ap_invoice`, `list_vendors`, `get_vendor_balance`, `get_doctype_meta`), full OAuth 2.1 RS, mandatory permission-regression tests, and an immutable audit log. Estimated 3–5 dev days.

---

## 2. Why Not GraphQL

The user originally raised GraphQL as a candidate. The research is clear:

- The canonical community app `leam-tech/frappe_graphql` (https://github.com/leam-tech/frappe_graphql) has been **frozen since Feb 2023**, no tags, no releases. Issue #91 (https://github.com/leam-tech/frappe_graphql/issues/91) documents SDL-generation failures on Frappe v15 with interface-field mismatches.
- The `bitspur/frappe/graphql` GitLab fork (https://gitlab.com/bitspur/frappe/graphql) is single-developer with last meaningful commit Feb 2025.
- DB-level GraphQL via Hasura (https://hasura.io/docs/2.0/databases/mariadb/index/) is a non-starter: Frappe's permission system lives in the Python layer (`frappe.has_permission`, User Permissions, permlevel masking) and Hasura would read `tab*` tables raw, serving every row to every authenticated requester.
- The Frappe team has no public GraphQL roadmap; they have moved to MCP (see `frappe/mcp` plus the Nov-2024 forum thread https://discuss.frappe.io/t/why-frappe-framework-needs-graphql-at-its-core/137536 which got zero maintainer engagement).
- For the LLM use case specifically: LLMs are post-trained on tool calling, not GraphQL composition. A small set of well-named typed tools wins on latency, accuracy, permission safety, and build cost.

**Verdict:** no GraphQL. The MCP path is both the secure path and the maintained path.

---

## 3. Research Findings — Patterns to Adopt and Reject

### 3.1 Frappe v15 query surfaces (what's already there)

| Surface | Joins/aggregations | Permission-safe | Source |
|---|---|---|---|
| `/api/resource/<DocType>` (REST) | No | Yes | https://docs.frappe.io/framework/user/en/api/rest |
| `/api/method/frappe.client.*` | No | Yes | https://github.com/frappe/frappe/blob/version-15/frappe/client.py |
| Whitelisted RPC (`@frappe.whitelist`) | Whatever the author writes | Whatever the author enforces | https://docs.frappe.io/framework/user/en/api/rest |
| `frappe.qb` (Query Builder, PyPika) | **Yes — joins, Sum/Count/Avg, group_by** | **No — caller must filter** | https://docs.frappe.io/framework/user/en/api/query-builder |
| `frappe.db.get_list` | No (single DocType) | **Yes (uses `DatabaseQuery`)** | https://docs.frappe.io/framework/user/en/api/database |
| `frappe.db.get_all` | No | **No — `ignore_permissions=True` baked in** at `apps/frappe/frappe/__init__.py:1384-1387` | Same |
| `frappe.db.sql` | Yes (raw SQL) | **No** | Same |
| `frappe.desk.query_report.run` | Pre-baked reports only | Report-level role gate | https://docs.frappe.io/framework/user/en/desk/reports/query-report |
| Global Search | Keyword only | Yes | https://docs.frappe.io/framework/user/en/api/full-text-search |
| Realtime (`frappe.publish_realtime`) | Push-only | Room-based | https://docs.frappe.io/framework/user/en/api/realtime |
| Background jobs (`frappe.enqueue`) | n/a | Runs as enqueuer | https://docs.frappe.io/framework/user/en/guides/app-development/running-background-jobs |

**The relevant gap:** there is no native permission-respecting endpoint that accepts an arbitrary cross-DocType query. The MCP server closes that gap with typed tools that combine `frappe.get_list` (for permission-gated name sets) and `frappe.qb` (for joins/aggregations).

### 3.2 What's in this fork already

Clean slate. A reconnaissance pass found no `ai/`, `chat/`, `llm/`, `openai`, `anthropic`, `graphql`, `socket.io`, or `langchain` in `hooks.py`, `pyproject.toml`, `package.json`, or `erpnext/public/js/`. Realtime pub/sub is used only for telephony popups and batch-job progress. One orphaned `bot_parsers` hook at `erpnext/hooks.py:527-529` points to a missing `FindItemBot` class — legacy stub, no impact.

### 3.3 Patterns to ADOPT from `Frappe_Assistant_Core` (v2.4.3, https://github.com/buildswithpaul/Frappe_Assistant_Core)

Reading-only audit; we do not vendor any code. License is AGPL-3.0, which would be a problem if we shipped a derivative work.

| Pattern | FAC location | Why adopt |
|---|---|---|
| Centralized `_safe_execute` wrapper guaranteeing every tool call produces an audit row | `frappe_assistant_core/core/base_tool.py:147-275` | Single funnel for success + every error class; consistent timing and error mapping; impossible to "forget" audit. |
| OAuth via Frappe's `OAuth Bearer Token` DocType (no homegrown token store) | `frappe_assistant_core/api/fac_endpoint.py:64-220` | Reuses Frappe's token lifecycle + refresh. |
| Basic-auth + PKCE + `code_challenge_methods_supported` + empty-`jwks_uri` shims on top of Frappe's stock OAuth | `frappe_assistant_core/api/oauth_token.py:23-65`, `frappe_assistant_core/api/oauth_discovery.py:53,80-90` | Minimal viable fixes so MCP Inspector + Claude Desktop work on v15. RFC 6749 §2.3.1 Basic-auth parsing in particular. |
| `Mcp-Session-Id` + `MCP-Protocol-Version` header capture for audit correlation | `frappe_assistant_core/mcp/server.py:255-285` | Cross-call correlation in audit logs; cheap, high value. |
| `permission_query_conditions` hook on the audit DocType | `frappe_assistant_core/hooks.py` | Desk list view of audit logs inherits the same row-level filter as the API. |
| Per-tool config DocType (enable/disable + role allowlist), cached, invalidated on save | `frappe_assistant_core/core/tool_registry.py:50-90`, `assistant_core/doctype/fac_tool_configuration/...` | Ops can kill a tool fleet-wide without redeploying. |
| Two-layer args redaction (predicate at tool layer + defensive re-check at audit sink) | `frappe_assistant_core/core/base_tool.py:35-58`, `frappe_assistant_core/utils/audit_trail.py:28-49` | Belt-and-braces against logging passwords/api_keys. |

### 3.4 Patterns to REJECT from `Frappe_Assistant_Core`

| Pattern | FAC location | Why reject |
|---|---|---|
| Hand-written `inputSchema` per tool; type-only validation in `_validate_type` | `frappe_assistant_core/core/base_tool.py:106-141` | Silently ignores `enum`, `maximum`, `minimum`, `format`, child-object validation. **Use Pydantic models that emit JSON Schema** (https://docs.pydantic.dev/latest/concepts/json_schema/). The schema is the LLM's contract; if it lies, the LLM acts on bad data. |
| Hardcoded `SENSITIVE_FIELDS` and `RESTRICTED_DOCTYPES` lists | `frappe_assistant_core/core/security_config.py:138-275` | Becomes stale; **completely ignores Frappe's `permlevel` metadata**. A custom doctype with `permlevel=1` on a salary field would have the field returned in full. Drive masking off `doc.apply_fieldlevel_read_permissions()` (`apps/frappe/frappe/model/document.py:917-944`) instead. |
| Module-level singleton `MCPServer` with `_tool_registry.clear()` per request | `frappe_assistant_core/api/fac_endpoint.py:60-77` | Race-y under multi-worker gunicorn. Build the tool list per-request into a local registry. |
| Three different OAuth/auth code paths | `api/assistant_api.py:_authenticate_request` + `api/fac_endpoint.py:_authenticate_mcp_request` + OAuth override | Drift risk. **One auth utility, period.** |
| No optimistic locking on `update_document` | `frappe_assistant_core/plugins/core/tools/update_document.py:31-128` | Lost-update hazard. (Moot for our v1 since we're read-only; relevant for Phase 3.) |
| `run_python_code` tool | `frappe_assistant_core/plugins/data_science/tools/run_python_code.py` | Massive attack surface. The subprocess + restricted `__import__` + RLIMITs is well-designed but the regex pre-scan (`:728`) is defeatable; we deliberately do not need this. |
| No rate limiting | n/a (absent) | Single LLM can fan out 100 tool calls/sec. **Use `frappe.rate_limiter`** (https://github.com/frappe/frappe/blob/version-15/frappe/rate_limiter.py). |
| Stringified `dict.__repr__` returned to LLM on legacy path | `frappe_assistant_core/api/handlers/tools.py:159-160` | Always `json.dumps(..., default=str)`. |
| Visualization plugin advertises two different tool lists | `plugins/visualization/plugin.py:42-50` vs `plugin_registry.py:60-86` | Code drift. Single source of truth per tool, deterministic registration at process boot. |

### 3.5 On `frappe/mcp` (https://github.com/frappe/mcp)

Self-described as "highly experimental, expect breaking changes." Single-author repo (Alan Tom, Frappe Technologies — 31 commits, last code change Nov 6 2025, dormant since). Implements `initialize`/`ping`/`tools/list`/`tools/call` + no-op notifications; `resources/*`, `prompts/*`, `completion`, `logging/setLevel` raise `NotImplementedError` (9 methods stubbed). Streamable HTTP only, no SSE. Ships **zero business tools** and **zero permission/audit/rate-limit logic** — it is a transport + `@mcp.tool()` registration library, not a server. **License: MIT.**

OAuth piggybacks on Frappe core's OAuth2 updates (`frappe/frappe#33188`). On **v15** that was absent → `/.well-known/oauth-protected-resource` 404'd (issue #2). **On v16 (our base now) that dependency is satisfied** — verified in `frappe/integrations/oauth2.py` (§0.1), so its OAuth path works out of the box.

**Verdict (amended for v16, see §0.1 / L5):** the package is MIT and its OAuth works on v16, so we **vendor its transport layer** (the JSON-RPC dispatch + `@frappe.whitelist`-as-transport bridge in `frappe_mcp/server/server.py` and `server/handlers.py`) into `erpnext/mcp/_vendor/`, pinned to a commit SHA — and patch the three seams it leaves (signature-inferred schema, swallowed JSON-RPC errors, no Origin/protocol-version validation). We do **not** take a live git/pip dependency, given the repo's dormancy and "breaks without notice" warning.

### 3.6 MCP Specification — non-negotiables (MUST requirements)

Sources: https://modelcontextprotocol.io/specification (current landing), https://modelcontextprotocol.io/specification/2025-11-25 (current stable), https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization, https://modelcontextprotocol.io/specification/2025-11-25/basic/transports, https://modelcontextprotocol.io/specification/2025-11-25/basic/security_best_practices, https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/ (next RC).

We build to `2025-11-25` and design for the `2026-07-28` RC's statelessness (no `initialize`/`initialized` handshake, no `Mcp-Session-Id`).

| Spec MUST | Our implementation |
|---|---|
| Streamable HTTP on a single endpoint; reject SSE-only legacy | `endpoint.py` accepts POST with optional `Accept: text/event-stream`; no separate SSE URL. |
| Validate `Origin` header on every connection (DNS-rebinding defense) | Allowlist in `MCP Settings` Single. |
| TLS for any non-loopback URL | Enforced by infra; refuse plaintext in production via `MCP Settings`. |
| Honor `MCP-Protocol-Version` header on every HTTP request; default `2025-03-26` when absent | Validate in `dispatcher.py`; 400 on unsupported. |
| OAuth 2.1 Resource Server with token audience binding (RFC 8707) | `auth.py` validates `aud` against this server's canonical URI. |
| Publish RFC 9728 Protected Resource Metadata | **Served natively by v16 core** (`frappe/integrations/oauth2.py:handle_wellknown`); we enable it via `OAuth Settings`. (§0.1) |
| `WWW-Authenticate: Bearer resource_metadata="..." scope="..."` on 401 | **Emitted by v16 core** (`frappe/app.py:322`) when resource metadata is enabled; `auth.py` adds `scope` for 403/`insufficient_scope`. |
| Reject tokens in query strings; `Authorization: Bearer` only | Enforced in `auth.py`. |
| **No token passthrough** — server MUST NOT forward tokens to ERPNext API | We map OAuth user → `frappe.set_user()` server-side. |
| 403 with `insufficient_scope` for missing scope | Per-tool scope check in `registry.py`. |
| Tool `inputSchema` is valid JSON Schema 2020-12, never `null` | Pydantic models emit schema. |
| Tool annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`) — honest, but untrusted by client | Set in `BaseTool`; not relied on for server-side authz. |
| Rate-limit tool invocations | `frappe.rate_limiter` per (user, tool). |
| Do NOT expose `sampling/createMessage` | Server does not call back into client LLM. Deprecated in 2026-07-28 RC anyway. |
| Sessions, if used, MUST be cryptographically random and MUST NOT be used for auth | `MCP-Session-Id` is correlation-only; auth is the OAuth token. |

### 3.7 Frappe permission enforcement — the rules every tool follows

Sources: https://docs.frappe.io/framework/user/en/basics/users-and-permissions, https://docs.frappe.io/framework/user/en/api/database, https://docs.frappe.io/framework/user/en/api/query-builder, plus `apps/frappe/frappe/permissions.py` and `apps/frappe/frappe/model/db_query.py` on the version-15 branch.

**Definitive permission-enforcement matrix:**

| API | Role perms | User perms | if_owner | Permlevel strip |
|---|---|---|---|---|
| `frappe.get_list` / `frappe.db.get_list` | yes | yes | yes | yes |
| `frappe.get_all` / `frappe.db.get_all` | **no** (forces `ignore_permissions=True`) | no | no | no |
| `frappe.qb.from_(X).select(...).run()` | **no** | no | no | no |
| `frappe.db.sql(query, values)` | **no** | no | no | no |
| `frappe.db.get_value` / `get_single_value` | basic doctype check only | no | no | no |
| `frappe.desk.query_report.run` | report-level role on `ref_doctype` | depends on report SQL | n/a | n/a |
| `/api/resource/...` REST | yes | yes | yes | yes (column-mode) |
| `/api/method/frappe.client.*` | yes | yes | yes | yes |

**Permission-safety checklist (every MCP tool MUST follow):**

1. MUST call `frappe.has_permission(doctype, ptype, throw=True)` for every DocType the tool reads or writes, before any data access.
2. MUST use `frappe.get_list()` (not `get_all`) for any list query returned to the caller.
3. MUST NOT call `frappe.get_all()` or pass `ignore_permissions=True` to any `frappe.*` API, except in documented system-maintenance paths never reachable from a tool. CI grep rule enforces this in `erpnext/mcp/tools/`.
4. MUST NOT call `frappe.db.sql()` with string-interpolated user input. Use the `values` kwarg with `%s` or `%(name)s` placeholders, or `frappe.qb`.
5. MUST use `frappe.qb` for joins/aggregations, AND MUST constrain the result set with a `WHERE name IN (frappe.get_list(...).pluck("name"))` clause.
6. MUST pass `parent_doctype=` when calling `has_permission` for a child DocType without a `doc` argument.
7. MUST pass `throw=True` to `has_permission` in tool entry points so the caller gets `PermissionError`, not a silently empty result.
8. MUST call `doc.apply_fieldlevel_read_permissions()` on any `frappe.get_doc(...)` result before serializing it back to the caller.
9. MUST treat `Administrator` as unsandboxable. If the tool must enforce a specific role's view of the world, wrap the work in `frappe.set_user(service_user)` / `frappe.set_user(prev)` with `try/finally`.
10. MUST NOT accept doctype or fieldname strings from tool input without an allowlist — `qb` parameterizes values, not identifiers.
11. MUST include unit tests that invoke the tool as a low-privilege role and assert the call raises `frappe.PermissionError` or returns an empty list, never leaked rows.

---

## 4. Architecture

### 4.1 Module layout

**v16 hybrid layout** (see §0.1 / ADR-MCP-5): the transport/dispatch/OAuth-handshake plumbing is vendored from `frappe/mcp` (MIT) under `_vendor/`; we own the thin shell that wires our security + Pydantic schemas into it. The v15 `oauth/` subpackage is **removed** — v16 core + the vendored handshake cover it (only `audience.py` survives, for the RFC 8707 gap v16 leaves).

```
erpnext/mcp/
├── __init__.py
├── _vendor/
│   └── frappe_mcp/        # VENDORED MIT transport: Streamable HTTP framing + JSON-RPC
│       └── ...            # dispatch (initialize/ping/tools/list/tools/call). Pinned to a
│                          # commit SHA; provenance + SHA recorded in ADR-MCP-5.
├── endpoint.py            # @frappe.whitelist() entry → wraps vendored transport; adds L1
│                          # (Origin allowlist + MCP-Protocol-Version) + real JSON-RPC error mapping
├── auth.py                # ONE auth utility: validate v16 OAuth Bearer + audience → frappe.set_user
├── audience.py            # RFC 8707 audience validation (the one OAuth gap v16 leaves)
├── audit.py               # _safe_execute, audit insertion, args sanitization
├── permissions.py         # has_permission helpers; "permitted names" pattern
├── registry.py            # per-request tool registry; injects Pydantic model_json_schema()
│                          # into the vendored OrderedDict (bypasses its signature-inferred schema)
├── tools/
│   ├── __init__.py
│   ├── base.py            # BaseTool with Pydantic input/output models
│   ├── ap_invoices.py     # list_ap_invoices, get_ap_invoice
│   ├── vendors.py         # list_vendors, get_vendor_balance
│   ├── schema.py          # get_doctype_meta (allowlisted DocTypes only)
│   └── _scope.py          # per-tool OAuth scope mapping
└── tests/
    ├── __init__.py
    ├── test_permissions.py  # MUST: low-priv role → PermissionError, never leaked rows
    ├── test_audit.py        # every call produces a row; args sanitization works
    ├── test_auth.py         # OAuth audience, scopes, 401/403
    ├── test_dispatcher.py   # JSON-RPC happy path + every error class
    └── test_tools.py        # per-tool integration: filter validation, pagination
```

### 4.2 New DocTypes

| DocType | Type | Purpose | Permission notes |
|---|---|---|---|
| `MCP Audit Log` | Standard | One row per `tools/call`. Fields: `user`, `tool`, `args_json` (sanitized), `result_status` (Success/Error/Timeout/PermissionDenied), `result_bytes`, `result_truncated`, `error_type`, `error_message`, `latency_ms`, `client_id`, `session_id`, `protocol_version`, `ip_address`, `timestamp`. | `permission_query_conditions` hook scopes list to caller; System Manager + Auditor see all. |
| `MCP Tool Config` | Standard, one row per tool | `tool_name` (Data, unique), `enabled` (Check), `required_role` (Link → Role, optional), `required_oauth_scope` (Data), `rate_limit_per_minute` (Int), `concurrency_cap` (Int), `timeout_seconds` (Int). | Read: System Manager only. |
| `MCP Settings` | Single | `enabled` (Check), `allowed_origins` (Code, JSON list), `allowed_protocol_versions` (Code, JSON list, default `["2025-11-25"]`), `audit_retention_days` (Int, default 180), `audit_output_max_bytes` (Int, default 51200), `oauth_resource_uri` (Data — this server's canonical URI for audience binding). | Read+write: System Manager only. |

All three DocTypes live under `erpnext/mcp/doctype/`.

### 4.3 Defense-in-depth — 14 layers

Each layer is independently testable. Failure at any one short-circuits the request.

| # | Layer | Mechanism | Test |
|---|---|---|---|
| L1 | Transport | TLS-only, `Origin` allowlist, `MCP-Protocol-Version` validation | Reject with 403/400 on violation |
| L2 | OAuth 2.1 RS | Token audience binding (RFC 8707); reject tokens for any other server | `test_auth.py::test_wrong_audience_rejected` |
| L3 | User mapping | OAuth token → `frappe.set_user(...)`; NO service-account fallback | Audit captures real user |
| L4 | Tool scope | Each tool declares OAuth scope; reject with 403 + `insufficient_scope` if missing | `test_auth.py::test_missing_scope_rejected` |
| L5 | Tool role gate | `MCP Tool Config.required_role`; cached, invalidated on save | Ops kill switch test |
| L6 | Frappe permission | `frappe.has_permission(doctype, ptype, throw=True)` for every DocType touched | `test_permissions.py::test_low_priv_user_gets_permission_error` |
| L7 | Query scoping | `frappe.get_list(...).pluck("name")` derives permitted names; `qb` joins constrained to those names | `test_permissions.py::test_qb_join_does_not_leak` |
| L8 | Field-level | `doc.apply_fieldlevel_read_permissions()` on any `get_doc` result; `get_list` already does this for column mode | `test_permissions.py::test_permlevel_1_field_stripped` |
| L9 | Argument validation | Pydantic model per tool; reject 400 before any DB access | `test_tools.py::test_invalid_filter_rejected` |
| L10 | Output sanitization | Treat ERPNext text fields as hostile (prompt-injection vector); strip control sequences in returned strings | `test_tools.py::test_control_chars_stripped` |
| L11 | Destructive ops | (Phase 3) `destructiveHint=true` requires `elicitation/create` confirmation | n/a in v1 |
| L12 | Rate limit | `frappe.rate_limiter` per (user, tool, minute); concurrency cap; per-tool timeout | `test_tools.py::test_rate_limit_enforced` |
| L13 | Audit | `_safe_execute` wraps every call → `MCP Audit Log` row; args sanitized at tool layer AND audit sink; output capped 50 KB | `test_audit.py::test_every_call_produces_row` |
| L14 | No sampling/roots | Server does not call `sampling/createMessage` or request `roots` | grep CI rule: zero references to `sampling/` in `erpnext/mcp/` |

### 4.4 Tool design pattern — the "permitted names" idiom

This is the single most important pattern in the build. It is how we reconcile "powerful (joins, aggregations, cross-DocType)" with "secure (no permission bypass)."

```python
# erpnext/mcp/tools/ap_invoices.py (illustrative)
from pydantic import BaseModel, Field
from typing import Optional
import frappe
from frappe.utils import cint
from erpnext.mcp.tools.base import BaseTool, ToolResult
from erpnext.mcp.permissions import permitted_names


class ListAPInvoicesInput(BaseModel):
    supplier: Optional[str] = Field(None, description="Supplier name to filter by")
    status_in: Optional[list[str]] = Field(None, description="Status filter, e.g. ['Unpaid', 'Overdue']")
    due_before: Optional[str] = Field(None, description="ISO date — include invoices due on or before")
    min_grand_total: Optional[float] = Field(None, ge=0)
    limit: int = Field(50, ge=1, le=200)


class ListAPInvoicesOutput(BaseModel):
    name: str
    supplier: str
    supplier_name: str
    grand_total: float
    outstanding_amount: float
    status: str
    due_date: Optional[str]


class ListAPInvoices(BaseTool):
    name = "list_ap_invoices"
    title = "List AP Invoices"
    description = (
        "List Purchase Invoices with supplier display name and outstanding balance. "
        "Respects the caller's permissions; results limited to invoices the caller may read."
    )
    required_scope = "erpnext:ap_invoice:read"
    annotations = {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False}
    input_model = ListAPInvoicesInput
    output_model = ListAPInvoicesOutput  # list[ListAPInvoicesOutput]

    def execute(self, args: ListAPInvoicesInput) -> ToolResult:
        # L6: Gate the doctypes the tool touches. Throws PermissionError on failure.
        frappe.has_permission("Purchase Invoice", "read", throw=True)
        frappe.has_permission("Supplier", "read", throw=True)

        # Build filters from validated input.
        filters: dict = {"docstatus": ("<", 2)}
        if args.supplier:
            filters["supplier"] = args.supplier
        if args.status_in:
            filters["status"] = ("in", args.status_in)
        if args.due_before:
            filters["due_date"] = ("<=", args.due_before)
        if args.min_grand_total is not None:
            filters["grand_total"] = (">=", args.min_grand_total)

        # L7: Derive permitted names — enforces role + user + if_owner + permlevel.
        names = permitted_names(
            "Purchase Invoice",
            filters=filters,
            limit=cint(args.limit),
            order_by="due_date asc",
        )
        if not names:
            return ToolResult(structured=[])

        # L7 (continued): Join via qb constrained to permitted names. No leak risk.
        pi = frappe.qb.DocType("Purchase Invoice")
        sup = frappe.qb.DocType("Supplier")
        rows = (
            frappe.qb.from_(pi)
            .left_join(sup).on(pi.supplier == sup.name)
            .select(
                pi.name, pi.supplier, sup.supplier_name,
                pi.grand_total, pi.outstanding_amount, pi.status, pi.due_date,
            )
            .where(pi.name.isin(names))
            .orderby(pi.due_date)
        ).run(as_dict=True)

        # L10: Output sanitization handled by base class on serialize.
        return ToolResult(structured=rows)
```

And the helper:

```python
# erpnext/mcp/permissions.py
import frappe

def permitted_names(doctype: str, filters: dict, limit: int = 50, order_by: str = None) -> list[str]:
    """Return the names of `doctype` the current user may read, matching `filters`.

    Wraps frappe.get_list with pluck="name". This enforces role + user permissions,
    if_owner, and permlevel — the canonical permission-safe name set for downstream
    qb joins.
    """
    return frappe.get_list(
        doctype,
        filters=filters,
        pluck="name",
        limit_page_length=limit,
        order_by=order_by,
        # ignore_permissions defaults to False; explicit for the reader.
        ignore_permissions=False,
    )
```

Aggregations follow the same pattern: derive permitted names from `get_list`, then `qb.from_(...).select(Sum(...)).where(name.isin(permitted))`. Aggregations never leak because the WHERE clause restricts to permitted rows.

### 4.5 JSON-RPC dispatcher shape

> **v16 note:** the JSON-RPC dispatch itself is **vendored from `frappe/mcp`** (§0.1) — `initialize`/`ping`/`tools/list`/`tools/call` already work there. Our `endpoint.py` wraps it to add the L1 transport checks and to map errors to real `-32601/-32602/-32603` codes (the vendored `handle_call_tool` swallows them into `isError` text). The table below is the behavior we guarantee, vendored or patched.

The dispatcher implements only what we need for v1:

| Method | Status |
|---|---|
| `initialize` | implemented; negotiates protocol version, returns server capabilities (`tools: {listChanged: false}`) |
| `notifications/initialized` | accepted, no-op |
| `ping` | implemented; returns `{}` |
| `tools/list` | implemented; returns the registry, filtered to tools the caller's scope + role allow |
| `tools/call` | implemented; dispatches to the named tool via `_safe_execute` |
| everything else | `-32601 Method not found` |

All five methods route through one `@frappe.whitelist(allow_guest=False, methods=["POST"])` handler in `endpoint.py`. The decorator's `methods=["POST"]` enforces POST-only at the framework level (https://github.com/frappe/frappe/blob/version-15/frappe/__init__.py).

We deliberately do NOT implement: `completion/complete`, `logging/setLevel`, `prompts/*`, `resources/*`, `sampling/*`, `roots/*`. Each is either out of scope (resources/prompts in v1) or actively unwanted (sampling crosses the trust boundary the wrong way).

### 4.6 OAuth flow

On v16 this flow is almost entirely served by core — we configure `OAuth Settings` rather than build endpoints (see §0.1). Steps 1–3 are **native v16**; only audience validation (step 5) and the user mapping (step 6) are our code.

1. Client (Claude Desktop, MCP Inspector) hits `/.well-known/oauth-protected-resource` → **served natively by v16** (`frappe/integrations/oauth2.py:handle_wellknown`) once `OAuth Settings.show_protected_resource_metadata` is enabled. Returns RFC 9728 metadata pointing to Frappe's AS.
2. Client performs OAuth 2.1 + PKCE authorization code flow against Frappe's native `authorize` (`/api/method/frappe.integrations.oauth2.authorize`) — **PKCE native in v16**.
3. Client exchanges code for token at Frappe's native `get_token` endpoint — **Basic-auth parsing handled natively by oauthlib in v16** (no override needed; the v15 shim is dropped).
4. Client calls our MCP endpoint with `Authorization: Bearer <token>`.
5. `auth.py` validates the token via `frappe.get_doc("OAuth Bearer Token", {"access_token": ...})`, checks `status == "Active"`, expiry, and **audience** (`audience.py`, RFC 8707 — the one check v16 does NOT do natively; compares against `MCP Settings.oauth_resource_uri`).
6. `auth.py` calls `frappe.set_user(token.user)` — every downstream tool runs as that user.

**No token passthrough:** the OAuth token is NEVER forwarded to ERPNext APIs. The server-side `frappe.set_user` is the only credential propagation.

---

## 5. v1 Tool Catalogue (AP, Read-Only)

| Tool | Purpose | DocTypes touched | OAuth scope | Notes |
|---|---|---|---|---|
| `list_ap_invoices` | List Purchase Invoices with supplier display name + outstanding balance | `Purchase Invoice`, `Supplier` | `erpnext:ap_invoice:read` | Filters: supplier, status_in, due_before, min_grand_total. Limit ≤ 200. |
| `get_ap_invoice` | Fetch single Purchase Invoice incl. items child table | `Purchase Invoice`, `Purchase Invoice Item` | `erpnext:ap_invoice:read` | Calls `apply_fieldlevel_read_permissions()` on the doc. |
| `list_vendors` | List Suppliers with summary fields | `Supplier` | `erpnext:vendor:read` | Filters: name_like, country, supplier_group. |
| `get_vendor_balance` | Aggregate outstanding balance for a supplier across all open Purchase Invoices | `Purchase Invoice`, `Supplier` | `erpnext:vendor:read` | `qb` with `Sum(outstanding_amount)` constrained to permitted invoice names. |
| `get_doctype_meta` | Schema introspection for an allowlisted DocType | n/a (reads `frappe.get_meta`) | `erpnext:schema:read` | Allowlist: `Purchase Invoice`, `Purchase Invoice Item`, `Supplier`. No other DocTypes. |

Each tool has:
- A Pydantic `input_model` (validates args before any DB access)
- A Pydantic `output_model` (defines the structured output for MCP `outputSchema`)
- Annotations: `readOnlyHint: true`, `idempotentHint: true`, `openWorldHint: false`
- `required_scope` declared
- A `MCP Tool Config` row (created by patch on install)
- Permission-regression tests (low-priv role → 0 rows or `PermissionError`)
- Audit-log assertion in the integration test

---

## 6. Phased Build Plan

### Phase 1 — Scaffolding + one end-to-end tool (1–2 days)

**Goal:** prove the architecture with a single tool an MCP Inspector can call.

| Slice | Deliverable | Acceptance |
|---|---|---|
| P1.0 | Vendor `frappe/mcp` transport into `erpnext/mcp/_vendor/` (pin SHA; record provenance in ADR-MCP-5); strip its tool examples, keep dispatch + transport | Vendored module imports cleanly; SHA documented |
| P1.1 | Shell: `endpoint.py` (wraps vendored transport + adds L1 Origin/protocol-version checks + real JSON-RPC error mapping), `registry.py`, `tools/base.py` (no-op tools/list returning empty array) | `mcp-inspector` connects, `tools/list` returns `[]`, `ping` works; unknown method → `-32601` |
| P1.2 | `MCP Audit Log` DocType + `audit.py` `_safe_execute` wrapper | Calling a stub tool produces one audit row with sanitized args |
| P1.3 | `MCP Settings` Single + `MCP Tool Config` DocType | Records exist; readable in Desk under System Manager |
| P1.4 | First tool: `list_ap_invoices` (the example in §4.4) with Pydantic input/output + `permitted_names` helper | Tool appears in `tools/list`; `tools/call` returns rows for System Manager; returns `[]` for a role without `Purchase Invoice` read |
| P1.5 | Auth stub: API key/secret for dev only (will be replaced in Phase 2 with full OAuth) | Tool requires valid token to call |

Phase 1 ends with `FORK-CHANGES.md` + `FORK-CHANGES-PLAIN.md` updated to register `erpnext/mcp/` as new fork scope, per `CLAUDE.md` working rules.

### Phase 2 — OAuth 2.1 RS (mostly config on v16) + audit polish + remaining tools (≈1 day — see §0.1)

> **v16 collapse:** the v15 plan budgeted three build slices (discovery, Basic-auth shim, audience) here. v16 ships discovery + Basic-auth + PKCE + dynamic client registration natively, so P2.1–P2.3 collapse into one **configuration** slice plus the one piece v16 doesn't do (audience binding).

| Slice | Deliverable | Acceptance |
|---|---|---|
| P2.1 | **Configure** v16 `OAuth Settings`: enable `show_protected_resource_metadata` + `show_auth_server_metadata`, set `resource_name`/`scopes_supported`/`allowed_public_client_origins` | `curl /.well-known/oauth-protected-resource` (served by core) returns valid RFC 9728 JSON with `resource`, `authorization_servers`, `scopes_supported`, `bearer_methods_supported` |
| P2.3 | `audience.py` — RFC 8707 audience validation (v16 does NOT do this natively) | Token minted for a different `resource` is rejected with 401 + `WWW-Authenticate` (header emitted by core) |
| P2.4 | `auth.py` consolidated: ONE entry point — validate v16 OAuth Bearer + audience → `frappe.set_user`; per-tool scope check; 403 + `insufficient_scope` | `test_auth.py` passes all scenarios |
| P2.5 | Rate limiter via `frappe.rate_limiter` per (user, tool); concurrency cap; per-tool timeout | `test_tools.py::test_rate_limit_enforced` passes |
| P2.6 | Remaining four tools: `get_ap_invoice`, `list_vendors`, `get_vendor_balance`, `get_doctype_meta` | All five tools in `tools/list`; integration tests green |
| P2.7 | Permission-regression test suite | Every tool tested with low-priv role; CI runs the suite |
| P2.8 | Audit log retention scheduler (daily cron, prunes rows older than `audit_retention_days`) | Test verifies prune respects retention |

### Phase 3 — Write tools + elicitation (deferred; 1–2 days when triggered)

Out of scope for v1. When unlocked, adds:

- `create_ap_invoice_draft`, `update_ap_invoice_draft` (`docstatus = 0` only)
- `submit_ap_invoice`, `cancel_ap_invoice`, `delete_ap_invoice` (annotated `destructiveHint=true`; require `elicitation/create` confirmation)
- Optimistic locking via `modified` timestamp check
- Dry-run / `validate_only` flag on create + update

### Phase 4 — Catalogue expansion (open-ended)

Whatever the pilot needs across modules — sales, inventory, payments, dashboards. Each new tool follows the same template (Pydantic input/output, `permitted_names` pattern, scope declared, audit-wrapped, permission-tested).

---

## 7. Test Strategy

### 7.1 Mandatory tests (block merge)

For every tool:

1. **Permission regression** — `test_permissions.py::test_<tool>_denies_low_priv_role`. Invoke the tool as a fresh user with only the default "Guest" role. Assert `PermissionError` or `[]`, never leaked rows.
2. **Argument validation** — `test_tools.py::test_<tool>_rejects_bad_input`. Send malformed args; assert 400 with structured Pydantic error, no DB access in the audit log.
3. **Audit produced** — `test_audit.py::test_<tool>_produces_audit_row`. Every call (success and error) yields exactly one row; args sanitized.

For the server:

4. **Auth — wrong audience rejected** — token minted for a different `resource` claim is rejected with 401 + `WWW-Authenticate`.
5. **Auth — missing scope rejected** — caller without `required_scope` gets 403 + `insufficient_scope`.
6. **Rate limit** — 61st call within a minute from the same user gets rate-limited.
7. **Origin allowlist** — non-allowed `Origin` rejected with 403.
8. **JSON-RPC errors** — unknown method → `-32601`; bad params → `-32602`; internal error → `-32603` with no traceback leak.

### 7.2 Permission-bypass canary

A separate `test_canaries.py` runs as part of CI (the vendored `erpnext/mcp/_vendor/` tree is **excluded** from these greps — it is third-party MIT code reviewed at vendor time, not our tool surface):

- Grep `erpnext/mcp/tools/` for `ignore_permissions=True` or `get_all(` — fail if found.
- Grep `erpnext/mcp/` (excluding `_vendor/`) for `frappe.db.sql(` with f-string or `%` interpolation — fail if found.
- Grep `erpnext/mcp/` (excluding `_vendor/`) for `sampling/` references — fail if found.

These run on every PR touching `erpnext/mcp/`.

### 7.3 Coverage targets

- Tool implementations: 90%+ line coverage.
- `auth.py`, `audit.py`, `permissions.py`: 100% line coverage (security-critical).
- `endpoint.py` (our wrapper over the vendored dispatch): every JSON-RPC error path tested — `-32601/-32602/-32603` mapping, plus L1 Origin/protocol-version rejections. Vendored `_vendor/` code is not a coverage target.

---

## 8. Documentation Updates Required at Merge

Per `CLAUDE.md` working rules:

| File | Update |
|---|---|
| `docs/architecture/FORK-CHANGES.md` | Add `erpnext/mcp/` to the tracked fork delta with the file inventory and a one-line per-module description. |
| `docs/architecture/FORK-CHANGES-PLAIN.md` | Plain-English explainer of the MCP server's purpose, scope, and security posture. Kept in lockstep with `FORK-CHANGES.md`. |
| `docs/architecture/UI-SITEMAP.md` | **No update** in v1 (no user-navigable Desk routes added). Updates required only if/when a Phase 4 widget exposes a Desk Page. |
| `docs/changes/IMPLEMENTATION-PLAN.md` | No update — MCP build runs in parallel to AP closed-loop phases, not as part of them. |
| `docs/planning/mcp-server-plan.md` | (This file) Updated as decisions resolve (O1–O4) and as phases close. |

---

## 9. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| ~~Frappe v15 ships without RFC 9728 metadata~~ — **RESOLVED by v16** | — | — | v16 serves RFC 9728/8414 metadata, PKCE, and dynamic client registration natively (§0.1). No self-published metadata needed; we only configure `OAuth Settings` + validate audience. |
| Vendored `frappe/mcp` transport has a latent bug or the upstream "breaks without notice" before we pull a fix | Medium | Low | Vendored at a pinned SHA, so upstream changes can't reach us unexpectedly; the transport is small and reviewed in PR. We own the seams (schema, error mapping, L1). Re-sync is a deliberate, reviewed action. |
| Prompt injection via ERPNext text fields (vendor name, invoice description) hijacks downstream LLM | Medium | High (vendor-controlled fields are externally writable) | L10 output sanitization strips control sequences; tool descriptions instruct LLM to treat tool output as untrusted data, not instructions. Reference: https://modelcontextprotocol.io/specification/2025-11-25/basic/security_best_practices |
| Tool poisoning — malicious instructions in a tool description influence the LLM | Low (we author the descriptions) | High | Tool descriptions versioned and reviewed in PR. Clients are warned in MCP spec to treat annotations as untrusted; we are the server, so the threat is internal authoring discipline. |
| Permission bypass via `frappe.get_all` slipping into a tool implementation | Medium | Critical | CI canary (§7.2) greps for the pattern; permission-regression tests catch behavioral leaks. |
| Rate limiter misconfigured, allows a single user to exhaust gunicorn workers | Medium | High | Concurrency cap per user (default 5) enforced even if per-minute rate limit fails. Slow-tool timeout (default 30s) prevents indefinite blocking. |
| OAuth token theft → impersonation | Low (TLS, short token lifetime) | High | Token expiry from Frappe's `OAuth Bearer Token` defaults (1 hour access, refresh required). Audit log captures `ip_address` for forensics. |
| Audit log size explodes | Medium | Low | Output capped at 50 KB per row (default); daily retention scheduler prunes per `audit_retention_days` (default 180). |
| Vendored `frappe/mcp` upstream matures (fills `NotImplementedError` stubs, adds resources/prompts) and we want those features | Low | Low | Re-sync from the tracked SHA is a bounded, reviewed merge. We watch upstream; on v16 the OAuth blocker is already gone (§0.1), so a future re-sync is low-friction. |
| MCP `2026-07-28` RC breaks our `2025-11-25` implementation | Medium | Medium | Design uses request-scoped state (no session-as-auth); the RC removes `Mcp-Session-Id` but we already treat it as correlation-only. Migration window is 12+ months per the RC. |

---

## 10. Citations

### Upstream documentation (Frappe v15)
- https://docs.frappe.io/framework/user/en/basics/users-and-permissions
- https://docs.frappe.io/framework/user/en/api/database
- https://docs.frappe.io/framework/user/en/api/query-builder
- https://docs.frappe.io/framework/user/en/api/rest
- https://docs.frappe.io/framework/user/en/api/full-text-search
- https://docs.frappe.io/framework/user/en/api/realtime
- https://docs.frappe.io/framework/user/en/python-api/hooks
- https://docs.frappe.io/framework/user/en/desk/reports/query-report
- https://docs.frappe.io/framework/user/en/guides/app-development/running-background-jobs
- https://docs.frappe.io/framework/user/en/guides/integration/how_to_set_up_oauth

### Frappe source (version-16 branch — our base, Frappe 16.18.3)
- https://github.com/frappe/frappe/blob/version-16/frappe/__init__.py (whitelist, set_user, get_list/get_all, has_permission wrapper)
- https://github.com/frappe/frappe/blob/version-16/frappe/permissions.py (has_permission impl, get_role_permissions, get_doc_permissions)
- https://github.com/frappe/frappe/blob/version-16/frappe/model/db_query.py (DatabaseQuery, apply_fieldlevel_read_permissions, build_match_conditions)
- https://github.com/frappe/frappe/blob/version-16/frappe/model/document.py (Document.apply_fieldlevel_read_permissions)
- https://github.com/frappe/frappe/blob/version-16/frappe/client.py (frappe.client.* whitelisted methods)
- https://github.com/frappe/frappe/blob/version-16/frappe/rate_limiter.py
- https://github.com/frappe/frappe/blob/version-16/frappe/integrations/oauth2.py (**v16 native OAuth metadata** — `handle_wellknown`, `get_protected_resource_metadata` (RFC 9728), `get_authorization_server_metadata` (RFC 8414), `register_client` (RFC 7591), `introspect_token` (RFC 7662); see §0.1)
- https://github.com/frappe/frappe/blob/version-16/frappe/app.py (`WWW-Authenticate: Bearer resource_metadata=…` emitted by core on 401/403)
- https://github.com/frappe/frappe/blob/version-16/frappe/integrations/doctype/oauth_settings/oauth_settings.json (`OAuth Settings` Single — new in v16)

### MCP specification
- https://modelcontextprotocol.io/specification (landing)
- https://modelcontextprotocol.io/specification/2025-11-25 (current stable)
- https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization (OAuth 2.1)
- https://modelcontextprotocol.io/specification/2025-11-25/basic/transports (Streamable HTTP)
- https://modelcontextprotocol.io/specification/2025-11-25/basic/security_best_practices
- https://modelcontextprotocol.io/specification/2025-11-25/server/tools (tool definition, annotations)
- https://modelcontextprotocol.io/specification/2025-11-25/client/elicitation (Phase 3)
- https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/ (next RC)
- https://blog.modelcontextprotocol.io/posts/2026-mcp-roadmap/

### OAuth + security RFCs
- https://www.rfc-editor.org/rfc/rfc6749 (OAuth 2.0)
- https://www.rfc-editor.org/rfc/rfc7591 (Dynamic Client Registration)
- https://www.rfc-editor.org/rfc/rfc8707 (Resource Indicators)
- https://www.rfc-editor.org/rfc/rfc9068 (JWT access tokens)
- https://www.rfc-editor.org/rfc/rfc9728 (Protected Resource Metadata)
- https://owasp.org/www-project-mcp-top-10/

### Reference implementations (patterns mined, not depended on)
- https://github.com/buildswithpaul/Frappe_Assistant_Core (FAC v2.4.3, AGPL-3.0)
- https://github.com/frappe/mcp (official Frappe MCP primitive, MIT, experimental)
- https://github.com/mascor/frappe-mcp-server (MIT, allowlist-driven security)
- https://github.com/The-Commit-Company/Raven (Frappe-native chat app; potential Phase 4 UI host)

### GraphQL — researched and rejected
- https://github.com/leam-tech/frappe_graphql (frozen since 2023; v15 broken per issue #91)
- https://gitlab.com/bitspur/frappe/graphql (single-maintainer fork; not depended on)
- https://discuss.frappe.io/t/why-frappe-framework-needs-graphql-at-its-core/137536 (no Frappe-team engagement)
- https://hasura.io/docs/2.0/databases/mariadb/index/ (DB-level GraphQL; bypasses Frappe permission system, unusable)

---

## 11. Glossary

- **MCP** — Model Context Protocol (https://modelcontextprotocol.io). An open standard for connecting LLM hosts to external tools, resources, and prompts. Maintained at https://github.com/modelcontextprotocol.
- **Resource Server (RS)** — In OAuth 2.1, the server that accepts and validates access tokens to serve protected resources. Our MCP server is an RS.
- **Authorization Server (AS)** — The OAuth server that issues tokens. Frappe's stock OAuth is the AS in our v1.
- **Audience binding (RFC 8707)** — The token includes the canonical URI of the server it's intended for; servers reject tokens not minted for them. Defense against token reuse across services.
- **PKCE** — Proof Key for Code Exchange (RFC 7636). Required by OAuth 2.1 for the authorization code flow.
- **Elicitation** — MCP server-to-host request for user input mid-flow; used for confirmation of destructive ops in Phase 3.
- **Permitted names pattern** — Our idiom for permission-safe joins: derive a `frappe.get_list(...).pluck("name")` set first, then constrain `qb` joins to those names.
- **FAC** — `Frappe_Assistant_Core` (https://github.com/buildswithpaul/Frappe_Assistant_Core), the community MCP server we mined patterns from.
