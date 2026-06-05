# ERPNext UI Sitemap

> **Purpose:** complete map of every place a user can land in the ERPNext desk UI on this fork. Use this before recommending where new functionality should live so suggestions are grounded in the navigation users actually see.
>
> **Last verified against repo:** 2026-06-01 *(adds §G — the global AI chat launcher, the first fork-added always-present desk element besides the navbar, injected via `app_include_js`/`css` and gated on `frappe.boot.ai_chat_enabled`. ERPNext Settings sidebar + shortcut still include AI Provider Settings, alphabetically after System Settings; Payables still includes Invoice Capture → Document Capture; Settings tail still includes AP Closed Loop Settings)*
>
> **Update triggers** — regenerate this doc when any of the following change:
> - `erpnext/workspace_sidebar/*.json` (primary navigation)
> - `erpnext/<module>/workspace/<name>/<name>.json` (legacy navigation)
> - `erpnext/<module>/page/<name>/*` (Frappe pages)
> - `erpnext/hooks.py` `website_route_rules` (portal routes), `app_include_js` / `app_include_css` (global desk-wide UI)
> - `erpnext/<module>/<module>_dashboard/` (module dashboards)

---

## Navigation systems — two layers coexist

| System | Files | Status | Renders |
|---|---|---|---|
| **Workspace Sidebar** (new, 2025-10-26+) | 22 in `erpnext/workspace_sidebar/*.json` | **Primary — what users see** | The collapsible left sidebar |
| **Classic Workspaces** (legacy) | 14 in `erpnext/<module>/workspace/<name>/<name>.json` | Still installed, mirrored by sidebars | Reachable at `/app/<workspace-name>` but no longer the entry point |

Every classic workspace has a sidebar equivalent. Sidebar is canonical.

---

## A. Workspace Sidebars (22 total)

### Accounts-area sidebars

- **Invoicing** (`invoicing.json`) — Home, Dashboard (Accounts), Chart of Accounts
  - **Receivables**: Customer, Sales Invoice, Credit Note *(Sales Invoice w/ `is_return:1`)*, Accounts Receivable *(Report)*
  - **Payables**: Invoice Capture *(Document Capture)*, Supplier, Purchase Invoice, Debit Note *(Purchase Invoice w/ `is_return:1`)*, Accounts Payable *(Report)*
  - **Payments**: Payment Entry, Journal Entry, Payment Request, Payment Order, Payment Reconciliation, Unreconcile Payment, Process Payment Reconciliation, Repost Accounting Ledger, Repost Payment Ledger
  - **Reports**: General Ledger, Trial Balance, Financial Reports *(workspace)*
  - Settings → Accounts Settings
  - **AP Closed Loop Settings** *(Single DocType — site-wide promote defaults for the AP capture pilot)*

- **Accounts Setup** (`accounts_setup.json`) — Setup *(15: Account, Cost Center, Accounting Dimension, Currency, Company, Fiscal Year…)* · Opening & Closing *(5)* · Settings *(3)*

- **Financial Reports** (`financial_reports.json`) — Financial Reports *(7: Balance Sheet, P&L, Cash Flow…)* · Ledgers *(3)* · Registers *(8: AR/AP Summary, Sales Register…)* · Profitability *(4)* · Other Reports *(7)*

- **Payments** (`payments.json`) — Dashboard (Payments) · Payments *(10)* · Reports *(5)*

- **Banking** (`banking.json`) — Bank Clearance, Bank Reconciliation Tool, Reconciliation Statement, Unreconcile Payment, Process Payment Reconciliation · Setup *(5: Bank, Bank Account, Plaid Settings…)* · Dunning *(2)*

- **Budget** (`budget.json`) — Budget, Cost Center, Accounting Dimension, Cost Center Allocation, Budget Variance Report

- **Taxes** (`taxes.json`) — Sales/Purchase/Item Tax Templates · Setup *(4)* · Lower Deduction Certificate · Reports *(2)*

### Operational sidebars

- **Selling** (`selling.json`) — Quotation, Sales Order, Sales Invoice · POS *(9: POS Page, POS Profile, POS Invoice, Opening/Closing Entry, Merge Log, Settings, Loyalty Program, Loyalty Point Entry)* · Items & Pricing *(8)* · Setup *(14)* · Reports *(17)* · Settings

- **Buying** (`buying.json`) — Material Request, RFQ, Supplier Quotation, Purchase Order, Purchase Invoice · Setup · Reports *(11)* · Settings

- **Stock** (`stock.json`) — Stock Entry, Purchase Receipt, Delivery Note, Material Request, Pick List · Tools *(5: Stock Reconciliation, Landed Cost Voucher, Repost Item Valuation, Packing Slip, Quality Inspection)* · Setup *(14)* · Reports *(22)* · Settings *(4)*

- **Manufacturing** (`manufacturing.json`) — BOM, Work Order, Job Card, Stock Entry · Material Planning *(5)* · Tools *(4: BOM Creator, BOM Update Tool, BOM Comparison Tool Page, Downtime Entry)* · Reports *(9)* · Setup *(7)* · Settings

- **CRM** (`crm.json`) — Lead, Opportunity, Customer · Reports *(8)* · Maintenance *(3)* · Sales Pipeline *(6)* · Campaign *(5)* · Setup *(7)* · Settings *(2)*

- **Projects** (`projects.json`) — Project, Task, Timesheet · Setup *(5)* · Reports *(5)* · Settings

- **Support** (`support.json`) — Issue, Maintenance Schedule, Maintenance Visit, Warranty Claim · Setup *(3)* · Reports *(1)* · Settings

- **Assets** (`assets.json`) — Asset, Asset Depreciation Schedule, Asset Capitalization, Asset Movement · Maintenance *(5)* · Reports *(5)* · Setup *(3)* · Settings *(navigates to Accounts Settings → assets tab)*

- **Quality** (`quality.json`) — Quality Inspection, Quality Goal, Quality Review, Quality Action, Non Conformance, Quality Feedback, Quality Meeting · Setup *(3)*

- **Subcontracting** (`subcontracting.json`) — Subcontracting BOM, Stock Entry · Inward Order *(3)* · Outward Order *(3)* · Setup *(2)* · Reports *(3)* · Settings

### Cross-cutting / top-level sidebars

- **Home** (`home.json`) — Item, Home workspace, Customer, Supplier, Sales Invoice
- **Organization** (`organization.json`) — Company, Letter Head, Department, Branch, User, Role Permissions *(permission-manager Page)*, Email Account
- **Subscription** (`subscription.json`) — Subscription, Subscription Plan, Subscription Settings · Setup *(3)*
- **Share Management** (`share_management.json`) — Shareholder, Share Transfer, Share Ledger, Share Balance
- **ERPNext Settings** (`erpnext_settings.json`) — 12 module Settings doctypes (System Settings, **AI Provider Settings** *(fork-added, System-Manager-only — shared AI provider credentials)*, Accounts Settings, POS Settings, Selling Settings, Buying Settings, Stock Settings, Manufacturing Settings, Projects Settings, CRM Settings, Support Settings, Global Defaults) + Other Settings *(8: Subscription Settings, Item Variant Settings, Delivery Settings…)*

---

## B. Classic Workspaces (legacy)

`erpnext/<module>/workspace/<name>/<name>.json` — 14 files. All have sidebar equivalents; kept for backward compatibility.

- `setup/workspace/home/home.json`
- `setup/workspace/erpnext_settings/erpnext_settings.json`
- `selling/workspace/selling/selling.json`
- `buying/workspace/buying/buying.json`
- `stock/workspace/stock/stock.json`
- `crm/workspace/crm/crm.json`
- `accounts/workspace/invoicing/invoicing.json`
- `accounts/workspace/financial_reports/financial_reports.json`
- `projects/workspace/projects/projects.json`
- `assets/workspace/assets/assets.json`
- `quality_management/workspace/quality/quality.json`
- `support/workspace/support/support.json`
- `manufacturing/workspace/manufacturing/manufacturing.json`
- `subcontracting/workspace/subcontracting/subcontracting.json`

Structure: `shortcuts`, `links` (with Card Breaks), `charts`, `number_cards`. When the sidebar version exists, edits should go to the sidebar, not the classic workspace.

---

## C. Frappe Pages (custom UIs beyond DocType forms)

| Page | Path | Linked from |
|---|---|---|
| Point of Sale | `selling/page/point_of_sale/` | Selling sidebar (POS section) |
| Sales Funnel | `selling/page/sales_funnel/` | Selling + CRM sidebars |
| BOM Comparison Tool | `manufacturing/page/bom_comparison_tool/` | Manufacturing sidebar (Tools) |
| Stock Balance | `stock/page/stock_balance/` | Stock module |
| Warehouse Capacity Summary | `stock/page/warehouse_capacity_summary/` | Stock module |
| Permission Manager | *(Frappe core)* | Organization sidebar (Role Permissions) |

These are the precedent for multi-step custom UIs that don't fit a DocType form.

---

## D. Web / portal routes (public-facing)

Defined in `erpnext/hooks.py` `website_route_rules`:

```
/orders, /orders/<name>            → Sales Order
/invoices, /invoices/<name>        → Sales Invoice
/quotations, /quotations/<name>    → Quotation
/shipments, /shipments/<name>      → Delivery Note
/material-requests/...             → Material Request
/supplier-quotations/...           → Supplier Quotation
/purchase-orders/...               → Purchase Order
/purchase-invoices/...             → Purchase Invoice
/rfq, /rfq/<name>                  → Request for Quotation
/addresses, /addresses/<name>      → Address
/boms                              → BOM
/timesheets                        → Timesheet
/project, /tasks                   → Project / Task
/banking/<path>                    → Banking SPA fallback
```

`/banking/<path>` resolves to a separate Banking SPA app — assets are gitignored in this repo (see `.gitignore` → `erpnext/public/banking`, `erpnext/www/banking.html`). The SPA is not part of this codebase.

Standard customer/supplier portal menu (via Portal Settings) exposes: Projects, Quotations, Orders, Invoices, Shipments, Issues, Addresses, Material Requests, Timesheets *(customer)* · RFQ, Supplier Quotations, Purchase Orders, Purchase Invoices *(supplier)*.

---

## E. Dashboards & data tiles

Module-level dashboards in `erpnext/<module>/<module>_dashboard/`:

- `accounts_dashboard/` — `accounts/`, `payments/`
- `assets_dashboard/`, `buying_dashboard/`, `crm_dashboard/`, `manufacturing_dashboard/`, `projects_dashboard/`, `selling_dashboard/`, `stock_dashboard/`

These are what the "Dashboard" sidebar entries link to (e.g., Invoicing → Dashboard → Accounts). They render Number Cards (`erpnext/<module>/number_card/`) and Dashboard Charts (`erpnext/<module>/dashboard_chart/`).

---

## F. Global / always-present desk elements (not navigation-tree)

Unlike everything above (which lives in a sidebar/workspace/page/route), these render on **every desk page** because they're injected app-wide via `erpnext/hooks.py` `app_include_js` / `app_include_css`, independent of the route.

| Element | Where it appears | How it's mounted | Visibility gate |
|---|---|---|---|
| **AI Chat launcher + panel** *(fork-added)* | Floating button bottom-right of every `/app/*` page; click (or **Ctrl/Cmd-J**) opens a right-side slide-over chat | `ai_chat.bundle.js` (in `app_include_js`) mounts one controller on `document.body` at `app_ready`; survives SPA navigation | Only when `frappe.boot.ai_chat_enabled` is true — i.e. signed-in (not Guest) **and** the MCP server is enabled. Absent otherwise. |

This is the **first fork-added always-present desk element besides the standard navbar** — it is deliberately *not* a sidebar/workspace entry (it's a global overlay, like a help widget). It reuses the §10 MCP read tools as the signed-in user; see `docs/architecture/FORK-CHANGES.md` §15.

---

## G. Cross-reference notes

1. **The screen at `/app/dashboard-view/Accounts` is the `Invoicing` sidebar + the `Accounts` Dashboard.** Top KPI cards are Number Cards (`accounts/number_card/total_outgoing_bills`, etc.). The P&L chart is a Dashboard Chart.

2. **No "Accounts Payable" sidebar exists today.** AP work is split: Purchase Invoice in `Buying`, payments in `Invoicing → Payables`, reconciliation in `Banking`.

3. **No orphans detected.** Every classic workspace has a sidebar mirror; every sidebar item points to a valid DocType, Report, Page, Workspace, or Dashboard.

4. **Document Capture (this fork's pilot DocType)** is linked from the Invoicing sidebar → Payables → "Invoice Capture". The form itself still has no custom buttons or list indicators — that's the next phase of UI work. See `docs/architecture/FORK-CHANGES.md` for the pilot's scope.
