# AI Chat Panel — Implementation Plan

> **Status:** Plan (design locked, awaiting build go-ahead). **No code written yet.**
>
> **Date drafted:** 2026-05-31.
>
> **Branch:** `russ/migrateToV16`.
>
> **Base:** Frappe **16.18.3** / ERPNext version-16.
>
> **Brief (the ask):** [`docs/planning/ai-chat-panel-brief.md`](./ai-chat-panel-brief.md) — a globally-accessible, context-aware, production-secure AI chat panel for the ERPNext desk that uses the existing Claude API key and the existing ERPNext MCP server.
>
> **Inputs:** [`docs/planning/mcp-server-plan.md`](./mcp-server-plan.md) + [`mcp-server-NEXT-STEPS.md`](./mcp-server-NEXT-STEPS.md) (the MCP server this consumes), [`docs/planning/real-ocr-implementation-plan.md`](./real-ocr-implementation-plan.md) + [`ocr-provider-choice-claude.md`](./ocr-provider-choice-claude.md) (the existing Claude/`AI Provider Settings` integration), [`docs/architecture/UI-SITEMAP.md`](../architecture/UI-SITEMAP.md), [`docs/architecture/ARCHITECTURE.md`](../architecture/ARCHITECTURE.md), `CLAUDE.md` (grounding + working rules).
>
> **Grounding rule (mandatory, from `CLAUDE.md`):** every claim about a Frappe surface cites an upstream doc URL or a source `file:line`. See §8.

---

## 0. TL;DR

Add a **globally-mounted, context-aware AI chat panel** to the ERPNext desk. It is a thin, **secure consumer** of two subsystems that are **already built on this branch** — it does not introduce a second secret store or a second permission path:

1. **The Claude API key** already lives on the `AI Provider Settings` Single (System-Manager-only, encrypted) and is read via `erpnext/ai/credentials.py::get_ai_credentials("anthropic")`. The chat reuses it verbatim. The key never reaches the browser.
2. **The ERPNext MCP server** (`erpnext/mcp/`) already exposes five permission-enforcing, audit-logged, read-only AP tools. The chat consumes that tool catalogue **in-process, running as the logged-in desk user**, so every RBAC + audit layer applies unchanged.

**The security crux:** because the desk session is already authenticated, the chat backend (a `@frappe.whitelist()` method already running as `frappe.session.user`) calls the MCP tools directly in-process — it does **not** mint an OAuth token for the browser. The OAuth/HTTP transport stays reserved for external clients (Claude Desktop, MCP Inspector). Result: the API key, the Claude call, and all credentials stay strictly server-side; every data read runs under the calling user's permissions.

**Two decisions locked (see §2):** streaming uses **enqueue + realtime (Socket.IO)** — validated against Raven, the flagship Frappe-native AI chat app; and **v1 is read-only** — the model has no write/exec tools, so the worst-case failure is "showed data the user could already see."

---

## 1. Discovery findings (Phase 1 — read-only)

### 1.1 Claude API key — reuse, don't re-store

- Stored on **`AI Provider Settings`** Single (`erpnext/ai/doctype/ai_provider_settings/`), **System Manager read+write only** (confirmed in its JSON `permissions`), as a Frappe `Password` field → encrypted at rest in `__Auth`.
- Retrieved via `erpnext/ai/credentials.py` → **`get_ai_credentials("anthropic")`** returning `AICredentials(api_key, default_model, zdr_enabled)`. Raises `AICredentialsNotConfigured` (a `ValidationError`, surfaced 4xx, key-free message) when unset.
- The `anthropic` SDK is already a dependency (`pyproject.toml:29`, `anthropic>=0.40.0`; installed 0.105.2).
- **Decision:** the chat backend calls `get_ai_credentials("anthropic")` server-side. No second secret store.

### 1.2 ERPNext MCP server — already built, read-only, permission-enforcing

- Lives at `erpnext/mcp/`. HTTP route `erpnext.mcp.endpoint.handle_mcp` wraps a vendored `frappe/mcp` transport; **OAuth 2.1 bearer auth** (`auth.py`) → `frappe.set_user(token.user)`. Five v1 tools, **AP, read-only**: `list_ap_invoices`, `get_ap_invoice`, `list_vendors`, `get_vendor_balance`, `get_doctype_meta`.
- **Permission enforcement is inside the tools** — the "permitted names" idiom: `frappe.get_list(...).pluck("name")` (role + User-Permission + permlevel safe) → `frappe.qb` joins constrained to that set; `frappe.has_permission(..., throw=True)`; `doc.apply_fieldlevel_read_permissions()`. The tools run as whatever `frappe.session.user` is set to — they do **not** run privileged.
- `audit.safe_execute(tool, ctx, cfg, callable, args)` wraps every call with per-(user,tool) rate-limit + concurrency cap + one immutable `MCP Audit Log` row, args sanitized.
- `registry.get_catalogue()` → `{name: ToolClass}`; `registry.assert_can_call(ctx, name)` enforces the enable/role/scope gate; `tools._scope.is_visible(ctx, cls, cfg)` filters the visible set.

### 1.3 Architecture conclusion (the security crux)

The panel must **not** mint an OAuth token for the browser. The desk session has already authenticated the user, so the chat backend consumes the MCP tool catalogue **in-process**: it builds an `AuthContext(user=frappe.session.user, …)` and dispatches each Claude tool call through `audit.safe_execute`. Every RBAC layer (`has_permission`, permitted-names, permlevel) and the audit funnel run unchanged, as the calling user. The OAuth/HTTP transport stays for external clients only. The API key, the Claude calls, and credentials stay strictly server-side.

### 1.4 Global desk mount point — grounded

- **`app_include_js`** (`hooks.py:25`, currently the string `"erpnext.bundle.js"`) injects JS into `desk.html` on **every desk route** and **accepts a string or a list** — [Frappe hooks docs](https://docs.frappe.io/framework/v15/user/en/python-api/hooks). The panel mounts once and **survives SPA navigation** (the desk never full-reloads), giving free state preservation.
- **Live context capture** via the client router: `frappe.router.on('change', cb)` ([router.js:441 `make_event_emitter`, :168 `trigger("change")`](https://github.com/frappe/frappe/blob/version-15/frappe/public/js/frappe/router.js)) and `frappe.get_route()` which returns `["Form", doctype, name]` / `["List", doctype, "List"]` / `["Workspaces", name]` (router.js:432–433). On a Form, `cur_frm`/`frm` exposes `frm.doctype`, `frm.docname`, `frm.doc` ([Frappe Form API](https://docs.frappe.io/framework/v15/user/en/api/form)).
- **`extend_bootinfo`** ([hooks docs] above) exposes a server-set `frappe.boot.ai_chat_enabled` flag so the launcher renders only when the feature is on and the user is permitted.
- `UI-SITEMAP.md` confirms there is no existing global AI affordance; the navbar/awesomebar is the only comparable global element.

### 1.5 Established fork conventions matched

- Whitelisted methods: `@frappe.whitelist()` defaults to **`allow_guest=False` → rejects Guest** ([`frappe/__init__.py:1263`](https://github.com/frappe/frappe/blob/version-15/frappe/__init__.py)). AP examples: `run_dedupe_for`, `run_fake_extraction_for` (`ap_invoice_capture.py`).
- Async: `frappe.enqueue` with `deduplicate=True` + per-entity `job_id` (the AP cascade `_enqueue_next`). Background jobs set the user, so tool calls in the job run under the session user's permissions.
- Streaming: `frappe.publish_realtime` to the `user:{username}` room (allowed without extra permission checks) + client `frappe.realtime.on` ([realtime docs](https://docs.frappe.io/framework/v15/user/en/api/realtime)) — the same Socket.IO pattern ARCHITECTURE.md notes for telephony/progress.

### 1.6 Reputable precedent — Raven (The Commit Company)

Raven is the flagship Frappe-native chat app with AI agents (by The Commit Company / Nikhil Kothari; on the [official Frappe blog](https://frappe.io/blog/community-updates/raven-v2-by-the-commit-company)). Reading its AI source ([`raven/ai/handler.py`, `ai.py`](https://github.com/The-Commit-Company/raven)):

- It runs the LLM call in a **background job** (`ai.py` comment: *"AI processing happens in background job"*), not a held-open web request.
- It delivers responses to the chat UI via **`frappe.publish_realtime` (Socket.IO)** — status events during tool execution, plus the completed message (`on_text_done` → `bot.send_message`). **No SSE / streaming HTTP endpoint.**
- It does **not** stream token-by-token to the browser; it pushes interim status + whole messages.

This is exactly the architecture this plan adopts (§2 decision D1). Frappe core has no first-class SSE-from-whitelisted-method path; realtime *is* Socket.IO. The SSE precedents that exist are all standalone async services (FastAPI/OpenFaaS), not the Frappe sync-gunicorn desk.

---

## 2. Locked decisions

| # | Decision | Locked value | Why |
|---|---|---|---|
| **D1** | **Streaming / turn execution** | **Enqueue + realtime (Socket.IO).** `start_turn` enqueues a background job that runs the Claude turn as the calling user and pushes interim status events + the answer (chunked for a typewriter feel) over `frappe.publish_realtime` to the `user:{username}` room. **No SSE, no held-open web worker.** | Keeps the desk responsive under load (a synchronous streaming HTTP endpoint would pin a scarce gunicorn web worker for the whole 5–30 s turn and can starve the site-wide pool). Matches the fork's async convention and the Raven precedent (§1.6). Survives mid-turn reloads (job completes, panel re-syncs from the persisted message). |
| **D2** | **Data-write scope (v1)** | **Read-only.** The chat exposes only the 5 existing read-only MCP tools. No write/exec tools. | Smallest secure surface: worst-case failure (injection, hallucination, forged context) is "showed data the user could already see," never corruption/sent email. Matches MCP v1. Write/action tools deferred to a later phase behind a server-enforced confirmation + role gate (MCP Phase 3 elicitation). |
| **D3** | **MCP consumption path** | **In-process** (not over OAuth/HTTP). Build an `AuthContext(user=frappe.session.user, …)`; dispatch via `audit.safe_execute`. | The desk session is the credential; minting an OAuth token for the browser would put a token client-side and cross an unnecessary boundary. In-process keeps everything server-side and runs as the calling user. |
| **D4** | **Scope-layer treatment for the desk path** | Grant the in-desk `ctx` the **union of catalogue OAuth scopes**; rely on Frappe RBAC (`has_permission`/permitted-names/permlevel) + `MCP Tool Config.enabled`/`required_role` for enforcement. | OAuth *scope* is a delegated-client concept (for Claude Desktop etc.). The directly-acting desk user is bounded by Frappe RBAC, which is strictly narrower. A user can reach any tool their **role** permits, never any data their **permissions** forbid. An optional chat-specific tool allowlist is tracked as a deferred control — see `TODO.md` **T-009**. |
| **D5** | **Conversation persistence** | New owner-scoped `AI Chat Conversation` + `AI Chat Message` DocTypes. | Cross-reload history, audit of "who asked what against which record," and the reconcile target when a realtime event is missed. |

---

## 3. Security design (Phase 2 — the priority)

**Trust boundary:** `Browser (desk session) → whitelisted Frappe endpoint (runs as frappe.session.user) → server-side Claude call (key from AI Provider Settings) → in-process MCP tools (same user) → MariaDB`. The browser never sees the API key, never holds an OAuth token, and never talks to Anthropic or MariaDB directly.

| Requirement | Where | Mechanism |
|---|---|---|
| **Authentication** | `chat/api.py` | `@frappe.whitelist(allow_guest=False, methods=["POST"])` (Guest rejected by default — [`frappe/__init__.py:1263`](https://github.com/frappe/frappe/blob/version-15/frappe/__init__.py)) **plus** an explicit `frappe.session.user not in ("Guest", None)` assertion → 401. No anonymous access; no key in the browser. |
| **Authorization / RBAC** | every tool call, via `audit.safe_execute` | Runs as `frappe.session.user` — **never Administrator, never a service account.** Each tool's `frappe.has_permission(..., throw=True)` ([:1362](https://github.com/frappe/frappe/blob/version-15/frappe/__init__.py)) + permitted-names (`get_list`, never `get_all` — [:1758 vs :1777](https://github.com/frappe/frappe/blob/version-15/frappe/__init__.py)) + permlevel field-stripping enforce role + record-level User Permissions + field-level access. Denial → `PermissionError` → `PermissionDenied` audit row → refusal returned to the model; no rows leak. |
| **Per-tool gating** | `registry.assert_can_call` | Honors `MCP Tool Config.enabled` (ops kill-switch) + `required_role` (role allowlist). |
| **Context re-validation** | `chat/context.py` | Client-supplied `{doctype, name, view}` is a **hint only**. Before any read: `frappe.has_permission(doctype, "read", doc=name, throw=True)`, then **re-fetch server-side** (`frappe.get_doc` + `apply_fieldlevel_read_permissions`). **Browser field values are never trusted and never used for a write.** Forged/escalated context (unreadable doctype/name) → `PermissionError`/403. |
| **Secret handling** | `chat/agent.py` | Key fetched per-turn via `get_ai_credentials`, held in process memory only for the Anthropic call; never logged, never in realtime payloads, audit rows, or `frappe.boot`. |
| **Rate limiting** | `chat/api.py` + `safe_execute` | Per-user turn cap via `frappe.cache` INCR window (mirrors `audit._check_rate_limit`); per-(user,tool) limits already enforced by `safe_execute`. |
| **Audit** | `MCP Audit Log` + `AI Chat Message` | Tool calls already logged by the MCP funnel (who, which tool, which record, IP/session, latency, result status). Chat turns (prompt + context + assistant summary + tools invoked) logged to the owner-scoped `AI Chat Message`. |
| **Prompt injection** | system prompt + L10 | Tool output (ERPNext text fields) is framed as **untrusted data, not instructions**; MCP's existing control-char sanitization (L10) applies; the model has **no write/exec tools** in v1. |
| **Write gating** | n/a in v1 | Read-only (D2). Any future write/action tool is gated behind explicit in-panel confirmation enforced server-side + a role check. |

### 3.1 Threat model

| Attacker | Vector | Mitigating control |
|---|---|---|
| Curious low-privilege user | Asks the chat for data they can't see | Tools run as `frappe.session.user`; `has_permission` + permitted-names return empty / `PermissionError`; audit row recorded |
| Compromised desk session | Drives the panel | Same RBAC ceiling as the user; read-only tools; per-user rate limit; full audit incl. IP/session |
| Prompt injection via document content | Malicious text in a supplier/description field | Tool output framed as untrusted data; no write/exec tools; control-char stripping; (any future action requires human confirmation) |
| Forged / escalated context payload | Browser sends a doctype+name the user can't access, or spoofed field values | Server re-validates via `has_permission(doc=…, throw=True)` and re-fetches; browser field values never used for writes |
| Secret exfiltration | Trick the model/UI into echoing the key | Key never enters model context, realtime, audit, or boot; only in memory during the API call |
| Guest / unauthenticated | Hits the endpoint directly | `allow_guest=False` + explicit session assertion → 401 |

---

## 4. Implementation plan (Phase 3)

### 4.1 Backend — `erpnext/ai/chat/` (inside the existing `erpnext/ai/` fork scope)

| File | Role |
|---|---|
| `context.py` | `resolve_context(doctype, name, view)`: re-validate via `has_permission(throw=True)`, re-fetch with `apply_fieldlevel_read_permissions`, return a compact permitted grounding dict. Forged context → `PermissionError`. |
| `agent.py` | Server-side Claude loop: build the tool list from `registry.get_catalogue()` filtered by `_scope.is_visible` for the in-desk `AuthContext`; convert each tool to an Anthropic tool schema (`tool_cls.input_schema()`); run the messages/tool-use loop; dispatch tool calls through `audit.safe_execute`; **prompt caching** on the system prompt + tool definitions; publish interim status events + the answer (chunked) via `frappe.publish_realtime` to `user:{session_user}`. |
| `api.py` | Whitelisted endpoints: `start_turn(conversation, message, context)` (`allow_guest=False`, `methods=["POST"]`, non-Guest assertion) → `frappe.enqueue(..., user=frappe.session.user, deduplicate=True, job_id=…, queue="short")` the agent loop; `get_conversation(name)`; `clear_conversation(name)`. (A dedicated chat queue keeps first-token latency low.) |
| `doctype/ai_chat_conversation/` | `AI Chat Conversation` — owner-scoped (user sees only own; System Manager all). |
| `doctype/ai_chat_message/` | `AI Chat Message` — owner-scoped; one row per turn (user prompt, context ref, assistant summary, tools invoked). Persistence + audit + cross-reload history. |
| `boot.py` (or extend existing) | `extend_bootinfo` handler → `frappe.boot.ai_chat_enabled`. |

### 4.2 Front-end — global, mounted via `app_include_js`

- New bundle `erpnext/public/js/ai_chat/ai_chat.bundle.js`; add it to `app_include_js` as a **list** alongside `erpnext.bundle.js`. Singleton mounted once → state survives SPA navigation.
- **Persistent launcher** (floating action button / docked rail) on every route, gated on `frappe.boot.ai_chat_enabled`; opens a non-blocking **slide-over**; **keyboard toggle** (Ctrl/Cmd-J); mobile-responsive.
- **Live context chip:** subscribe to `frappe.router.on('change')`; read `frappe.get_route()` / `cur_frm` (`frm.doctype/docname/doc`); display "Context: Purchase Invoice ACC-PINV-0001" with **clear/pin**; refresh on every route change. Context sent to the backend is a hint only.
- **Streaming + states:** `frappe.realtime.on('ai_chat_delta:<conversation>')` renders status + chunked answer incrementally; graceful loading/error/empty states; conversation history from the DocType; reconcile against the persisted message if a socket event is missed.

### 4.3 Files to add / modify

**Add:**
- `erpnext/ai/chat/__init__.py`, `context.py`, `agent.py`, `api.py`, `boot.py`
- `erpnext/ai/chat/doctype/ai_chat_conversation/` (+ `.json`, `.py`, `__init__.py`)
- `erpnext/ai/chat/doctype/ai_chat_message/` (+ `.json`, `.py`, `__init__.py`)
- `erpnext/public/js/ai_chat/ai_chat.bundle.js` (+ panel/launcher/context-chip components)
- `erpnext/ai/chat/tests/` (see §5)
- `test/testplans/ai-chat-panel.md` (clean-room runbook)

**Modify (upstream-shared, additive):**
- `erpnext/hooks.py` — convert `app_include_js` to a list incl. the new bundle; register `extend_bootinfo`.
- `docs/architecture/FORK-CHANGES.md` + `FORK-CHANGES-PLAIN.md` — register the new module, DocTypes, hook deltas, bundle.
- `docs/architecture/UI-SITEMAP.md` — add the new **global launcher/slide-over** cross-cutting element; bump "Last verified".

**Scope notes:** the module lives in existing `erpnext/ai/` fork scope. `hooks.py` and `erpnext/public/js/` are upstream-shared — edits are additive and grounded in §8. The AP-capture sequence diagram is **not** affected (no change to the capture cascade), so no AP-sequence update is required.

---

## 5. Tests

### 5.1 Automated (mandatory — `from frappe.tests import IntegrationTestCase`, `erpnext/ai/chat/tests/`)

Roll back DB writes in `tearDown`. Cover:

1. **Auth rejection** — a Guest / unauthenticated call to `start_turn` is rejected (401 / `PermissionError`).
2. **RBAC scoping** — a low-privilege user gets empty/`PermissionError` from a tool, never leaked rows; assert the tool ran as the session user (audit `user` field).
3. **Context re-validation / forged context** — context naming an unreadable doctype/name raises `PermissionError`; browser-sent field values are ignored (not used for any write path).
4. **Unknown tool / denied permission** — both return clean errors and write audit rows.
5. **Audit + secret hygiene** — exactly one `AI Chat Message` per turn; the API key appears in no stored field and no realtime payload.
6. **Enqueue identity** — `start_turn` enqueues the job as `frappe.session.user`.

### 5.2 Clean-room runbook — `test/testplans/ai-chat-panel.md`

Per the CLAUDE.md 7-section format: (1) feature under test; (2) branch/commit; (3) env setup (AI Provider Settings key, MCP enabled + `MCP Tool Config` rows, roles); (4) test-data prerequisites (users/roles, a Purchase Invoice + Supplier); (5) numbered positive/negative/edge cases incl. forged-context and low-priv, plus Playwright UI steps for launcher / slide-over / context-chip / streaming; (6) cleanup/rollback; (7) pass/fail checklist.

UI steps run through the Playwright MCP per `test/testplans/BROWSER-TESTING-SETUP.md`; screenshots saved under `test/testplans/screenshots/ai-chat-panel/`.

---

## 6. Documentation updates required at merge (per `CLAUDE.md`)

| File | Update |
|---|---|
| `docs/architecture/FORK-CHANGES.md` | Add `erpnext/ai/chat/` + the two DocTypes + the `app_include_js`/`extend_bootinfo` hook deltas + the new front-end bundle to the tracked fork delta. |
| `docs/architecture/FORK-CHANGES-PLAIN.md` | Plain-English explainer of the chat panel (kept in lockstep with `FORK-CHANGES.md`). |
| `docs/architecture/UI-SITEMAP.md` | Add the global launcher/slide-over as a cross-cutting always-present element; bump "Last verified against repo". |
| `test/testplans/ai-chat-panel.md` | The clean-room runbook (ships with the code). |
| `TODO.md` | T-009 (deferred chat-specific scope-limit control) already tracked; close/advance as the build lands. |

---

## 7. Phased build order (suggested)

1. **Backend core** — `erpnext/ai/chat/` (`context.py`, `agent.py`, `api.py`, the two DocTypes, `extend_bootinfo`) + the §5.1 `IntegrationTestCase` suite; run green locally (`bench --site … run-tests --module erpnext.ai.chat.tests.…`).
2. **Front-end global panel** — bundle, launcher, slide-over, keyboard toggle, live context chip, realtime rendering, responsive behavior.
3. **Docs + test plan** — `FORK-CHANGES`(+PLAIN), `UI-SITEMAP`, `test/testplans/ai-chat-panel.md`, in the same commit set per CLAUDE.md.
4. **Clean-room / Playwright UI pass** — separate downstream gate (external instance / browser pass).

Each slice ends green tests + a verifiable artifact. v1 stays read-only; write/action tools are a later phase gated behind confirmation + role.

---

## 8. Citations (grounding rule)

### Frappe docs (v15 user guide)
- [Hooks — `app_include_js`/`app_include_css` (string or list; inject into `desk.html` every page), `after_migrate`, `extend_bootinfo`/`boot_session` → `frappe.boot`](https://docs.frappe.io/framework/v15/user/en/python-api/hooks)
- [Client-side Form API — `frm.doc`, `frm.doctype`, `frm.docname`, `frappe.ui.form.on` events (`refresh`/`onload`)](https://docs.frappe.io/framework/v15/user/en/api/form)
- [Realtime (Socket.IO) — `frappe.publish_realtime` to `user:{username}` room, `frappe.realtime.on`, `publish_progress`](https://docs.frappe.io/framework/v15/user/en/api/realtime)
- [REST / whitelisted methods (`@frappe.whitelist`, `/api/method/`)](https://docs.frappe.io/framework/v15/user/en/api/rest)
- [Users and Permissions (roles, User Permissions, permission levels)](https://docs.frappe.io/framework/v15/user/en/basics/users-and-permissions)

### Frappe source (version-15 branch — surfaces the docs are silent on)
- [`frappe/public/js/frappe/router.js`](https://github.com/frappe/frappe/blob/version-15/frappe/public/js/frappe/router.js) — `frappe.router.on('change')` (`make_event_emitter` :441, `trigger("change")` :168); `frappe.get_route()` returns `["Form", doctype, name]` / `["List", doctype, "List"]` / `["Workspaces", name]` (:432–433); `frappe.set_route` (:436–437).
- [`frappe/__init__.py`](https://github.com/frappe/frappe/blob/version-15/frappe/__init__.py) — `whitelist(allow_guest=False, …)` (:1263, rejects Guest by default); `set_user` (:1083); `has_permission(…, throw=…)` (:1362); `get_list` perm-checked (:1758) vs `get_all` forces `ignore_permissions=True` (:1777).

### Reputable precedent (architecture)
- [Raven v2 — The Commit Company (Frappe blog)](https://frappe.io/blog/community-updates/raven-v2-by-the-commit-company)
- [Raven repo — `raven/ai/handler.py`, `ai.py`](https://github.com/The-Commit-Company/raven) — background job + `frappe.publish_realtime` (Socket.IO); no SSE.
- [Werkzeug Request/Response (streaming-generator support — the *rejected* SSE path)](https://werkzeug.palletsprojects.com/en/stable/wrappers/)

### Repo-internal
- `erpnext/ai/credentials.py` — `get_ai_credentials("anthropic")` (key retrieval).
- `erpnext/mcp/` — `registry.get_catalogue`, `audit.safe_execute`, `auth.AuthContext`, `tools/_scope` (the consumed tool layer).
- `docs/planning/mcp-server-plan.md`, `mcp-server-NEXT-STEPS.md` — the MCP server design + status.
- `docs/planning/real-ocr-implementation-plan.md` — the `AI Provider Settings` design this reuses.
- `CLAUDE.md` — grounding + working rules.
