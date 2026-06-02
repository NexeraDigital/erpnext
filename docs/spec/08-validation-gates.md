---
spec: 08-validation-gates
title: Validation, Anomaly Detection & Three-Way Match
plan_step: "Step 7 — Validation suite + amount-anomaly + vendor bank-detail change + three-way match; plus the optional PO upstream control"
stream: both
status: Done
depends_on: [01-foundations-settings-async-idempotency, 04-extraction-confidence-line-items, 05-supplier-resolution, 06-gl-coding-tax-costcenter, 11-approval-sod-workflow]
related: [00-overview, 02-intake-stream-tagging, 07-classification-doctype-branching, 09-confidence-routing, 10-ap-review-observability, 14-closure-audit-retention]
---

# 08 — Validation, Anomaly Detection & Three-Way Match
> _Revised 2026-05-31: applied native-vs-custom review findings; added Playwright UI test plan (§7.3)._
> _Revised 2026-06-02: re-visioned automation-first ([[00-overview]] "Guiding principle")._

> [!info] Automation-first stance
> **What flows with no human:** all three gates run **automatically** inside the existing validation step and **auto-PASS** when the controls hold — a Stream-I invoice within 3WM tolerance, with in-range amount history and unchanged vendor bank details, validates to `Validated` and keeps advancing untouched. Stream R is records-only: the heavy gates self-resolve to `Not Applicable` / informational and **never block** (the money already moved). The gates add **no** false pause to the happy path (AC-08-21).
> **The single escalation seam:** a human is pulled in only when a control **actually FAILS on Stream I** — a 3WM Exception, an `Anomalous` amount, or a detected bank-detail change — each of which appends an issue, forces `Blocked`, and routes to review ([[09-confidence-routing]]/[[10-ap-review-observability]]). A passing control is silent.
> **Automation to grow into:** today 3WM matches at **PO level** (header PO + the maintained `received_qty`/`billed_amt` rollups). The growth target is **per-line 3-way match** off `capture.line_items`' per-line `po_reference` ([[04-extraction-confidence-line-items]]) — it auto-clears more invoices by matching each line to its own PO line instead of failing a multi-PO or partial invoice that a PO-level check can't resolve, pushing more documents through with no human. Per [[00-overview]] "Automation-first doctrine" row 08.

## 1. Summary
This spec adds three new server-side validation gates to the AP capture pipeline — **three-way match** (invoice ↔ Purchase Order ↔ received-qty), **amount-anomaly detection** (per-supplier rolling-average / sigma), and a **vendor bank-detail change detector** (social-engineering-fraud defence) — and wires them into the single existing validation entry point so any failure routes the capture to the review queue. It implements **workflow-v2-plan.md Step 7** for **both** streams but the heavy gates are **Stream I only**: receipts (Stream R) skip 3WM / anomaly-block / bank-change-block because the money already moved and there is nothing to authorize. Current-state delta: today the only validation gate is `validate_for_purchase_invoice` (`ap_invoice_capture.py:1020`), which checks **supplier match + mandatory fields only** — there is **no** totals-consistency, anomaly, three-way-match, or bank-change check anywhere in the fork; all three detectors and the daily baseline scheduler are net-new.

## 2. Plan alignment

**workflow-v2-plan.md Step 7 (quoted):**

> "The system runs the full validation suite: required fields present, totals consistent with line items, vendor active, expense account valid, entity assigned, duplicate check confirmed, vendor bank details unchanged since last payment. An **amount-anomaly check** flags any invoice where the total significantly exceeds this supplier's recent history (default rule: > 3x the rolling 6-month average for the same supplier, or > 2 standard deviations if there's enough history). … For unpaid vendor bills with a referenced PO, a three-way match is run against the Purchase Order and Goods Receipt — invoices that don't match the PO within tolerance are flagged. PO-less / two-way matching is acceptable for small environments but is an explicit policy choice, not a default."

**Upstream-control note (quoted):**

> "The strongest lever for shrinking step 9 is upstream: a **Purchase Order pre-approves the receipt of a future invoice** … when the invoice arrives, the three-way match (step 7) reconciles invoice against PO and goods receipt *before* the outbound payment is made, and most of the questions a step-9 reviewer would otherwise have to chase are already answered by the PO record. … Whether to make the PO loop in-scope for v1 is an explicit policy decision per client."

**Control-Summary rows this spec implements (quoted):**

| Control | Where it lives | Why it matters |
|---|---|---|
| Three-way match (where PO exists) | Step 7 | Prevents overpayment and duplicate billing |
| Amount-anomaly check (per-supplier rolling avg) | Step 7 | Catches typo'd amounts, double-billing, fraudulent invoices |
| Vendor bank-detail change workflow | Step 7 | Defends against social-engineering fraud |
| PO-as-upstream-control (optional, per-client policy) | Step 7 + upstream | Pre-authorizes payables; collapses most step-9 questions |

**Stream R vs Stream I divergence here (explicit):**

- **Stream I (Invoice, unpaid payable):** all three gates fire. 3WM runs when a PO reference exists; an Exception, an `Anomalous` flag, OR a detected bank change appends an issue and forces `validation_status = Blocked` + `action_required = 1`, routing to the review queue ([[09-confidence-routing]] / [[10-ap-review-observability]]). The bank-change gate hard-**blocks promotion** until an Approved `Supplier Master Change Request` of type `Update Bank Details` ([[05-supplier-resolution]]) approved by a non-AP user ([[11-approval-sod-workflow]]) exists.
- **Stream R (Receipt, already-paid card/cash):** the three heavy gates are **short-circuited**. A receipt still gets dedupe ([[03-deduplication]]) + the **existing** mandatory-field / supplier validation, but 3WM is `Not Applicable` (receipts have no PO), the anomaly result is **recorded but never blocking** (informational only — it cannot hold up the 72h SimpleFIN reconciliation SLA), and a detected bank change is recorded as a warning but does **not** block (the GL impact already happened on the card). No approval-gating applies to Stream R at all.

Where there is no `stream` tag yet (the field is introduced by [[02-intake-stream-tagging]], not shipped today), this spec's fallback is **treat the capture as Stream I** (the stricter path) so no gate is silently skipped — see §5.4 and Open Decision D7.

## 3. Current state

What ships today on branch `russ/migrateToV16`, verified against the code (not memory):

- **One validation gate, supplier + mandatory only.** `validate_for_purchase_invoice(capture, actor=None, source=None, save=True)` at `ap_invoice_capture.py:1020-1102` (whitelisted thin wrapper `validate_for_purchase_invoice_for(capture, source=None)` at `:1677-1683`). It: (a) requires `status == STATUS_CONFIRMED`, else raises `CaptureValidationError` (`:1041-1047`); (b) matches the supplier via `_match_supplier` (`:975-1002`, exact-name then unique `supplier_name`, **never** auto-creates) and writes `capture.matched_supplier` / `capture.supplier_match_status` (`:1051-1052`); (c) classifies the purchase reference via `_classify_purchase_reference` (`:1005-1017` — a PR reference dominates a PO reference, both absent ⇒ `Non-PO / Not Applicable`); (d) checks `MANDATORY_HEADER_FIELDS` presence (`:1061-1064`); (e) writes the audit quintet `validated_by` / `validated_at` / `validation_source` (`:1079-1081`) and sets `validation_status` ∈ {`Validated`, `Blocked`} + `validation_result` text + `action_required` / `action_required_reason` (`:1083-1098`). **There is NO totals-consistency, vendor-active, expense-account-valid, duplicate, anomaly, 3WM, or bank-change check today** — those are the spec-08 additions. The `issues: list[str]` accumulator at `:1059` is the existing seam each new gate appends to.

- **Status / literal constants** at `ap_invoice_capture.py:36-91`: `STATUS_CONFIRMED = "Confirmed"` (`:41`); `SUPPLIER_MATCH_*` = Not Validated / Matched / Unknown / Ambiguous (`:48-51`); `PURCHASE_REF_*` (`:53-56`); `VALIDATION_STATUS_*` = Not Validated / Validated / Blocked (`:58-60`); `VALIDATION_SOURCE_DEFAULT = "ap-validation-v1"` (`:65`). Spec 08 adds `THREE_WAY_MATCH_*`, `ANOMALY_*`, and bank-change constants alongside these.

- **Capture is no longer strictly header-only — [[04-extraction-confidence-line-items]] adds a line table.** The shipped JSON has 76 fields and **zero** child tables today, but spec 04 (a hard dependency of this one) adds an `AP Invoice Capture Item` child table referenced by a new parent `line_items` Table field, with **per-line `po_reference` / `pr_reference`** columns — and spec 04 **explicitly defers per-line PO matching to this spec** (spec 04 §5, risk 3). This is the key data-model input for 3WM: when `capture.line_items` is populated, each row already carries the PO reference; spec 08 does **not** need its own line table (this retires the Option-A/Option-B dilemma from the brief — see §5.1 and Open Decision D5). Today's auto-typed fields block (`:153-235`) shows `matched_supplier: DF.Link`, `purchase_order_reference: DF.Link` (`:195`), `purchase_receipt_reference: DF.Link` (`:196`), `purchase_reference_status: DF.Literal[...]` (`:197-202`), `validation_status: DF.Literal[...]` (`:203`), `validation_result: DF.SmallText` (`:204`), and the decision audit fields `decision_by` / `decision_at` / `decision_notes` (`:221-223`) the 3WM-override path reuses.

- **`AP Closed Loop Settings` (Single) already exists** at `erpnext/accounts/doctype/ap_closed_loop_settings/ap_closed_loop_settings.json` with promote/OCR fields (`default_company`, `default_expense_account`, `default_cost_center`, `ocr_provider`, `ocr_confidence_threshold = 0.70`, `ocr_max_file_mb = 25`, …) — but **no** `qty_tolerance_pct` / `amount_tolerance_pct` / anomaly fields. [[01-foundations-settings-async-idempotency]] reserves a collapsible `anomaly_section` placeholder on this Single for spec 08 to fill (foundations §5.1-A). Spec 08 **extends this existing Single** (it does not create a competing `AP Settings`) and **fills the reserved `anomaly_section`** plus a new tolerance section. The established getter pattern is `frappe.db.get_singles_dict("AP Closed Loop Settings")` + manual text coercion (`ap_closed_loop_settings.py:99,120`) — **mandatory** for all new getters (foundations §3 correction).

- **`AP Supplier Coding Profile` is owned by [[06-gl-coding-tax-costcenter]], not net-new here.** The research brief assumed this doctype did not exist anywhere — **correction:** [[06-gl-coding-tax-costcenter]] §5.1.1 introduces it (`autoname: field:supplier`, `unique:1` on `supplier`, carrying `default_expense_account` / `default_cost_center` / tax / terms). Spec 08 therefore **EXTENDS the spec-06 profile** with optional per-supplier tolerance/anomaly override fields (§5.1) rather than creating a parallel doctype, which avoids the double-definition risk the brief flagged (risk 6).

- **Audit-evidence precedent.** `build_closure_evidence(capture)` at `:1523-1631` aggregates per-stage state into a dict with a `validation` block (`:1590-1598`) reading `validation_status` / `validation_result` / `matched_supplier` / `purchase_reference_status` / `validated_by` / `validated_at` / `source`. Spec 08 gate outcomes (3WM / anomaly / bank-change status + result) are added to this dict under a new `gates` block for the [[14-closure-audit-retention]] audit trail (§5.5).

- **Cascade.** `_determine_next_step()` (`:321-366`) is a pure state machine returning `(method, reason)`; validation is "Step 2" of the ladder (`:339-343`, runs after Confirmed OCR). The gates live **inside** `validate_for_purchase_invoice`, so the ladder is untouched — only the existing validation step gets heavier (§5.4).

- **No `stream` field exists anywhere in the fork today** (confirmed by grep — see [[05-supplier-resolution]] §3, [[06-gl-coding-tax-costcenter]] §3). Spec 08 reads it if present and falls back to Stream I if absent (§5.4, D7).

- **`pandas` 2.3.3 / `numpy` 2.4.6 are present in the bench venv** (verified). The anomaly math adds **no** new dependency.

## 4. Upstream grounding

Mandatory grounding evidence. Each framework / ERPNext surface this spec touches is anchored here and inline in §5 where a specific signature is asserted. Per CLAUDE.md, where the manual is thin on field-level detail the in-repo source is the source of truth and is cited path:line.

| # | URL | What it confirms | Quoted signature / section |
|---|-----|------------------|----------------------------|
| C1 | https://docs.frappe.io/erpnext/user/manual/en/purchase-order | PO line items carry **Quantity and Rate**; the More-Information section exposes status, **% received** and **% billed** (`per_received` / `per_billed`) — grounds the 3WM read of qty/rate and the received/billed roll-up the match compares against. **(verified)** | "3.4 The Items table … 'Quantity and Rate' … 'Received Qty' will be updated when the items are billed. … 3.11 More Information … shows the status of the Purchase Order, percentage of items received, and percentage of items billed." |
| C2 | https://docs.frappe.io/erpnext/user/manual/en/purchase-receipt | A submitted Purchase Receipt updates the **Pending Quantity** on the linked Purchase Order (the `received_qty` roll-up 3WM reconciles). Manual is silent on billing tolerance — for `over_billing_allowance` the in-repo `Accounts Settings` JSON + `status_updater.py` are source of truth (cited below). **(verified — fetched 2026-05-30)** | "The 'Pending Quantity' is updated in the Purchase Order." (No mention of billing tolerance / over-billing — confirmed absent on the page.) |
| C3 | https://github.com/frappe/frappe/blob/version-15/frappe/core/doctype/version/version.json | `Version` doctype fields used by the bank-change detector: `ref_doctype` (Link → DocType), `docname` (Data), `data` (Code, **hidden**, holds the change diff). `track_changes` on the watched doctypes is what writes Version rows. **(verified)** | `{"fieldname": "ref_doctype", "fieldtype": "Link", "options": "DocType"}` ; `{"fieldname": "docname", "fieldtype": "Data"}` ; `{"fieldname": "data", "fieldtype": "Code", "hidden": 1}` |
| C4 | https://docs.frappe.io/framework/v15/user/en/api/database | Query APIs the detectors rely on: `frappe.db.get_all` (aliased to `frappe.get_all`), `frappe.db.get_value`, `frappe.db.count`. `pluck` / `limit` / `as_dict` appear in usage examples, not the formal signature line — build phase must confirm them against the installed frappe. **(verified — fetched 2026-05-30)** | "frappe.db.get_all(doctype, filters, or_filters, fields, order_by, group_by, start, page_length, run)" — "Also aliased to frappe.get_all". "frappe.db.get_value(doctype, name, fieldname)" / "frappe.db.get_value(doctype, filters, fieldname)". "frappe.db.count(doctype, filters)". |
| C5 | https://docs.frappe.io/framework/v15/user/en/python-api/hooks | `scheduler_events` cadences for wiring the daily `refresh_anomaly_baselines` job; in this fork the `daily_maintenance` list at `hooks.py:464-482` is the precedent slot (cf. `…supplier_scorecard.refresh_scorecards` at `hooks.py:471`). **(verified — reused from [[01-foundations-settings-async-idempotency]] §4 citation 2)** | `scheduler_events = {"daily": ["app.scheduled_tasks.manage_recurring_invoices"], "cron": {"15 18 * * *": ["app.scheduled_tasks.delete_all_barcodes_for_users"]}}` |
| C6 | In-repo source (manual is silent — CLAUDE.md "read source when docs are vague") | (a) **3WM join keys are already indexed** — no new index needed: `purchase_invoice_item.po_detail` (Data) and `.purchase_order` (Link) are `search_index: 1` (`erpnext/accounts/doctype/purchase_invoice_item/purchase_invoice_item.json`); `purchase_receipt_item.purchase_order` (Link) and `.purchase_order_item` (Data) are `search_index: 1` (`erpnext/stock/doctype/purchase_receipt_item/purchase_receipt_item.json`). (b) **PO Item maintains the rollup** — `purchase_order_item` carries `received_qty` (Float) and `billed_amt` (Currency), maintained by ERPNext's status updater (`erpnext/buying/doctype/purchase_order.py:547` target_field, `:653` `received_qty += min(item.received_qty, item.qty)`). (c) **`po_detail` is the verified join key** — used at `purchase_invoice.py:230-231` (join_field), `:406` (ref_dn_field), and `controllers/buying_controller.py:919-920`. (d) **Over-billing tolerance** lives in `Accounts Settings.over_billing_allowance` (Currency, label "Over Billing Allowance (%)") + per-`Item.over_billing_allowance` / `Item.over_delivery_receipt_allowance`, resolved in `erpnext/controllers/status_updater.py:757-779`. | Verified by reading the local JSON / source on this bench (erpnext 16.x, frappe 16.18.3). |
| C7 | In-repo source — **three-doctype bank model** (manual silent; the most important correction to the brief) | The **Supplier** doctype (`track_changes = 1`) carries **only** `default_bank_account` (Link → Bank Account) — it has **no** `bank_name` / `bank_account_no` / `iban` / `swift` fields. Real bank detail lives on `Bank Account` (`track_changes = 1`, not submittable): `iban`, `bank_account_no`, `account_name`, `branch_code`, `bank` (Link → Bank), `mask`; and on `Bank` (`track_changes = 1`): `bank_name`, `swift_number`. **All three doctypes have `track_changes = 1`**, so Version rows exist for each. `Payment Entry` carries `party_type` (Link DocType) / `party` (Dynamic Link) / `posting_date` / `party_bank_account` (Link → Bank Account) for the "since last payment" anchor. **The three-doctype bank-change watch set described here was VERIFIED against source** (Supplier carries only `default_bank_account`; real bank fields live on `Bank Account`/`Bank`), so the `Version`-watch targets in §5.3-3 are correct (ties to [[05-supplier-resolution]]'s bank-details fix). | Verified by reading `supplier.json`, `bank_account.json`, `bank.json`, `payment_entry.json` on this bench. |
| C8 | In-repo source — **ERPNext ALREADY enforces three-way / over-billing on PI submit** (the native-vs-custom correction to the brief's 3WM framing) | A submitted Purchase Invoice is natively validated against its PO/PR: (a) `validate_multiple_billing(self, "Purchase Order"/"Purchase Receipt", "amount")` blocks over-billing beyond `over_billing_allowance` — `erpnext/controllers/accounts_controller.py:2141`; (b) `validate_line_items` enforces "Maintain same rate throughout the purchase cycle" (invoice rate must match the PO/PR rate) — `accounts_controller.py:849`; (c) the per-`Item` / global `over_billing_allowance` (`accounts_settings.json:215`, `item.json`) is resolved via `get_allowance_for(...)` — `erpnext/controllers/status_updater.py:728`. These raise on **submit**, with native escape roles `role_allowed_to_over_bill` / `role_to_override_stop_action`. So the **post-promotion** match is native; the custom layer's real value is the **pre-promotion** gate (no PI exists yet) + AP tolerances **stricter** than the ERP-wide allowance. | Verified by reading `accounts_controller.py`, `status_updater.py`, `accounts_settings.json`, `item.json` on this bench (erpnext 16.x). |

**Version note:** this branch is `russ/migrateToV16` (`frappe >=16,<17`). Grounding cites v15 docs/source per CLAUDE.md priority and because v16 docs are sparse. The query-API kwargs (`pluck`, `limit`, `as_dict`), the `Version` schema, and the PO/PR/PI field names are stable v15→v16, but the build phase MUST re-verify `frappe.get_all` / `frappe.db.get_value` / `Version` query semantics against the installed frappe (`bench console`; read the local `frappe/core/doctype/version/version.json` and `frappe/utils/data.py`) before finalizing (Open Decision D9 / Risks).

## 5. Design

### 5.1 Data model

#### (A) EXTEND `AP Closed Loop Settings` (`issingle: 1`) — fill the reserved `anomaly_section` + add a tolerance section

All persist as TEXT in `tabSingles`; every new getter coerces exactly like `get_ocr_config` does (`ap_closed_loop_settings.py:124-147`). Defaults set in JSON **and** backfilled by foundations' install step. Insert into `field_order` inside the existing `anomaly_section` placeholder ([[01-foundations-settings-async-idempotency]] §5.1-A) and a new tolerance section.

New section: **`three_way_match_section`** (Section Break, `collapsible: 1`, label "Three-Way Match Tolerance"):

| fieldname | fieldtype | options / default | purpose |
|---|---|---|---|
| `three_way_match_section` | Section Break | `collapsible: 1`, label "Three-Way Match Tolerance" | group |
| `qty_tolerance_pct` | Float | default `0` (strict) | Max allowed % over-receipt/over-bill on qty before a line is an Exception. `0` = exact match required. |
| `amount_tolerance_pct` | Float | default `0` (strict) | Max allowed % over-PO on rate/amount before a line is an Exception. `0` = exact match required. |
| `respect_over_billing_allowance` | Check | default `0` | When `1`, the effective amount tolerance is `max(amount_tolerance_pct, Accounts Settings.over_billing_allowance)` so 3WM never blocks something ERPNext itself would allow to over-bill. Default off → AP tolerance is **independent and stricter** (resolves brief risk 4 / Open Decision D2). |
| `require_po_for_invoices` | Check | default `0` | PO-upstream-control policy switch (per-client). When `1`, a **Stream I** invoice with **no** PO reference is itself a 3WM Exception. Default off leaves PO-less / two-way as an allowed explicit policy choice. |

Fill **`anomaly_section`** (Section Break already reserved by foundations, `collapsible: 1`, label "Anomaly Detection"):

| fieldname | fieldtype | options / default | purpose |
|---|---|---|---|
| `anomaly_lookback_months` | Int | default `6` | Rolling window of submitted PI history per supplier. |
| `anomaly_multiple` | Float | default `3.0` | "> N× rolling average" rule (the `> 3x` plan default). |
| `anomaly_sigma` | Float | default `2.0` | "> N standard deviations from mean" rule (plan says 2–3σ; recommend 2.0). |
| `anomaly_min_sample` | Int | default `5` | Minimum prior submitted PIs before the rule can fire; below this ⇒ `Insufficient History` (record, never block). |

Permissions: **unchanged** (System Manager rw / Accounts Manager rw / Accounts User read) — all config.

#### (B) EXTEND `AP Supplier Coding Profile` (owned by [[06-gl-coding-tax-costcenter]]; ADD optional override fields)

Add the following **nullable** fields to the spec-06 profile (one row per Supplier, `autoname: field:supplier`). Null = "no override, fall through to settings".

| fieldname | fieldtype | options / default | purpose |
|---|---|---|---|
| `qty_tolerance_pct` | Float | default empty (null) | Per-supplier override of the qty tolerance; null ⇒ use settings. |
| `amount_tolerance_pct` | Float | default empty (null) | Per-supplier override of the amount tolerance; null ⇒ use settings. |
| `anomaly_multiple` | Float | default empty (null) | Per-supplier override of the anomaly multiple (e.g. a high-variance vendor). |
| `anomaly_sigma` | Float | default empty (null) | Per-supplier override of the sigma threshold. |
| `anomaly_min_sample` | Int | default empty (null) | Per-supplier override of the minimum sample. |

**Tolerance/anomaly resolution order** (the "registry resolution" case the test bar requires): per-supplier `AP Supplier Coding Profile` field (if non-null) → `AP Closed Loop Settings` field → (amount only, when `respect_over_billing_allowance=1`) `Accounts Settings.over_billing_allowance` → hard default `0` (tolerance) / the documented anomaly defaults. The **no-profile / unknown-supplier** path falls straight through to settings — explicitly tested.

#### (C) NEW capture header fields (`ap_invoice_capture.json` + auto-typed DF block ~`:153-235`)

Mirror the existing `validation_status` / `validation_result` / `validated_by` / `validated_at` / `validation_source` quintet style so each gate's audit trail is uniform and `build_closure_evidence` can serialize them.

Three-way match:

| fieldname | fieldtype | options / default | purpose |
|---|---|---|---|
| `three_way_match_status` | Select (DF.Literal) | `Not Checked` \| `Not Applicable` \| `Matched` \| `Exception` \| `Matched (Override)`; default `Not Checked` | gate outcome |
| `three_way_match_result` | Long Text | JSON per-line diff (see §5.3-1) | machine + human evidence |
| `three_way_match_checked_at` | Datetime | — | when 3WM last ran |
| `three_way_match_override_by` | Link | → User | clerk who overrode an Exception (reuses the decision-audit pattern; **dedicated** fields so an override here doesn't clobber the approval-decision quintet at `:221-223` — Open Decision D6) |
| `three_way_match_override_at` | Datetime | — | when overridden |
| `three_way_match_override_notes` | Small Text | — | override rationale |

Amount anomaly:

| fieldname | fieldtype | options / default | purpose |
|---|---|---|---|
| `anomaly_status` | Select (DF.Literal) | `Not Checked` \| `Normal` \| `Anomalous` \| `Insufficient History`; default `Not Checked` | gate outcome |
| `anomaly_result` | Small Text | human blurb, e.g. `Total 18,400 vs 6-mo mean 5,200 ± 700, z=18.9` | evidence |
| `anomaly_checked_at` | Datetime | — | when anomaly last ran |

Vendor bank change:

| fieldname | fieldtype | options / default | purpose |
|---|---|---|---|
| `vendor_bank_change_detected` | Check | default `0` | `1` ⇒ a watched bank field changed since the last submitted PE |
| `vendor_bank_change_result` | Small Text | which record/field changed + when | evidence |
| `vendor_bank_change_checked_at` | Datetime | — | when the detector last ran |

Permissions on the capture are unchanged (these are server-written audit fields; not in any role's write set beyond the existing capture permissions).

#### (D) NEW cache DocType — `AP Supplier Anomaly Baseline` (non-Single, one row per Supplier)

Caches the per-supplier mean/stddev so the per-capture anomaly check is O(1) instead of re-querying 6 months of PIs every time. `autoname: field:supplier`, `track_changes: 0` (it *is* a derived cache; versioning is noise), module Accounts, `is_submittable: 0`.

| fieldname | fieldtype | options / flags | purpose |
|---|---|---|---|
| `supplier` | Link | → Supplier, `reqd: 1`, `unique: 1` | the vendor this baseline is for (UNIQUE so the docname == supplier and a duplicate insert raises) |
| `sample_count` | Int | — | number of submitted PIs in the window |
| `mean_grand_total` | Float | — | rolling mean of `grand_total` over the window |
| `stddev_grand_total` | Float | — | rolling population stddev over the window |
| `window_months` | Int | — | the lookback used (audit; lets a stale baseline be detected) |
| `computed_at` | Datetime | — | when the baseline was last refreshed |

Permissions: System Manager rw; Accounts Manager read; Accounts User read; `Auditor (Read Only)` (new role, bible) read. Rows are written server-side (`ignore_permissions=True`) by the scheduler / on-submit hook only. **Open Decision D3**: this dedicated cache DocType vs a JSON field vs native `frappe.cache()` (Redis) — keep the DocType **only if** baselines must be queryable/reportable (then a clean UNIQUE-on-supplier guarantee is the payoff); if it is **purely** a perf cache, prefer `frappe.cache()` to avoid a migrate-affecting schema add (see D3).

### 5.2 Endpoints

Mirror the established `*_for` whitelisted-wrapper convention (internal pure function takes a doc-or-name + `save` flag; public `@frappe.whitelist()` wrapper takes `capture: str`, normalizes args, calls the pure function, and resumes the cascade with `_kick_next_step()` — cf. `validate_for_purchase_invoice_for` at `:1677-1683`). All public wrappers return `str` (the capture name) for UI symmetry.

```python
# --- internal pure functions (module-level, ap_invoice_capture.py) ---

def three_way_match_for(
    capture: "APInvoiceCapture | str",
    save: bool = True,
) -> "APInvoiceCapture":
    """Run three-way match (invoice <-> PO <-> received_qty) for a Stream-I
    capture with a PO reference. Writes three_way_match_status / _result /
    _checked_at. Stream R or no-PO -> 'Not Applicable'. Never raises on a
    mismatch (a mismatch is an Exception STATUS, surfaced via validation)."""

def detect_amount_anomaly_for(
    capture: "APInvoiceCapture | str",
    save: bool = True,
) -> "APInvoiceCapture":
    """Compare grand_total against the supplier's rolling mean/stddev baseline.
    Writes anomaly_status / anomaly_result / anomaly_checked_at. n < min_sample
    -> 'Insufficient History' (recorded, never blocking)."""

def detect_vendor_bank_change_for(
    capture: "APInvoiceCapture | str",
    save: bool = True,
) -> "APInvoiceCapture":
    """Query Version rows for the supplier's Bank Account / Bank / default_bank_account
    changes since the last submitted Payment Entry. Sets vendor_bank_change_detected
    + _result + _checked_at. Block-on-Stream-I is enforced at promotion, not here."""

def override_three_way_match(
    capture: "APInvoiceCapture | str",
    notes: str,
    actor: str | None = None,
    save: bool = True,
) -> "APInvoiceCapture":
    """Clerk override of a 3WM Exception -> 'Matched (Override)' + audit fields.
    Raises CaptureValidationError if current status is not 'Exception'."""

# --- whitelisted wrappers ---

@frappe.whitelist()
def three_way_match_for_capture(capture: str) -> str: ...

@frappe.whitelist()
def detect_amount_anomaly_for_capture(capture: str) -> str: ...

@frappe.whitelist()
def detect_vendor_bank_change_for_capture(capture: str) -> str: ...

@frappe.whitelist()
def override_three_way_match_for(capture: str, notes: str) -> str:
    # frappe.only_for("Accounts User") / "AP Clerk" gate; normalize notes; resume cascade
    ...
```

Scheduler entry point (not whitelisted; invoked by `scheduler_events`):

```python
def refresh_anomaly_baselines() -> None:
    """Daily: recompute AP Supplier Anomaly Baseline for every supplier with
    >=1 submitted PI in the window. Bounded per-supplier; idempotent."""
```

**Normalization convention:** each internal function normalizes at the top with `if isinstance(capture, str): capture = frappe.get_doc("AP Invoice Capture", capture)` (matches `:1038-1039`). The whitelisted wrappers receive `capture` as a **str name**.

### 5.3 Logic

#### (1) `three_way_match_for(capture, save=True)`

**Native-vs-custom split (read first).** ERPNext **already enforces** 3WM / over-billing on PI **submit** (C8): `validate_multiple_billing` (over-billing vs `over_billing_allowance`, `accounts_controller.py:2141`) + `validate_line_items` ("Maintain same rate throughout purchase cycle", `accounts_controller.py:849`) + the per-Item/global `over_billing_allowance` (`accounts_settings.json:215`, `item.json`) resolved via `get_allowance_for` (`status_updater.py:728`). So this custom gate is split by **promotion phase**:
- **PRE-promotion (genuinely net-new — no native equivalent):** there is no Purchase Invoice yet, so nothing native fires. The custom `three_way_match_for` runs off `capture.line_items` per-line `po_reference` (spec 04) + the header `purchase_order_reference`, computing the per-line qty/rate diff itself. **This is where the real added value lives** — a blocking gate *before* the PI exists, plus AP-team tolerances (`qty_tolerance_pct`/`amount_tolerance_pct`) that can be **STRICTER** than the ERP-wide `over_billing_allowance`.
- **POST-promotion (a submitted PI exists):** do **NOT** re-derive the per-line qty/amount diff that ERPNext already computes. Instead **SURFACE the native exceptions** — catch what `validate_multiple_billing` / `validate_line_items` throw on submit, honour the native escape roles `role_allowed_to_over_bill` / `role_to_override_stop_action`, and map the caught native error into `three_way_match_status = "Exception"` + `three_way_match_result`. The custom post-promotion job is *exception surfacing*, not re-computation.

(D5 governs which phase runs when; the recommendation below is to keep the custom compute for the pre-promotion case and lean on native enforcement post-promotion.)

1. **Normalize** capture (doc-or-name). **Stream gate:** resolve the stream (§5.4); if **Stream R** → set `three_way_match_status = "Not Applicable"`, write `three_way_match_result = "{}"`, `three_way_match_checked_at = now`, save, return. (No PO on receipts.)
2. **PO-presence gate:** determine the PO line set. Source order:
   a. If `capture.line_items` rows exist (from [[04-extraction-confidence-line-items]]) and any carries a `po_reference`, use the per-line PO references.
   b. Else fall back to the header `capture.purchase_order_reference` (single PO).
   c. If **neither** yields a PO reference: if `settings.require_po_for_invoices` is **off** → `three_way_match_status = "Not Applicable"` (two-way is the allowed policy); if **on** → `three_way_match_status = "Exception"` with result `{"reason": "PO required by policy but none referenced"}`. Save, return.
3. **Resolve tolerances** (per-supplier profile → settings → over_billing_allowance(if opted) → 0) via a helper `_resolve_tolerances(capture)` returning `(qty_tol_pct, amount_tol_pct)`.
4. **Read PO line authority.** For each referenced PO Item (`Purchase Order Item.name`), read `qty`, `rate`, `received_qty`, `billed_amt` **directly off the PO item** — `received_qty` and `billed_amt` are the ERPNext-maintained rollups (`purchase_order.py:547,653`; verified C6). This is simpler and authoritative versus re-summing PR lines. *Per-invoice vs PO-cumulative* note: `received_qty` reflects **all** receipts against the PO line, not only the slice this invoice covers — **Open Decision D1** (recommend PO-cumulative for phase-1: "is there at least `invoiced_qty` received against this PO line", which is the standard guard against billing for goods not yet received).
5. **Compute the invoiced quantities/rates — pre-promotion only.** When **no PI exists yet** (the pre-promotion gate), use `capture.line_items` qty/rate; else (header-only fallback) treat the whole invoice as one line at qty = 1, rate = `final_total_amount` against the single header PO. **When the capture is already promoted, do NOT re-sum the PI's `po_detail` lines here** — ERPNext's own `validate_multiple_billing` / `validate_line_items` already enforced the qty/rate match on submit (C8); the post-promotion job instead **surfaces** any native exception (catch-and-map per the split note above) rather than re-deriving the diff. (This is why 3WM differs **pre- vs post-promotion** — see §5.4 / D5.)
6. **Per-line comparison.** For each PO line:
   - `qty_diff_pct = (invoiced_qty - received_qty) / received_qty * 100` (guard `received_qty == 0`).
   - `amount_diff_pct = (invoiced_rate - po_rate) / po_rate * 100` (guard `po_rate == 0`).
   - `within_tolerance = (qty_diff_pct <= qty_tol_pct) and (amount_diff_pct <= amount_tol_pct)`. (Over-receipt / over-bill is the failure direction; being **under** is fine.)
7. **Aggregate.** `three_way_match_status = "Matched"` if **every** line is within tolerance, else `"Exception"`.
8. **Persist** `three_way_match_result` as a JSON list of per-line dicts `{po_item, ordered_qty, received_qty, billed_amt, ordered_rate, invoiced_qty, invoiced_rate, qty_diff_pct, amount_diff_pct, within_tolerance}`, set `three_way_match_checked_at = now`. **No new index** is created — the join keys (`po_detail`, `purchase_order_item`) are already `search_index: 1` (C6). `save` if requested. **Never raises** on a mismatch — the Exception is a *status*, surfaced by the validation wiring (§5.4-5).

#### (2) `detect_amount_anomaly_for(capture, save=True)`

1. **Normalize.** If `matched_supplier` is empty → `anomaly_status = "Insufficient History"` (cannot key a baseline), result "No matched supplier", save, return.
2. **Read the baseline.** Prefer the cached `AP Supplier Anomaly Baseline` row for `matched_supplier` (O(1)). If absent or stale (`computed_at` older than today's run window) → compute inline: `frappe.get_all("Purchase Invoice", filters={"supplier": matched_supplier, "docstatus": 1, "posting_date": [">=", add_months(today(), -lookback_months)]}, pluck="grand_total")` (C4 query API). Resolve `lookback_months` / `multiple` / `sigma` / `min_sample` via the per-supplier-profile → settings chain (§5.1-B).
3. **Sample-size guard.** `n = len(totals)`. If `n < anomaly_min_sample` → `anomaly_status = "Insufficient History"`, `anomaly_result = f"n={n} < min {anomaly_min_sample}"`. **Record, do NOT block.** Save, return.
4. **Compute** `mean` and population `stddev` with `numpy` (`numpy.mean` / `numpy.std`; pandas available too — verified present). `total = flt(capture.final_total_amount)`.
5. **Rule.** `is_anomalous = (total > anomaly_multiple * mean) OR (stddev > 0 and abs(total - mean) > anomaly_sigma * stddev)`. Set `anomaly_status = "Anomalous"` or `"Normal"`.
6. **Persist** `anomaly_result` as a human blurb, e.g. `f"Total {total:,.0f} vs {lookback_months}-mo mean {mean:,.0f} ± {stddev:,.0f}, z={ (total-mean)/stddev if stddev else 0 :.1f}"`, `anomaly_checked_at = now`. `save`. **Never raises.**

`refresh_anomaly_baselines()` (daily scheduler): iterate suppliers with ≥1 submitted PI in the window (a single grouped query — **not** a full-table scan; bounded per-supplier, mirroring `refresh_scorecards` at `hooks.py:471` / `supplier_scorecard.py:183`); recompute mean/stddev/count and **upsert** the `AP Supplier Anomaly Baseline` row (idempotent — re-running yields identical rows). **Cache invalidation:** also recompute (or mark stale) the affected supplier's baseline on **Purchase Invoice `on_submit`** via a `doc_events` hook so a brand-new PI is reflected before the next daily run (Open Decision D4: on-submit recompute vs mark-stale-and-lazy-recompute — recommend mark-stale + lazy recompute in `detect_amount_anomaly_for` step 2 to keep `on_submit` cheap).

#### (3) `detect_vendor_bank_change_for(capture, save=True)` — the corrected **three-doctype** model (C7)

**Verified correct (C7):** the three-doctype watch set below — `Bank Account` fields (`iban`/`bank_account_no`/`branch_code`) + `Bank.swift_number`/`bank_name` + a re-pointed `Supplier.default_bank_account` — was VERIFIED against source: Supplier carries **only** `default_bank_account`; the real bank fields live on `Bank Account`/`Bank`. So these `Version`-watch targets are correct (ties to [[05-supplier-resolution]]'s bank-details fix). No change needed to the watch set.

1. **Normalize.** If `matched_supplier` is empty → `vendor_bank_change_detected = 0`, result "No matched supplier", save, return.
2. **Anchor "since last payment".** `last_pe = frappe.get_all("Payment Entry", filters={"party_type": "Supplier", "party": matched_supplier, "docstatus": 1}, fields=["name", "posting_date"], order_by="posting_date desc", limit=1)`. If **no** prior PE → **no baseline**: set `vendor_bank_change_detected = 0` and record `vendor_bank_change_result = "No prior payment — bank-change baseline not established (soft)"`. **Do NOT false-block a first-ever payment** (Open Decision D8 — recommend soft-skip; first payment is gated by normal approval, not by this detector).
3. **Resolve the watched records** (C7): `default_bank_account = frappe.db.get_value("Supplier", matched_supplier, "default_bank_account")`; if set, `bank = frappe.db.get_value("Bank Account", default_bank_account, "bank")`. The watch set is:
   - `("Bank Account", default_bank_account)` — watch fields `iban`, `bank_account_no`, `branch_code`.
   - `("Bank", bank)` — watch fields `swift_number`, `bank_name`.
   - `("Supplier", matched_supplier)` — watch field `default_bank_account` itself being **re-pointed** to a different account.
4. **Query Version.** For each `(ref_doctype, docname)` in the watch set, `frappe.get_all("Version", filters={"ref_doctype": ref_doctype, "docname": docname, "creation": [">", last_pe.posting_date]}, fields=["name", "data", "creation"])`. Parse each row's `data` (Code JSON, C3) for a `changed` entry touching a watched fieldname. (Build phase: confirm the v16 Version `data` JSON shape via `bench console` — D9; the diff structure is `{"changed": [[fieldname, old, new], ...], ...}`.)
5. **Outcome.** If any watched field changed after `last_pe.posting_date` → `vendor_bank_change_detected = 1`, `vendor_bank_change_result = f"{ref_doctype}.{field} changed {when}"`. Else `0`. `vendor_bank_change_checked_at = now`. `save`. **Never raises.**
6. **Block enforcement** is **not** in this function — it is applied (a) by the validation wiring (§5.4-5: a detected change appends an issue ⇒ `Blocked`), and (b) by a **promotion precondition** added to `promote_to_purchase_invoice` (`:1148`): if `vendor_bank_change_detected == 1` **and** the capture is **Stream I**, raise `CapturePromotionError` **unless** an Approved `Supplier Master Change Request` exists keyed by `(target_supplier == matched_supplier, change_type == "Update Bank Details", workflow_state == "Approved"/"Posted")` whose `decision_by` is a **non-AP** user (SoD — interface owned by [[05-supplier-resolution]] for the request doctype and [[11-approval-sod-workflow]] for the non-AP-approver rule). The interface this spec **expects**: a helper `has_approved_bank_change(supplier) -> bool` exported by spec 05/11 (§9); until it lands, spec 08 defines a local stub that returns `False` (so the block holds) and is replaced when 05/11 ship.

#### (4) `override_three_way_match(capture, notes, actor=None, save=True)`

1. `frappe.only_for(("Accounts User", "AP Clerk"))` (the override is a clerk decision; "AP Clerk" is a new role, bible).
2. Guard: if `three_way_match_status != "Exception"` → raise `CaptureValidationError("Only a 3WM Exception can be overridden")`.
3. Set `three_way_match_status = "Matched (Override)"`, `three_way_match_override_by = actor or frappe.session.user`, `three_way_match_override_at = now`, `three_way_match_override_notes = notes` (notes **required** — empty ⇒ raise). `save`. Re-run validation (§5.4) so the capture can leave `Blocked` if 3WM was the only issue.

#### (5) Wiring into `validate_for_purchase_invoice` (`:1020`)

After the existing supplier / purchase-ref / mandatory-field checks (`:1049-1077`) and before writing the audit quintet (`:1079`):

1. Resolve the stream (§5.4).
2. **If Stream I** (or fallback): call `three_way_match_for(capture, save=False)`, `detect_amount_anomaly_for(capture, save=False)`, `detect_vendor_bank_change_for(capture, save=False)` in sequence (each mutates the capture in memory; the single `capture.save()` at `:1100-1101` persists all of them — keeps the write atomic).
   - If `three_way_match_status == "Exception"` → `issues.append(_("Three-way match exception: {0}").format(<short summary>))`.
   - If `anomaly_status == "Anomalous"` → `issues.append(_("Amount anomaly: {0}").format(capture.anomaly_result))`. (`Insufficient History` does **NOT** append an issue — non-blocking.)
   - If `vendor_bank_change_detected == 1` → `issues.append(_("Vendor bank details changed since last payment — approved Update-Bank-Details request required"))`.
3. **If Stream R:** still run `three_way_match_for` (it self-resolves to `Not Applicable`) and `detect_amount_anomaly_for` (recorded, informational) for the audit trail, but **append NO issue** from any of the three — receipts are not approval-gated. `detect_vendor_bank_change_for` may run for the record but never appends an issue on Stream R.
4. The existing `if issues:` branch (`:1083-1089`) already forces `validation_status = Blocked` + `action_required = 1`; no change there. Each appended issue is what routes the capture to the review queue ([[09-confidence-routing]] / [[10-ap-review-observability]]).

**Idempotency:** every gate is a pure recompute over current state (no document creation), so re-running validation is naturally idempotent — no [[01-foundations-settings-async-idempotency]] `with_idempotency` key is needed for the gates themselves. The **bank-change-block lift** depends on an external Approved request, also idempotent.

### 5.4 Cascade & stream-awareness

- **Slots into `_determine_next_step`:** **unchanged.** The gates live *inside* the existing "Step 2" validation call (`:339-343`); the pure state machine still returns `("validate_for_purchase_invoice_for", …)` and the if-ladder is untouched. The validation step just does more work and can land in `Blocked` (which it already could).
- **Pause vs auto-advance:** a `Blocked` capture sets `action_required = 1` and does **not** match any later branch of `_determine_next_step`, so the cascade naturally **pauses** at review — exactly as a supplier-Unknown block does today. A clerk fixing the field (or overriding 3WM, or an Approved bank-change request landing) and re-running validation flips it to `Validated` and the cascade resumes.
- **Stream resolution (the fallback contract):** a helper `_resolve_stream(capture) -> str` returns `capture.get("stream")` if the field exists and is set, else `"I"` (stricter path — never silently skip a gate). When [[02-intake-stream-tagging]] ships the `stream` field, this helper reads it with no other change here (Open Decision D7).
- **Stream R vs Stream I divergence:** Stream I runs all three gates as blocking; Stream R runs them informationally (3WM = `Not Applicable`, anomaly recorded-not-blocking, bank-change recorded-not-blocking) and appends no issue. The **promotion block** (§5.3-3 step 6) is **Stream I only**.

### 5.5 Cross-cutting

- **Permissions / SoD:** the bank-change block's lift requires an Approved `Supplier Master Change Request` approved by a **non-AP** user — the SoD rule and the approver role (`Treasury Approver`, new) are owned by [[11-approval-sod-workflow]]; the request doctype + `change_type = "Update Bank Details"` is owned by [[05-supplier-resolution]]. Spec 08 only **consumes** the `has_approved_bank_change(supplier)` interface (§9). The 3WM override is gated by `frappe.only_for(("Accounts User", "AP Clerk"))`.
- **Idempotency ([[01-foundations-settings-async-idempotency]]):** the gates create no documents, so they need no idempotency key; the promotion guard they add reuses promote's existing `promotion_status` guard. No new `AP Posting Ledger` rows.
- **Async / enqueue ([[01-foundations-settings-async-idempotency]]):** the three detectors run **synchronously inside** the already-enqueued validation step (the existing cascade enqueues `validate_for_purchase_invoice_for` on the `short` queue via `async_runner.enqueue_step`). `refresh_anomaly_baselines` is its **own** daily scheduler job (a `daily_maintenance` entry at `hooks.py:464`, following the `refresh_scorecards` precedent).
- **Observability ([[10-ap-review-observability]]):** each blocking gate's issue text carries a root-cause-mappable phrase (`three-way match exception`, `amount anomaly`, `vendor bank … changed`) so spec 10's reviewer can tag `missing_po` / `policy_violation` / `vendor_error`. The PO-upstream-control savings (`require_po_for_invoices`) are **instrumented by spec 10**, not here.
- **Audit ([[14-closure-audit-retention]]):** `build_closure_evidence` (`:1523`) gains a `gates` block serializing `three_way_match_status` / `_result`, `anomaly_status` / `_result`, `vendor_bank_change_detected` / `_result`, plus the 3WM-override audit fields — so the full control record is in the closure evidence.

## 6. Acceptance criteria

- **AC-08-1** (positive, 3WM Matched): a Stream-I capture whose invoiced qty + rate are within tolerance of the PO line's `received_qty` / `rate` ⇒ `three_way_match_status == "Matched"`, every per-line `within_tolerance` is True, validation **not** Blocked on 3WM.
- **AC-08-2** (negative, 3WM Exception — qty): invoiced qty exceeds `received_qty` beyond `qty_tolerance_pct` ⇒ `"Exception"`, an issue is appended, `validation_status == "Blocked"`, `action_required == 1`.
- **AC-08-3** (negative, 3WM Exception — rate): invoiced rate over PO rate beyond `amount_tolerance_pct` ⇒ `"Exception"` + Blocked.
- **AC-08-4** (edge, strict boundary): with both tolerances `0`, an exact match passes (`Matched`) and a 1-cent / 1-unit over fails (`Exception`).
- **AC-08-5** (edge, per-supplier override widens): an `AP Supplier Coding Profile` with a higher `amount_tolerance_pct` flips an otherwise-Exception case to `Matched` (resolution-order: profile beats settings).
- **AC-08-6** (edge, no-profile fallback): a supplier with **no** profile uses the settings tolerance (the unknown-key fallback path).
- **AC-08-7** (positive, override): `override_three_way_match` on an `Exception` ⇒ `"Matched (Override)"` with `three_way_match_override_by` / `_at` / `_notes` set; empty notes ⇒ `CaptureValidationError`; non-Exception status ⇒ `CaptureValidationError`.
- **AC-08-8** (edge, not-applicable): a capture with **no** PO reference and `require_po_for_invoices` off ⇒ `"Not Applicable"`, no block; a **Stream R** capture ⇒ `"Not Applicable"`, no block.
- **AC-08-9** (edge, PO-required policy): with `require_po_for_invoices` **on**, a Stream-I capture with no PO ⇒ `"Exception"` + Blocked.
- **AC-08-10** (positive, anomaly Normal): `grand_total` within `anomaly_multiple × mean` and within `anomaly_sigma × stddev` ⇒ `"Normal"`, not Blocked.
- **AC-08-11** (negative, anomaly Anomalous): `total = 18400` against a 6-month mean ≈ 5200 (n ≥ 5) ⇒ `"Anomalous"`, `anomaly_result` populated, issue appended, Blocked (Stream I).
- **AC-08-12** (edge, insufficient history): `n < anomaly_min_sample` (default 5) submitted PIs ⇒ `"Insufficient History"`, and the capture is **NOT** Blocked on this alone.
- **AC-08-13** (edge, empty history): a brand-new supplier with **zero** prior PIs ⇒ `"Insufficient History"`, not Blocked.
- **AC-08-14** (positive, baseline cache): `refresh_anomaly_baselines` writes an `AP Supplier Anomaly Baseline` row whose `mean_grand_total` / `stddev_grand_total` equal a direct recompute; a second run is idempotent (same values, one row).
- **AC-08-15** (positive, bank-change none): bank detail unchanged since the last submitted PE ⇒ `vendor_bank_change_detected == 0`, not Blocked, promotion allowed.
- **AC-08-16** (negative, bank-change detected): mutating `Bank Account.iban` (or `Bank.swift_number`, or re-pointing `Supplier.default_bank_account`) **after** a submitted PE writes a Version row and ⇒ `vendor_bank_change_detected == 1`, issue appended, Blocked; **`promote_to_purchase_invoice` raises `CapturePromotionError`** while no Approved Update-Bank-Details request exists.
- **AC-08-17** (edge, no prior PE): a supplier with **no** prior submitted PE ⇒ `vendor_bank_change_detected == 0` (soft-skip, no false block).
- **AC-08-18** (SoD cross-check): an Update-Bank-Details `Supplier Master Change Request` approved by an **AP** user does **NOT** lift the promotion block (the lift requires a non-AP approver — interface owned by [[11-approval-sod-workflow]]).
- **AC-08-19** (Stream R short-circuit): a **Stream R** capture skips all three blocking gates — `three_way_match_status == "Not Applicable"`, anomaly recorded but **no** issue appended, bank-change (if any) **no** issue appended — and still validates on mandatory + supplier only.
- **AC-08-20** (integration, audit): `build_closure_evidence` includes the new `gates` block with the 3WM / anomaly / bank-change outcomes.
- **AC-08-21** (regression): the full existing `test_ap_invoice_capture.py` suite passes unchanged — a Stream-I capture with no PO / sufficient-but-normal history / unchanged bank detail validates to `Validated` exactly as today (the gates add no false blocks to existing happy-path tests).

## 7. Tests

### 7.1 Automated
Use `from frappe.tests import IntegrationTestCase`; roll back DB writes in `tearDown` so suites are reentrant (follow the existing pattern — the file already imports `IntegrationTestCase` and the capture constants). Co-locate new cases in **`erpnext/accounts/doctype/ap_invoice_capture/test_ap_invoice_capture.py`**. Run: `bench --site <site> run-tests --module erpnext.accounts.doctype.ap_invoice_capture.test_ap_invoice_capture`. Baseline-cache tests for the new DocType may also live in a sibling module `erpnext.accounts.doctype.ap_supplier_anomaly_baseline.test_ap_supplier_anomaly_baseline`.

- **`three_way_match_for`** — positive Matched (AC-08-1); negative qty Exception (AC-08-2) and rate Exception (AC-08-3); strict-boundary edge (AC-08-4); per-supplier-profile override widens tolerance → flips to Matched (AC-08-5); no-profile settings fallback (AC-08-6); Not-Applicable for no-PO + Stream R (AC-08-8); PO-required policy Exception (AC-08-9). Tolerance resolution coverage bar (CLAUDE.md registry rule): one test per resolution source — profile present, settings fallback, `over_billing_allowance` (when opted), hard-default 0 — **and** the no-profile/unknown-supplier fallback.
- **`override_three_way_match`** — positive override sets status + audit (AC-08-7 positive); empty-notes raise and non-Exception raise (AC-08-7 negatives).
- **`detect_amount_anomaly_for`** — Normal (AC-08-10); Anomalous with the 18,400-vs-5,200 fixture (AC-08-11); Insufficient History when n<5, asserting **not** Blocked (AC-08-12); empty history (AC-08-13); baseline-cache O(1) read equals recompute + idempotent re-run (AC-08-14).
- **`detect_vendor_bank_change_for`** — no-change positive (AC-08-15); changed `Bank Account.iban` / `Bank.swift_number` / re-pointed `Supplier.default_bank_account` after a submitted PE, asserting a Version row was written and detection fires + promotion blocked (AC-08-16); no-prior-PE soft-skip (AC-08-17); SoD — AP-user-approved request does not lift the block (AC-08-18).
- **Wiring / integration** — `validate_for_purchase_invoice` end-to-end: a capture with a 3WM Exception OR anomaly OR bank-change ends `Blocked` with `action_required == 1` and the reason text contains the gate issue; a **Stream R** capture skips all three and still validates on mandatory + supplier (AC-08-19); `build_closure_evidence` includes the `gates` block (AC-08-20); full-suite regression green (AC-08-21).

### 7.2 Clean-room test plan
Ship **`test/testplans/three-way-match-anomaly-bank-change.md`** (one file, kebab-case). Scope: clean-room verification of the three gates and the bank-change promotion block, end to end against a fresh bench. Self-contained per CLAUDE.md: feature-under-test paragraph; branch `russ/migrateToV16` + commit SHA; env setup (bench app + `bench new-site` / `bench --site … install-app erpnext` commands, pandas/numpy already in the venv, **no external API key needed** for these gates); test-data prerequisites (a Supplier with a linked Bank Account + Bank; a submitted Purchase Order with a received Purchase Receipt; 5+ submitted historical Purchase Invoices to seed the anomaly baseline; a submitted Payment Entry to anchor the "since last payment" bank-change check; an Update-Bank-Details `Supplier Master Change Request` for the SoD lift); numbered positive / negative / edge cases with exact whitelisted-method payloads + expected DB state (the DB is the source of truth — assert `three_way_match_status` / `anomaly_status` / `vendor_bank_change_detected` via `bench … mariadb`) + pass/fail criteria; cleanup/rollback; and a pass/fail checklist template (one row per case).

### 7.3 UI testing (Playwright MCP)
Browser-driven verification of the desk UI this slice adds, via the **Playwright MCP** server. These are the UI steps of the §7.2 clean-room runbook.
- **Prereq:** Playwright MCP per `test/testplans/BROWSER-TESTING-SETUP.md` (`claude mcp list` must list `playwright`; restart after registering). `.mcp.json` / `.playwright-mcp/` gitignored.
- **Evidence:** screenshots to `test/testplans/screenshots/three-way-match-anomaly-bank-change/<name>.png` (committed; pass as `filename`).
- **Source of truth stays the DB:** after every UI write, verify via `bench --site <site> mariadb` / `bench … execute`, then delete UI-created data.

**Scenarios** (`route → action → expected UI → DB assertion`):
- A capture whose lines exceed the linked PO beyond tolerance → the form shows `three_way_match_status = Exception` + the `three_way_match_result` diff and is blocked from promotion; screenshot → DB-assert the status/result. Then click the clerk override action → `Matched (Override)` with the decision audit; screenshot → DB-assert override fields.
- An anomalous-amount capture (vs the supplier's 6-mo history) → `anomaly_status = Anomalous` + reason shown, routed to review; screenshot → DB-assert.
- A vendor-bank-change capture → blocked with the bank-change warning until an approved change exists; screenshot → DB-assert `vendor_bank_change_detected`.

**Not browser-testable in this slice** (covered by §7.1/§7.2): the pandas anomaly math, the Version-diff bank-change query, the daily baseline scheduler (§7.1).

## 8. Open decisions

- **D1 — 3WM granularity: per-invoice-line vs PO-cumulative (HIGH).** PO Item `received_qty` is the maintained rollup of **all** receipts, not just this invoice's slice. **Options:** (a) PO-cumulative guard ("≥ invoiced_qty received against this PO line"); (b) per-invoice-line reconciliation using PR-line summation filtered to this invoice. **Recommended default: (a)** for phase-1 — it is the standard "don't bill for goods not yet received" control and reads the authoritative rollup with no extra queries. **Owner:** spec 08 author + accounting. **Lock:** before `three_way_match_for` step 4/6 is built. *(Automation-first growth target, 2026-06-02: phase-1 ships the PO-level/cumulative guard (a); the **planned** automation-first extension is full **per-line** 3WM (b) off `capture.line_items`' per-line `po_reference` ([[04-extraction-confidence-line-items]]) — it auto-clears invoices a PO-level check can't (multi-PO invoices, partial billing across lines) by matching each line to its own PO line, advancing more documents with no human. See the stance callout + [[00-overview]] "Automation-first doctrine" row 08. Phase-1 default (a) kept.)*
- **D2 — Respect `Accounts Settings.over_billing_allowance`? (MEDIUM).** **Options:** (a) AP tolerance independent and stricter (`respect_over_billing_allowance` default **off**); (b) always fold in ERPNext's allowance so 3WM never blocks something ERPNext would permit. **Recommended default: (a)** — AP control should be able to be stricter than the ERP-wide over-bill setting; the Check lets a client opt into (b). **Owner:** spec 08 author. **Lock:** before the tolerance resolver is built.
- **D3 — Anomaly baseline cache: dedicated DocType vs JSON field vs `frappe.cache()` (MEDIUM).** **Options:** (a) dedicated `AP Supplier Anomaly Baseline` DocType (queryable, UNIQUE-on-supplier, cheap upsert — but a migrate-affecting schema add); (b) a JSON field on an existing record; (c) **native `frappe.cache()` (Redis)** keyed by supplier — the right choice **IF the baseline is PURELY a performance cache** (no migrate cost, no schema, evicts/recomputes transparently). **Recommended default:** keep the **dedicated DocType ONLY if baselines must be queryable/reportable** (e.g. for observability — a report of which suppliers have stale/high-variance baselines, or feeding [[10-ap-review-observability]]); **otherwise use `frappe.cache()`** to avoid adding a migrate-affecting DocType for what is just a derived perf cache. Decide on the queryability requirement first, then pick. **Owner:** spec 08 author. **Lock:** before the cache is created.
- **D4 — Baseline freshness on new PI: on-submit recompute vs mark-stale + lazy (MEDIUM).** **Recommended default: mark-stale on `Purchase Invoice.on_submit`, lazy-recompute inside `detect_amount_anomaly_for`** (keeps `on_submit` cheap; the daily job catches the rest). **Owner:** spec 08 author. **Lock:** before the `doc_events` hook is wired.
- **D5 — 3WM pre- vs post-promotion ordering + native-vs-custom division (HIGH).** Blocking 3WM must run **before** promotion (no PI exists yet — nothing native fires), but ERPNext **already** enforces the qty/rate match on PI **submit** via `validate_multiple_billing` (`accounts_controller.py:2141`) + `validate_line_items` (`accounts_controller.py:849`) resolved through `over_billing_allowance` / `get_allowance_for` (`status_updater.py:728`, C8). **Options:** (a) **RESERVE the custom `three_way_match_for` for the PRE-promotion gate** (computed off `capture.line_items` per-line `po_reference` + header `purchase_order_reference`, where no native equivalent exists) AND for the POST-promotion case **SURFACE the native exceptions** — catch what `validate_multiple_billing` / `validate_line_items` throw on submit, honour the native escape roles `role_allowed_to_over_bill` / `role_to_override_stop_action`, and map them into `three_way_match_status` — rather than re-deriving the per-line diff ERPNext already computes; (b) run only post-promotion and block at the *approval* gate instead of promotion; (c) re-derive the per-line `po_detail` diff post-promotion in custom code (duplicates native enforcement — **not recommended**). **Recommended default: (a).** The custom layer's **real added value = the pre-promotion blocking gate (genuinely net-new) + AP-team tolerances STRICTER than the ERP-wide `over_billing_allowance`**; post-promotion it should defer to (and surface) native enforcement, not duplicate it. **Owner:** spec 08 + [[07-classification-doctype-branching]] (ordering). **Lock:** before wiring into `validate_for_purchase_invoice`.
- **D6 — 3WM-override audit fields: reuse `decision_*` vs dedicated (LOW).** **Recommended default: dedicated `three_way_match_override_*` fields** so an override never clobbers the approval-decision quintet (`:221-223`). **Owner:** spec 08 author. **Lock:** before the capture JSON is edited.
- **D7 — Stream fallback when `stream` field is absent (HIGH).** **Recommended default: treat as Stream I** (stricter — never silently skip a gate) until [[02-intake-stream-tagging]] ships the field. **Owner:** spec 08 + spec 02. **Lock:** at build time; revisit when spec 02 lands.
- **D8 — Bank-change with no prior PE (MEDIUM).** **Options:** (a) soft-skip (no false block); (b) hard-flag the first-ever payment. **Recommended default: (a)** — a first payment is already gated by normal approval; blocking it on a non-existent baseline is a false positive. **Owner:** spec 08 author + controls reviewer. **Lock:** before `detect_vendor_bank_change_for` step 2.
- **D9 — Version `data` JSON shape + query-API kwargs on v16 (MEDIUM).** The v15 docs show `frappe.get_all` / `frappe.db.get_value` but `pluck` / `limit` / `as_dict` are only in examples; the Version diff `data` structure must be confirmed on the installed frappe (16.18.3). **Recommended default: re-inspect via `bench console` + read local `version.json` / `frappe/utils/data.py` before finalizing** (citation source stays v15 per CLAUDE.md). **Owner:** spec 08 author. **Lock:** before the bank-change detector is merged.
- **D10 — `has_approved_bank_change(supplier)` interface ownership (MEDIUM).** Spec 08 needs a helper that confirms an Approved, non-AP-approved Update-Bank-Details request exists. **Options:** (a) spec 05 (request doctype) exports it; (b) spec 11 (SoD/approver-role rule) exports it; (c) spec 08 defines a local stub returning `False` until 05/11 land. **Recommended default: (c) interim stub → (a)+(b) provide the real impl** (05 keys the request, 11 enforces non-AP approver). **Owner:** spec 08 + 05 + 11. **Lock:** before the promotion block is testable end-to-end.

## 9. Dependencies & sequencing

- **Depends on (must land first or define a documented stub):**
  - [[01-foundations-settings-async-idempotency]] — the `anomaly_section` placeholder on `AP Closed Loop Settings`, the Singles getter/coercion pattern, the `async_runner` the validation step is enqueued through, and the daily scheduler conventions. **Sequence after 01.**
  - [[04-extraction-confidence-line-items]] — supplies `capture.line_items` rows with per-line `po_reference`/`pr_reference` (the 3WM input); spec 04 explicitly defers per-line PO matching here. Without it, 3WM falls back to the header PO + single-line (still functional, coarser).
  - [[06-gl-coding-tax-costcenter]] — owns `AP Supplier Coding Profile`; spec 08 **extends** it with tolerance/anomaly overrides (coordinate the field additions in one DocType JSON, not a parallel doctype).
  - [[05-supplier-resolution]] — owns `Supplier Master Change Request` (`change_type = "Update Bank Details"`), the vehicle that lifts the bank-change block.
  - [[11-approval-sod-workflow]] — owns the non-AP-approver SoD rule and `Treasury Approver` role; provides the real `has_approved_bank_change` enforcement. Until 05/11 land, spec 08 ships a local stub returning `False` (block holds).
  - [[02-intake-stream-tagging]] — owns the `stream` field; spec 08 only **reads** it and falls back to Stream I if absent (D7).
- **Unblocks / feeds:**
  - [[09-confidence-routing]] / [[10-ap-review-observability]] — consume the `Blocked` status + issue text and the per-gate outcomes for review-queue routing and root-cause tagging; the `require_po_for_invoices` savings are instrumented by spec 10.
  - [[14-closure-audit-retention]] — `build_closure_evidence`'s new `gates` block is serialized into the audit trail.
- **Estimated size:** **L** (per IMPLEMENTATION-PLAN units). Three new detector functions + one override function + their whitelisted wrappers, a Settings extension (~9 fields, 1 new + 1 filled section), a coding-profile extension (5 fields), ~12 new capture header fields, one new cache DocType (`AP Supplier Anomaly Baseline`), a daily scheduler job + `on_submit` invalidation, a promotion-block precondition, the validation-wiring change, the `build_closure_evidence` extension, the automated-test additions, and one clean-room test plan.
