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
| `docs/changes/NewUpdates.md` | The 13-step AP workflow design (ambition spec, broader than what's shipped) | Workflow design changes — distinct from current implementation |
| `docs/changes/GAP-ANALYSIS.md` | Gap between current ERPNext capability and pilot target | Pilot scope or upstream capability changes |
| `docs/changes/IMPLEMENTATION-PLAN.md` | Build sequence and milestones for the pilot | Pilot milestones move or new tasks are added |
| `docs/spec/00-overview.md` + `docs/spec/01`–`14` | The v2 AP-workflow implementation specs (one per workflow step) + the index | A spec's design changes — keep its frontmatter `status:` current |
| `docs/spec/STATUS.md` | Build-status tracker for the v2 spec implementation (per-spec status, AC checklist, gating decisions) | A spec slice is implemented/verified — **gated on actual verification; see "Spec build-status tracking" below** |
| `test/testplans/*.md` | Per-feature, self-contained test plans executed by an **external** Claude instance for independent clean-room verification (local `bench run-tests` works too — see "Automated tests") | Any feature is added or modified — see "Test plans" section below |
| `AGENTS.md` (root) | Codex ↔ Claude ↔ Obsidian orchestration for the pilot (Brandon's working notes) | Codex/Claude workflow itself changes — not for code work |

## Working rules

- **For "where in the UI does X go?" questions:** consult `docs/architecture/UI-SITEMAP.md` first. Verify against the current repo before recommending placement — the sitemap is dated, not live.
- **For changes inside the AP closed-loop scope** (`erpnext/accounts/ap_closed_loop/`, `erpnext/accounts/doctype/ap_invoice_capture/`): update `docs/architecture/FORK-CHANGES.md` in the same commit so the fork delta stays accurate.
- **For navigation changes** (any file under the UI-SITEMAP update triggers): refresh `docs/architecture/UI-SITEMAP.md` in the same commit. Update the "Last verified against repo" date at the top.
- **Don't duplicate Frappe docs.** If something is generic ERPNext/Frappe behavior, link to upstream docs rather than restating in this repo.
- **Existing convention is to keep `FORK-CHANGES.md` and `FORK-CHANGES-PLAIN.md` paired** — if you update one, update both.
- **When the user references a screenshot or image file by name without a full path** (e.g. *"see Screenshot 2026-05-27 093723.png"*), look in `/mnt/c/Users/russw/OneDrive/Pictures/Screenshots 1/` first. That's their Windows Pictures → Screenshots folder mounted via WSL — note the literal folder name `Screenshots 1` (with the trailing space and `1`). A Windows-style path like `C:\Users\russw\OneDrive\Pictures\Screenshots 1\...` translates to `/mnt/c/Users/russw/OneDrive/Pictures/Screenshots 1/...`.
- **For every feature added or modified**, write a test plan in `test/testplans/` per the "Test plans" section below. A code change without a paired test plan is incomplete.

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
- **Status levels & what ✅ means.** ✅ **Done** = every AC's automated test green **this session** + `FORK-CHANGES.md`(+`-PLAIN`) updated + the `test/testplans/<slug>.md` runbook **written**. The §7.2 clean-room and §7.3 Playwright runbooks are a **separate downstream gate** (executed by an external instance / a dedicated browser pass) — record their execution state in STATUS.md (e.g. a *"clean-room/UI: pending"* note) and **never claim them executed when they were not**. Use **👀 In review** for a spec whose code has landed but whose automated ACs are not yet all green this session.
- **Same-commit set.** A landed slice updates together, in one commit: `docs/spec/STATUS.md` (dashboard row + AC boxes + the header tally), the spec's frontmatter `status:`, `FORK-CHANGES.md`(+`-PLAIN`), and `test/testplans/<slug>.md`.

## Test plans (mandatory for every feature)

Local `bench run-tests` works in this WSL bench (use it — see "Automated tests" above), but it runs against a developer site carrying accumulated local state. A test plan is the **independent clean-room verification**: the actual runbook is executed by a **separate, isolated Claude instance** (cloud VM or fresh bench) that has **no prior context** about this repo, the conversation that produced the feature, or the developer's local state — so it catches "works on my machine" gaps the local automated tests can't. Every new or modified feature MUST ship with a self-contained test plan that the external instance can execute without asking clarifying questions.

- **Path:** `test/testplans/<feature-slug>.md`. One file per feature. Slug in kebab-case matching the feature (e.g. `ap-invoice-capture-promote.md`, `real-ocr-anthropic.md`, `v16-upgrade-smoke.md`).
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
- **Screenshots are test evidence and ARE committed.** Save them under `test/testplans/screenshots/<feature-slug>/<descriptive-name>.png` — always pass that path as the screenshot `filename` so they don't land in the repo root. The transient `.playwright-mcp/` runtime dir (snapshots, console logs, traces) stays gitignored.
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
