---
spec: 14-closure-audit-retention
title: Closure & Audit Trail (dual-signal closure, TB drift, 7-year retention)
plan_step: Step 13 — Closure & Audit Trail
stream: both
status: Draft
depends_on: [01-foundations-settings-async-idempotency, 13-bank-feed-reconciliation, 07-classification-doctype-branching]
related: [00-overview, 08-validation-gates, 10-ap-review-observability, 11-approval-sod-workflow, 12-payment-execution, 05-supplier-resolution]
---

# 14 — Closure & Audit Trail (dual-signal closure, TB drift, 7-year retention)
> _Revised 2026-05-31: applied native-vs-custom review findings._

## 1. Summary
This spec closes the loop. It (a) upgrades the closure signal from single (PI Paid + PE submitted) to **dual** — `settled` plus `bank_cleared` — by reading the Bank Transaction match landed by [[13-bank-feed-reconciliation]]; (b) adds **single-record audit retrieval** (`build_audit_trail_for`) that assembles the live closure evidence + a Frappe-`Version` field-level history block + a validation-gates summary + a bank-match block into one composite dict and renders it to one PDF via an `AP Audit Trail` Print Format; (c) ships an **`Accounts Payable Trial Balance Drift`** report comparing current Creditors / Credit-Card-Clearing balances to the prior-period `Account Closing Balance` snapshot; and (d) installs a **flag-only 7-year retention scheduler** (IRS — never deletes). It is stream-agnostic in structure, but `closure_basis` differs by stream: Stream R closes on the bank-match of the Journal Entry, Stream I on the bank-match of the Payment Entry. **Current-state delta:** today closure is single-signal and `closure_basis` asserts "Bank Transaction count must remain 0" — this spec rewrites that to require a Bank Transaction for the bank-cleared leg.

## 2. Plan alignment

**workflow-v2-plan.md Step 13 (quoted, lines 93–94):**
> "The invoice, payment, GL entries, and bank-transaction match are linked and the transaction is closed. Trial-balance reconciliation runs against the prior period to detect any drift. Frappe's built-in Version doctype captures field-level history across the entire lifecycle, and attachments are retained for 7 years per IRS requirements. From this point the full audit chain — image, extraction, validation, approval, payment, bank-match, posting — is retrievable from a single record."

**Control-Summary rows (lines 139–140):**
> "| Bank-feed match for closure | Step 12 | External confirmation of money movement |"
> "| 7-year audit retention | Step 13 | IRS requirement |"

**Key-design-principle (line 108):**
> "Closure comes from outside. 'Mock payment issued' or 'payment entry submitted' is internal confirmation. The transaction is not closed until the bank feed confirms the money moved."

**Stream R vs Stream I divergence here:**
- **Structure is stream-agnostic** — the audit-trail payload, the Version-history block, the gates block, the TB-drift report, the retention scheduler, and the Print Format are identical for both streams.
- **`closure_basis` and the bank-match resolution differ:** Stream R's disbursing voucher is a **Journal Entry** (DR expense / CR card-clearing), so it clears on the JE's Bank Transaction match. Stream I's disbursing voucher is a **Payment Entry**, so it clears on the PE's Bank Transaction match. The plan principle "closure comes from outside" applies to **both** streams — neither is closed until the bank feed confirms.
- v1 of this spec implements the **Stream I (PE) path fully** and stubs the Stream R (JE) path behind a `stream` discriminator + `journal_entry` Link that do not yet exist on the capture (owned by [[07-classification-doctype-branching]] / [[02-intake-stream-tagging]]). See §3 correction and §8 D-14-3.

## 3. Current state

What ships today on `russ/migrateToV16` @ `51ef0f7554` that this builds on or replaces:

1. **`build_closure_evidence(capture)`** — `erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.py:1523-1631`. Accepts a capture name or doc; returns one dict with blocks `capture`, `ocr` (`proposal{}`/`final{}`), `validation`, `approval`, `payment`, `native` (`purchase_invoice`, `payment_entry`, `gl_entries[]`, `gl_entry_count`, `bank_transaction_count`), plus top-level `closed` (bool) and `closure_basis` (str). **This is the single-record seed for `build_audit_trail_for`, but it has NO `history` block (Version), NO `gates` block, and NO `bank_match` block today.**

2. **Current `closure_basis` (quote, `ap_invoice_capture.py:1626-1630`):**
   > "Closed is derived from native ERPNext state: submitted Purchase Invoice, submitted Payment Entry, Purchase Invoice outstanding_amount=0, and status Paid. No custom closed flag is stored; Bank Transaction count must remain 0."
   The final clause **conflicts with dual-signal closure** — bank-cleared closure *requires* a Bank Transaction. This string and the assertions at `test_ap_invoice_capture.py:1208` (`bank_transaction_count == 0`) and `:1210` ("No custom closed flag") must be rewritten in the same PR.

3. **`closed` derivation** (`ap_invoice_capture.py:1551-1558`) and **`_derive_payment_lifecycle_status`** (`ap_invoice_capture.py:1402-1423`) are **single-signal**: `closed == (PI docstatus 1 AND PE docstatus 1 AND PI outstanding == 0 AND PI status == 'Paid')`. No bank-clearing leg.

4. **`payment_lifecycle_status` field options** (`ap_invoice_capture.json:577-581`) are exactly `"Not Requested\nConfirmed\nClosed\nBlocked"` (default `Not Requested`, `read_only`, `in_standard_filter`). Constants `PAYMENT_LIFECYCLE_*` at `ap_invoice_capture.py:88-91`; `PAYMENT_LIFECYCLE_CLOSED == "Closed"`.

5. **`_bank_transaction_count_for_payment_entry(payment_entry)`** (`ap_invoice_capture.py:1393-1399`) counts rows in child table `Bank Transaction Payments` where `payment_document='Payment Entry'` and `payment_entry=<pe>`. **This is the only existing hook into bank reconciliation.** It returns a count, not the parent Bank Transaction — it must be generalized to resolve the parent BT name and to accept `Journal Entry` as `payment_document`.

6. **Whitelisted entrypoints** (`@frappe.whitelist()`): `build_closure_evidence_for(capture)` at `ap_invoice_capture.py:1748`; `get_ap_lifecycle_rows_for()` at `:1753`; `get_manager_approval_queue_for()` at `:1758`. `build_audit_trail_for` will be a sibling of `build_closure_evidence_for`.

7. **Walking-skeleton twin** — `erpnext/accounts/ap_closed_loop/walking_skeleton.py` defines `ClosureEvidence` (lines 100-121, fields include `bank_transaction_count: int = 0`, `closed`, `closure_basis`) and `build_closure_evidence(...)` (~lines 285-339) with the same single-signal logic and analogous `closure_basis` string (lines 310-315). Its tests assert the old string at `test_walking_skeleton.py:78-79` (`"docstatus=1"` and `"No custom closed flag"`). Keep in sync or document the divergence.

**Net-new (confirmed absent — grep across `erpnext/` found zero AP-scoped hits):** no `build_audit_trail` / `build_audit_trail_for`; no `AP Audit Trail` Print Format; no `Accounts Payable Trial Balance Drift` report (existing TB reports are `trial_balance`, `consolidated_trial_balance`, `trial_balance_for_party`, `trial_balance_simple` under `erpnext/accounts/report/`); no `archive_pending` field; no **keep-forever** 7-year retention scheduler.

**Correction to §3 (native retention DOES exist — but it is the wrong direction).** The earlier framing "no retention scheduler" is imprecise. Frappe ships a **native, scheduler-driven retention engine: `Log Settings`** (`apps/frappe/frappe/core/doctype/log_settings/log_settings.py`), run daily via `run_log_clean_up()` (registered under `daily_maintenance` at `apps/frappe/frappe/hooks.py:270`). It iterates each configured `logs_to_clear` entry and calls `controller.clear_old_logs(days)` for any DocType implementing the `LogType` protocol (`log_settings.py:15-19`, gated by `_supports_log_clearing` → `issubclass(controller, LogType)` at `:23-26`). The honest answer to *"is there native retention?"* is therefore **"yes — but it DELETES rows older than N days,"** which is the **exact opposite** of IRS 7-year keep-forever retention. It is consequently **UNUSABLE here**, which is precisely why this spec's **flag-only, never-delete** scheduler (§5.3-8) is justified rather than redundant. (The only AP-scoped "retention" hit is the unrelated MCP pruner `erpnext/mcp/tasks.py`, registered at `hooks.py:461` — also delete-oriented.) See §4 row C-13.

**Vendored upstream primitives present and callable:** `Account Closing Balance` doctype (`erpnext/accounts/doctype/account_closing_balance/`) with `get_previous_closing_entries(company, closing_date, accounting_dimensions)` at `account_closing_balance.py:119-153` — finds the latest submitted Period Closing Voucher with `period_end_date < closing_date` and `frappe.qb`-selects its Account Closing Balance rows. **This is the exact mechanism the TB-drift report reuses.**

**Corrections to the brief, after reading the code:**
- **Brief item D (track_changes on linked docs) — VERIFIED, all four covered.** I confirmed `track_changes: 1` on **Purchase Invoice, Payment Entry, Journal Entry, AND Bank Transaction** (all four JSONs). The brief flagged this as conditional/unverified ("MUST verify… otherwise those history sub-blocks are silently empty"). It resolves favorably: field-level history is available for every linked voucher type. The spec promises history coverage for all four — see §4 citation and §8 D-14-5 (which is therefore downgraded to a confirmation, not a risk).
- **Brief item C settings home — confirmed.** `AP Closed Loop Settings` (`erpnext/accounts/doctype/ap_closed_loop_settings/ap_closed_loop_settings.json`) currently carries `promote_defaults` + an `ocr_section` only; it is the correct home for the three new config values. No competing `AP Settings` exists.
- **`AP Posting Ledger` / idempotency keys** (brief references [[01-foundations-settings-async-idempotency]]) do not exist in the fork yet — the retention scheduler's idempotency in v1 is a self-guard (skip already-flagged) rather than a ledger key; see §5.5.

## 4. Upstream grounding

The grounded research brief returned an **empty `upstream_citations` array** (verified=false for all seeds). Per the authoring rule, the canonical seed URLs are cited below **without fabricated quotes**; every framework-surface assertion is instead grounded against the **vendored in-repo JSON/source** (the source of truth that ships, per CLAUDE.md priority 3), cited as `path:line`. The doc-page gaps (notably the v15 Print Format page, which 404'd on multiple candidate paths during research) are called out so the build phase re-verifies against the v16 sources actually installed in bench.

| # | Source (canonical URL / in-repo path) | What it confirms | Verified signature/section |
|---|---|---|---|
| C-1 | `erpnext/accounts/doctype/account_closing_balance/account_closing_balance.py:119-153` (in-repo) | The canonical prior-period snapshot fetch. `get_previous_closing_entries(company, closing_date, accounting_dimensions)` selects the latest submitted Period Closing Voucher with `period_end_date < closing_date` and `frappe.qb`-selects its Account Closing Balance rows. | `frappe.db.get_all("Period Closing Voucher", filters={"docstatus":1,"company":company,"period_end_date":("<",closing_date)}, ... order_by="period_end_date desc", limit=1)` then `frappe.qb.from_(account_closing_balance).select(... debit, credit, account, account_currency, cost_center ...)`. |
| C-2 | `erpnext/accounts/report/financial_statements.py:455-474` (in-repo) | Proof that `Account Closing Balance` is the canonical snapshot source the standard financial reports already read from (same PCV-lookback pattern), validating reuse for TB-drift. | `get_accounting_entries("Account Closing Balance", from_date, to_date, filters, ...)` guarded by the same `Period Closing Voucher … period_end_date ("<", filters["period_start_date"])` lookup. |
| C-3 | `https://docs.frappe.io/erpnext/user/manual/en/period-closing-voucher` (seed, verified=false) | ERPNext Period Closing Voucher + Account Closing Balance concept (TB-drift prior baseline). No quote — re-verify against installed v16 docs. | (page-level; grounding rests on C-1/C-2 in-repo source). |
| C-4 | `frappe/frappe` core `frappe/core/doctype/version/version.json` (vendored, in bench) | The `Version` doctype field shape for the history block. Fields: `ref_doctype` (Link→DocType, reqd), `docname` (Data, reqd), `data` (Code, hidden), `table_html` (HTML). `track_changes: 1`, `in_create: 1`, `sort_field: creation`, `sort_order: DESC`, `naming_rule: Random`/`autoname: hash`. | Read at `apps/frappe/frappe/core/doctype/version/version.json` lines 16-51, 81. Change payload is `Version.data`. |
| C-5 | `https://github.com/frappe/frappe/blob/version-15/frappe/core/doctype/version/version.json` (seed, verified=false) | Public mirror of C-4. Branch is `version-15`; bench runs v16 — **C-4 (the installed JSON) is authoritative**, this URL is for reference only. | (mirror of C-4). |
| C-6 | `erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.json:669` (in-repo) | `track_changes: 1` on AP Invoice Capture — the capture's own field-level history is automatic. | `"track_changes": 1`. |
| C-7 | `erpnext/accounts/doctype/purchase_invoice/purchase_invoice.json`, `payment_entry.json`, `journal_entry.json`, `bank_transaction.json` (in-repo) | **All four linked voucher types carry `track_changes: 1`** — history coverage for PI/PE/JE/BT is real, not aspirational. | Verified `track_changes: 1` on each of the four DocType JSONs. |
| C-8 | `erpnext/accounts/doctype/bank_transaction_payments/bank_transaction_payments.json` (in-repo) | The bank-match link shape. Child table fields: `payment_document` (Link→DocType), `payment_entry` (Dynamic Link, options=`payment_document`), `allocated_amount` (Currency), `clearance_date` (Date). Parent is Bank Transaction. | The `bank_match` block reads the parent `Bank Transaction` via this child's `parent`. The Dynamic Link `payment_entry` holds the disbursing-voucher name regardless of doctype, so JE rows are addressable for Stream R. |
| C-9 | `erpnext/accounts/doctype/bank_transaction/bank_transaction.json` (in-repo) | Bank Transaction fields available to the bank-match block: `date` (Date), `status` (Select), `bank_account` (Link), `reference_number` (Small Text), `deposit`/`withdrawal`/`allocated_amount` (Currency). **There is NO native `reconciled_by`/`reconciled_at` field, and [[13-bank-feed-reconciliation]] adds none** (its new fields are `bank_transaction`, `bank_cleared`, `bank_cleared_at`). Per **resolved D-14-5**, the block sources `reconciled_by` ← BT `modified_by` and `reconciled_at` ← BT `modified`. | `bank_transaction.json` has no `reconciled_by`/`reconciled_at`; fallback to the framework audit columns `modified_by` / `modified` (always present). **Resolved — no spec-13 dependency.** |
| C-10 | `https://docs.frappe.io/framework/v15/user/en/desk/print-format` (seed, verified=false — **page 404'd in research**) | Print Format mechanism for the single-PDF render. Grounding falls back to the frappe-core Print Format DocType JSON (vendored): `html` = Code (Jinja), `print_format_type` options `Jinja\nJS`, `custom_format` checkbox, `standard`, `doc_type` (Link). The `doc` Jinja var is the server-side render input. | **Doc-page gap noted** — re-verify option strings against the installed v16 Print Format JSON before writing the format. |
| C-11 | `erpnext/hooks.py:433-462` (in-repo) | `scheduler_events` is already extended by the fork — `erpnext.mcp.tasks.prune_audit_logs` is registered under `"daily"` at line 461. The retention job slots into `"daily"` (or `"hourly"`) the same way. | `scheduler_events = { ... "daily": ["erpnext.mcp.tasks.prune_audit_logs"], ... }`. |
| C-12 | `https://docs.frappe.io/framework/v15/user/en/api/document` (`frappe.db.set_value`) and `.../background-jobs` (seed, verified=false) | `frappe.db.set_value` for the flag write and the scheduler background-job convention. No quote — standard framework API; re-verify against installed v16. | (page-level). |
| C-13 | `apps/frappe/frappe/core/doctype/log_settings/log_settings.py` (vendored, in bench) + `apps/frappe/frappe/hooks.py:270` | **Native retention exists but is DELETE-oriented — the opposite of IRS keep-forever, hence unusable here and the custom flag-only scheduler is justified.** `Log Settings` is a scheduler-driven retention engine: `run_log_clean_up()` (registered under `daily_maintenance`, `hooks.py:270`) calls `controller.clear_old_logs(days)` for every DocType implementing the `LogType` protocol. It **purges** rows older than N days; it cannot keep-forever or flag-without-delete. | `class LogType(Protocol): … def clear_old_logs(days: int) -> None` (`log_settings.py:15-19`); `_supports_log_clearing` → `issubclass(controller, LogType)` (`:23-26`); `run_log_clean_up()` (`:112`) iterates `logs_to_clear` and calls `controller.clear_old_logs` (`:91-92`). Direction = **delete**, so unusable for 7-year retention. |

> **CLAUDE.md grounding compliance:** every framework surface this spec touches (the `Version` query, the `Bank Transaction Payments` join, the Print Format mechanism, the `scheduler_events` hook, the report `execute`, `frappe.db.set_value`, `frappe.only_for`) is grounded above against the **vendored in-repo source** (priority-3 per CLAUDE.md) because the priority-1/2 doc pages returned no verified quote. The build-phase implementer MUST re-confirm the v16 signatures (Version.data fieldtype, Account Closing Balance schema, `get_previous_closing_entries` signature, Print Format option strings) against the JSON/source installed in this bench before finalizing — those are the source of truth, not the v15 doc URLs.

## 5. Design

### 5.1 Data model

**No new closure/audit DocType.** `build_audit_trail_for` returns an **in-memory composite dict** assembled on demand from (1) live `build_closure_evidence`, (2) a `Version`-history block, (3) a gates block, (4) a bank-match block. It MUST NOT be persisted — a stored snapshot would drift from live linked-doc state.

**A) Changed field — `payment_lifecycle_status`** (existing Select, `ap_invoice_capture.json:577-581`) — **reconciled with [[13-bank-feed-reconciliation]] (cross-spec consistency).**

> **Vocabulary aligned with spec 13.** An earlier draft of this spec proposed two new terminals `Closed (Settled)` / `Closed (Bank Cleared)`. That **diverged** from [[13-bank-feed-reconciliation]], which adds the single value `Bank Cleared`. To keep specs 13 and 14 in agreement, **do NOT add `Closed (Settled)` / `Closed (Bank Cleared)`.** Instead, keep the existing enum and add **only** `Bank Cleared`, and carry the two closure SIGNALS as derived fields (`settled`, `bank_cleared`), not as extra enum values.

| fieldname | fieldtype | options / default | purpose |
|---|---|---|---|
| `payment_lifecycle_status` | Select | `Not Requested\nConfirmed\nClosed\nBank Cleared\nBlocked` (default `Not Requested`, `read_only`, `in_standard_filter`) | Adds **only** `Bank Cleared` (matching [[13-bank-feed-reconciliation]]). `Closed` is the **settled-state value / back-compat alias** (keeps `PAYMENT_LIFECYCLE_CLOSED == "Closed"`); `Bank Cleared` means `settled AND bank_cleared`. `_derive_payment_lifecycle_status` returns the most-specific applicable value. JSON Select-option add only = **test-exempt** per CLAUDE.md; the derivation change is **not** exempt. |

**A2) Closure-signal fields (derived, not stored as enum values) — shared with [[13-bank-feed-reconciliation]]:**

| field | shape | derivation |
|---|---|---|
| `settled` | bool | submitted Purchase Invoice **+** submitted Payment Entry, PI `outstanding_amount == 0`, PI `status == "Paid"` (existing single-signal logic at `ap_invoice_capture.py:1551-1558`). The state behind the `Closed` enum value. |
| `bank_cleared` | Check, `read_only` (the field [[13-bank-feed-reconciliation]] adds) **/** bool in the evidence dict | set on bank match — the disbursing voucher is matched to a Bank Transaction (`Bank Transaction Payments`). `settled AND bank_cleared` ⇒ `payment_lifecycle_status == "Bank Cleared"`. |

**B) New fields on `AP Invoice Capture` (retention):**

| fieldname | fieldtype | options / default | purpose |
|---|---|---|---|
| `archive_pending` | Check | default `0`, `read_only` | Set by the 7-year retention scheduler. **Flag only — never triggers deletion.** JSON-only add = test-exempt; the scheduler that sets it is not. |
| `archived_flagged_at` | Datetime | `read_only` | Timestamp the scheduler flagged the record (drives idempotency + audit). |

**C) New config on `AP Closed Loop Settings`** (Single, `erpnext/accounts/doctype/ap_closed_loop_settings/`) — new `retention_section` Section Break:

| fieldname | fieldtype | options / default | purpose |
|---|---|---|---|
| `retention_years` | Int | default `7` | IRS retention window for the flagging scheduler. Falls back to 7 if 0/blank. |
| `drift_threshold_cents` | Int | default `100` (= $1.00) | TB-drift report flags rows where `abs(drift)` in cents exceeds this. Cents to avoid FX/rounding false-positives. |
| `ap_notification_role` | Link → Role | default `Accounts Manager` | Role notified when the scheduler flags records for archive. Recommend `AP Clerk` once that role lands ([[11-approval-sod-workflow]]). |

**D) Composite dict — `build_audit_trail_for(capture)` return shape** (in-memory, not stored). Extends the `build_closure_evidence` dict (`ap_invoice_capture.py:1560-1631`) with:

| key | shape | source |
|---|---|---|
| `bank_match` | `{bank_transaction, date, amount, reconciled_by, reconciled_at}` or `None` | `_bank_match_for(payment_doctype, payment_name)` — joins `Bank Transaction Payments` → parent `Bank Transaction` (C-8/C-9). |
| `settled` | bool | existing single-signal logic (PI Paid + PE submitted). |
| `bank_cleared` | bool | `bool(bank_match)`. |
| `closed` | bool | `settled or bank_cleared` (back-compat: still present). |
| `history` | `list[{name, owner, creation, data}]` ordered by `creation asc` | `_audit_history_for(capture)` — `Version` rows for the capture + each linked PI/PE/JE/BT (C-4/C-7). |
| `gates` | `list[{gate, outcome, detail, source}]` | `_audit_gates_for(capture)` — see below. |

**E) `gates[]` block — explicit fidelity gap (state this in the build):** there is **no `AP Review Event`, `Supplier Master Change Request`, or rejection-log DocType in the fork yet** (grep found none — these are owned by [[10-ap-review-observability]], [[05-supplier-resolution]], [[11-approval-sod-workflow]]). So the v1 `gates[]` block is a **best-effort summary derived from existing capture fields + `mock_payment_response` JSON**, not a per-gate event history:

| gate | v1 source (existing) | full source (future spec) |
|---|---|---|
| dedupe | (none yet) → `outcome: "not-instrumented"` | [[03-deduplication]] `STATUS_DUPLICATE` / `duplicate_of` |
| OCR confidence | `ocr_status`; `proposed_missing_fields`/`proposed_ambiguous_fields`; settings `ocr_confidence_threshold` | [[04-extraction-confidence-line-items]] per-field confidence child |
| supplier match | `matched_supplier`, `validation_result` | [[05-supplier-resolution]] alias hit detail |
| three-way match | `purchase_reference_status` | [[08-validation-gates]] three-way result |
| amount anomaly | (none yet) → `outcome: "not-instrumented"` | [[08-validation-gates]] anomaly flag |
| vendor bank change | (none yet) → `outcome: "not-instrumented"` | [[08-validation-gates]] / [[11-approval-sod-workflow]] |
| SoD | `assigned_approver_role`, `decision_by` vs submitter | [[11-approval-sod-workflow]] Workflow + Server-Script backstop |
| AP review events | (none yet) | [[10-ap-review-observability]] `AP Review Event` list |

**F) TB-drift report — `Accounts Payable Trial Balance Drift`** (Script/Query Report, **no new DocType**). Columns:

| column | type | meaning |
|---|---|---|
| `supplier` | Link → Supplier | party (blank for non-party Credit-Card-Clearing rows) |
| `account` | Link → Account | Creditors or Credit-Card-Clearing |
| `current_balance` | Currency | current-period balance (GL aggregation) |
| `prior_close_balance` | Currency | from latest Account Closing Balance snapshot (C-1) |
| `drift` | Currency | `current_balance - prior_close_balance` |
| `drift_cents` | Int | `round(drift * 100)` |
| `over_threshold` | Check | `abs(drift_cents) > settings.drift_threshold_cents` |

**G) Print Format — `AP Audit Trail`** (Jinja Print Format, **no new DocType**). `print_format_type = Jinja`, `custom_format = 1`, `doc_type = AP Invoice Capture`, `html` = Jinja template. Place under `erpnext/accounts/print_format/ap_audit_trail/`. Template renders the `build_audit_trail_for(doc.name)` payload sections (image ref → extraction → validation → approval → payment → bank-match → posting/GL → history → gates) to one PDF (C-10).

**Permissions:** `build_audit_trail_for` is a read endpoint exposing financial + actor data — gate it with the capture's read permission (default `@frappe.whitelist()` already enforces the doc read-perm path used by `build_closure_evidence_for`). An auditor-only print variant SHOULD be gated with `frappe.only_for(...)` consistent with `issue_mock_payment`'s `frappe.only_for(MANAGER_APPROVAL_ROLE_DEFAULT)` at `ap_invoice_capture.py:1441`. New role `'Auditor (Read Only)'` (per bible) is the recommended grant for read-only audit retrieval — call it out as new when used.

### 5.2 Endpoints

All whitelisted methods live in `erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.py` (sibling to `build_closure_evidence_for` at `:1748`) and follow the file's `str | doc` dual-accept convention. Report `execute` lives in the new report module.

```python
# New — single-record audit retrieval (whitelisted)
@frappe.whitelist()
def build_audit_trail_for(capture: str) -> dict:
    """Composite audit dict: closure evidence + Version history + gates + bank_match.
    Read-perm gated. capture is a name string (UI passes a string)."""

# Internal aggregator (str | doc dual-accept, mirrors build_closure_evidence)
def build_audit_trail(capture: "APInvoiceCapture | str") -> dict: ...

# Internal helpers
def _audit_history_for(capture: "APInvoiceCapture | str") -> list[dict]: ...
def _audit_gates_for(capture: "APInvoiceCapture | str") -> list[dict]: ...
def _bank_match_for(payment_doctype: str, payment_name: str | None) -> dict | None:
    """Join Bank Transaction Payments -> parent Bank Transaction.
    payment_doctype in ('Payment Entry','Journal Entry'). Returns
    {bank_transaction, date, amount, reconciled_by, reconciled_at} or None."""

# Generalized from _bank_transaction_count_for_payment_entry (ap_invoice_capture.py:1393)
def _bank_transaction_for_payment(payment_doctype: str, payment_name: str | None) -> str | None:
    """Resolve the parent Bank Transaction name for a disbursing voucher; None if unmatched."""

# Changed — build_closure_evidence(ap_invoice_capture.py:1523) extended in place:
#   + top-level bank_match{}, settled, bank_cleared; closed = settled or bank_cleared;
#   + rewritten closure_basis (stream-aware, no "must remain 0" clause).

# Changed — _derive_payment_lifecycle_status(ap_invoice_capture.py:1402): signal-aware.
```

**Report module** `erpnext/accounts/report/accounts_payable_trial_balance_drift/accounts_payable_trial_balance_drift.py`:

```python
def execute(filters: dict | None = None) -> tuple[list[dict], list[dict]]:
    """Returns (columns, data). filters: company (reqd), closing_date (reqd,
    the period boundary), supplier (optional)."""
```

**Retention module** `erpnext/accounts/ap_closed_loop/retention.py` (registered in `hooks.py` `scheduler_events`):

```python
def flag_captures_for_retention() -> None:
    """Scheduler entrypoint (daily). FLAG-ONLY — never deletes (IRS 7-year)."""
```

**Normalization convention:** UI callers pass `capture` as a name **string**; internal helpers accept `str | doc` and `frappe.get_doc("AP Invoice Capture", capture)` if a string — identical to `build_closure_evidence` (`ap_invoice_capture.py:1526-1527`). The report `execute` receives `filters` as a dict (Frappe deserializes the JSON filter payload before calling).

### 5.3 Logic

**(1) `build_audit_trail(capture)`**
1. `payload = build_closure_evidence(capture)` (now dual-signal — step 2 below).
2. `payload["history"] = _audit_history_for(capture)`.
3. `payload["gates"] = _audit_gates_for(capture)`.
4. `bank_match` is already folded into `payload` by `build_closure_evidence`.
5. Return the single composite dict. **No persistence** — always live.
- *Precondition:* `capture` resolves; otherwise `frappe.get_doc` raises **`frappe.DoesNotExistError`** (no custom exception needed — this is a read path).
- *Idempotency:* pure read; naturally idempotent.

**(2) `build_closure_evidence` extension** (`ap_invoice_capture.py:1523`):
1. Resolve the disbursing voucher: Stream I → `(payment_doctype="Payment Entry", payment_name=capture.payment_entry)`; Stream R → `(payment_doctype="Journal Entry", payment_name=capture.journal_entry)` **iff** the `journal_entry` field exists (else `None` — R path stubbed, see §5.4).
2. `bank_match = _bank_match_for(payment_doctype, payment_name)`; add top-level `payload["bank_match"] = bank_match`.
3. `settled = <existing PI-Paid + PE-submitted logic>` (unchanged at `:1551-1558`).
4. `bank_cleared = bool(bank_match)`.
5. `closed = settled or bank_cleared` (back-compat key retained); also expose `settled` and `bank_cleared` top-level.
6. **Rewrite `closure_basis`** (drops the "must remain 0" clause):
   > "Settled = submitted Purchase Invoice (outstanding_amount=0, status Paid) + submitted disbursing voucher. Bank-cleared = the disbursing voucher is matched to a Bank Transaction (Bank Transaction Payments). Closed when either signal holds. Stream R clears on the Journal Entry's bank match; Stream I clears on the Payment Entry's bank match."
7. `native.bank_transaction_count` stays for back-compat but is **no longer asserted to be 0**.
- *Test-migration item:* `test_ap_invoice_capture.py:1208` (`== 0`) and `:1210` ("No custom closed flag") MUST change in the same PR; `test_walking_skeleton.py:78-79` if the twin is updated (see §5.5).

**(3) `_bank_match_for(payment_doctype, payment_name)`**
1. If `payment_name` falsy or `Bank Transaction`/`Bank Transaction Payments` DocTypes absent → return `None` (mirrors the guard at `ap_invoice_capture.py:1394`).
2. Find the `Bank Transaction Payments` row where `payment_document == payment_doctype` and `payment_entry == payment_name`; read its `parent` (the Bank Transaction name) and `allocated_amount`.
3. Read parent `Bank Transaction`: `date`, and `reconciled_by` ← BT `modified_by`, `reconciled_at` ← BT `modified` (**resolved D-14-5** — no native or spec-13 `reconciled_by`/`reconciled_at` field exists; use the framework audit columns).
4. Return `{bank_transaction, date, amount, reconciled_by, reconciled_at}` or `None` if no row.

**(4) `_audit_history_for(capture)`**
1. Collect `(ref_doctype, docname)` pairs: `("AP Invoice Capture", capture.name)`, and for each non-null link `("Purchase Invoice", capture.purchase_invoice)`, `("Payment Entry", capture.payment_entry)`, `("Journal Entry", capture.journal_entry if present)`, and the resolved Bank Transaction.
2. For each pair, `frappe.get_all("Version", filters={"ref_doctype": dt, "docname": name}, fields=["name","owner","creation","data"], order_by="creation asc")` (mirrors the `transaction_deletion_record.py` Version query pattern; C-4).
3. Merge all rows, sort by `creation asc`, return. Coverage is **real for all four linked voucher types** (C-7 confirmed `track_changes:1` on each).

**(5) `_audit_gates_for(capture)`** — return the §5.1-E gate list, deriving `outcome`/`detail` from existing capture fields + `json.loads(capture.mock_payment_response or "{}")`. Gates with no instrumentation yet emit `{"gate": ..., "outcome": "not-instrumented", "source": "<future spec>"}` so the print/print-format is honest about coverage.

**(6) `_derive_payment_lifecycle_status` (signal-aware)** (`ap_invoice_capture.py:1402`):
1. `if is_payment_blocked(capture): return PAYMENT_LIFECYCLE_BLOCKED`.
2. `if not capture.payment_entry (and no journal_entry): return PAYMENT_LIFECYCLE_NOT_REQUESTED`.
3. Compute `settled`/`bank_cleared` (reuse the evidence helpers).
4. `if settled and bank_cleared: return PAYMENT_LIFECYCLE_BANK_CLEARED` (`"Bank Cleared"`); `elif settled: return PAYMENT_LIFECYCLE_CLOSED` (`"Closed"` = settled state); `else: return PAYMENT_LIFECYCLE_CONFIRMED`. (Aligned with [[13-bank-feed-reconciliation]] — single new `Bank Cleared` value, `Closed` retained as the settled state, signals carried by the derived `settled`/`bank_cleared` fields.)
5. Keep `PAYMENT_LIFECYCLE_CLOSED == "Closed"` as the **settled-state value / back-compat alias**; add `PAYMENT_LIFECYCLE_BANK_CLEARED == "Bank Cleared"` (the new dual-signal terminal).

**(7) TB-drift `execute(filters)`**
1. Validate `filters.company` and `filters.closing_date` present; else `frappe.throw`.
2. **Current balances:** aggregate current-period GL for the Creditors + Credit-Card-Clearing accounts per supplier, using the same GL-aggregation pattern the standard `trial_balance` report uses (`erpnext/accounts/report/trial_balance/trial_balance.py` `get_data`).
3. **Prior snapshot:** `prior = get_previous_closing_entries(company, closing_date, get_accounting_dimensions())` (C-1); index by `(account, supplier-dimension)`.
4. `drift = current - prior_close` per `(supplier, account)`; `drift_cents = round(drift * 100)`.
5. `over_threshold = abs(drift_cents) > settings.drift_threshold_cents`.
6. **Degrade gracefully:** no prior PCV → `get_previous_closing_entries` returns `[]` → treat prior as 0, do not throw.
7. **Multi-currency:** compare in account currency (`account_currency` on Account Closing Balance, C-1) to avoid FX false-positives.

**(8) Retention scheduler `flag_captures_for_retention()`**

*Why a custom scheduler and not native `Log Settings`:* native `Log Settings` (C-13) is a real scheduler-driven retention engine, but it **deletes** rows older than N days via `clear_old_logs` — the opposite of IRS 7-year keep-forever. There is no native "flag-and-keep" retention surface, so this flag-only, never-delete scheduler is the justified custom path, not a reinvention.

1. `years = settings.retention_years or 7`; `cutoff = now - years`.
2. Select `AP Invoice Capture` where `received_at < cutoff` AND `archive_pending = 0` (idempotent self-guard — skips already-flagged).
3. For each: `frappe.db.set_value("AP Invoice Capture", name, {"archive_pending": 1, "archived_flagged_at": now})` (C-12). **Never `delete`.**
4. Flag linked `File` rows (`attached_to_doctype="AP Invoice Capture"`, `attached_to_name=name`) — set a marker (recommend a custom `File` flag field added by this spec, or skip if out-of-scope and note it).
5. Emit **one** `Notification`/notification-log to `settings.ap_notification_role` summarizing the batch (not per-record, to avoid spam).
- *Guarantee:* zero deletions — asserted in tests (§7).
- *Cold-storage handoff is explicitly out of scope* (later phase).

### 5.4 Cascade & stream-awareness

- **No new pause point.** Closure/audit-trail retrieval is a **read-side aggregator**, not a state transition — it does NOT participate in `_determine_next_step` / the `after_insert → _kick_next_step → _enqueue_next` cascade. The mock-payment wrapper already calls `_kick_next_step()` "for symmetry … so any future hop (e.g. closure-evidence auto-generation) plugs in" (`ap_invoice_capture.py:1739-1743`) — closure remains a terminal read, not an auto-advanced step.
- **Dual-signal terminal:** the capture's terminal `payment_lifecycle_status` advances **passively** from `Closed` (settled) → `Bank Cleared` (settled AND bank_cleared) when [[13-bank-feed-reconciliation]] lands the Bank Transaction match. There is no enqueue here — the value is **derived** each time evidence is built from the `settled`/`bank_cleared` signals (consistent with the "no custom closed flag" design, and with spec 13's vocabulary).
- **Stream R vs Stream I divergence:**
  - **Stream I (PE path) — fully implemented in v1.** `_bank_match_for("Payment Entry", capture.payment_entry)`.
  - **Stream R (JE path) — stubbed in v1.** Requires a `stream` discriminator + `journal_entry` Link on the capture, **neither of which exists today** (grep for `stream`/`journal_entry`/`Reimbursable` in the JSON returned nothing). Those are owned by [[02-intake-stream-tagging]] (stream) and [[07-classification-doctype-branching]] (JE branch / link). Until they land, `_bank_match_for("Journal Entry", …)` has no `journal_entry` field to read → R closure is a documented stub. v1 asserts the I-path is unaffected.
- **Scheduler cadence:** retention runs under `scheduler_events["daily"]` alongside `prune_audit_logs` (C-11). TB-drift is an on-demand report (no scheduler).

### 5.5 Cross-cutting

- **Permissions / SoD:** `build_audit_trail_for` exposes actor + financial data → enforce the capture read-perm (default whitelist path). Auditor-only print variant → `frappe.only_for('Auditor (Read Only)')` (new role per bible). The gates block surfaces the SoD outcome (`decision_by` vs submitter) sourced fully from [[11-approval-sod-workflow]] once it lands.
- **Idempotency ([[01-foundations-settings-async-idempotency]]):** `AP Posting Ledger` / idempotency keys do not exist in the fork yet. The retention scheduler's idempotency in v1 is the `archive_pending = 0` self-guard (re-runs skip already-flagged). When [[01-foundations-settings-async-idempotency]] ships, the scheduler MAY record a ledger key per flagged batch; not required for v1 since the operation is non-posting.
- **Async / enqueue:** retention is scheduler-driven (`hooks.py` daily). `build_audit_trail_for` is synchronous (read). PDF generation for the Print Format uses Frappe's standard print pipeline (synchronous on demand).
- **Observability ([[10-ap-review-observability]]):** the `gates[]` block is the audit-trail's read-side view of validation outcomes; full per-gate event history is unblocked when [[10-ap-review-observability]]'s `AP Review Event` lands. No new `AP Review Event` is emitted by closure itself.
- **Walking-skeleton twin sync:** `walking_skeleton.py` `ClosureEvidence`/`build_closure_evidence` is the offline twin. **Decision (§8 D-14-6):** recommend updating the twin's `closure_basis` + adding `settled`/`bank_cleared` to keep parity, updating `test_walking_skeleton.py:78-79` in the same PR; OR explicitly documenting the divergence (twin stays single-signal as a frozen reference). Default: **update the twin** for parity.
- **FORK-CHANGES + UI-SITEMAP (CLAUDE.md):** this adds files under the AP closed-loop scope (report folder, print-format folder, `retention.py`, capture-field + settings-field JSON edits, `hooks.py` edit) → `docs/architecture/FORK-CHANGES.md` and `FORK-CHANGES-PLAIN.md` MUST be updated in the same commit; `docs/architecture/UI-SITEMAP.md` MUST be refreshed because the TB-drift report and the `AP Audit Trail` print format add desk navigation entries.

## 6. Acceptance criteria

- **AC-14-1 (audit-trail composite, positive):** `build_audit_trail_for(<closed capture>)` returns a dict containing keys `capture`, `ocr`, `validation`, `approval`, `payment`, `native`, `bank_match`, `settled`, `bank_cleared`, `closed`, `history`, `gates`.
- **AC-14-2 (history non-empty):** for a capture that went through promotion + payment (so Versions exist), `history` is a non-empty list of `{name, owner, creation, data}` rows ordered `creation asc`.
- **AC-14-3 (audit-trail negative):** `build_audit_trail_for("does-not-exist")` raises `frappe.DoesNotExistError`.
- **AC-14-4 (audit-trail edge):** a capture with no PI/PE yields `bank_match == None` and an empty (or capture-only) `history` **without throwing**.
- **AC-14-5 (dual closure, settled-only, positive):** PI Paid + PE submitted, **no** Bank Transaction match → `settled == True`, `bank_cleared == False`, `payment_lifecycle_status == "Closed"` (the settled state), and `closure_basis` mentions **both** signals and does **not** contain "must remain 0".
- **AC-14-6 (dual closure, bank-cleared, Stream I, positive):** a Bank Transaction matched to the PE (a `Bank Transaction Payments` row) → `settled == True`, `bank_cleared == True`, `bank_match` populated with `{bank_transaction, date, amount, reconciled_by, reconciled_at}` (where `reconciled_by`/`reconciled_at` come from BT `modified_by`/`modified`, D-14-5), `payment_lifecycle_status == "Bank Cleared"`.
- **AC-14-7 (closure negative — blocked):** `payment_readiness == Blocked` → `payment_lifecycle_status == "Blocked"`, `settled == False`, `bank_cleared == False`.
- **AC-14-8 (Stream R stub, edge):** if the `journal_entry`/`stream` field is absent, the I-path closure is unaffected and the R-path is a documented no-op (test skips with a reason); if present, a JE matched to a Bank Transaction closes on the JE.
- **AC-14-9 (TB-drift, positive):** with a submitted Period Closing Voucher + Account Closing Balance rows for Creditors/Credit-Card-Clearing and divergent current-period GL, the report returns a row with non-zero `drift` and `over_threshold == True`.
- **AC-14-10 (TB-drift, zero/negative):** current == prior close → `drift == 0`, `over_threshold == False`.
- **AC-14-11 (TB-drift, edge — no PCV):** no prior Period Closing Voucher → `get_previous_closing_entries` returns `[]` → report treats prior as 0 and does not throw; a 1-cent-under-threshold drift is **not** flagged.
- **AC-14-12 (retention, positive):** a capture with `received_at` older than `retention_years` → `archive_pending == 1`, `archived_flagged_at` set, a Notification created for `ap_notification_role`, linked File flagged.
- **AC-14-13 (retention, negative):** a capture newer than the threshold → `archive_pending` stays `0`.
- **AC-14-14 (retention, edge — idempotent + no-delete):** re-running the scheduler on an already-flagged capture creates **no** duplicate Notification and performs **no** deletion (the record still exists).
- **AC-14-15 (retention, config fallback):** missing/zero `retention_years` falls back to 7 years.
- **AC-14-16 (print format):** the `AP Audit Trail` Print Format renders a single PDF for a closed capture containing the image ref, extraction, validation, approval, payment, bank-match, GL/posting, history, and gates sections.

## 7. Tests

### 7.1 Automated

Base class `frappe.tests.IntegrationTestCase`; roll back DB writes in `tearDown` so suites are reentrant.

**Module 1 — `erpnext/accounts/doctype/ap_invoice_capture/test_ap_invoice_capture.py`** (extend; reuse `_capture_through_payment` at `:1159`):
- `test_build_audit_trail_for_full_lifecycle` *(positive, AC-14-1/2)* — payload has all required keys; `history` non-empty and `creation asc`; blocks carry the same values the existing closure test asserts.
- `test_build_audit_trail_unknown_raises` *(negative, AC-14-3)* — `frappe.DoesNotExistError`.
- `test_build_audit_trail_no_payment_no_history` *(edge, AC-14-4)* — `bank_match is None`, no throw.
- `test_build_audit_trail_history_ordered_with_corrections` *(edge, AC-14-2)* — a corrected capture (Version `>1` row) → `len(history) > 1`, ordered ascending.
- **UPDATE `test_closure_evidence_reconstructs_full_lifecycle`** (`:1192-1210`) *(AC-14-5)* — change `assertEqual(...bank_transaction_count, 0)` and `assertIn("No custom closed flag", closure_basis)`; assert `settled is True`, `bank_cleared is False`, lifecycle `"Closed"` (settled state), and `closure_basis` mentions both signals.
- `test_dual_closure_bank_cleared_stream_i` *(positive, AC-14-6)* — seed a `Bank Transaction` + `Bank Transaction Payments` row for the PE → `bank_cleared`, `bank_match` populated, lifecycle `"Bank Cleared"`.
- `test_closure_blocked_neither_signal` *(negative, AC-14-7)*.
- `test_stream_r_closure_stub` *(edge, AC-14-8)* — skip-with-reason if `journal_entry` field absent; else JE-match path.

**Module 2 — `erpnext/accounts/report/accounts_payable_trial_balance_drift/test_accounts_payable_trial_balance_drift.py`** (new):
- `test_drift_flagged_over_threshold` *(positive, AC-14-9)*.
- `test_zero_drift_not_flagged` *(negative, AC-14-10)*.
- `test_no_prior_pcv_treats_prior_zero` *(edge, AC-14-11)* — and a sub-threshold (1-cent-under) row is unflagged.

**Module 3 — retention** (`test_ap_invoice_capture.py` or a new `erpnext/accounts/ap_closed_loop/test_retention.py`):
- `test_retention_flags_old_capture` *(positive, AC-14-12)*.
- `test_retention_skips_recent` *(negative, AC-14-13)*.
- `test_retention_idempotent_no_delete` *(edge, AC-14-14)* — assert no duplicate Notification AND `frappe.db.exists(...)` still true.
- `test_retention_defaults_to_seven_years` *(config edge, AC-14-15)*.

Run locally:
```
bench --site <site> run-tests --module erpnext.accounts.doctype.ap_invoice_capture.test_ap_invoice_capture
bench --site <site> run-tests --module erpnext.accounts.report.accounts_payable_trial_balance_drift.test_accounts_payable_trial_balance_drift
```
Confirm green before declaring done — console probes are not sufficient (CLAUDE.md).

### 7.2 Clean-room test plans

One `.md` per feature under `test/testplans/`, kebab-case, each following the 7 required CLAUDE.md sections (feature; branch/commit; env setup; test-data prereqs incl. how to obtain keys but never the key; numbered positive/negative/edge cases with full URLs/payloads/expected DB state; cleanup; pass/fail checklist):

- `test/testplans/closure-audit-trail-single-record.md` — single-record `build_audit_trail_for` retrieval (history + gates + bank_match composite).
- `test/testplans/closure-dual-signal-bank-cleared.md` — settled vs bank-cleared dual closure and the lifecycle terminals.
- `test/testplans/ap-trial-balance-drift.md` — TB-drift report against a seeded Period Closing Voucher.
- `test/testplans/ap-7yr-retention-flagging.md` — flag-only retention scheduler (assert no deletion).
- `test/testplans/ap-audit-trail-print-format.md` — Playwright-driven (per `test/testplans/BROWSER-TESTING-SETUP.md`); save evidence screenshots under `test/testplans/screenshots/ap-audit-trail-print-format/`.

## 8. Open decisions

- **D-14-1 — `payment_lifecycle_status` value set (RECONCILED with [[13-bank-feed-reconciliation]]).** Options: (a) keep `Closed` (= settled state) + add the single value `Bank Cleared` matching spec 13, carry the signals as derived `settled`/`bank_cleared` fields; (b) add two terminals `Closed (Settled)`/`Closed (Bank Cleared)` (the original draft — **rejected: diverges from spec 13**); (c) migrate all and drop `Closed`. **Recommended default: (a)** — single new `Bank Cleared` value, `Closed` retained as the settled-state value / back-compat alias (avoids breaking `PAYMENT_LIFECYCLE_CLOSED`, `ap_invoice_capture.py:90`, and the 5 existing assertions), and **agrees with [[13-bank-feed-reconciliation]]'s enum** so the two specs don't fork the vocabulary. Owner: AP closed-loop lead. Lock: before the JSON Select edit lands (build start). Verify v16 patch conventions before writing any data patch.
- **D-14-2 — persist audit payload vs render-on-demand.** Options: (a) in-memory composite each call; (b) store a snapshot DocType. **Recommended: (a)** — must always reflect live linked-doc state. Owner: architecture. Lock: at spec sign-off (decided here, flagged for confirmation).
- **D-14-3 — Stream R (JE) closure scope in v1.** Options: (a) stub behind the missing `journal_entry`/`stream` field, ship I-path only; (b) block this spec until [[07-classification-doctype-branching]]/[[02-intake-stream-tagging]] land the field. **Recommended: (a) stub** — unblocks the I-path and the audit trail now. Owner: AP lead + classification-spec owner. Lock: when [[07-classification-doctype-branching]] data model is finalized.
- **D-14-4 — `gates[]` fidelity in v1.** Options: (a) best-effort summary from existing fields + `mock_payment_response`, mark uninstrumented gates `"not-instrumented"`; (b) block until [[10-ap-review-observability]]/[[05-supplier-resolution]]/[[11-approval-sod-workflow]] land their event doctypes. **Recommended: (a)** — honest partial coverage now. Owner: AP lead. Lock: build start.
- **D-14-5 — `reconciled_by`/`reconciled_at` source. RESOLVED → (b) fall back to BT `modified_by` / `modified`.** Source-verified: **neither [[13-bank-feed-reconciliation]] nor the native `Bank Transaction` defines `reconciled_by`/`reconciled_at`.** Spec 13's new fields are `bank_transaction`, `bank_cleared`, and `bank_cleared_at` (the last sourced from `Bank Transaction Payments.clearance_date`); native BT exposes `date`, `status`, `deposit`/`withdrawal`/`allocated_amount`, `reference_number` — none of those names (C-9). There is therefore **no spec-13 field to be conditional on**, so this resolves to the fallback: the `bank_match` block sources `reconciled_by` from BT `modified_by` and `reconciled_at` from BT `modified` (the last actor/timestamp on the Bank Transaction, which for a reconciled BT is the reconciliation edit). Owner: AP lead. **Lock: resolved here — no longer pending spec 13.**
- **D-14-6 — walking-skeleton twin parity.** Options: (a) update the twin to dual-signal + update `test_walking_skeleton.py:78-79`; (b) freeze the twin as a single-signal reference and document the divergence. **Recommended: (a) update for parity.** Owner: AP lead. Lock: same PR as the `build_closure_evidence` change.
- **D-14-7 — retention scheduler cadence + File flagging.** Options: `"daily"` vs `"hourly"`; flag File rows via a new `File` custom flag field vs skip File flagging in v1. **Recommended: `"daily"` (matches the existing `prune_audit_logs` slot, C-11) + add a minimal File flag field.** Owner: AP lead. Lock: build start.
- **D-14-8 — drift threshold unit + multi-currency.** Options: cents in company default currency vs per-account-currency comparison. **Recommended: compare per `account_currency` (C-1), threshold in cents.** Owner: accounting lead. Lock: before TB-drift `execute` is written.
- **D-14-9 — auditor read role.** Options: gate `build_audit_trail_for` with capture read-perm only vs add a dedicated `'Auditor (Read Only)'` role for the print variant. **Recommended: read-perm for the data endpoint; `'Auditor (Read Only)'` for the audit print format.** Owner: security/SoD lead ([[11-approval-sod-workflow]]). Lock: when the print format ships.

## 9. Dependencies & sequencing

**Must land first:**
- [[13-bank-feed-reconciliation]] — produces the `Bank Transaction` + `Bank Transaction Payments` match that the `bank_cleared` leg and `bank_match` block read. **Hard dependency** for the bank-cleared path (the settled-only path works without it).
- [[07-classification-doctype-branching]] + [[02-intake-stream-tagging]] — provide the `stream` discriminator + `journal_entry` Link required for **Stream R closure**. v1 stubs R behind these (D-14-3). **Hard dependency for Stream R only.**
- Period Closing Voucher run (operational, not a spec) — produces the `Account Closing Balance` snapshots TB-drift compares against. No PCV → report degrades to prior=0 (AC-14-11). Reuses the **vendored** `get_previous_closing_entries` (`account_closing_balance.py:119`) — depends on it not changing across the v16 migration (re-verify, §8/risks).

**Soft / forward dependencies (improve fidelity but not blocking):**
- [[10-ap-review-observability]] (`AP Review Event`), [[05-supplier-resolution]] (`Supplier Master Change Request`), [[08-validation-gates]] (three-way/anomaly/bank-change), [[11-approval-sod-workflow]] (SoD result) — fill the `gates[]` block with per-gate event history. Absent in v1 → gates are best-effort (D-14-4).
- [[01-foundations-settings-async-idempotency]] — optional idempotency-ledger key for the retention batch (not required; non-posting op).

**This unblocks:**
- The **single-PDF AP Audit Trail** deliverable (the Print Format depends on `build_audit_trail_for` existing first).
- The **auto-rate / closure dashboards** ([[10-ap-review-observability]]) that read `settled`/`bank_cleared` and `payment_lifecycle_status`.
- The **7-year IRS retention** posture (flag-only now; cold-storage handoff later).
- Closes the v2 loop end-to-end (Step 13).

**Estimated size:** **L** (per IMPLEMENTATION-PLAN units) — four distinct deliverables (audit-trail aggregator + dual-signal closure rewrite; TB-drift report; retention scheduler; print format), a breaking change to `closure_basis` + lifecycle options requiring test migration across two suites, plus five clean-room test plans. The Stream-R stub and gates best-effort keep it from being XL.
