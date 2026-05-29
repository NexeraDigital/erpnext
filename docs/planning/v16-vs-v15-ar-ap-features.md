# ERPNext v16 vs v15 — AR / AP Feature Delta

> **Purpose:** A citation-backed, customer-readable list of accounting features that exist in ERPNext v16 but not in v15. Use as supporting material for the v16 upgrade conversation with the customer.
>
> **Date drafted:** 2026-05-28.
>
> **Audience:** NexeraDigital pilot stakeholders + customer-side IT / finance leads.
>
> **Verification basis:** Every bullet below is anchored to either (a) a verbatim commit subject on `upstream/version-16` that is **not** reachable from `upstream/version-15` (verified via `git merge-base --is-ancestor`), (b) a file path that exists on `upstream/version-16` and does **not** exist on `upstream/version-15`, or (c) a verbatim quote from the official Frappe v16 features page at https://frappe.io/erpnext/version-16.
>
> **Reference points used:** `upstream/version-15` HEAD = `v15.109.0` (commit `16fbf8299f`, dated 2026-05-27). `upstream/version-16` HEAD = `v16.20.0` (commit `ff46d20b25`, dated 2026-05-27). Customer is on `v15.108.3`, which is on the same v15 line and behind v15.109.0 — any feature not in v15.109.0 is not in v15.108.3.
>
> **Grounding rule (per `CLAUDE.md`):** every claim in this document is traceable to an upstream URL, a commit SHA in `frappe/erpnext`, or a file path verifiable in the repo.

---

## 0. TL;DR

ERPNext v16 adds substantial AR / AP capability that v15 does not have, including 20 new standalone print format records, two new DocTypes for tax withholding (Tax Withholding Entry + Tax Withholding Group), a Financial Report Template engine for IFRS / multi-company P&L and Balance Sheet, a Consolidated Trial Balance Report with automatic currency conversion, restructured per-item tax detail on Purchase Invoice (flagged by Frappe as a breaking change), payment-schedule-driven Payment Requests, and a number of smaller accounting plumbing improvements.

Every item in this document has been verified to exist on `upstream/version-16` and verified to be **absent** from `upstream/version-15`.

---

## 1. Accounts Payable

- **Standalone print format for the Accounts Payable report.**
  Source: commit `1c6dc80b7` on `upstream/version-16` — *"feat: add print format for accounts payable report"*. New file `erpnext/accounts/print_format/accounts_payable_standard/`. Not present on `upstream/version-15`.

- **Standalone print format for Purchase Invoice.**
  Source: commit `222f51b4d` — *"feat: standard print format for Sales Order and Purchase Invoice"*. New file `erpnext/accounts/print_format/purchase_invoice_standard/`. Not present on v15.

- **Standalone print format for Purchase Invoice "with item image" variant.**
  Source: new file `erpnext/accounts/print_format/purchase_invoice_with_item_image/` on v16; not present on v15.

- **Standalone print format for Purchase Order (and a "with item image" variant).**
  Source: new files `erpnext/buying/print_format/purchase_order_standard/` and `purchase_order_with_item_image/` on v16; not present on v15.

- **"With item image" variant of the Request for Quotation print format.**
  Source: new file `erpnext/buying/print_format/request_for_quotation_with_item_image/` on v16; not present on v15.

- **Restructured per-item tax storage on Purchase Invoice via a new `Item Wise Tax Detail` child DocType. Frappe flagged this as a breaking change.**
  Source: commit `91f3c82bd` — *"feat!: Item Wise Tax Details Table (#48692)"*. The `!` after `feat` is Conventional Commits notation for a breaking change. New folder `erpnext/accounts/doctype/item_wise_tax_detail/` on v16; not present on v15.
  Implication for the AP pilot: building tax-aware AP automation on v15 means it has to be reworked when the v16 upgrade happens.

- **New `Tax Withholding Entry` DocType plus a new `Tax Withholding Group` DocType.**
  Source: commit `c66f78c78` — *"feat: Introduce tax withholding entry"*. New folders `erpnext/accounts/doctype/tax_withholding_entry/` and `tax_withholding_group/` on v16; neither exists on v15. (v15 has tax withholding configuration via `tax_withholding_category`, `tax_withholding_account`, and `tax_withholding_rate`, but no first-class entry record.)

- **Exchange rate and base field added to the Advance Payment Ledger; exchange rate is set in journal entry on every refresh.**
  Source: commit `9c2525a8f` (verbatim) — *"feat: add exchange rate & base field in advance payment ledger, set exchange rate in journal entry on every refresh"*.

- **Subsidiary companies' values now shown in Purchase Analytics.**
  Source: commit `c8afc0495` (verbatim) — *"feat: show subsidiary companies value in purchase analytics"*.

---

## 2. Accounts Receivable

- **Standalone print format for the Accounts Receivable report.**
  Source: commit `4e7f2eeaa` — *"feat: introduce print format for Accounts Receivable report"*. New file `erpnext/accounts/print_format/accounts_receivable_standard/`. Not present on v15.

- **Standalone print format for Sales Order.**
  Source: commit `222f51b4d` (same as PI) — *"feat: standard print format for Sales Order and Purchase Invoice"*. New file `erpnext/selling/print_format/sales_order_standard/` on v16; not present on v15.

- **Standalone print format for Sales Invoice (and a "with item image" variant).**
  Source: new files `erpnext/accounts/print_format/sales_invoice_standard/` and `sales_invoice_with_item_image/` on v16; not present on v15.

- **Standalone print format for Quotation (and a "with item image" variant).**
  Source: new files `erpnext/selling/print_format/quotation_standard/` and `quotation_with_item_image/` on v16; not present on v15.

- **Standalone print format for POS Invoice (and a "with item image" variant).**
  Source: new files `erpnext/accounts/print_format/pos_invoice_standard/` and `pos_invoice_with_item_image/` on v16; not present on v15.

- **Payment Request can now be created from a payment schedule.**
  Source: commit `751a081253` — *"feat(payment request): create payment request as per payment schedules"*.

- **Option to calculate the Payment Request amount using the payment schedule.**
  Source: commit `298ea33922` — *"feat(payment_request): add option to calculate request amount using payment schedule"*.

- **Toggle for whether to use the payment schedule on a Payment Request.**
  Source: commit `5ade905ee8` — *"feat(Payment Request): Added a toggle for using the payment schedule (backport #53922)"*.

---

## 3. General accounting (both AP and AR)

- **Financial Report Templates** — turn P&L and Balance Sheet reports into fully customizable, formula-driven statements. Generate multi-company reports such as IFRS using reusable templates.
  Source: https://frappe.io/erpnext/version-16 (verbatim) — *"Financial Report Templates that turns P&L and Balance Sheet reports into fully customizable, formula-driven statements. Generate multi-company reports such as IFRS and others easily using reusable templates."* Backed by new DocType folder `erpnext/accounts/doctype/financial_report_template/` on v16 (not on v15).

- **Consolidated Trial Balance Report** — see all child companies in one unified report with currencies converted automatically.
  Source: https://frappe.io/erpnext/version-16 (verbatim) — *"Now, you can see a consolidated view of all child companies in one unified report. Currencies are converted automatically, giving a reliable, consolidated view of your group's financial health."* Backed by new report folder `erpnext/accounts/report/consolidated_trial_balance/` on v16 (not on v15).

- **Standalone print formats for Balance Sheet, P&L Statement, and Cash Flow Statement.**
  Source: commit `3283c461f` — *"feat: introduce print formats for financial statements"*. New files `erpnext/accounts/print_format/balance_sheet_standard/`, `p&l_statement_standard/`, `cash_flow_statement_standard/`. Not present on v15.

- **Standalone print format for Trial Balance.**
  Source: commit `1d08448d1` — *"feat: print format for report trial balance"*. New file `erpnext/accounts/print_format/trial_balance_standard/`. Not present on v15.

- **Standalone print format for General Ledger.**
  Source: new file `erpnext/accounts/print_format/general_ledger_standard/` on v16; not present on v15.

- **Item Tax Templates now support a "not applicable" tax option.**
  Source: commit `52a4ca9c4` (verbatim) — *"feat: add support for 'not applicable' tax in item tax templates (#50898)"*.

- **Journal Entry Template expanded to support accounting dimensions and party.**
  Source: commit `d06a46ae8` (verbatim) — *"feat(accounts): expand Journal Entry Template to support dimensions and party (#51621)"*.

- **Bank Transaction can be used as a Reference Type on a Journal Entry Account.**
  Source: commit `2c5bdefd1` (verbatim) — *"feat(Journal Entry Account): add Bank Transaction as Reference Type (backport #52760)"*.

- **Account category now supports root type.**
  Source: commit `96bab08ae` (verbatim) — *"feat: enhance account category with root type (#53190)"*.

- **XLSX styling support for custom financial report templates.**
  Source: commit `055ff56ce` (verbatim) — *"feat: Add XLSX styling support to custom financial report templates (#52612)"*.

- **Single remark field, with a custom remark toggle.**
  Source: commit `27c5dab7e` (verbatim) — *"feat: use single remark field with custom remark toggle"*.

- **Deferred revenue / expense report now includes service start date, service end date, and amount roll-ups.**
  Source: commit `407c3cd57` (verbatim) — *"feat(report): add service start/end date and amount with roll-ups in deferred revenue/expense report"*.

---

## 4. Summary statistics

- **20 new standalone print format records** added to `erpnext/*/print_format/` between v15 and v16, none of which exist on `upstream/version-15`.
  Source: file diff of `upstream/version-15` vs `upstream/version-16` for `erpnext/*/print_format/*/*.json`.

- **Two new tax-withholding DocTypes** (`tax_withholding_entry`, `tax_withholding_group`) added between v15 and v16.

- **One new DocType supporting the Financial Report Template engine** (`financial_report_template`) added between v15 and v16.

- **One new report folder for Consolidated Trial Balance** (`consolidated_trial_balance`) added between v15 and v16.

- **One new child DocType** (`item_wise_tax_detail`) added between v15 and v16, flagged as breaking by Frappe.

---

## 5. Items deliberately excluded from this list

The following items were considered for inclusion but **dropped** because the customer-facing description would have gone beyond what an upstream source verbatim says:

- **"Recurring journal entry templates can include cost center, project, and the customer or supplier."** This interprets "dimensions" → "cost center + project" and "party" → "customer or supplier". Standard ERPNext terminology, almost certainly accurate, but the commit message itself only says "dimensions and party". Item kept in the list above with the literal phrasing.

- **"Remarks on bills, payments, and journal entries are unified into one consistent field."** This invents the scope ("bills, payments, journal entries"). The commit message only says "use single remark field". Item kept in the list above with the literal phrasing.

- **"Chart of accounts is more consistent — accounts and their categories now agree on whether they're assets, liabilities, income, or expenses."** This invents a customer-facing explanation. The commit message only says "enhance account category with root type". Item kept in the list above with the literal phrasing.

If a customer asks for further detail on any of these, the next step is to read the actual code change of the cited commit and produce a verifiable customer-facing description.

---

## 6. What is NOT claimed in this document

- This document does **not** claim that every v15 accounting capability is broken or worse on v16. v16's AR / AP surface is a strict superset of v15's; no AR / AP capability present on v15 has been removed on v16 that we have found.
- This document does **not** make customer-friendly claims about runtime behavior. Every claim is anchored to a commit subject, a file path on the upstream repo, or a verbatim quote from frappe.io. If the customer demands a live demo of any specific feature, that requires spinning up a clean v16 site to walk through — not a citation exercise.
- This document does **not** address non-accounting v16 features (HR, manufacturing, inventory, MRP, etc.) — those are out of scope for the AR / AP-specific business case.

---

## 7. Sources

### Official Frappe

- https://frappe.io/erpnext/version-16 — official ERPNext v16 features page; source of the Financial Report Templates and Consolidated Trial Balance Report quotes.
- https://github.com/frappe/erpnext/tree/version-16 — the `version-16` branch source of truth for all commits and DocType folders cited above.
- https://github.com/frappe/erpnext/tree/version-15 — the `version-15` branch used as the comparison baseline.

### Verification commands (reproducible)

For any commit SHA cited above, the following local commands reproduce the verification:

```bash
cd /home/rsmith/frappe-bench/apps/erpnext
git log -1 --format="%s" <SHA>                                  # show the commit subject
git merge-base --is-ancestor <SHA> upstream/version-16 && echo "on v16" || echo "NOT on v16"
git merge-base --is-ancestor <SHA> upstream/version-15 && echo "on v15" || echo "NOT on v15"
```

For any file path cited above, the following commands reproduce the existence check:

```bash
git ls-tree upstream/version-15 -- <path>     # empty output means absent on v15
git ls-tree upstream/version-16 -- <path>     # non-empty output means present on v16
```

### Project docs

- `docs/planning/v16-upgrade-business-case.md` — broader business case for the v16 upgrade (timing, customer-side toolchain requirements, cost / risk profile, recommended sequence).
- `docs/planning/local-v17-to-v16-migration-plan.md` — separate technical plan for the fork's own migration from develop / v17-dev to v16.
