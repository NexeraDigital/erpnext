# AI Chat Panel — Completion Plan (finish to shippable)

> **Status:** Plan for the remaining work. The **backend slice is built and merged**
> into `russ/migrateToV16` (merge `52c3e02a84`, feature commit `96dea75d5e`); it is
> **not yet migrated or test-run**. This doc is the runway from "backend merged" to
> "a user can click a launcher and chat."
>
> **Date drafted:** 2026-05-31.
>
> **Branch:** `russ/migrateToV16`.
>
> **Base:** Frappe **16.18.3** / ERPNext version-16.
>
> **Parent docs:** [`ai-chat-panel-brief.md`](./ai-chat-panel-brief.md) (the ask),
> [`ai-chat-panel-plan.md`](./ai-chat-panel-plan.md) (the design + Phase 1/2/3),
> [`mcp-server-plan.md`](./mcp-server-plan.md) (the consumed tool layer).
>
> **Grounding rule (mandatory, per `CLAUDE.md`):** every Frappe surface below cites
> an upstream doc URL or a source `file:line`. See §9.

---

## 0. TL;DR — what's left

The backend (server-side Claude loop, in-process MCP tool dispatch, whitelisted API,
two owner-scoped DocTypes, `extend_bootinfo` flag, `IntegrationTestCase` suite) is
**code-complete and merged**. Six slices remain:

| Slice | What | State-changing? | Est. |
|---|---|---|---|
| **A. Migrate + verify backend** | `bench migrate` (install the 2 DocTypes), run the test module green, quote the result | Yes (dev site) | 0.5 d |
| **B. Front-end global panel** | The launcher + slide-over bundle, wired via `app_include_js`; live context capture; realtime streaming render; state preservation; responsive | No | 2–3 d |
| **C. Config + ops** | MCP enabled, Anthropic key set, `MCP Tool Config` confirmed, workers/realtime up; optional chat-specific tuning | Yes (settings) | 0.5 d |
| **D. Docs** | `FORK-CHANGES.md`/`-PLAIN`, `UI-SITEMAP.md`, `test/testplans/platform/ai-chat-panel.md` | No | 0.5 d |
| **E. Clean-room + Playwright UI pass** | Browser verification of launcher/slide-over/context-chip/streaming | Yes (browser) | 0.5–1 d |
| **F. Polish + hardening** | Abort-on-disconnect, conversation list, error/empty/loading states, a11y, i18n, prompt-injection copy | No | 1 d |

**Total remaining: ~5–6.5 dev-days.** v1 stays **read-only**; write/action tools and
the chat-specific tool gate (`TODO.md` T-009) remain deferred.

---

## 1. Current state (what is already true)

- **Merged backend** (`erpnext/ai/chat/`): `context.py` (server-side re-validation /
  forged-context guard), `agent.py` (Claude loop consuming the MCP catalogue
  in-process as the desk user via `audit.safe_execute`; status + chunked answer over
  `frappe.publish_realtime`; prompt caching; key in memory only), `api.py`
  (`start_turn`/`get_conversation`/`list_conversations`/`clear_conversation`;
  `allow_guest=False`; per-user rate limit; enqueue as caller), `boot.py`
  (`frappe.boot.ai_chat_enabled`).
- **Merged DocTypes** (`erpnext/ai/doctype/`): `AI Chat Conversation`,
  `AI Chat Message` (owner-scoped: `if_owner` for the user, System Manager read-all).
- **Merged wiring**: `hooks.py` `extend_bootinfo` → `erpnext.ai.chat.boot.boot_session`.
- **Merged tests** (`erpnext/ai/chat/tests/test_chat.py`): 9 cases — compiles; **not
  yet executed** (needs a migrated site; the test mocks the Anthropic call at
  `agent._create_message`, so no key/network is required to run them).
- **Reused, already-built**: `erpnext/ai/credentials.get_ai_credentials` (Claude key
  from `AI Provider Settings`), `erpnext/mcp/*` (the 5 read-only AP tools + audit).

**Not built yet:** any UI. There is no launcher, nothing reads `ai_chat_enabled`, and
`app_include_js` is unchanged — so a user cannot open the chat today.

---

## 2. Slice A — Migrate + verify the backend (the gate)

**Goal:** prove the merged backend works on a migrated site; satisfy the CLAUDE.md
"run tests green this session before declaring done" rule.

**Steps (state-changing — run with approval):**
```bash
bench --site erpnext.localhost migrate                 # installs the 2 DocTypes
bench --site erpnext.localhost run-tests --module erpnext.ai.chat.tests.test_chat
# regression guard (shared surface): the chat adds an extend_bootinfo handler
bench --site erpnext.localhost run-tests --module erpnext.mcp.tests.test_permissions
```

**Acceptance:**
- `migrate` creates `tabAI Chat Conversation` / `tabAI Chat Message`; `bench … console`
  → `frappe.db.exists("DocType","AI Chat Message")` is truthy.
- The test module reports `Ran 9 tests … OK`; quote that line.
- The `extend_bootinfo` handler does not break boot: load `/app` as a normal user and a
  System Manager; no console/server error; `frappe.boot.ai_chat_enabled` resolves to a
  boolean.

**Note on the blast-radius check (CLAUDE.md):** the boot handler runs on every desk
load, so the acceptance includes a real desk boot for two role profiles, not just the
unit module.

---

## 3. Slice B — Front-end global panel (the visible feature)

### 3.1 Mount mechanism (grounded)

- Add a new esbuild bundle entry `erpnext/public/js/ai_chat/ai_chat.bundle.js` and
  register it in **`app_include_js`** as a **list** (it currently is the single string
  `"erpnext.bundle.js"`):
  ```python
  app_include_js = ["erpnext.bundle.js", "ai_chat.bundle.js"]
  ```
  `app_include_js` injects into `desk.html` on **every desk route** and accepts a list
  — https://docs.frappe.io/framework/v15/user/en/python-api/hooks. Build with
  `bench build --app erpnext` (or `bench build` dev watch).
- **Singleton mount that survives SPA navigation:** on `frappe.ready` (or `$(document)
  .on("app_ready")`), construct one panel controller and append its DOM to
  `document.body` (outside `.page-container`, so route changes never re-render it). The
  desk is a single-page app — it does not full-reload between Forms/Lists/Reports — so a
  body-level singleton preserves conversation state for free.
- Render the launcher only when `frappe.boot.ai_chat_enabled` is true (set by
  `extend_bootinfo` → `frappe.boot.<key>`, same hooks doc). Guests never get the bundle
  behavior because the flag is false for them.

### 3.2 Components (vanilla JS / Frappe UI, matching ERPNext's desk convention)

ERPNext ships **no SPA**; desk UI is vanilla JS + Frappe UI
(`docs/architecture/ARCHITECTURE.md` §4.10). Match that — do **not** introduce a new
framework.

1. **`launcher.js`** — persistent floating action button (bottom-right) / docked rail
   on every route; `aria-label`; toggles the slide-over. **Keyboard toggle**
   `Ctrl/Cmd-J` via a `keydown` listener (documented in the panel's help).
2. **`panel.js`** — the non-blocking slide-over (right-side drawer, ~380px desktop,
   full-width mobile). Holds: header (title + context chip + clear/pin), message list,
   composer (textarea + send), loading/error/empty states. Focus-trap when open; `Esc`
   closes.
3. **`context.js`** — live context capture:
   - Subscribe with `frappe.router.on("change", refreshContext)` — router emits
     `"change"` after each route render
     ([router.js:441 `make_event_emitter`, :168 `trigger("change")`](https://github.com/frappe/frappe/blob/version-15/frappe/public/js/frappe/router.js)).
   - Read `frappe.get_route()` → `["Form", dt, name]` / `["List", dt, "List"]` /
     `["Workspaces", name]` (router.js:432–433). On a Form, read `cur_frm.doctype`,
     `cur_frm.docname`, `cur_frm.doc` (the on-screen field values) —
     https://docs.frappe.io/framework/v15/user/en/api/form. On a List, capture the
     DocType and `cur_list?.get_filters_for_args?.()` (filters) if present.
   - Show the chip "Context: Purchase Invoice ACC-PINV-0001" with **clear** (drop the
     hint) and **pin** (freeze the hint so navigation doesn't change it).
   - The captured context is sent **only as a hint** `{doctype, name, view, filters}`;
     the server re-validates + re-fetches it (already implemented in `context.py`).
     Never send it as authority; browser field values are never used for writes.
4. **`stream.js`** — realtime render:
   - After `start_turn` returns `{conversation}`, subscribe
     `frappe.realtime.on("ai_chat:" + conversation, onEvent)` and handle
     `{type:"status"|"delta"|"done"|"error"}`. `publish_realtime` to the user room is
     the delivery channel — https://docs.frappe.io/framework/v15/user/en/api/realtime.
   - `status` → ephemeral "thinking / looking up X" line; `delta` → append to the
     in-progress assistant bubble (typewriter); `done` → finalize + reconcile against
     the persisted message (`get_conversation`) in case a socket event was missed;
     `error` → inline error bubble + retry affordance.
   - Unsubscribe on `done`/`error` to avoid leaks.
5. **`api.js`** (client) — thin wrappers over `frappe.call("erpnext.ai.chat.api.*")`
   (`frappe.call` posts to `/api/method/…` with the session cookie + CSRF; the
   whitelisted method rejects Guest — https://docs.frappe.io/framework/v15/user/en/api/rest).

### 3.3 State, history, responsiveness

- **State preservation:** because the panel is a body-level singleton, in-memory
  conversation state persists across all SPA navigation automatically. On first open,
  hydrate the thread list via `list_conversations`; lazy-load a thread via
  `get_conversation`.
- **History across reloads:** restored from the `AI Chat Conversation`/`Message`
  DocTypes (already persisted server-side).
- **Responsive:** drawer becomes full-screen below ~768px; launcher stays thumb-reachable.
- **Graceful states:** loading skeleton while a turn runs; empty state with example
  prompts; error state with a retry button; "AI chat is being configured" state when a
  turn returns the `AICredentialsNotConfigured` message.
- **Accessibility:** ARIA roles for the dialog/log, focus management, keyboard-only
  operation, reduced-motion respect.

### 3.4 Files (Slice B)

**Add:** `erpnext/public/js/ai_chat/ai_chat.bundle.js` (entry) + `launcher.js`,
`panel.js`, `context.js`, `stream.js`, `api.js`, and `erpnext/public/scss/ai_chat.scss`
(or a `.bundle.css`). **Modify:** `erpnext/hooks.py` (`app_include_js` → list).

---

## 4. Slice C — Config + ops

- **`AI Provider Settings`**: System Manager sets `anthropic_api_key` (+ optional
  `anthropic_default_model`, ZDR). The chat reads it via `get_ai_credentials("anthropic")`.
- **MCP**: `MCP Settings.enabled` must be on (drives `ai_chat_enabled` boot flag) and the
  five `MCP Tool Config` rows seeded (the `after_migrate` hook already does this for the
  MCP module — verify post-migrate).
- **Workers/realtime**: the turn runs on a background worker and streams over Socket.IO,
  so `bench worker` (short queue) and the realtime/node process must be running. Document
  this in the runbook.
- **Optional (not v1-blocking):** a dedicated high-priority `chat` RQ queue to minimize
  first-token latency (plan §2 D1 note). Defer unless latency is a problem.

---

## 5. Slice D — Documentation (same-commit convention)

| File | Update |
|---|---|
| `docs/architecture/FORK-CHANGES.md` | Register `erpnext/ai/chat/`, the two DocTypes, the `app_include_js`/`extend_bootinfo` deltas, and the front-end bundle. |
| `docs/architecture/FORK-CHANGES-PLAIN.md` | Plain-English "the desk now has an AI chat assistant" paragraph (kept in lockstep). |
| `docs/architecture/UI-SITEMAP.md` | Add the **global launcher / slide-over** as a cross-cutting always-present element (it appears on every desk route — the first such element besides the navbar). Bump "Last verified against repo". |
| `test/testplans/platform/ai-chat-panel.md` | The clean-room runbook (§6). |

The AP-capture sequence diagram is **unaffected** (no cascade change) — no AP-sequence
update required.

---

## 6. Slice E — Test plan + clean-room / Playwright pass

### 6.1 Automated (already written; run in Slice A)
`erpnext/ai/chat/tests/test_chat.py` — auth rejection, RBAC scoping + `PermissionDenied`
audit, forged-context rejection, unknown tool, secret hygiene, enqueue identity,
happy-path, tool-call recording, missing-credentials.

### 6.2 Clean-room runbook — `test/testplans/platform/ai-chat-panel.md`
Per the CLAUDE.md 7-section format: feature under test; branch/commit; env setup
(Anthropic key, MCP enabled + tool configs, workers up, roles); test data (a low-priv
user, a System Manager, a Purchase Invoice + Supplier); numbered cases incl. **forged
context** and **low-priv data isolation**; cleanup; pass/fail checklist.

### 6.3 Playwright UI pass (driven via the Playwright MCP, per `BROWSER-TESTING-SETUP.md`)
- Launcher appears on a Form, a List, a Report, and a Workspace route (global mount).
- `Ctrl/Cmd-J` toggles the slide-over; `Esc` closes; focus trap holds.
- On a Purchase Invoice form, the context chip reads "Purchase Invoice <name>"; navigating
  to a List updates it live; **pin** freezes it; **clear** drops it.
- A turn streams `status` → `delta` → `done`; the answer persists after reload
  (history restore); DB shows the `AI Chat Message` rows (verify via `bench … mariadb`).
- A low-priv user asking about a record they can't read gets a refusal, and the
  `MCP Audit Log` shows a `PermissionDenied` row — never leaked data.
- Screenshots saved under `test/testplans/screenshots/ai-chat-panel/`.

---

## 7. Slice F — Polish + hardening

- **Abort on disconnect:** when the panel closes / user navigates away mid-turn, stop
  rendering and (future) signal cancellation; the job still persists its result for
  history.
- **Conversation list UI:** switch/rename/delete threads (backed by
  `list_conversations`/`clear_conversation`).
- **Prompt-injection UX:** when the model flags suspicious document content, surface it
  as a caution, not an action.
- **i18n:** wrap user-facing strings in `__()`.
- **Rate-limit UX:** friendly toast on `RateLimitExceededError`.
- **a11y audit:** keyboard-only run, screen-reader labels, contrast, reduced motion.

---

## 8. Acceptance criteria for "done"

1. `bench migrate` clean; `erpnext.ai.chat.tests.test_chat` green this session (quoted).
2. Launcher visible on every desk route for a permitted user; hidden for Guest / when
   MCP disabled.
3. Context chip tracks the current record live, with pin/clear; sent only as a hint.
4. A turn streams and persists; history survives reload and route changes.
5. Low-priv isolation proven (refusal + `PermissionDenied` audit; no leaked rows).
6. Secret never in any stored field, realtime payload, or `frappe.boot`.
7. `FORK-CHANGES`(+PLAIN), `UI-SITEMAP`, and `test/testplans/platform/ai-chat-panel.md` updated.
8. Clean-room + Playwright pass recorded (or explicitly marked pending per CLAUDE.md).

---

## 9. Citations (grounding rule)

- **`app_include_js` / `extend_bootinfo`** (global desk JS + boot flag) —
  https://docs.frappe.io/framework/v15/user/en/python-api/hooks
- **Client router** (`frappe.router.on('change')`, `frappe.get_route()`,
  `frappe.set_route`) —
  https://github.com/frappe/frappe/blob/version-15/frappe/public/js/frappe/router.js
  (`make_event_emitter` :441, `trigger("change")` :168, `get_route` :432–433,
  `set_route` :436–437)
- **Client Form API** (`cur_frm`, `frm.doctype`/`docname`/`doc`, `frappe.ui.form.on`) —
  https://docs.frappe.io/framework/v15/user/en/api/form
- **Realtime** (`frappe.publish_realtime` to `user:{username}`, `frappe.realtime.on`) —
  https://docs.frappe.io/framework/v15/user/en/api/realtime
- **Whitelisted methods / `frappe.call`** (`allow_guest=False` default rejects Guest) —
  https://docs.frappe.io/framework/v15/user/en/api/rest ·
  https://github.com/frappe/frappe/blob/version-15/frappe/__init__.py (`whitelist` :1263)
- **Permissions** (`has_permission(throw=True)`, `get_list` vs `get_all`,
  `apply_fieldlevel_read_permissions`) —
  https://docs.frappe.io/framework/v15/user/en/basics/users-and-permissions ·
  frappe/__init__.py (:1362 / :1758 / :1777)
- **Desk frontend convention** (vanilla JS + Frappe UI, no SPA) —
  `docs/architecture/ARCHITECTURE.md` §4.10
- **Reused subsystems** — `erpnext/ai/credentials.py`, `erpnext/mcp/*`,
  `docs/planning/ai-chat-panel-plan.md`, `docs/planning/mcp-server-plan.md`.

---

## 10. Open items / deferrals

- **T-009** (`TODO.md`) — optional chat-specific tool allowlist (`MCP Tool Config.
  chat_enabled`); add only on a concrete governance requirement.
- **Write/action tools** — deferred to a later phase behind server-enforced confirmation
  + role (MCP Phase 3 elicitation).
- **Dedicated chat queue** — add only if first-token latency is a problem.
- **Worktree cleanup** — remove `.claude/worktrees/ai-chat-panel` once this work is fully
  merged (mirrors `TODO.md` T-006 for the MCP worktree).
