# Claude working notes for this repo

This is a fork of `frappe/erpnext` carrying the **AP Closed Loop Receipt Processing** pilot for NexeraDigital. Branch convention: pilot work lives on `russ/bryanwork`; upstream tracks `develop`.

Before doing non-trivial work, read the doc that matches your task.

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

## What this repo is *not* the place for

- **Frappe framework changes** — separate repo (`frappe/frappe`), separate bench app.
- **Banking SPA assets** — gitignored (`erpnext/public/banking`, `erpnext/www/banking.html`). The `/banking/<path>` route resolves to a separate app.
- **Obsidian project notes** — Brandon's PMO vault is referenced in `AGENTS.md` but lives outside this repo.
