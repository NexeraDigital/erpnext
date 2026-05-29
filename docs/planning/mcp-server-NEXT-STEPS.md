# MCP Server — Next Steps / Handoff Context

> **Date:** 2026-05-28. **Branch:** built on `russ/mcp-server`, merged into `russ/migrateToV16`.
> **Base:** Frappe 16.18.3 / ERPNext version-16.
> **Plan:** [`docs/planning/mcp-server-plan.md`](./mcp-server-plan.md) · **Decision:** [`docs/changes/ADR-MCP-5-vendor-frappe-mcp-transport.md`](../changes/ADR-MCP-5-vendor-frappe-mcp-transport.md) · **Fork delta:** [`docs/architecture/FORK-CHANGES.md`](../architecture/FORK-CHANGES.md) §10.

---

## 1. What is done

v1 of the AP MCP server (read-only) is **built, unit-tested, and committed**. Two commits:

- `feat(mcp): add read-only AP MCP server (v1)` — module, 3 DocTypes, 5 tools, vendored transport, hooks.
- `test(mcp): full unit + integration test suite` — 104 test methods across 12 modules.

**Verified so far:** all modules compile (bench Python 3.14); all 3 DocType JSONs valid; **43 DB-free unit tests pass**; the vendored transport imports through the `sys.path` shim and round-trips JSON-RPC (ping / unknown-method `-32601` / tools-list / tools-call).

**NOT yet verified:** anything that needs a migrated site — `bench migrate`, the ~61 integration tests, and a live MCP Inspector round-trip. That is the top of the next-steps list.

---

## 2. Immediate next steps (the critical path to a working server)

Do these in order. Items marked **(state-changing)** modify the local site — run them yourself or approve them.

### 2.1 Migrate the site **(state-changing)**
```bash
bench --site erpnext.localhost migrate
```
This installs the `MCP` module, the three DocTypes (`MCP Settings`, `MCP Tool Config`, `MCP Audit Log`), and — via the `after_migrate` hook — seeds one `MCP Tool Config` row per tool. Confirm:
```bash
bench --site erpnext.localhost console
>>> frappe.get_all("MCP Tool Config", pluck="name")
# expect: list_ap_invoices, get_ap_invoice, list_vendors, get_vendor_balance, get_doctype_meta
```

### 2.2 Run the integration tests **(state-changing — writes test data, rolls back)**
```bash
for m in test_dispatcher test_audit test_rate_limit test_tools_integration \
         test_endpoint test_permissions test_config test_tasks; do
  bench --site erpnext.localhost run-tests --module erpnext.mcp.tests.$m
done
# DB-free (fast, always-green) subset:
for m in test_canaries test_tools test_auth test_registry; do
  bench --site erpnext.localhost run-tests --module erpnext.mcp.tests.$m
done
```
If `test_permissions::TestUserPermissionScoping` fails on a missing Supplier read, give the test user the role that carries Supplier read in your build (it currently uses `Accounts User`).

### 2.3 Configure OAuth on the AS side (Frappe core, v16) **(state-changing)**
In **OAuth Settings** (Single, new in v16):
- Enable `show_protected_resource_metadata` and `show_auth_server_metadata`.
- Set `scopes_supported` (one per line):
  `erpnext:ap_invoice:read`, `erpnext:vendor:read`, `erpnext:schema:read`.
- Optionally enable `enable_dynamic_client_registration` for MCP clients that self-register.

Verify discovery is served by core:
```bash
curl -s http://erpnext.localhost/.well-known/oauth-protected-resource | python -m json.tool
```

### 2.4 Configure **MCP Settings** **(state-changing)**
- `enabled` = ✔
- `oauth_resource_uri` = the canonical URL of this MCP endpoint (e.g. `http://erpnext.localhost/api/method/erpnext.mcp.endpoint.handle_mcp`). **Required for RFC 8707 audience binding** — if left blank, audience checks are skipped (dev only). See §3.
- `allowed_origins` — keep localhost for dev; add the production origin(s) later (open item **O4**).
- `allowed_protocol_versions` — default `["2025-11-25", "2025-06-18", "2025-03-26"]` is fine.

### 2.5 Register an OAuth Client for the MCP client **(state-changing)**
Create an **OAuth Client** for Claude Desktop / MCP Inspector with redirect URI, the scopes above, and PKCE (native in v16). Note the `client_id`.

### 2.6 Smoke-test with MCP Inspector
```bash
npx @modelcontextprotocol/inspector
```
Point it at `http://erpnext.localhost/api/method/erpnext.mcp.endpoint.handle_mcp`, complete the OAuth flow, then: `initialize` → `tools/list` (should show only the tools your token's scopes allow) → `tools/call list_ap_invoices`. Confirm an `MCP Audit Log` row appears per call.

---

## 3. Known caveats / TODOs discovered during the build

These are real and should be triaged before production. None block local bring-up.

1. **`initialize` advertises `protocolVersion: "2025-03-26"`** — the vendored `handle_initialize` returns that constant. Our `endpoint.py` validates the client's `MCP-Protocol-Version` header against `MCP Settings.allowed_protocol_versions`, but the *negotiated* version echoed back is the vendored constant. If a client strictly requires `2025-11-25` in the initialize result, patch the vendored `handle_initialize` to echo the negotiated version (record it in `_vendor/PROVENANCE.md`).
2. **Malformed-JSON body → HTTP 500, not JSON-RPC `-32700`** — the vendored `handle()` catches `json.JSONDecodeError`, but Werkzeug raises `BadRequest` on bad JSON, so it falls through to our generic 500 handler. Low impact (well-behaved clients send valid JSON); fix by normalizing in `endpoint.py` if a client needs the spec error.
3. **Audience binding requires `oauth_resource_uri`** — leaving it blank skips the RFC 8707 check (documented dev behavior). MUST be set before any non-loopback deployment.
4. **Frappe v16 token has no native `aud` claim** — `audience.validate_audience` matches the resource URI against the token's *scope* string (Frappe stores resource indicators there for the auth-code flow). If you mint tokens differently, revisit `audience.py`.
5. **Concurrency cap uses cache counters** with a 300s safety expiry; a crashed worker could transiently over-count its slot until expiry. Acceptable for the pilot.
6. **`.claude/worktrees/mcp-server` shows as a modified tracked path** in the main repo working tree — looks like an embedded-worktree gitlink artifact. Clean up the worktree (`git worktree remove`) once this work is merged so it doesn't get committed accidentally.
7. **No CI wiring yet** — the §7.2 canaries and DB-free unit tests should be added to the repo's test workflow so they run on every PR touching `erpnext/mcp/`.

---

## 4. Open decisions (from the plan §0) — current state

| # | Item | Current value | Action |
|---|---|---|---|
| O1 | OAuth Authorization Server | **Resolved** — Frappe v16 native AS | none |
| O2 | Rate-limit numbers | Defaults seeded: 30/min/tool, concurrency 5, 30s timeout | confirm with security; tune `MCP Tool Config` rows |
| O3 | Audit retention | 180 days (default) | GDPR/SOX review by Brandon → ADR if changed |
| O4 | Allowed Origins (prod) | localhost only | set production origins before deploy → ADR |

Record an ADR (`docs/changes/ADR-MCP-<n>-<slug>.md`) when O2/O3/O4 are finalized.

---

## 5. Later phases (not started)

- **Phase 3 — write tools** (plan §6): `create_ap_invoice_draft`, `update_ap_invoice_draft` (docstatus 0 only), `submit/cancel/delete_ap_invoice` (annotated `destructiveHint=true`, require `elicitation/create` confirmation), optimistic locking via `modified`, `validate_only` dry-run. The `BaseTool` and audit funnel already support this; add a write path + elicitation in `endpoint.py`.
- **Phase 4 — catalogue expansion** (plan §6): sales, inventory, payments, dashboards. Each new tool follows the same template (Pydantic in/out, `permitted_names`, scope declared, audit-wrapped, permission-tested). Add a `MCP Tool Config` row via `install.sync_tool_configs`.

---

## 6. Re-sync the vendored transport (if ever needed)

Vendored at `frappe/mcp` @ `0ea7d0e` (MIT). To update: re-clone upstream, check out the new commit, copy the same file set into `erpnext/mcp/_vendor/frappe_mcp/`, re-apply the one lazy-import patch, update the SHA in `_vendor/PROVENANCE.md` + ADR-MCP-5, and re-run the MCP test suite. Watch for upstream filling its `NotImplementedError` stubs (resources/prompts) — that would be the trigger to re-sync.

---

## 7. Quick reference — module map

| File | Role |
|---|---|
| `erpnext/mcp/endpoint.py` | the only HTTP route; L1 transport + auth + scope gate + dispatch |
| `erpnext/mcp/auth.py` / `audience.py` | OAuth bearer → `set_user`; RFC 8707 audience |
| `erpnext/mcp/audit.py` | `safe_execute`: rate-limit, concurrency, one audit row per call |
| `erpnext/mcp/permissions.py` | `permitted_names` idiom |
| `erpnext/mcp/registry.py` | per-request registry + `assert_can_call` |
| `erpnext/mcp/config.py` | MCP Settings / Tool Config accessors |
| `erpnext/mcp/tools/` | `BaseTool`, `_scope`, and the 5 AP tools |
| `erpnext/mcp/doctype/` | `MCP Settings`, `MCP Tool Config`, `MCP Audit Log` |
| `erpnext/mcp/_vendor/frappe_mcp/` | vendored MIT transport |
| `erpnext/mcp/tests/` | 12 test modules (`_helpers.py` has the fixtures) |
