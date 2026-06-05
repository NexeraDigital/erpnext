# ERPNext Architecture

> **Repo:** `C:\GitHub\erpnext-1` &nbsp;&nbsp;|&nbsp;&nbsp; **Branch:** `develop` &nbsp;&nbsp;|&nbsp;&nbsp; **Upstream:** [frappe/erpnext](https://github.com/frappe/erpnext)
>
> Fork owner: `NexeraDigital` — see [`FORK-CHANGES.md`](FORK-CHANGES.md) for the AP Closed Loop pilot added in this fork.

---

## 1. What ERPNext Is

ERPNext is a 100% open-source, full-stack Enterprise Resource Planning (ERP) system built as a Frappe Framework application. It is delivered as a single Python package (`erpnext`) that plugs into a Frappe Bench. The functional surface area is large — accounting, stock, manufacturing, selling, buying, projects, assets, CRM, support, quality, subcontracting, EDI, regional tax/compliance, and portal/website.

ERPNext does not run standalone — it is hosted by the **Frappe Framework** (separate Python project) which provides:

- A persistent **DocType** model (metadata-driven schemas → MariaDB tables)
- Database abstraction (`frappe.db`, `frappe.qb` query builder)
- User auth, role/permission engine, workflow engine
- REST/RPC API surface (`/api/method/*`, `/api/resource/*`)
- Background job queue (RQ-backed) and a cron-like scheduler
- A desk UI (Jinja + Vanilla JS / Frappe UI), portal/website rendering, print, email, file storage
- Test runner (`bench --site … run-tests`)

So "ERPNext" is best read as **business doctypes + controllers + reports + hooks** layered on top of Frappe.

---

## 2. High-Level System Topology

```
                       ┌──────────────────────────────────────────────────────┐
                       │                     Bench Host                        │
                       │                                                       │
   Browser  ─────────► │  Nginx → Gunicorn (web) ─► Frappe app ─► ERPNext app  │
                       │                                       │               │
   Email / Cron ─────► │  Frappe Scheduler ─► RQ workers ──────┘               │
                       │            │                                          │
                       │            ▼                                          │
                       │  MariaDB  ◄──►  Redis (cache + queue + websocket)     │
                       │            ▲                                          │
                       │            │                                          │
                       │  File storage (private/public)                        │
                       └──────────────────────────────────────────────────────┘
```

- **Web tier:** Nginx in front of Gunicorn workers running the Frappe Werkzeug app.
- **Async tier:** Frappe scheduler enqueues into Redis-backed RQ; workers consume `default`, `short`, `long` queues. ERPNext registers callbacks under `scheduler_events` (see `hooks.py`).
- **Persistence:** MariaDB is the canonical store; each DocType becomes a `tab<DocType>` table. Redis is cache + websocket bus, not the source of truth.
- **Files:** `File` doctype wraps uploads on local disk (or S3 if configured). Used by Document Capture.
- **Realtime:** Socket.IO via Frappe for desk notifications and live document updates.

---

## 3. Repository Layout

```
erpnext-1/
├── pyproject.toml        flit build, Python ≥ 3.10, frappe >=16.0.0-dev,<17
├── package.json          frontend bundles (esbuild via Frappe), husky/commitlint
├── hooks.py              ► single most important file: app wiring
├── modules.txt           21 functional modules
├── patches.txt           ordered DB migrations
├── README.md / SECURITY / TRADEMARK / CODE_OF_CONDUCT
├── AGENTS.md             ◀ FORK: Codex/Claude operating notes for AP pilot
└── erpnext/
    ├── accounts/         finance: GL, AR/AP, taxes, PI/SI, PE, BoM cost flow
    │   ├── doctype/      187 doctypes (Account, GL Entry, Purchase Invoice, …)
    │   ├── ap_closed_loop/                       ◀ FORK: walking skeleton
    │   ├── doctype/document_capture/           ◀ FORK: capture doctype + flow
    │   ├── report/       finance reports (P&L, BS, Trial Balance, GL, AR/AP …)
    │   └── utils.py, party.py, general_ledger.py, deferred_revenue.py
    ├── stock/            78 doctypes — Item, Warehouse, Bin, Stock Entry, SLE, Serial/Batch
    ├── manufacturing/    48 doctypes — BOM, Work Order, Job Card, Routing
    ├── selling/          19 doctypes — Quotation, Sales Order, Customer
    ├── buying/           21 doctypes — Supplier, RFQ, Purchase Order, SQ
    ├── assets/           27 doctypes — Asset, Depreciation, Repair, Movement
    ├── crm/              29 doctypes — Lead, Opportunity, Prospect, Campaign
    ├── projects/         Project, Task, Timesheet, Activity
    ├── support/          Issue, SLA, Maintenance Schedule
    ├── subcontracting/   Subcontracting Order/Receipt
    ├── edi/              Code List / Common Code (UN/CEFACT-style master data)
    ├── quality_management/
    ├── regional/         per-country overrides (Italy e-invoice, UAE/SA VAT, France, …)
    ├── erpnext_integrations/  Plaid, GoCardless, etc.
    ├── controllers/      cross-doctype superclasses (AccountsController,
    │                     SellingController, BuyingController, StockController,
    │                     TaxesAndTotals, StatusUpdater, SubcontractingController)
    ├── public/           bundled JS/CSS/SVG assets (esbuild entrypoints)
    ├── templates/        portal + email templates
    ├── www/              static website routes
    ├── portal/           customer/supplier self-service portal
    ├── setup/            install, setup wizard, demo data, holiday lists
    ├── patches/          ordered migration scripts referenced by patches.txt
    ├── startup/          boot session, leaderboards, filters, notifications
    ├── domains/          domain (Mfg/Retail/Services/Distribution/Healthcare) presets
    ├── change_log/       per-release notes
    ├── locale/ gettext/  i18n catalogs (Crowdin-managed)
    └── tests/            cross-module integration tests
```

---

## 4. Core Architectural Concepts

### 4.1 DocType — the universal building block

Every business object — a Customer, a Sales Invoice line item, a setting page, a workflow state — is a **DocType**. Each DocType is defined by a JSON descriptor (field list, naming rule, permissions, child tables) and optionally a Python `Document` subclass for behavior. ERPNext ships a `*.json` and `*.py` pair per doctype under `<module>/doctype/<name>/`.

Document lifecycle hooks invoked by Frappe:

```
before_insert → validate → before_save → after_save → on_update
                                       └─ on_submit → on_cancel → on_trash
```

Cross-doctype reactions are wired in `hooks.py:doc_events`, e.g.:

- `*` → `validate` → SLA application + transaction-deletion lock
- All period-closing doctypes → `validate` → accounting-period guard
- `Stock Entry` → `on_submit/on_cancel` → recompute material-request fulfillment
- `Sales Invoice` → `on_submit/on_cancel` → regional Italian e-invoice utils

### 4.2 Controllers (cross-doctype mixins)

`erpnext/controllers/` holds the inheritance backbone of transactional documents:

- **`AccountsController`** — base for any document that touches the GL (Sales/Purchase Invoice, Payment Entry, Journal Entry, etc.). Owns posting-date validation, currency conversion, tax calc orchestration, payment schedule, advance handling.
- **`BuyingController` / `SellingController`** — purchase/sale-side shared logic (party validation, pricing rules, item defaults).
- **`StockController`** — anything that creates Stock Ledger Entries (Stock Entry, Delivery Note, Purchase Receipt, Subcontracting Receipt).
- **`SubcontractingController` / `SubcontractingInwardController`** — the special inventory flow for outsourced manufacturing.
- **`TaxesAndTotals`** — the single tax/total recomputation engine called by every transactional controller.
- **`StatusUpdater`** — recomputes "Billed", "Delivered", "Completed" etc. status percentages on parent documents from child rows.

### 4.3 The accounting spine (AR / AP / GL)

```
   Sales Quotation ─► Sales Order ─► Delivery Note ─► Sales Invoice ─► Payment Entry
                                            │                  │             │
                                            │                  ▼             ▼
                                            │            GL Entry +    GL Entry +
                                            │            Payment       Payment
                                            │            Ledger        Ledger
                                            ▼
                                       Stock Ledger Entry (Bin)

   Material Request ─► Request for Quotation ─► Supplier Quotation ─► Purchase Order
                                                                            │
                                                                            ▼
                                                               Purchase Receipt ─► Purchase Invoice ─► Payment Entry
                                                                       │                  │                  │
                                                                       ▼                  ▼                  ▼
                                                                   SLE + Bin        GL + PL Ledger     GL + PL Ledger
```

- **GL Entry** is the journal-line truth; **Payment Ledger Entry** is the parallel AR/AP-perspective ledger that powers the receivable/payable reports without re-scanning GL.
- **Period Closing Voucher** snapshots a year's P&L into `Account Closing Balance`.
- **Accounting Dimensions** (Cost Center + arbitrary additional dimensions registered in `accounting_dimension_doctypes`, see `hooks.py`) carry through every GL Entry and every transaction line.
- Bank reconciliation has its own subsystem (`Bank Reconciliation Tool`, `Bank Transaction`, `Bank Clearance`). Whether a payment is reconciled is a **separate** signal from whether the AR/AP is settled.

### 4.4 Stock / inventory engine

- **Stock Ledger Entry** is append-only; quantity and valuation are derived from it.
- **Bin** caches per-(Item, Warehouse) on-hand state for fast lookups.
- **Repost Item Valuation** is the queued job that recomputes SLE valuation when historic stock is edited; runs every 30 min via `scheduler_events.cron` and on demand.
- **Serial No / Batch No / Serial and Batch Bundle** track identity-bearing inventory.
- Subcontracting (outsourced work) has its own receipt doctype because the cost flow (raw material consumption at vendor, finished good receipt with conversion) differs from a plain Purchase Receipt.

### 4.5 Manufacturing

- **BOM** (with version & cost-update jobs scheduled every 15 min).
- **Production Plan** → **Work Order** → **Job Card** → **Stock Entries** (Manufacture / Material Transfer for Manufacture).
- **Routing** + **Workstation** + **Operation** drive capacity planning and job-card creation.

### 4.6 Hooks system — how ERPNext extends Frappe

`erpnext/hooks.py` declares every cross-cutting integration with Frappe. The most load-bearing entries:

| Hook | Purpose |
|---|---|
| `app_include_js/css`, `web_include_*`, `email_css` | bundle entrypoints (esbuild) |
| `doctype_js`, `doctype_list_js`, `page_js` | client-side script attachments |
| `doc_events` | server-side observers on documents (incl. wildcard `*`) |
| `scheduler_events` | cron/hourly/daily/weekly/monthly jobs |
| `regional_overrides` | country-specific monkey-patches of tax/GL logic |
| `setup_wizard_stages`, `after_install` | first-run bootstrapping |
| `boot_session`, `extend_bootinfo` | inject data into the desk on login |
| `website_route_rules`, `standard_portal_menu_items` | portal/website URLs |
| `period_closing_doctypes` | doctypes guarded by Accounting Period locks |
| `accounting_dimension_doctypes` | doctypes that carry accounting dimensions |
| `auto_cancel_exempted_doctypes` | breaks chained cancellation for Payment Entry |
| `bank_reconciliation_doctypes`, `invoice_doctypes`, `advance_payment_*_doctypes` | feature catalogs other modules read |
| `user_privacy_documents` | GDPR personal-data fields |
| `naming_series_variables` | custom token resolvers (e.g. `FY`, `ABBR`) |

### 4.7 Regional / multi-jurisdiction

`erpnext/regional/<country>/utils.py` provides per-country overrides registered via `regional_overrides` and direct `doc_events`. Examples:
- **Italy**: e-invoicing (FatturaPA), state code on Address.
- **United Arab Emirates / Saudi Arabia**: reverse-charge VAT, itemised tax data, regional GL entries.
- **France**: regional test hooks.

### 4.8 Background processing & scheduler

Defined entirely in `hooks.py:scheduler_events`:
- **Every 15 min**: BOM cost-update job resumer.
- **Every 30 min**: parallel reposting of item valuation.
- **Every 30 past the hour**: GLE/SLE rename queue.
- **Hourly**: project deadline reminders.
- **Hourly maintenance**: repost valuation, bulk-transaction retries, project status, Plaid sync, YouTube data.
- **Daily maintenance**: ~25 jobs — auto-close tickets, update invoice statuses, fiscal year auto-create, supplier scorecards, asset maintenance/depreciation posting, dunning, reorder, subscriptions, e-mail digests.
- **Weekly / Monthly long**: exchange rate revaluation, deferred revenue/expense processing.

### 4.9 Test architecture

- Module-local `test_<doctype>.py` files use `frappe.tests.IntegrationTestCase`, run inside an isolated test site against MariaDB.
- `before_tests = erpnext.setup.utils.before_tests` bootstraps a `_Test Company`, `_Test Item`, `_Test Supplier`, `_Test Bank - _TC`, `_Test Cost Center - _TC`, etc. The AP Closed Loop tests rely on those names directly.
- Tests roll back with `frappe.db.rollback()` in `tearDown` rather than truncating tables.

### 4.10 Frontend

ERPNext does **not** ship a separate SPA. The desk UI is delivered via Frappe with ERPNext contributing:
- esbuild bundles declared in `package.json` (`erpnext.bundle.js`, `erpnext-web.bundle.css`, `email_erpnext.bundle.css`, plus POS-specific bundles).
- DocType-attached client scripts (`erpnext/public/js/*.js`, plus per-doctype `*.js` inside `<doctype>/`).
- A small Vue/Frappe-UI surface for POS and a handful of pages.
- Portal/website pages are server-rendered Jinja from `erpnext/templates/` and `erpnext/www/`.

---

## 5. Module Inventory

From `erpnext/modules.txt` (21 modules) — doctype counts measured in this repo:

| Module | Doctypes | Role |
|---|---:|---|
| Accounts | 187 | GL, AR/AP, taxes, payment, banking, AP Closed Loop (fork) |
| Stock | 78 | inventory, valuation, warehousing, serial/batch |
| Manufacturing | 48 | BOM, work orders, job cards, routing |
| CRM | 29 | leads, opportunities, prospects, campaigns |
| Assets | 27 | asset, depreciation, repair, movement |
| Buying | 21 | supplier, RFQ, PO, SQ |
| Selling | 19 | customer, quotation, sales order |
| Setup | — | company, fiscal year, employee, holidays, naming series |
| Support | — | issue, SLA, maintenance schedule/visit |
| Projects | — | project, task, timesheet, activity |
| Portal | — | customer/supplier self-service |
| Subcontracting | — | outsourced manufacturing flow |
| EDI | — | UN/CEFACT code lists |
| Regional | — | country-specific tax/e-invoice |
| ERPNext Integrations | — | Plaid, Tally, GoCardless, etc. |
| Quality Management | — | quality goal, procedure, review |
| Communication | — | call log + communication metadata |
| Telephony | — | call log + linked-conversations |
| Bulk Transaction | — | bulk submit/cancel via background jobs |
| Maintenance | — | maintenance schedule/visit |
| Utilities | — | activation, bot, helpers, video |

---

## 6. Data Flow Examples

### 6.1 Submit a Purchase Invoice (the AP path the fork extends)

1. User (or API) creates `Purchase Invoice` referencing a `Supplier` and items.
2. `BuyingController.validate` → `TaxesAndTotals` recomputes totals; `AccountsController.validate` checks posting date / accounting period.
3. `period_closing_doctypes` validator (`hooks.py`) confirms the date isn't in a closed period.
4. On `submit`: `make_gl_entries` posts journal lines to `GL Entry`, parallel `Payment Ledger Entry`, advances `Payment Schedule`, updates `Supplier` outstanding.
5. `StatusUpdater` updates linked `Purchase Order` / `Purchase Receipt` billed-status.
6. Reports (Accounts Payable, Trial Balance) read from `GL Entry` + `Payment Ledger Entry`.

### 6.2 Settle a Purchase Invoice via Payment Entry

1. `get_payment_entry("Purchase Invoice", pi.name, …)` (in `accounts/doctype/payment_entry/payment_entry.py`) prefills a draft PE.
2. On submit: GL Entries debit `Creditors`, credit the bank account; PI `outstanding_amount` → 0; PI `status` → "Paid".
3. **No `Bank Transaction` is created** by Payment Entry submission. Bank Transactions originate from bank statement import / Plaid; `Bank Reconciliation Tool` links them to existing PEs. The AP Closed Loop pilot intentionally never crosses into Bank Transaction territory.

### 6.3 Scheduler invocation

`bench schedule` → cron tick → Frappe scheduler reads `hooks.py:scheduler_events` for every installed app → enqueues jobs into RQ → workers execute the dotted-path callable.

---

## 7. Configuration & Build

- **Python**: `pyproject.toml` declares core deps (Unidecode, rapidfuzz, holidays, googlemaps, plaid-python, python-youtube, mt-940, pandas, statsmodels) and pins `frappe >=16.0.0-dev,<17.0.0`.
- **JS/CSS**: `package.json` uses `husky` + `commitlint`; bundles are built by Frappe's esbuild runner (no custom webpack).
- **Lint/format**: `ruff` with line-length 110, tab indent, Python target 3.10.
- **i18n**: Crowdin (`crowdin.yml`), `babel_extractors.csv`, locale catalogs under `locale/`.
- **CI**: GitHub Actions referenced by README (`server-tests-mariadb.yml` etc.), `codecov.yml`, `sider.yml`.

---

## 8. Extension Points (how to add functionality cleanly)

1. Add a `DocType` JSON + `Document` subclass under `erpnext/<module>/doctype/<name>/`.
2. Wire cross-doctype reactions through `hooks.py:doc_events` rather than monkey-patching.
3. Whitelisted server methods (`@frappe.whitelist()`) become RPC endpoints at `/api/method/erpnext.<path>.<fn>` — this is how the AP Closed Loop pilot exposes its actions.
4. Reports go under `<module>/report/<name>/` with `*.json` (report meta) + `*.py` (data) + `*.js` (filters).
5. Workspaces & dashboards under `<module>/workspace/` and `<module>/dashboard_chart/`.
6. For country-specific behavior: drop a module under `erpnext/regional/<country>/` and register hooks in `regional_overrides`.

---

## 9. The Fork Overlay

This repository is `develop` of upstream **plus** an AP Closed Loop Receipt Processing pilot owned by NexeraDigital. The pilot adds **one** new accounting doctype (`Document Capture`), a deterministic walking-skeleton module, and an `AGENTS.md` operating note. **No upstream business logic is replaced.** See [`FORK-CHANGES.md`](FORK-CHANGES.md) for the full breakdown.
