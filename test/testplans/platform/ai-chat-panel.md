# Test Plan — AI Chat Panel (context-aware desk assistant, read-only v1)

> Clean-room runbook for the **AI Chat Panel** (`docs/architecture/FORK-CHANGES.md` §15; plan `docs/planning/ai-chat-panel-plan.md`). Executable by a fresh Claude instance with **no prior context** on a clean bench. The panel is **read-only**: it answers questions by calling the MCP read tools **as the signed-in user** and streaming the reply back over Socket.IO.

## 1. Feature under test

A floating chat launcher (bottom-right of every `/app/*` desk page; also **Ctrl/Cmd-J**) opens a right-side slide-over. The user types a plain-English question; a **server-side Claude tool loop** answers it by calling the five read-only MCP tools (`list_ap_invoices`, `get_ap_invoice`, `list_vendors`, `get_vendor_balance`, `get_doctype_meta`) **under the signed-in user's permissions**, streaming the answer back token-by-token. The panel is **context-aware** — it tells the backend which record the user is currently viewing (`{doctype, name, view}`), and the backend **re-validates the user's read permission and re-fetches the record server-side** before grounding the model on it (the browser's claimed field values are discarded).

User-visible behavior change vs. a stock bench: a new always-present chat button appears for signed-in users on a site where the MCP server is enabled; nothing else in the navigation changes. The assistant cannot create, modify, send, or delete anything in v1.

## 2. Branch / commit

- **Branch:** `russ/migrateToV16`. Backend committed in `96dea75d5e`; the front-end (`erpnext/public/js/ai_chat/*`, `erpnext/public/scss/ai_chat.bundle.scss`) + the `hooks.py` `app_include_js`/`app_include_css` list change land in the same slice as this plan.
- **Sanity:** confirm `erpnext/ai/chat/agent.py` exists, `frappe.boot.ai_chat_enabled` is wired in `hooks.py` `extend_bootinfo`, and `app_include_js` in `hooks.py` is a **list** containing `"ai_chat.bundle.js"`.

## 3. Environment setup

```bash
# 1. Install the DocTypes + boot flag.
bench --site <test-site> migrate          # creates tabAI Chat Conversation / tabAI Chat Message

# 2. Build the desk assets so ai_chat.bundle.{js,css} are emitted to dist/.
bench build --app erpnext

# 3. The turn runs in a background job and streams over Socket.IO, so BOTH must be up:
bench --site <test-site> doctor           # confirm redis + workers
#   `bench start` runs web + socketio + worker + schedule together (dev). For a
#   production-style bench, ensure the `short` queue worker and the socketio node
#   process are both running.
```

- **frappe v16 + this erpnext fork.**
- **MCP server must be ENABLED** (the chat consumes its tool catalogue and the launcher self-gates on it): open **MCP Settings** (`/app/mcp-settings`) and switch the master enable on. With it off, `frappe.boot.ai_chat_enabled` is false and the launcher never renders (that is TC-2b).
- **Anthropic API key** required for any live turn (TC-4/5/6). The human operator obtains a key from the Anthropic console (https://console.anthropic.com/ → API Keys) and sets it in **AI Provider Settings** (`/app/ai-provider-settings`, System-Manager-only) → Anthropic API Key; set a default model (e.g. `claude-haiku-4-5-20251001`). **Never paste the key into this plan or any log.** TC-7 deliberately tests the missing-key path.
- **Socket.IO hostname gotcha (WSL/dev):** the realtime stream uses the browser's Origin host. If the desk is served at `http://erpnext.localhost:8000` but the node socketio process cannot resolve `erpnext.localhost`, streaming silently fails with an `Unauthorized: fetch failed` console error. Fix by mapping the host (`echo "127.0.0.1 erpnext.localhost" | sudo tee -a /etc/hosts`) or by browsing via `http://localhost:8000`. Verify realtime works at all before running TC-4.

## 4. Test data prerequisites

- **User A — System Manager** (or Accounts Manager) for the main UI cases. Can read all suppliers/invoices.
- **User B — low-privilege "Accounts User"** with a **User Permission** restricting them to exactly one Supplier (call it `Vendor Allowed`) and explicitly NOT another (`Vendor Denied`). This is the permission-enforcement case (TC-6). (`/app/user-permission/new` → User = B, Allow = Supplier, For Value = `Vendor Allowed`.)
- **At least one submitted Purchase Invoice** for `Vendor Allowed` with a known total — for the context-grounding case (TC-5). Note its name (e.g. `ACC-PINV-2026-00001`).
- Two suppliers `Vendor Allowed` and `Vendor Denied` (any details).
- For the automated line (TC-1): no external key needed — `test_chat` mocks the model boundary (`_create_message`).

## 5. Numbered test cases

### TC-1 — Automated suites (no API key needed)
- **Action:**
  ```bash
  bench --site <test-site> run-tests --module erpnext.ai.chat.tests.test_chat
  bench --site <test-site> run-tests --module erpnext.mcp.tests.test_permissions   # blast-radius: boot handler fires on every desk boot
  ```
- **Expected:** `Ran 10 tests … OK` for `test_chat` (owner-scoping, rate limit, forged-context `PermissionError`, mocked tool loop, missing-key error); `test_permissions` green.
- **Pass/fail:** PASS iff both report `OK`.

### TC-2a — Launcher renders for a signed-in user (MCP enabled)
- **Precondition:** MCP enabled; logged in as User A.
- **Action:** hard-reload `/app` (Ctrl/Shift-R). Look at the bottom-right corner.
- **Expected:** a round chat button is visible. In the browser console, `frappe.boot.ai_chat_enabled` is `true`. No console errors mentioning `ai_chat`.
- **Pass/fail:** PASS iff the button renders and the flag is `true`.

### TC-2b — Launcher absent for Guest / when MCP disabled (negative)
- **Action (i):** open `/app` in a logged-out/incognito window (Guest) — **no** launcher; if a login wall blocks the desk, confirm `frappe.boot.ai_chat_enabled` is not true on any Guest boot.
- **Action (ii):** as System Manager, disable MCP in **MCP Settings**, hard-reload `/app`.
- **Expected:** the launcher is **absent**; `frappe.boot.ai_chat_enabled` is `false`. Re-enable MCP afterward.
- **Pass/fail:** PASS iff the launcher does not render in either case.

### TC-3 — Open / close / keyboard
- **Action:** click the launcher → panel slides in from the right. Press **Esc** → it closes. Press **Ctrl/Cmd-J** → it opens; press again → closes.
- **Expected:** smooth open/close; focus lands in the textarea on open; the launcher shows an active state while open.
- **Pass/fail:** PASS iff all three toggles behave and no console error.

### TC-4 — A turn streams, persists, and survives reload (positive, needs key)
- **Precondition:** Anthropic key set; socketio + worker up; logged in as User A; open the panel from `/app` (no record context).
- **Action:** type `List my recent AP invoices` and press Enter.
- **Expected:**
  - An ephemeral status line appears (`Thinking…`, then `Looking up list_ap_invoices…`).
  - The assistant reply **streams in token-by-token** and names real invoices the user can see.
  - The composer re-enables when done.
- **DB check:**
  ```bash
  bench --site <test-site> mariadb -e "SELECT role, LEFT(content,50), model, tools_invoked FROM \`tabAI Chat Message\` ORDER BY creation DESC LIMIT 4\\G"
  ```
  Expect a `User` row and an `Assistant` row; the Assistant row has a `model` and a non-null `tools_invoked` listing `list_ap_invoices`.
- **Reload check:** refresh `/app`, open the panel, open the conversation from the **history** (list) button → the prior turn is still there.
- **Audit check:** `/app/mcp-audit-log` shows a row for `list_ap_invoices` by User A (the in-process tool call is audited identically to an external client).
- **Pass/fail:** PASS iff it streamed, persisted both rows, survived reload, and produced an audit row.

### TC-5 — Context awareness (positive, needs key)
- **Action:** navigate to the Purchase Invoice from §4 (`/app/purchase-invoice/<name>`). Open the panel.
- **Expected (chip):** the header shows `Context: Purchase Invoice <name>`.
- **Action:** ask `Summarize this invoice`.
- **Expected (answer):** the reply describes **that** invoice (correct supplier/total) without you naming it — proving the context hint was used and the record was re-fetched server-side.
- **Route-change check:** with the panel open, navigate to a different record (or a List) → the chip updates live. **Pin** the original record → navigate away → the chip stays pinned; **Unpin**/**Clear** drops it.
- **Pass/fail:** PASS iff the chip is correct, updates on navigation, pin/clear behave, and the answer is grounded in the viewed record.

### TC-6 — Permissions are enforced; context cannot leak (negative, needs key)
- **Precondition:** log in as **User B** (the restricted Accounts User).
- **Action (i):** open the panel and ask `List all vendors`.
- **Expected:** the reply includes `Vendor Allowed` but **not** `Vendor Denied` — the tool ran under B's User Permission. (Contrast: User A sees both. Suppliers named `_MCP Allowed/_MCP Denied` from the test fixtures are expected noise and are governed by the same rule.)
- **Action (ii) — forged context:** while logged in as B, navigate to (or craft a route to) a Purchase Invoice for `Vendor Denied` that B may not read, open the panel, and ask `Summarize this invoice`.
- **Expected:** a clean **"Permission denied"** error in the chat (the server's `has_permission(..., throw=True)` guard) — **never** the record's contents.
- **Pass/fail:** PASS iff B sees only permitted vendors AND the forbidden record's data never appears.

### TC-7 — Missing API key → configure message (negative)
- **Precondition:** temporarily blank the Anthropic key in AI Provider Settings (record the prior value to restore).
- **Action:** as User A, ask any question.
- **Expected:** an inline chat error: *"The AI chat is not configured yet — a System Manager must set the Anthropic API key in AI Provider Settings."* No traceback, no key fragment anywhere.
- **Cleanup:** restore the key.
- **Pass/fail:** PASS iff the friendly message shows and no secret leaks.

### TC-8 — Rate limit (edge)
- **Action:** as User A, send 21+ messages within one minute (short prompts are fine; they need not complete).
- **Expected:** after ~20 turns in the window, `start_turn` returns *"You're sending messages too quickly. Please wait a moment."* in the chat. It recovers after the minute rolls over.
- **Pass/fail:** PASS iff the limit trips around 20/min and recovers.

### TC-9 — Owner-scoping of threads (negative)
- **Action:** note a conversation name owned by User A (from TC-4's DB check). Log in as User B and attempt to load it — e.g. via the API:
  ```
  POST /api/method/erpnext.ai.chat.api.get_conversation   {"conversation":"<A's conversation name>"}
  ```
- **Expected:** `Conversation not found.` (B is told not-found, not denied — A's thread existence is not revealed). B's own history (`list_conversations`) never lists A's threads.
- **Pass/fail:** PASS iff B cannot read A's conversation and the error does not confirm its existence.

### TC-10 — No markdown injection / new-chat reset (edge)
- **Action:** ask the assistant something whose reply contains `**` or HTML-ish text (or send `<b>hi</b> **bold**` and ask it to echo). Then click the **New chat** (+) button.
- **Expected:** the bubble shows the characters **literally** (`**bold**`, `<b>hi</b>`) — never rendered bold/HTML (v1 is HTML-escaped by design). New chat clears the thread to the empty state and re-enables the composer.
- **Pass/fail:** PASS iff no markup is rendered and New chat resets cleanly.

## 6. Cleanup / rollback

- Delete test conversations: `bench --site <test-site> execute frappe.db.delete --kwargs "{'doctype':'AI Chat Message'}"` then the same for `AI Chat Conversation` (or `clear_conversation` per thread via the UI).
- Restore the Anthropic key if TC-7 blanked it; re-enable MCP if TC-2b disabled it.
- Remove the User B User Permission and any throwaway Purchase Invoice/suppliers you created.
- The `tabAI Chat Conversation` / `tabAI Chat Message` tables and the `dist/` assets are intended to persist — leave them.

## 7. Pass/fail summary template

| Test | Description | Result |
|---|---|---|
| TC-1  | Automated suites (`test_chat` 10 OK + `test_permissions`) | [ ] |
| TC-2a | Launcher renders for signed-in user (MCP on) | [ ] |
| TC-2b | Launcher absent for Guest / MCP off | [ ] |
| TC-3  | Open / close / Ctrl-Cmd-J / Esc | [ ] |
| TC-4  | Turn streams, persists, survives reload, audited | [ ] |
| TC-5  | Context chip correct + grounded answer + pin/clear | [ ] |
| TC-6  | Permissions enforced; forged context cannot leak | [ ] |
| TC-7  | Missing key → friendly configure message, no leak | [ ] |
| TC-8  | Rate limit trips ~20/min and recovers | [ ] |
| TC-9  | Owner-scoping: B cannot read A's thread | [ ] |
| TC-10 | No markdown/HTML injection; New chat resets | [ ] |

**Overall:** [ ] PASS / [ ] FAIL — notes:
