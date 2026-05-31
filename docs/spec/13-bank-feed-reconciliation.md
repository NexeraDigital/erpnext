---
spec: 13-bank-feed-reconciliation
title: Bank-Feed Match & Reconciliation (SimpleFIN, mocked in dev)
plan_step: Step 12 — Bank-Feed Match & Reconciliation (closes the loop; retires the Phase-1 "no Bank Transaction" guardrail; dual closure)
stream: both
status: Draft
depends_on: [01-foundations-settings-async-idempotency, 02-intake-stream-tagging, 07-classification-doctype-branching]
related: [10-ap-review-observability, 14-closure-audit-retention, 12-payment-execution, 00-overview]
---

# 13 — Bank-Feed Match & Reconciliation (SimpleFIN, mocked in dev)
> _Revised 2026-05-31: applied native-vs-custom review findings._

## 1. Summary
This spec implements **Step 12** of `docs/planning/workflow-v2-plan.md`: the **external** bank-feed signal that actually closes an AP transaction. It reuses ERPNext's native Bank Reconciliation engine — it does **not** rebuild matching — and writes a clearance result back onto `AP Invoice Capture` via two new fields (`bank_transaction`, `bank_cleared`). It serves **both streams**: deposit (card) bank lines clear Stream R already-paid **Journal Entries**; withdrawal (ACH/check) bank lines clear Stream I **Payment Entries**. The one-line current-state delta: today closure is a single derived `closed` boolean with an active guardrail asserting **zero** Bank Transactions; this spec **retires that guardrail** and splits closure into `settled` (today's internal derivation) + `bank_cleared` (the new external half), with the live SimpleFIN feed mocked by fixtures during development.

## 2. Plan alignment

**Step 12 text (`docs/planning/workflow-v2-plan.md:88-91`), quoted:**
> The actual money movement is reconciled against the bank feed: card transactions match Journal Entries for already-paid receipts; ACH/check disbursements match Payment Entries for vendor bills and reimbursements. Exact-amount + date-window matching is used as the primary signal; fuzzy auto-matching by party name is known to be unreliable when similar vendor names exist and is treated as a hint, not a clearance. Bank-feed match is the **external** signal that closes the loop — until it lands, the transaction is not truly closed.
>
> **During development this step is mocked** using fixture bank transactions that mirror the shape of real feed data. The matching logic, exception paths, and reconciliation reports are all exercised end-to-end against the mock; only the live feed connection is deferred until pre-cutover, at which point the mock is swapped for the real bank-feed integration with no other workflow changes.

**Control-Summary rows (`docs/planning/workflow-v2-plan.md:134,139`), quoted:**
> | Async background queue (`frappe.enqueue`) | Steps 3, 12 | Keeps UI responsive during AI extraction and bank-feed sync |
> | Bank-feed match for closure | Step 12 | External confirmation of money movement |

**Key Design Principle (`docs/planning/workflow-v2-plan.md:108`), quoted:**
> **Closure comes from outside.** "Mock payment issued" or "payment entry submitted" is internal confirmation. The transaction is not closed until the bank feed confirms the money moved.

**Stream R vs Stream I divergence here (the routing axis):**
- **Stream R (already-paid card receipts).** The bank line is a **deposit** on the card-clearing account (SimpleFIN `amount > 0`). The matched voucher is a **Journal Entry** (or PI + Credit-Card-Clearing, see [[07-classification-doctype-branching]]). There is no payable to settle — `settled` for Stream R is achieved at JE submission — so for Stream R `bank_cleared` is the **primary and often only** closure half, and its 72h SimpleFIN SLA (`sla_due_at` from [[02-intake-stream-tagging]]) is the live metric.
- **Stream I (unpaid invoices / reimbursements).** The bank line is a **withdrawal** (SimpleFIN `amount < 0`). The matched voucher is a **Payment Entry**. `settled` (PI submitted + PE submitted + outstanding 0 + status Paid) is achieved internally first; `bank_cleared` then confirms the disbursement actually left the account. **Truly-closed = settled AND bank_cleared.**

## 3. Current state

What ships today on branch `russ/migrateToV16` (verified against the code, not just the brief):

1. **Closure is DERIVED, not stored, and the active guardrail is "no Bank Transaction."** Two parallel implementations:
   - **`erpnext/accounts/ap_closed_loop/walking_skeleton.py`** (older skeleton):
     - Module docstring `walking_skeleton.py:17-21` states *"No Bank Transaction is created; bank reconciliation is NOT implied."* and *"No custom 'closed' flag is stored."* — **this is the guardrail this spec retires; the docstring updates in the same PR.**
     - `ClosureEvidence` dataclass `walking_skeleton.py:100-121` carries `bank_transaction_count: int = 0`, `closed: bool = False`, `closure_basis: str = ""`.
     - `_bank_transaction_count(pi_name, pe_name)` `walking_skeleton.py:263-275` counts `Bank Transaction Payments` rows where `payment_document="Payment Entry"`, `payment_entry=pe_name`; returns 0 when the DocType is absent.
     - `derive_closure_evidence(...)` `walking_skeleton.py:278-339`: `closed = (pi.docstatus==1 AND pe.docstatus==1 AND flt(outstanding)==0 AND status=="Paid")` (`walking_skeleton.py:304-309`). `closure_basis` literal at `walking_skeleton.py:310-315`. **This is today's `settled` derivation that this spec splits into `settled` + `bank_cleared`.**
     - `MOCK_PAYMENT_REMARK` `walking_skeleton.py:36-39` puts the MOCK label on the Payment Entry; **this spec moves the MOCK label off the PE remark and onto the feed source.**
   - **`erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.py`** (production controller):
     - Module docstring `ap_invoice_capture.py:9-10`: *"must not progress silently into Purchase Invoice, Payment Entry, or Bank Transaction."* — **second docstring to update in the same PR.**
     - `_bank_transaction_count_for_payment_entry(payment_entry)` `ap_invoice_capture.py:1393-1399`: same count helper.
     - `_derive_payment_lifecycle_status(capture)` `ap_invoice_capture.py:1402-1423`: returns `Blocked / Not Requested / Closed / Confirmed`; `Closed` uses the same 4-condition test (`ap_invoice_capture.py:1415-1422`). **This is where the new `bank_cleared` terminal sub-state slots.**
     - `issue_mock_payment(...)` `ap_invoice_capture.py:1426-1504`: creates+submits a native PE via `get_payment_entry`, writes `mock_payment_*` fields, gated by `frappe.only_for(MANAGER_APPROVAL_ROLE_DEFAULT)` + `pe.insert(ignore_permissions=True)`. Response dict includes `bank_transaction_count` (`ap_invoice_capture.py:1487`).
     - `build_closure_evidence(capture)` `ap_invoice_capture.py:1523-1631`: computes `closed` identically (`ap_invoice_capture.py:1551-1558`); `native.bank_transaction_count` at `ap_invoice_capture.py:1623`; `closure_basis` at `ap_invoice_capture.py:1626-1630` **literally asserts "Bank Transaction count must remain 0" — this string is inverted by this spec.**

2. **The reconciliation hook is ALREADY WIRED.** `erpnext/hooks.py` registers `get_matching_queries = "erpnext.accounts.doctype.bank_reconciliation_tool.bank_reconciliation_tool.get_matching_queries"`. `bank_reconciliation_doctypes = ["Payment Entry", "Journal Entry", "Purchase Invoice", "Sales Invoice"]`. The `doc_events` block exists (`hooks.py:351`) and has **no Bank Transaction handler today** — that is where the writeback `doc_event` is added.

3. **`AP Invoice Capture` JSON already has** `purchase_invoice` (Link, read-only, idx 53) and `payment_entry` (Link, read-only, idx 67) plus a `mock_payment_*` section (idx 66-75). It does **not** have `bank_transaction` or `bank_cleared` — confirmed via JSON parse (`has bank_transaction field? False`, `has bank_cleared field? False`). `autoname: format:APIC-{YYYY}-{#####}`, `track_changes: 1`.

4. **No SimpleFIN, `mock_bank_feed.py`, idempotency module, or `journal_entry` link field exists yet** under `erpnext/accounts/ap_closed_loop/` (only `__init__.py`, `walking_skeleton.py`, `test_walking_skeleton.py`, `extractors/`). **Corrections to the brief, verified against source:**
   - **`sla_due_at` and `STATUS_DUPLICATE` are NOT yet in the repo** (`grep` returned nothing). They are owned by [[02-intake-stream-tagging]] / [[03-deduplication]]; this spec **consumes** `sla_due_at` and must not invent it — confirmed it is a true cross-spec dependency, not an existing field.
   - **Bank Transaction has no `on_submit` or `on_update_after_submit` *controller method*** — the controller defines `before_submit` (`bank_transaction.py:127`, which calls `set_status`) and `before_update_after_submit` (`bank_transaction.py:134-139`, which calls `set_status`). `set_status` (`bank_transaction.py:80-87`) flips `status` to `"Reconciled"` when `unallocated_amount <= 0`. There **is** an `on_cancel` (`bank_transaction.py:141-147`) that delinks payment entries and re-runs `set_status`. The framework still fires the `on_submit` / `on_update_after_submit` **doc_events** for any registered app even though the controller doesn't override those method names, so the writeback hooks there cleanly (see §5.3).

## 4. Upstream grounding

| # | URL | Confirms | Quoted signature / section |
|---|---|---|---|
| 1 | https://docs.frappe.io/erpnext/user/manual/en/bank-reconciliation | Matching engine is **RANK-based**; party-name is a fuzzy **hint**, not a clearance; manual reconciliation sets `Clearance Date`. Grounds "exact-amount + date PRIMARY, party-name HINT." | "The vouchers that are related to this transaction will be displayed. They will be ranked on the basis of the maximum number of fields matched." Also: "a party is auto set (if matched) in the Bank Transaction" via "fuzzy matching capabilities for approximate name matching." |
| 2 | https://docs.frappe.io/erpnext/user/manual/en/bank-transaction | `Bank Transaction` doctype shape for the new `bank_transaction` Link target + the `Bank Transaction Payments` child as the match link. `deposit` vs `withdrawal` is the card(JE)-vs-disbursement(PE) routing axis. | "status workflow values: Pending, Settled, Unreconciled, Reconciled, Cancelled; payment_document … (Sales Invoice, Purchase Invoice, Payment Entry, Journal Entry, Expense Claim)" |
| 3 | https://www.simplefin.org/protocol.html | **EXTERNAL** (not Frappe) — the named v2 feed; mock fixtures mirror this JSON. Transaction object: `id` (string, required), `posted` (UNIX ts), `amount` (numeric string, positive = deposit), `description` (required), `pending` (bool), `extra` (object). v2 replaced `Organization` with `Connection`; **no dedicated payee field in v2** — only `description`. | `"amount": "-33293.43"` (numeric string; positive = deposit); transaction has `id`, `posted`, `amount`, `description`, `pending`, `extra` |
| 4 | https://docs.frappe.io/framework/v15/user/en/python-api/hooks | `get_matching_queries` is an **ACCUMULATE** hook — the fork can ADD a matching method via `hooks.py` WITHOUT overriding native ERPNext. Distinguishes override (last value wins) from extension (all values collected). Grounds "reuse the native engine, do not rebuild." | "When you call frappe.get_hooks, it will convert all the values in a list. This means that if the hook is defined in multiple apps, the values will be collected from those apps." |
| 5 | `erpnext/erpnext_integrations/doctype/plaid_settings/plaid_settings.py` + `plaid_connector.py` (in-repo) | **Native bank-feed integration in ERPNext is PLAID, not SimpleFIN.** Plaid ALREADY creates the native `Bank Transaction` rows this spec reconciles against, via a scheduled `automatic_synchronization` run under `hourly_maintenance`. `plaid-python` is a declared dependency in `erpnext/pyproject.toml:19`. SimpleFIN has **zero code** in erpnext → it is a NEW external integration (custom HTTP client + external API + per-customer access token). See the SimpleFIN-vs-Plaid note below and Decision D8. | `plaid_settings.py` defines `automatic_synchronization()`; `hooks.py` schedules it under `hourly_maintenance`; `Plaid Settings` is config-only (no per-feed connector code needed to adopt). |

**SimpleFIN-vs-Plaid (native-vs-custom finding — read before building the feed).** ERPNext's **native** bank-feed integration is **Plaid** (`erpnext/erpnext_integrations/doctype/plaid_settings/` + `plaid_connector.py`; `plaid-python` declared at `erpnext/pyproject.toml:19`; scheduled `automatic_synchronization` under `hourly_maintenance`). Plaid **already produces the exact native `Bank Transaction` rows this spec reconciles against** — adopting it would need **ZERO connector code**, only `Plaid Settings` configuration. **SimpleFIN is NOT native** (zero code in erpnext): choosing it means writing a new custom HTTP client, talking to an external API, and managing a per-customer access token. Because the dev mock targets the `Bank Transaction` shape **both** providers would produce (§5.1), the swap-to-live is clean **either way** — so the choice of feed provider is a business decision, not a technical one, and it is recorded as **Decision D8 (§8)**. **Recommendation: default to native Plaid** unless there is a strong business reason for SimpleFIN (cost, or the customer's existing SimpleFIN / Mercury account). The mock and all downstream reconciliation/writeback logic in this spec are provider-agnostic and do not change with the decision.

**In-repo source corroboration (v16 ships this; trust over v15 docs for exact arg lists — see §8 / risk 2):**
- `get_matching_queries(...)` contract — `erpnext/accounts/doctype/bank_reconciliation_tool/bank_reconciliation_tool.py:628-684`:
  ```python
  def get_matching_queries(bank_account, company, transaction, document_types=None,
      exact_match=None, account_from_to=None, from_date=None, to_date=None,
      filter_by_reference_date=None, from_reference_date=None, to_reference_date=None,
      common_filters=None):  # -> list[sql_string]
  ```
  Routing within it (verified `bank_reconciliation_tool.py:645-682`): `"payment_entry" in document_types` and `"journal_entry" in document_types` always considered; `transaction.deposit > 0.0 and "sales_invoice"` adds SI; `transaction.withdrawal > 0.0` + `"purchase_invoice"` adds PI. `exact_match` filters on amount equality; party is only a rank booster — exactly "exact-amount PRIMARY, party HINT."
- Bank Transaction lifecycle — `erpnext/accounts/doctype/bank_transaction/bank_transaction.py`: `set_status` flips to `"Reconciled"` when `unallocated_amount <= 0` (`:80-87`); `before_update_after_submit` re-allocates + re-status (`:134-139`); `on_cancel` delinks + re-status (`:141-147`); status enum from `bank_transaction.json` = `Pending / Settled / Unreconciled / Reconciled / Cancelled`.
- Native reconcile entrypoint — `reconcile_vouchers(bank_transaction_name, vouchers)` at `bank_reconciliation_tool.py:474`.
- `Bank Transaction Payments` child fields (verified JSON parse): `payment_document` (Link→DocType), `payment_entry` (Dynamic Link on `payment_document`), `allocated_amount` (Currency), `clearance_date` (Date). **This is the join surface** between a Bank Transaction and the capture's PE/JE.

## 5. Design

### 5.1 Data model

#### New fields on `AP Invoice Capture` (mirror existing read-only `mock_payment_*` convention; place after `payment_entry`, idx 67)

| fieldname | fieldtype | options / default | purpose |
|---|---|---|---|
| `bank_transaction` | Link | options=`Bank Transaction`; `read_only=1` | External bank-feed clearance evidence. Set only when a **Reconciled** Bank Transaction allocates to this capture's Payment Entry (Stream I) or Journal Entry (Stream R). Writeback-only. |
| `bank_cleared` | Check | default `0`; `read_only=1` | The NEW half of dual closure. `1` once the linked Bank Transaction is Reconciled. `settled != bank_cleared`: settled is internal (PI+PE, outstanding 0, Paid); `bank_cleared` is the **external** signal that closes the loop. |
| `bank_cleared_at` | Datetime | `read_only=1` | Set from the matched `Bank Transaction Payments.clearance_date` (the native clearance field is the source). Used for the 72h SLA breach comparison (`bank_cleared_at` vs `sla_due_at`) and for [[10-ap-review-observability]] / [[14-closure-audit-retention]] reporting. Consumed, not invented. |

**`payment_lifecycle_status` Select — add one terminal value.** Current options: `Not Requested / Confirmed / Closed / Blocked`. Add `Bank Cleared` as the terminal state representing `settled AND bank_cleared`. (Decision D5 — see §8 — locks whether to rename `Closed` or keep both.)

**Stream-R dependency (new link field, ownership shared with [[07-classification-doctype-branching]]).** A Stream R capture promotes to a **Journal Entry**, but `AP Invoice Capture` has **no `journal_entry` link field today** (only `purchase_invoice` + `payment_entry`). For `bank_cleared` to attach to a JE-backed (deposit) capture, a `journal_entry` (Link → `Journal Entry`, read-only) field must exist. **Decision D4 (§8):** owned by [[07-classification-doctype-branching]]; this spec consumes it. If 07 has not landed it, this spec adds it (it is harmless and read-only).

> **Conditional on spec 07's D-07-1 — the Stream-R disbursing voucher may be a Purchase Invoice, not a Journal Entry.** This spec currently models the Stream-R already-paid voucher as a **Journal Entry** (hence the `journal_entry` link + the JE clearing path). But [[07-classification-doctype-branching]] decision **D-07-1** may resolve the Stream-R promotion to a **Purchase Invoice with `is_paid=1`** (now its *recommended* option), in which case the already-paid receipt **is** a Purchase Invoice — matched against the bank line as a **withdrawal/charge** on the card-clearing account, exactly like the native `withdrawal > 0` + `purchase_invoice` routing the engine already does (§4). **If D-07-1 lands on PI `is_paid=1`, then no separate `journal_entry` link is required for Stream R at all** — the existing `purchase_invoice` link is the match surface and the writeback resolves the capture by `purchase_invoice` (or its derived Payment Entry / GL) instead of `journal_entry`. **Therefore keep the entire Stream-R clearing path conditional on spec 07's choice:** if 07 = JE, use the `journal_entry` link + the `payment_document == "Journal Entry"` branch in §5.3.B; if 07 = PI `is_paid=1`, drop the `journal_entry` dependency and resolve Stream-R captures via `purchase_invoice`. Decision D4 (the `journal_entry` field) is consequently **gated on D-07-1** and is only needed under the JE outcome — do not add the field if 07 settles on PI `is_paid=1`.

#### Mock-feed records — NATIVE `Bank Transaction` docs (do NOT create a custom doctype)

The mock builds native `Bank Transaction` docs shaped like SimpleFIN output. SimpleFIN → Bank Transaction mapping:

| SimpleFIN transaction field | Bank Transaction field | Notes |
|---|---|---|
| `amount` > 0 (numeric string) | `deposit` (Currency) | Card credits / already-paid receipts → Stream R → match **Journal Entries**. `flt()`-parse the string. |
| `amount` < 0 (numeric string) | `withdrawal` (Currency) | ACH/check disbursements → Stream I → match **Payment Entries**. Use `abs(flt(amount))`. |
| `posted` / `transacted_at` (UNIX) | `date` (Date) | Prefer `transacted_at` when present, else `posted`. |
| `description` | `description` (Small Text) | SimpleFIN v2 has **no payee field**; derive `bank_party_name` from `description` only as a fuzzy HINT, never authoritative. |
| `id` | `transaction_id` (Data) | **Idempotency key** (see §5.5 / [[01-foundations-settings-async-idempotency]]). |
| `extra.check_no` / ACH ref (if present) | `reference_number` (Small Text) | Carries the "MOCK FEED — pilot fixture" tag (Decision D6). |
| — | `bank_account` (Link→Bank Account), `company` (fetched) | **Required** on Bank Transaction. The fixture must reference a seeded Bank Account on a card-clearing account (deposits) and an operating bank account (withdrawals). |

Every mock row is tagged **"MOCK FEED — pilot fixture"** — the MOCK label moves OFF the PE remark and ONTO the feed source. Tag location locked by Decision D6 (recommended: `reference_number` prefix, kept greppable for cleanup).

**Native child table reused (do NOT recreate): `Bank Transaction Payments`** — `payment_document` (Link→DocType), `payment_entry` (Dynamic Link), `allocated_amount` (Currency), `clearance_date` (Date).

**Permissions.** No new doctype, so no new permission rows for the feed. The three new `AP Invoice Capture` fields are `read_only=1` (writeback-only) and inherit the existing capture permission set. The whitelisted replay wrapper (§5.2) is gated to `MANAGER_APPROVAL_ROLE_DEFAULT` ("Accounts Manager") to match the existing payment-issuance authorization boundary — see [[11-approval-sod-workflow]] for the role model and the new `Treasury Approver` role this may migrate to.

### 5.2 Endpoints

All whitelisted methods live in `erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.py` and follow the existing string/dict-normalization convention of the `*_for` wrappers (`ap_invoice_capture.py:1677-1759`): accept `capture: str`, coerce JSON-string args, call `_kick_next_step()` after a state change.

```python
# Core writeback — called by the Bank Transaction doc_event AND by the replay wrapper.
def ingest_bank_transaction_match_for(bank_transaction: "Document | str") -> list[str]:
    """For a Bank Transaction, write bank clearance back onto every AP Invoice
    Capture whose payment_entry / journal_entry is allocated in it.
    Returns the list of capture names updated. Idempotent."""

@frappe.whitelist()
def ingest_bank_transaction_match(bank_transaction: str) -> list[str]:
    """Whitelisted manual-replay wrapper. frappe.only_for(MANAGER_APPROVAL_ROLE_DEFAULT)."""

# Mock feed entrypoint — module erpnext/accounts/ap_closed_loop/mock_bank_feed.py.
def build_mock_bank_feed(fixtures: "list[dict] | str") -> list[str]:
    """Create + submit native Bank Transaction docs from SimpleFIN-shaped dicts.
    Skip-if-exists by transaction_id (idempotent). Tags each 'MOCK FEED — pilot
    fixture'. Returns Bank Transaction names. NOT auto-run; invoked by tests /
    dev shell / the clean-room runbook."""

@frappe.whitelist()
def build_mock_bank_feed_for(fixtures: str) -> list[str]:
    """Whitelisted wrapper (dev/UAT only). frappe.only_for(MANAGER_APPROVAL_ROLE_DEFAULT).
    Refuses to run unless a dev guard is set (see Decision D7)."""
```

**Optional fork matching method (Decision D1 — default: DO NOT build).** If the pilot shows native ranking mis-prioritizes capture-linked vouchers, append a second method to the `get_matching_queries` accumulate hook in `hooks.py`. It MUST match the native arg signature in §4 and return a list of SQL strings the engine `UNION`s. Lean: native suffices; appending is safe (accumulate semantics) but is new code requiring its own tests, so it is deferred until evidence demands it.

### 5.3 Logic

**Native reuse (affirmed, not rebuilt).** This spec reuses ERPNext's native reconciliation engine wholesale: matching is performed by the native `Bank Reconciliation Tool.get_matching_queries` accumulate hook (`erpnext/accounts/doctype/bank_reconciliation_tool/bank_reconciliation_tool.py:628`, registered via `hooks.py`), and the PE/JE match surface is the native `Bank Transaction Payments` child (the `payment_document`/`payment_entry` Dynamic-Link join, §4). No matching logic, no match-storage doctype, and no reconciliation UI are rebuilt here. The fork adds **only** a post-reconciliation writeback (below) and an optional ranking-bias method behind Decision D1 (default: not built). Everything else is native.

**A. Writeback trigger — hook the Bank Transaction lifecycle, NOT `get_matching_queries`.**
`get_matching_queries` is a FIND/READ hook (returns SQL, fires DURING search; `bank_reconciliation_tool.py:628`) — it **cannot** carry post-reconciliation writeback. The clearance writeback must fire after `set_status` flips a Bank Transaction to `"Reconciled"`. Register in `hooks.py` `doc_events` (block at `hooks.py:351`):

```python
doc_events = {
    "Bank Transaction": {
        "on_submit": "erpnext.accounts.doctype.ap_invoice_capture.ap_invoice_capture.ingest_bank_transaction_match_for",
        "on_update_after_submit": "erpnext.accounts.doctype.ap_invoice_capture.ap_invoice_capture.ingest_bank_transaction_match_for",
        "on_cancel": "erpnext.accounts.doctype.ap_invoice_capture.ap_invoice_capture.revert_bank_transaction_match_for",
    },
}
```
Rationale: a Bank Transaction reaches `"Reconciled"` either at submit-with-allocations (`before_submit` → `set_status`) or after a post-submit allocation edit (`before_update_after_submit` → `set_status`, `bank_transaction.py:134-139`). Both paths emit the corresponding `doc_event`. `on_cancel` (`bank_transaction.py:141-147`) reverts.

**B. `ingest_bank_transaction_match_for(bank_transaction)` steps:**
1. Resolve `doc = frappe.get_doc("Bank Transaction", bank_transaction)` if a string was passed.
2. If `doc.status != "Reconciled"`: return `[]` (a partially-allocated / Unreconciled BT must not clear anything — guard for the negative test).
3. For each `row` in `doc.payment_entries`:
   - `payment_document, payment_entry = row.payment_document, row.payment_entry`.
   - Find captures: `WHERE payment_entry == row.payment_entry` (Stream I, when `row.payment_document == "Payment Entry"`) **OR** `WHERE journal_entry == row.payment_entry` (Stream R, when `row.payment_document == "Journal Entry"`).
   - **Idempotency guard:** if `capture.bank_transaction == doc.name AND capture.bank_cleared == 1`, **skip** (no double-write, no error — guard for the idempotency test).
   - Else set `capture.bank_transaction = doc.name`, `capture.bank_cleared = 1`, `capture.bank_cleared_at = row.clearance_date`.
   - Recompute `capture.payment_lifecycle_status = _derive_payment_lifecycle_status(capture)` (extended — see C).
   - `capture.save(ignore_permissions=True)` (writeback runs in a doc_event, not as the AP user) and emit an observability event (§5.5).
4. Return the list of capture names updated.

**C. Extend `_derive_payment_lifecycle_status` (`ap_invoice_capture.py:1402-1423`)** to add the terminal `Bank Cleared` state: after the existing `Closed` check (`settled` is true), if `capture.bank_cleared == 1` return `PAYMENT_LIFECYCLE_BANK_CLEARED`. For Stream R (no `payment_entry`, JE-backed), `settled` is JE-submission; the function must accept the JE path so a deposit clear is recognized (Decision D4 dependency).

**D. Split closure in `build_closure_evidence` (`ap_invoice_capture.py:1523-1631`) and `derive_closure_evidence` (`walking_skeleton.py:278-339`):**
- `settled` = the existing `closed` formula, **unchanged**: `PI.docstatus==1 AND PE.docstatus==1 AND flt(outstanding)==0 AND PI.status=="Paid"` (Stream I); JE submitted (Stream R).
- `bank_cleared` (NEW) = linked `Bank Transaction.status == "Reconciled"` AND a `Bank Transaction Payments` row allocates to `capture.payment_entry` (Stream I) OR `capture.journal_entry` (Stream R).
- `truly_closed` = `settled AND bank_cleared`. Emit all three in the evidence dict; keep `closed` as an alias of `settled` for backward compatibility (Decision D2).
- **Invert the `closure_basis` strings.** `walking_skeleton.py:310-315` and `ap_invoice_capture.py:1626-1630` (the latter literally says *"Bank Transaction count must remain 0"*) become a dual-signal description, e.g. *"settled = submitted PI + submitted PE + outstanding 0 + status Paid; bank_cleared = matched Bank Transaction status Reconciled; truly closed = settled AND bank_cleared."* **Update both module docstrings (`walking_skeleton.py:17-21`, `ap_invoice_capture.py:9-10`) in the same PR.**

**E. `revert_bank_transaction_match_for(bank_transaction)` (on_cancel)** — Decision D3, recommended default REVERT: for each capture whose `bank_transaction == doc.name`, set `bank_cleared = 0`, `bank_cleared_at = None`, clear `bank_transaction`, recompute `payment_lifecycle_status`, emit a reversal observability event. Idempotent (skip captures already cleared of this BT).

**F. `build_mock_bank_feed(fixtures)` steps (`mock_bank_feed.py`):**
1. For each SimpleFIN-shaped dict:
   - **Idempotency (via [[01-foundations-settings-async-idempotency]]):** if `frappe.db.exists("Bank Transaction", {"transaction_id": fixture["id"]})` → skip (re-running the fixture is a no-op; guard for the mock-idempotency test). Prefer the foundations content-hash/idempotency helper if it exists rather than rolling a bespoke exists-check.
   - Build a native `Bank Transaction`: map per §5.1; `flt()`-parse `amount`; sign → `deposit` vs `withdrawal`; `transaction_id = fixture["id"]`; `reference_number` carries the `MOCK FEED — pilot fixture` tag; `bank_account` from the seeded fixture account; `company` fetched.
   - `insert()` then `submit()`.
2. Return Bank Transaction names. Reconciliation (allocating to a PE/JE) is a **separate** native step (`reconcile_vouchers`, `bank_reconciliation_tool.py:474`) the test/runbook drives; the feed builder only creates the unreconciled bank lines.
3. **Swap-to-live = replace the fixture source with a SimpleFIN HTTP client returning the same dict shape — NO other workflow change** (the plan's explicit pre-cutover contract).

**G. SLA (Stream R 72h).** Consume `sla_due_at` from [[02-intake-stream-tagging]]. Breach = `bank_cleared_at > sla_due_at` (or `now() > sla_due_at AND bank_cleared == 0`). Emit breach rows for [[10-ap-review-observability]] / [[14-closure-audit-retention]]; do not build the report here.

### 5.4 Cascade & stream-awareness

- **Not a new auto-advance hop driven by `_kick_next_step`.** Bank clearance is **externally** triggered (the feed lands asynchronously), so it does NOT slot into the synchronous `_determine_next_step` cascade the way promote/approve/pay do. The capture **pauses** at `payment_lifecycle_status == Closed` (settled) after mock payment; the **Bank Transaction `doc_event`** then advances it to `Bank Cleared` when the matched bank line reconciles. This is the one cascade hop whose trigger is a sibling doctype's lifecycle, not the capture's own `after_insert`/wrapper chain.
- **Stream R:** deposit bank line → Journal Entry → on reconcile, `bank_cleared = 1` is the **primary** closure signal (no approval/payment hops preceded it). SLA clock (`sla_due_at`) is live and breaches feed observability.
- **Stream I:** withdrawal bank line → Payment Entry → on reconcile, `bank_cleared = 1` is the **second** half after internal `settled`. No SLA clock by default (Stream I has no 72h target in the plan).
- **`_kick_next_step` symmetry:** the existing `issue_mock_payment_for` wrapper already calls `_kick_next_step()` "for symmetry … so any future hop … plugs in" (`ap_invoice_capture.py:1739-1743`). The writeback path reuses `_kick_next_step()` post-write so a future closure-evidence-auto-generation hop ([[14-closure-audit-retention]]) plugs in without changing this wrapper.

### 5.5 Cross-cutting

- **Idempotency ([[01-foundations-settings-async-idempotency]]).** Two surfaces: (1) mock-feed creation keyed on SimpleFIN `transaction_id` (skip-if-exists); (2) writeback keyed on `capture.bank_transaction == doc.name AND bank_cleared == 1` (skip). Both must be no-ops on replay. If [[01-foundations-settings-async-idempotency]] ships idempotency helpers / an `AP Posting Ledger`, `mock_bank_feed` and `ingest_*` call them rather than rolling their own.
- **Async / enqueue.** Per Control-Summary row (`workflow-v2-plan.md:134`), bank-feed sync is queue-backed. The live SimpleFIN poller (deferred) runs under `frappe.enqueue`. The `doc_event` writeback is synchronous to the Bank Transaction save (cheap, single-doc) but MUST be re-entrant under retry.
- **Observability ([[10-ap-review-observability]]).** Emit an `AP Review Event` on each clearance (`event=bank_cleared`, capture, bank_transaction, stream) and on each reversal and SLA breach, so the auto-rate / breach dashboards consume them.
- **Permissions / SoD ([[11-approval-sod-workflow]]).** The writeback runs `ignore_permissions=True` inside a doc_event (system context). The manual replay + mock-feed wrappers are gated to `MANAGER_APPROVAL_ROLE_DEFAULT`. The mock-feed wrapper additionally refuses to run in production (Decision D7).
- **Paired-doc obligations (CLAUDE.md).** Changes under `erpnext/accounts/ap_closed_loop/` and `.../ap_invoice_capture/` require `docs/architecture/FORK-CHANGES.md` AND `FORK-CHANGES-PLAIN.md` updates in the same commit. Write an **ADR** locking the guardrail-retirement decision (settled vs bank_cleared split).

## 6. Acceptance criteria

- **AC-13-1 (fields exist).** `AP Invoice Capture` gains `bank_transaction` (Link→Bank Transaction, read-only), `bank_cleared` (Check, read-only), `bank_cleared_at` (Datetime, read-only); `payment_lifecycle_status` gains a `Bank Cleared` option.
- **AC-13-2 (mock feed, deposit).** `build_mock_bank_feed` on a SimpleFIN dict with `amount > 0` creates one submitted Bank Transaction with `deposit` set (`withdrawal == 0`), `transaction_id == fixture id`, `reference_number` containing `MOCK FEED — pilot fixture`.
- **AC-13-3 (mock feed, withdrawal).** Same with `amount < 0` → `withdrawal` set, `deposit == 0`.
- **AC-13-4 (Stream I clear, positive).** A capture with submitted PI+PE (`settled` true) and `bank_cleared` false → after a withdrawal Bank Transaction is reconciled to its Payment Entry, the writeback sets `capture.bank_transaction`, `bank_cleared == 1`, `bank_cleared_at` = the row clearance_date, `payment_lifecycle_status == Bank Cleared`; `truly_closed` true.
- **AC-13-5 (Stream R clear, positive).** A capture with a submitted Journal Entry → after a deposit Bank Transaction is reconciled to that JE, `bank_cleared == 1` and the capture is recognized as cleared via the JE path.
- **AC-13-6 (dual closure derivation).** `build_closure_evidence` returns `settled`, `bank_cleared`, and `truly_closed = settled AND bank_cleared`; `closure_basis` no longer asserts "Bank Transaction count must remain 0."
- **AC-13-7 (guardrail tests flipped).** `test_walking_skeleton_end_to_end` and `test_closure_evidence_reconstructs_full_lifecycle` assert the dual state (settled true now; bank_cleared false until a mock BT reconciles, then true) instead of `bank_transaction_count == 0`.
- **AC-13-8 (idempotent writeback).** Re-running `ingest_bank_transaction_match_for` on an already-cleared capture does not double-write and does not raise.
- **AC-13-9 (idempotent mock feed).** Re-running `build_mock_bank_feed` with the same `transaction.id` creates no duplicate Bank Transaction.
- **AC-13-10 (party-name is NOT auto-clearance — the core negative).** A Bank Transaction whose `bank_party_name` fuzzy-matches the vendor but whose amount does NOT match the voucher must NOT set `bank_cleared` (exact-amount is the gate; party is a hint only).
- **AC-13-11 (unreconciled guard).** A Bank Transaction with `status != "Reconciled"` (partial allocation) → `bank_cleared` stays 0; the writeback returns `[]`.
- **AC-13-12 (revert on cancel — edge).** A reconciled Bank Transaction that is later cancelled → the capture's `bank_cleared` reverts to 0 and `bank_transaction` clears.
- **AC-13-13 (mock-PE path unaffected).** `issue_mock_payment` still creates **no** Bank Transaction (the FEED, not the PE, creates BTs); the existing mock-PE response assertions remain green.

## 7. Tests

### 7.1 Automated

Use `from frappe.tests import IntegrationTestCase`; roll back DB writes in `tearDown` (delete created Bank Transactions, reset capture fields) so suites are reentrant. Run:
`bench --site <site> run-tests --module erpnext.accounts.ap_closed_loop.test_mock_bank_feed`
`bench --site <site> run-tests --module erpnext.accounts.doctype.ap_invoice_capture.test_ap_invoice_capture`
`bench --site <site> run-tests --module erpnext.accounts.ap_closed_loop.test_walking_skeleton`

**New module: `erpnext/accounts/ap_closed_loop/test_mock_bank_feed.py`** (positive / negative / edge per public function):
- `build_mock_bank_feed`: deposit→`deposit` set (AC-13-2); withdrawal→`withdrawal` set (AC-13-3); `transaction_id` + MOCK tag asserted; **negative:** duplicate `id` → no second Bank Transaction (AC-13-9); **edge:** `amount` numeric-string sign parsing (`"-33293.43"` → withdrawal, `"33293.43"` → deposit).
- `ingest_bank_transaction_match_for`: **positive** Stream I PE clear (AC-13-4) and Stream R JE clear (AC-13-5); **negative** unreconciled BT → `[]`, `bank_cleared` stays 0 (AC-13-11); **negative** party-name match but amount mismatch → not cleared (AC-13-10); **idempotent** re-run no double-write (AC-13-8); **edge** cancel-reverts (AC-13-12).

**Updated guardrail tests (these MUST be flipped, not deleted):**
- `erpnext/accounts/ap_closed_loop/test_walking_skeleton.py:42` `test_walking_skeleton_end_to_end` — replace the `frappe.db.count("Bank Transaction") == before` and `evidence.bank_transaction_count == 0` assertions (`:61-62`) with the dual-state assertion (AC-13-7).
- `erpnext/accounts/doctype/ap_invoice_capture/test_ap_invoice_capture.py:1192` `test_closure_evidence_reconstructs_full_lifecycle` — replace `native.bank_transaction_count == 0` (`:1208`) with the dual-state assertion (AC-13-7).
- **Left intentionally green (per ADR scope):** `test_issue_mock_payment_does_not_create_bank_transaction` (`test_ap_invoice_capture.py:1123`) and the `response["bank_transaction_count"] == 0` assertion (`:1075`) — the FEED creates BTs, the mock PE does not (AC-13-13). Confirm the ADR scopes "guardrail retired" to the closure-evidence assertions only.

### 7.2 Clean-room test plan

`test/testplans/bank-feed-match-simplefin-mock.md` — self-contained runbook for an external instance: bench app install; seed a Bank + Bank Account on a card-clearing and an operating account; drive a capture through to a submitted PE (Stream I) and a submitted JE (Stream R); load the inline SimpleFIN-shaped JSON fixture (id / posted / amount / description — given verbatim so no SimpleFIN account is needed); run native reconciliation; assert in the DB (source of truth) that `Bank Transaction.status == "Reconciled"` and the capture's `bank_transaction` + `bank_cleared` + `payment_lifecycle_status == "Bank Cleared"` are set; assert the party-name-only / amount-mismatch case does NOT clear; cover the four §4 grounding links in the plan's context section; cleanup deletes the seeded fixtures.

## 8. Open decisions

| # | Decision | Options | Recommended default | Owner | Must lock by |
|---|---|---|---|---|---|
| D0 | **Retire the Phase-1 "no Bank Transaction" guardrail** (split closure into `settled` + `bank_cleared`). | (a) retire + dual closure; (b) keep guardrail, model clearance off-record. | **(a)** — write an ADR; update both docstrings + both guardrail tests in the same PR. | AP pilot lead | Before any code lands (gates the whole spec). |
| D1 | Append a fork `get_matching_queries` method to bias ranking toward capture-linked vouchers? | (a) native ranking only; (b) append fork method. | **(a)** — native suffices; appending is safe (accumulate hook) but is new code needing its own tests. Add only if the pilot shows mis-ranking. | Build phase | At reconciliation-tuning review. |
| D2 | Keep `closed` as an alias of `settled` in the evidence dict for backward compat? | (a) alias; (b) remove `closed`, callers migrate. | **(a)** — alias `settled`, add `bank_cleared` + `truly_closed`; revisit when consumers migrate. | Build phase | At evidence-schema freeze. |
| D3 | `bank_cleared` behavior when a reconciled BT is later **cancelled**. | (a) revert to 0; (b) keep + flag stale. | **(a) revert** — mirrors native `on_cancel` delink (`bank_transaction.py:141-147`). | AP pilot lead | With D0. |
| D4 | Who owns the new `journal_entry` link field on `AP Invoice Capture` (needed for Stream R deposit clears) — **and whether it is needed at all**, gated on spec 07's **D-07-1**. | (a) [[07-classification-doctype-branching]] owns it (JE outcome); (b) this spec adds it; (c) **not needed** — if D-07-1 lands on PI `is_paid=1`, Stream-R clears via the existing `purchase_invoice` link (withdrawal/charge match), no `journal_entry` field at all. | **(c) if D-07-1 = PI `is_paid=1`** (its recommended option) → no `journal_entry` link; resolve Stream-R via `purchase_invoice`. **Else (a)** — owned by 07; this spec consumes it and adds it only if 07 hasn't landed. | Spec 07 / this spec | After D-07-1 locks; before Stream R clearing is testable. |
| D5 | `payment_lifecycle_status` terminal value naming. | (a) add `Bank Cleared`, keep `Closed`=settled; (b) rename `Closed`→`Settled` + add `Bank Cleared`. | **(a)** — additive, no migration of existing rows. | Build phase | At JSON freeze. |
| D6 | Physical location of the "MOCK FEED — pilot fixture" tag on Bank Transaction. | (a) `reference_number` prefix; (b) `description`; (c) new custom marker field. | **(a)** — greppable for cleanup, no schema change, doesn't pollute `description` (which seeds `bank_party_name`). | Build phase | With first `mock_bank_feed` commit. |
| D7 | Production guard on `build_mock_bank_feed_for` (must never create mock BTs on a live customer site). | (a) refuse unless a `developer_mode` / explicit settings flag is set; (b) role gate only. | **(a)** — refuse outside dev/UAT via an [[01-foundations-settings-async-idempotency]] settings flag (e.g. on `AP Closed Loop Settings`). | AP pilot lead | Before the wrapper ships. |
| D8 | **Live feed provider for swap-to-live: SimpleFIN vs native Plaid.** Native ERPNext bank feed is **Plaid** (`erpnext/erpnext_integrations/doctype/plaid_settings/` + `plaid_connector.py`; `plaid-python` at `pyproject.toml:19`; scheduled `automatic_synchronization` under `hourly_maintenance`) and it **already** creates the native `Bank Transaction` rows this spec reconciles — adopting it is **ZERO connector code**, only `Plaid Settings` config. SimpleFIN is **NOT** native (zero code in erpnext) = a new custom HTTP client + external API + per-customer access token. The mock targets the shared `Bank Transaction` shape so the swap is clean **either way**. | (a) native **Plaid** (config-only, no connector code); (b) **SimpleFIN** custom client (justify the business reason — cost, or the customer's existing SimpleFIN / Mercury account). | **(a) native Plaid by default** unless a strong business reason for SimpleFIN exists. Lock the decision and, if (b) is chosen, record the reason verbatim: *"SimpleFIN chosen over native Plaid because &lt;reason&gt;."* Whichever is chosen, the dev mock and downstream logic in this spec are unchanged (provider-agnostic). | AP pilot lead | Before the swap-to-live (pre-cutover); the mock-based build does not block on it. |

## 9. Dependencies & sequencing

**Must land first:**
- [[01-foundations-settings-async-idempotency]] — idempotency primitive (used to make mock Bank Transactions re-runnable via `transaction_id`; and the D7 production guard flag on `AP Closed Loop Settings`). Not yet implemented under `ap_closed_loop/`; this spec consumes it.
- [[02-intake-stream-tagging]] — `sla_due_at` (consumed for the Stream-R 72h breach comparison; not invented here).
- [[07-classification-doctype-branching]] — the `journal_entry` link + the `promote_to_journal_entry` Stream R path (deposit clears attach to a JE-backed capture).

**Unblocks / feeds:**
- [[10-ap-review-observability]] and [[14-closure-audit-retention]] — `bank_cleared`, `bank_cleared_at`, clearance events, reversal events, and SLA-breach rows are emitted for those reports/dashboards.
- Retires the Phase-1 "no Bank Transaction" guardrail repo-wide, enabling real bank-clearance evidence for the dual-closure model across the fork.

**Estimated size: L** (per `docs/changes/IMPLEMENTATION-PLAN.md` units). Three new fields + one Select option, a new `mock_bank_feed.py` module, a writeback + revert path wired via three new `doc_events`, dual-closure derivation changes in two controllers, two guardrail tests flipped, a new test module, an ADR, the clean-room runbook, and paired FORK-CHANGES updates — but it reuses the native matching engine (no new matching code in the default path), which caps the size below XL.
