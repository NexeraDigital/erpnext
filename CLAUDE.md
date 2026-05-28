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
| `AGENTS.md` (root) | Codex ↔ Claude ↔ Obsidian orchestration for the pilot (Brandon's working notes) | Codex/Claude workflow itself changes — not for code work |

## Working rules

- **For "where in the UI does X go?" questions:** consult `docs/architecture/UI-SITEMAP.md` first. Verify against the current repo before recommending placement — the sitemap is dated, not live.
- **For changes inside the AP closed-loop scope** (`erpnext/accounts/ap_closed_loop/`, `erpnext/accounts/doctype/ap_invoice_capture/`): update `docs/architecture/FORK-CHANGES.md` in the same commit so the fork delta stays accurate.
- **For navigation changes** (any file under the UI-SITEMAP update triggers): refresh `docs/architecture/UI-SITEMAP.md` in the same commit. Update the "Last verified against repo" date at the top.
- **Don't duplicate Frappe docs.** If something is generic ERPNext/Frappe behavior, link to upstream docs rather than restating in this repo.
- **Existing convention is to keep `FORK-CHANGES.md` and `FORK-CHANGES-PLAIN.md` paired** — if you update one, update both.
- **When the user references a screenshot or image file by name without a full path** (e.g. *"see Screenshot 2026-05-27 093723.png"*), look in `/mnt/c/Users/russw/OneDrive/Pictures/Screenshots 1/` first. That's their Windows Pictures → Screenshots folder mounted via WSL — note the literal folder name `Screenshots 1` (with the trailing space and `1`). A Windows-style path like `C:\Users\russw\OneDrive\Pictures\Screenshots 1\...` translates to `/mnt/c/Users/russw/OneDrive/Pictures/Screenshots 1/...`.

## Remote (SSH) access to customer machines

The customer's UAT/test machine and any other remote host reachable via SSH are **read-only by default**.

- **Allowed without asking:** read-only inspection commands — `ls`, `cat`, `tail`, `grep`, `ps`, `systemctl status`, `journalctl`, `bench --site … list-apps`, `bench --site … console` for SELECT-only queries, log fetches, config reads, etc.
- **Requires explicit per-action permission from the user:** anything that writes, updates, modifies, deletes, restarts, deploys, or otherwise changes state on the remote host. This includes — but is not limited to — `bench migrate`, `bench update`, `bench restart`, `bench --site … set-config`, editing files, `pip install`, `apt`/`yum`, `git pull`, `git checkout`, database writes (INSERT/UPDATE/DELETE/DDL), service restarts, cron edits, firewall changes, and any `sudo` invocation.
- **How to apply:** before running a state-changing command over SSH, quote the exact command back to the user and wait for explicit approval ("yes", "go ahead", etc.). A prior approval covers only the specific command approved — not similar commands later in the session. If unsure whether a command mutates state, treat it as state-changing and ask.

## What this repo is *not* the place for

- **Frappe framework changes** — separate repo (`frappe/frappe`), separate bench app.
- **Banking SPA assets** — gitignored (`erpnext/public/banking`, `erpnext/www/banking.html`). The `/banking/<path>` route resolves to a separate app.
- **Obsidian project notes** — Brandon's PMO vault is referenced in `AGENTS.md` but lives outside this repo.
