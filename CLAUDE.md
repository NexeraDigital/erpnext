# Claude working notes for this repo

This is a fork of `frappe/erpnext` carrying the **AP Closed Loop Receipt Processing** pilot for NexeraDigital. Branch convention: pilot work lives on `russ/bryanwork`; upstream tracks `develop`.

Before doing non-trivial work, read the doc that matches your task.

## Grounding rule (mandatory)

**Every plan for a code change MUST cite the relevant upstream documentation page(s) before editing.** Do not rely on training data for Frappe/ERPNext API signatures, hook names, DocType field types, permission semantics, or bench commands — these change between versions and the in-repo behavior is what ships, not what you remember.

- **Canonical sources, in priority order:**
  1. `https://docs.frappe.io/framework/v15/user/en/` — Frappe framework v15 (DocTypes, hooks, controllers, `frappe.db`, whitelisted methods, background jobs, permissions, client scripts, bench). Append the section path, e.g. `.../basics/doctypes`, `.../python-api/hooks`. The bare `/framework` URL is a landing page — skip it.
  2. `https://docs.frappe.io/erpnext/user/manual/en/` — ERPNext manual (no version segment; site serves current). Append the module path, e.g. `.../accounts`, `.../buying`. The bare `/erpnext` URL is a landing page — skip it.
  3. `https://github.com/frappe/frappe` and `https://github.com/frappe/erpnext` — source of truth when docs are vague, out of date, or silent
- **How to apply:** before writing or editing code, `WebFetch` the matching upstream page(s) and quote the specific URL(s) in your plan/response. If the docs contradict your local memory, trust the docs. If the docs are silent, read the upstream source and cite the file + line.
- **Scope:** applies to all server code (`*.py`), client scripts (`*.js`), DocType JSON, `hooks.py`, fixtures, and bench/migration commands. Trivial edits inside fork-only files (under `erpnext/accounts/ap_closed_loop/` or `erpnext/accounts/doctype/ap_invoice_capture/`) that don't touch a framework surface are exempt — but anything that calls into `frappe.*` is not.
- **When the upstream behavior is itself the bug or limitation** (i.e. the reason for the fork change), still cite the upstream doc/source so the delta is explicit.

## Documentation index

| Doc | Purpose | Update when… |
|---|---|---|
| `docs/DEVELOPMENT-GUIDE.md` | Local WSL + bench setup, common commands, site/admin creds | Local dev environment, bench scripts, or site config change |
| `docs/architecture/ARCHITECTURE.md` | What ERPNext is, system topology, how Frappe hosts it | Frappe/ERPNext upgrade that changes topology — rare |
| `docs/architecture/FORK-CHANGES.md` | Authoritative list of files added/modified by this fork vs upstream | Files are added, removed, or significantly changed within the AP closed-loop scope |
| `docs/architecture/FORK-CHANGES-PLAIN.md` | Plain-English explainer of the fork's scope for non-engineers | Same triggers as `FORK-CHANGES.md`, kept in sync |
| `docs/architecture/UI-SITEMAP.md` | Every place a user can land in the desk UI — sidebar items, classic workspaces, Frappe pages, portal routes, dashboards | Any change under `erpnext/workspace_sidebar/`, `erpnext/*/workspace/`, `erpnext/*/page/`, `erpnext/*/dashboard*/`, or `website_route_rules` in `erpnext/hooks.py` |
| `docs/architecture/AP-CAPTURE-SEQUENCE.md` **+ `.png`** | Sequence diagram of the **as-implemented** AP Invoice Capture cascade (intake → dedupe → OCR → validate → promote → approve → mock-pay). The `.md` holds the Mermaid source; the `.png` is its render. | The cascade / state machine changes — see the AP-sequence rule under "Working rules". **The `.md` and `.png` MUST stay in sync.** |
| `docs/changes/NewUpdates.md` | The 13-step AP workflow design (ambition spec, broader than what's shipped) | Workflow design changes — distinct from current implementation |
| `docs/changes/GAP-ANALYSIS.md` | Gap between current ERPNext capability and pilot target | Pilot scope or upstream capability changes |
| `docs/changes/IMPLEMENTATION-PLAN.md` | Build sequence and milestones for the pilot | Pilot milestones move or new tasks are added |
| `docs/spec/00-overview.md` + `docs/spec/01`–`14` | The v2 AP-workflow implementation specs (one per workflow step) + the index | A spec's design changes — keep its frontmatter `status:` current |
| `docs/spec/STATUS.md` | Build-status tracker for the v2 spec implementation (per-spec status, AC checklist, gating decisions) | A spec slice is implemented/verified — **gated on actual verification; see "Spec build-status tracking" below** |
| `test/testplans/` (`specs/`, `ocr/`, `platform/` + `README.md` index) | Per-feature, self-contained test plans executed by an **external** Claude instance for independent clean-room verification, organized in subfolders with numbered names (local `bench run-tests` works too — see "Automated tests"). Screenshots live in `test/testplans/screenshots/<plan-basename>/` | Any feature is added or modified — see "Test plans" section below |
| `TODO.md` (root) | Single source of truth for persistent, cross-session outstanding work (tasks with stable `T-NNN` IDs, priority, status) | A task that outlives the current session/PR is added, changes status, or is completed — see "Todo management" below |
| `AGENTS.md` (root) | Codex ↔ Claude ↔ Obsidian orchestration for the pilot (Brandon's working notes) | Codex/Claude workflow itself changes — not for code work |

## Working rules

- **For "where in the UI does X go?" questions:** consult `docs/architecture/UI-SITEMAP.md` first. Verify against the current repo before recommending placement — the sitemap is dated, not live.
- **For changes inside the AP closed-loop scope** (`erpnext/accounts/ap_closed_loop/`, `erpnext/accounts/doctype/ap_invoice_capture/`): update `docs/architecture/FORK-CHANGES.md` in the same commit so the fork delta stays accurate.
- **For navigation changes** (any file under the UI-SITEMAP update triggers): refresh `docs/architecture/UI-SITEMAP.md` in the same commit. Update the "Last verified against repo" date at the top.
- **For changes to the AP capture cascade / workflow** — any edit that changes the flow the sequence diagram depicts: a new/removed/reordered cascade hop, a changed branch or pause seam, a renamed step function, or a new actor/participant. This includes edits to `_determine_next_step`, the whitelisted step functions (`run_dedupe_for` / `run_fake_extraction_for` / `validate_for_purchase_invoice_for` / `request_approval_for` / `issue_mock_payment_for`), `after_insert` / `_kick_next_step`, or the async runner's step routing. **In the same commit you MUST:**
  1. Update the Mermaid source in `docs/architecture/AP-CAPTURE-SEQUENCE.md` to match the code, and bump its "Last derived from code" date.
  2. **Regenerate the PNG** so it matches — run `<bench>/env/bin/python docs/architecture/render_sequence_diagram.py` (renders the `.md`'s Mermaid block via headless Chromium → `docs/architecture/AP-CAPTURE-SEQUENCE.png`). Visually confirm the render isn't clipped before committing.
  3. Commit **both** files together — a stale `.png` that disagrees with the `.md` (or with the code) is worse than none. Never hand-edit the `.png`.
- **Don't duplicate Frappe docs.** If something is generic ERPNext/Frappe behavior, link to upstream docs rather than restating in this repo.
- **Existing convention is to keep `FORK-CHANGES.md` and `FORK-CHANGES-PLAIN.md` paired** — if you update one, update both.
- **When the user references a screenshot or image file by name without a full path** (e.g. *"see Screenshot 2026-05-27 093723.png"*), look in `/mnt/c/Users/russw/OneDrive/Pictures/Screenshots 1/` first. That's their Windows Pictures → Screenshots folder mounted via WSL — note the literal folder name `Screenshots 1` (with the trailing space and `1`). A Windows-style path like `C:\Users\russw\OneDrive\Pictures\Screenshots 1\...` translates to `/mnt/c/Users/russw/OneDrive/Pictures/Screenshots 1/...`.
- **For every feature added or modified**, write a test plan in `test/testplans/` per the "Test plans" section below. A code change without a paired test plan is incomplete.

## Todo management (`TODO.md`)

`TODO.md` at the repo root is the **single source of truth for persistent, cross-session work** — tasks that outlive the conversation or PR that surfaced them. It is deliberately separate from the harness's in-session todo scratchpad (the `TodoWrite` tool). Keep the two distinct and use the right one:

- **In-session scratchpad (`TodoWrite`)** — the step-by-step plan for the task you're doing *right now*. Ephemeral; it vanishes with the session. Use it freely for multi-step tasks; do **not** mirror its transient steps into `TODO.md`.
- **`TODO.md`** — anything that must survive the session: deferred work, follow-ups, known gaps, tech debt, "do this after X ships." If you'd be sad to lose it when the conversation ends, it goes here.

**Promotion rule.** When work in a session produces a follow-up that won't be finished in that same session/PR (a deferred fix, a discovered gap, a "later" item the user mentions), **promote it to `TODO.md`** before you wrap up — don't leave it only in the scratchpad.

**How to maintain it (industry-standard, file-based kanban):**

- **One source of truth.** Don't scatter todos across other docs. A planning doc may describe work; the actionable, trackable item still gets a `T-NNN` entry in `TODO.md`.
- **Stable IDs, never reused.** Assign the next free ID from the counter at the top of `TODO.md`, then bump the counter in the same edit. IDs are permanent handles — never renumber, never recycle a retired ID.
- **Status = section.** A task's status is which section it sits in (**In Progress** / **Backlog** / **Blocked** / **Done**). Change status by moving the whole bullet between sections, keeping its ID and history.
- **Prioritize every item** with `P0`–`P3` (see the legend in `TODO.md`). Default new items to `P2` unless the user signals otherwise.
- **Capture context, don't restate it.** Each task carries a one-line description plus a `ref:` to the spec / planning doc / PR / `path:line` that explains it. Link, don't duplicate.
- **Completion is archival, not deletion.** When a task is done, check its box, append `· done YYYY-MM-DD`, and move it to **Done** (newest-first). Never delete a completed task — `TODO.md` is the audit trail. Only delete an entry if it was created in error.
- **Dates are absolute.** Write `2026-05-31`, never "today" / "next week" — entries are read months later out of context.
- **Commit alongside related work.** When a code change closes or creates a `TODO.md` item, update `TODO.md` in the same commit so the tracker never lags the tree.
- **When the user says "add a todo" / "remember to…" / "we should later…"**, treat it as a request to add a `TODO.md` entry (not just the in-session scratchpad), unless it's clearly only about the current task.

## Definition of Done — the proof gate (every feature / spec slice)

**Confidence comes from reproducible, committed evidence — not from the agent asserting "tests pass."** A feature or spec slice is **DONE** only when every applicable item below has produced an **artifact another person can check without re-running anything**. This section is the umbrella; the sections that follow (Automated tests, Spec build-status, Test plans, Browser testing) are its mechanics.

1. **Automated tests, mapped to ACs, green this session.** Quote the `Ran N … OK` line. (See "Automated tests" + "verify before you tick".)
2. **Full regression run green** — the relevant pre-existing suites pass unchanged. Quote it. State which suites and why they're the blast radius.
3. **Browser smoke with COMMITTED SCREENSHOTS** — for any slice with desk-visible behavior, drive the real user path through Playwright (see "Browser testing") and **commit screenshots that prove the acceptance criteria** under `test/testplans/screenshots/<plan-basename>/` (the numbered folder matching the runbook, e.g. `05-supplier-resolution-3tier/`). This is mandatory and non-negotiable: *"the tests pass" is not proof the UI works — the screenshot is.* A backend-only slice with no desk surface is exempt **only if** it explicitly records "no UI surface — screenshots N/A" in STATUS.md.
4. **One small commit per spec/feature** — reviewable and revertible, bundling code + tests + docs + `STATUS.md` + screenshots. Not a multi-spec blob. (Commit when the user asks, or per the agreed cadence; always show the message first.)
5. **Clean-room test plan written** (`test/testplans/<slug>.md`), and — at phase boundaries — executed by a fresh instance.

**Screenshots-as-proof (the rule the user cares about most).** After testing a feature, **capture screenshots of the actual desk behavior that demonstrate each acceptance criterion** — the rendered form + field values (e.g. `Supplier Match Status = Alias`), the created/linked record, the blocked-vs-validated banner, the dialog, the list row. Name them descriptively (`alias-resolved-matched.png`, `unknown-blocked.png`) and commit them under the numbered folder `test/testplans/screenshots/<plan-basename>/`. The DB stays the source of truth (run a query and cite it), but the screenshot is the human-facing proof that ships with the work. **No screenshots ⇒ not done; never claim a UI feature works without them.** If the Playwright MCP isn't available, setting it up (per `test/testplans/BROWSER-TESTING-SETUP.md`) is a prerequisite to calling the slice done — not a reason to skip the proof.

**Cadence.** Per spec: build → automated tests green → **browser smoke + commit screenshots** → commit the slice. Per **phase boundary** (Resolve 05–07, Gate 08–10, Approve 11–12, Close 13–14): execute the clean-room test plans with a fresh instance **and** run a live browser demo for the user. This delivers continuous green tests, tangible visual proof every spec, and independent verification every phase — never a big-bang "trust me" at the end.

## Automated tests (mandatory for every feature with testable logic)

**Every feature that adds or changes Python logic MUST ship automated tests in the same commit/PR as the code.** This is separate from — and complementary to — the test *plan* (below): automated tests are the local, repeatable regression guard that runs under `bench run-tests`; the test plan is the runbook an external instance follows for end-to-end / UI verification. A feature needs **both**, not one or the other.

- **What to test:** any new function, DocType controller, helper, or adapter with branching logic. Unit-level behavior (a function returns the right value, raises the right error), plus the state transitions a controller drives. If a code change is purely a no-behavior-change refactor, the regression proof is that the **existing** suites pass unchanged — but new code paths (new modules, new providers, new registry entries) still need their own new tests.
- **Where:** mirror the existing convention — `test_*.py` co-located with the code (e.g. `erpnext/<module>/tests/test_*.py` or `erpnext/<module>/doctype/<dt>/test_<dt>.py`). New standalone packages get a `test_<package>.py` inside them.
- **Base class:** use `from frappe.tests import IntegrationTestCase` (the v16 convention used across this fork). Roll back DB writes in `tearDown` so suites are reentrant.
- **Coverage bar:** positive case, negative case (the error path / guard), and at least one edge case per public function. For registries/adapters: resolution of each registered key AND the unknown-key error.
- **How to apply:** write the tests as you write the code, run them locally with `bench --site <site> run-tests --module <dotted.path>`, and confirm green before declaring the feature done. "Verified via throwaway console probes" is NOT sufficient — probes vanish with the session; commit the assertions as tests.
- **Exemption:** pure docs, JSON-only DocType field additions with no controller logic, and trivial config edits don't need automated tests (but may still need a test plan if they change user-visible behavior).

## Spec build-status tracking — verify before you tick (`docs/spec/STATUS.md`)

`docs/spec/STATUS.md` is the **source-of-truth tracker** for the v2 workflow build (the `docs/spec/01`–`14` specs): each spec's status, its acceptance-criteria checklist, and the gating decisions. Updating it when a spec slice lands is **mandatory** — **and every tick in it is gated on an actual, executed verification, never on the code merely being written.**

- **Verify-before-tick (the mandatory gate).** Before you flip any AC checkbox to `[x]`, change a spec's **Status** to ✅, or set a spec's frontmatter `status:` to `Done`, you MUST have **run the verification in the current session and seen it pass**, then cite the result in your reply. Concretely: run the spec's automated test module(s) — `bench --site <site> run-tests --module <dotted.path>` — **plus the relevant regression suite** — and confirm `Ran N tests … OK`. Quote that line. No green run this session ⇒ no tick.
- **Inference is not verification.** "The code is written", "it compiles / `py_compile` passed", "it should pass", or "I verified it in an earlier session" do **not** count. Code written ≠ verified.
- **Blast-radius check.** If the slice adds something app-wide (a `hooks.py` / `doc_events` handler that fires across all docs, a shared controller method, a data patch), the verification must run at least one suite that exercises that surface — or STATUS.md must explicitly record that it was not run, and why.
- **Status levels & what ✅ means.** ✅ **Done** = every AC's automated test green **this session** + `FORK-CHANGES.md`(+`-PLAIN`) updated + the `test/testplans/<slug>.md` runbook **written** + (for any slice with desk-visible behavior) a **Playwright browser smoke executed this session with screenshots committed** under `test/testplans/screenshots/<slug>/` (see "Definition of Done"). A backend-only slice records *"no UI surface — screenshots N/A"* instead. The §7.2 clean-room runbook executed by an **external** fresh instance remains a separate downstream gate — record its state in STATUS.md (e.g. *"clean-room: pending"*) and **never claim it executed when it was not** (this is distinct from the per-slice browser smoke, which IS required for ✅). Use **👀 In review** for a spec whose code has landed but whose automated ACs are not yet all green this session, or whose required screenshots aren't yet committed.
- **Same-commit set.** A landed slice updates together, in one commit: `docs/spec/STATUS.md` (dashboard row + AC boxes + the header tally), the spec's frontmatter `status:`, `FORK-CHANGES.md`(+`-PLAIN`), `test/testplans/<slug>.md`, and the committed `test/testplans/screenshots/<slug>/` proof (or the explicit N/A note).

## Test plans (mandatory for every feature)

Local `bench run-tests` works in this WSL bench (use it — see "Automated tests" above), but it runs against a developer site carrying accumulated local state. A test plan is the **independent clean-room verification**: the actual runbook is executed by a **separate, isolated Claude instance** (cloud VM or fresh bench) that has **no prior context** about this repo, the conversation that produced the feature, or the developer's local state — so it catches "works on my machine" gaps the local automated tests can't. Every new or modified feature MUST ship with a self-contained test plan that the external instance can execute without asking clarifying questions.

- **Path & organization (kept in subfolders — never a flat dump):**
  - **v2 AP-workflow spec runbooks → `test/testplans/specs/NN-<slug>.md`**, where `NN` is the spec number so the folder sorts in spec order (e.g. `specs/05-supplier-resolution-3tier.md`, `specs/03-deduplication.md`). A spec with more than one runbook reuses its number (`specs/04-extraction-per-field-confidence.md`, `specs/04-extraction-line-items-promote.md`).
  - **Real-OCR build phases → `test/testplans/ocr/phaseN-<slug>.md`** (e.g. `ocr/phase2-real-ocr-anthropic.md`).
  - **Non-AP-workflow / platform features → `test/testplans/platform/<slug>.md`** (e.g. `platform/ai-chat-panel.md`).
  - **Infra/setup runbooks stay at the root** (`test/testplans/BROWSER-TESTING-SETUP.md`), and `test/testplans/README.md` is the index — add a row when you add a plan.
  - One file per feature; slug in kebab-case matching the feature. The basename (e.g. `05-supplier-resolution-3tier`) is also the screenshot-folder name — see "Browser testing".
- **Trigger:** create or update the test plan in the **same commit / PR** that introduces or modifies the feature. Code change without a paired test plan is incomplete.
- **Audience assumptions:** the external Claude instance has zero prior knowledge. It has not read this `CLAUDE.md`, it has not seen the planning docs, it has no memory of design discussions. It has a checkout of the branch and shell access on a clean bench. Write accordingly — the plan must read like a runbook.
- **Required sections (in this order):**
  1. **Feature under test.** One-paragraph description of what it does and the user-visible behavior change. Link any relevant planning doc in `docs/planning/` for context (don't restate it).
  2. **Branch / commit.** Exact branch name and commit SHA the plan applies to.
  3. **Environment setup.** Bench apps that must be installed, site to create or use, required Frappe apps and versions, environment variables, third-party API keys (named, with instructions on how the human operator obtains them — **never the key itself**). Include the exact `bench` commands to set the environment up from scratch.
  4. **Test data prerequisites.** Fixtures, DocType records to create, files to upload (give the exact content or a SHA-256 if relevant), users and roles to create with their permissions.
  5. **Numbered test cases.** Each case has: (a) preconditions, (b) the exact action — full URL to visit, button to click, or API call with full payload and headers, (c) the expected result — specific text / status code / DB state / log line, (d) the pass/fail criterion. Include positive cases, negative cases, edge cases.
  6. **Cleanup / rollback.** How to reset state between runs, what to delete, what to leave in place.
  7. **Pass/fail summary template.** A checklist the executor fills in and returns. One row per test case with `[ ]` boxes.
- **What NOT to write:**
  - "Verify it works as expected" — say WHAT to verify and HOW.
  - References to local file paths the external instance can't see (`/home/rsmith/...`, `C:\Users\russw\...`).
  - Assumptions about other docs being open — link them explicitly if needed.
  - Secrets (API keys, passwords, customer data). Instructions on how to obtain them, never the values.
- **Maintenance:** when a feature changes, update its test plan in the same commit. Out-of-date test plans are worse than missing ones — they look authoritative while being wrong.
- **How to apply:** when planning a new feature, write the test-plan skeleton early (right after the planning doc), then refine as the feature shapes up. The skeleton forces design clarity. The finished plan ships with the code.

## Browser testing (Playwright MCP)

UI test steps are executed by Claude Code driving a real browser through the **Playwright MCP server**. This is **not** committed config — the MCP setup is machine-specific (it pins an absolute path to the local Chromium binary), so each developer's machine sets it up once.

- **Setup runbook:** `test/testplans/BROWSER-TESTING-SETUP.md` is the authoritative, reproducible recipe. Follow it exactly — it encodes a known WSL gotcha (Playwright's auto-download extracts incompletely on WSL, so we install Chromium normally and point the MCP at it via `--executable-path`).
- **If `.mcp.json` is missing or the `playwright` MCP isn't registered** (check with `claude mcp list`), and the user asks to run a UI test or "test in the browser": offer to set it up by following `test/testplans/BROWSER-TESTING-SETUP.md`. Walk its steps — `claude mcp add playwright --scope project`, `npx playwright install chromium`, install system libs (sudo — ask first per the SSH/sudo rule below), write `.mcp.json` with the discovered binary path, then tell the user to **restart Claude Code** (MCP config loads only at startup).
- **`.mcp.json` and `.playwright-mcp/` are gitignored.** Never commit them. Never hand-edit `.mcp.json` to a path from another machine.
- **Screenshots are test evidence and ARE committed — one subfolder per feature, named with its spec/phase number, never mixed.** Every screenshot goes in a folder named exactly after its test plan's **basename** (which carries the spec/phase number): `test/testplans/screenshots/<plan-basename>/<descriptive-name>.png` — e.g. `…/screenshots/05-supplier-resolution-3tier/alias-resolved.png` (for `specs/05-supplier-resolution-3tier.md`), `…/screenshots/01-foundations-settings-async-idempotency/…`, `…/screenshots/phase2-real-ocr-anthropic/…`. The number prefix is **required** for any spec/phase-derived feature so the folder sorts and maps 1:1 to its runbook. This is mandatory organization, not a suggestion:
  - **One slug → one subfolder.** Never drop screenshots from two different features into the same folder, never into a shared/top-level `screenshots/` bucket, and **never** into the repo root. Always pass the full `test/testplans/screenshots/<slug>/<name>.png` path as the screenshot `filename` so the browser tool writes it straight there.
  - **Match the folder to the test plan basename.** The screenshot folder name is the SAME basename as the feature's runbook under `test/testplans/specs|ocr|platform/`, so the runbook and its proof map 1:1 and stay findable (runbook `specs/05-supplier-resolution-3tier.md` → screenshots `screenshots/05-supplier-resolution-3tier/`).
  - **Descriptive names within the folder**, optionally grouped by scenario in a sub-subfolder (`…/<slug>/<scenario>/<name>.png`) when a feature has many shots — but the per-feature top folder is always the boundary that keeps features from bleeding together.
  - The transient `.playwright-mcp/` runtime dir (snapshots, console logs, traces) stays gitignored.
- **The DB is the source of truth, not the screenshot.** After a UI action that writes data, verify the result with `bench --site … mariadb` / `bench … execute`, then clean up any test data written through the UI.

## Remote (SSH) access to customer machines

The customer's UAT/test machine and any other remote host reachable via SSH are **read-only by default**.

- **Allowed without asking:** read-only inspection commands — `ls`, `cat`, `tail`, `grep`, `ps`, `systemctl status`, `journalctl`, `bench --site … list-apps`, `bench --site … console` for SELECT-only queries, log fetches, config reads, etc.
- **Requires explicit per-action permission from the user:** anything that writes, updates, modifies, deletes, restarts, deploys, or otherwise changes state on the remote host. This includes — but is not limited to — `bench migrate`, `bench update`, `bench restart`, `bench --site … set-config`, editing files, `pip install`, `apt`/`yum`, `git pull`, `git checkout`, database writes (INSERT/UPDATE/DELETE/DDL), service restarts, cron edits, firewall changes, and any `sudo` invocation.
- **How to apply:** before running a state-changing command over SSH, quote the exact command back to the user and wait for explicit approval ("yes", "go ahead", etc.). A prior approval covers only the specific command approved — not similar commands later in the session. If unsure whether a command mutates state, treat it as state-changing and ask.

## What this repo is *not* the place for

- **Frappe framework changes** — separate repo (`frappe/frappe`), separate bench app.
- **Banking SPA assets** — gitignored (`erpnext/public/banking`, `erpnext/www/banking.html`). The `/banking/<path>` route resolves to a separate app.
- **Obsidian project notes** — Brandon's PMO vault is referenced in `AGENTS.md` but lives outside this repo.
