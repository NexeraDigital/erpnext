---
spec: 12-payment-execution
title: Payment Execution (Stream I only; automation secondary)
plan_step: "Step 11 — Payment Execution; Stream I only; phase-1 default is human-triggered Payment Entry, full automation behind a per-supplier auto_pay_eligible flag (off by default)"
stream: I
status: Done
depends_on: [01-foundations-settings-async-idempotency, 02-intake-stream-tagging, 07-classification-doctype-branching]
related: [00-overview, 11-approval-sod-workflow, 13-bank-feed-reconciliation, 14-closure-audit-retention]
---

# 12 — Payment Execution (Stream I only; automation secondary)
> _Revised 2026-05-31: applied native-vs-custom review findings; added Playwright UI test plan (§7.3)._
> _Revised 2026-06-02: re-visioned automation-first ([[00-overview]] "Guiding principle"). §1 and §5.3-(4) now lead with the `auto_pay_eligible` opt-in as the automation lever (grow the trusted set so routine in-policy payments need no human); the human "Pay" click is the exception, not the rule. The care boundary is scoped to **real external rails** (moving money) — mock/dev flows freely. Stream R = no-op. ACs/§8 D-12-1 already align._

> **North-star alignment ([[00-overview]]).** Payment moves money, so the *care* boundary is the **real external rail** — but that does not make a human the default. The automation lever is the per-supplier **`auto_pay_eligible`** opt-in: a vendor a controller has explicitly trusted flows **hands-free** (approved → paid, no click), and the pilot's job is to **grow that trusted set over time** so routine, in-policy payments need no human at all. "Automation secondary" means *secondary by default, not unavailable*: the human "Pay" click is the **exception** (new vendor, unusual amount, opt-out), never the rule, and it shrinks as the auto-pay set grows. The extra care is reserved for real external disbursement (ACH/check/card — moving money irreversibly); the **mock/dev path flows freely** and is the automation proving ground. Stream R stays a no-op (money already moved).

## 1. Summary
This spec hardens the existing "mock payment" leg into the **Step-11 payment-execution control** for **Stream I (unpaid invoices) only**, anchored automation-first. The **automation lever** is the per-supplier **`auto_pay_eligible`** Custom Field: a supplier a controller has explicitly trusted flows **approved → paid hands-free** (the cascade issues the Payment Entry with no human click), and the pilot's intent is to **grow that trusted set** so routine, in-policy disbursements need no human. For everyone else the cascade **pauses for a single human "Pay" click** — the exception path, not the default mindset. The flag ships **OFF** so the safe boundary (real money) is opt-in, but the goal is more auto, not less. The spec also replaces the guard-only idempotency with a real idempotency key on the Payment Entry insert (via [[01-foundations-settings-async-idempotency]]), and specs the deferred phase-2 rail seam `issue_real_payment_for(capture, rail)` — where the **real external rail** is the one place extra care applies (the mock/dev path flows freely). For **Stream R (already-paid receipts)** this step is a **no-op**: a short-circuit asserts the offsetting Journal Entry from [[07-classification-doctype-branching]] is already submitted, sets `payment_lifecycle_status = "Confirmed"`, creates no Payment Entry, and advances directly to [[13-bank-feed-reconciliation]]. Current-state delta: today the cascade **auto-pays every** approved+ready capture (gated only by test flags) with **no per-supplier trust signal** — this spec makes auto-pay a **per-supplier trust decision** (`auto_pay_eligible`) rather than an all-or-nothing default, and adds **key-based idempotency**, the **rail seam**, and the **stream concept** the controller lacks today.

## 2. Plan alignment
From `docs/planning/workflow-v2-plan.md`, **Step 11 — Payment Execution — Stream I only, automation is secondary**:

> **Applies only to Stream I (unpaid invoices and employee expense claims).** For Stream R receipts this step is a no-op (the money already moved on the card; advance directly to step 12).
>
> For invoices, the approved Purchase Invoice triggers a Payment Entry — either via the configured payment rail (ACH, check, card) or a controlled mock execution in pilot environments. Automation of the disbursement leg is **explicitly a phase-2 goal, not phase 1** … The phase-1 default is **"approved Purchase Invoice → human triggers Payment Entry → Payment Entry recorded in ERPNext"**, with full automation behind a per-supplier `auto_pay_eligible` flag set off by default. The bank-feed match in step 12 still confirms closure regardless of whether the Payment Entry was triggered automatically or manually.
>
> For employee reimbursements, the Expense Claim is paid out via Payment Entry on the configured cadence — same human-trigger default in phase 1.

Control-Summary rows this spec implements:

> | Idempotency keys on all posting operations | Throughout | Prevents duplicate Suppliers / PIs / Payment Entries from retried jobs |
> | Bank-feed match for closure | Step 12 | External confirmation of money movement |

And the design principle:

> **Closure comes from outside.** "Mock payment issued" or "payment entry submitted" is internal confirmation. The transaction is not closed until the bank feed confirms the money moved.

**Stream R vs Stream I divergence (the core of this spec):**
- **Stream I (in scope):** approved + ready Purchase Invoice → (human trigger by default; `auto_pay_eligible` suppliers via cascade) → Payment Entry recorded. This is the only stream that creates a Payment Entry.
- **Stream R (no-op):** money already moved on the card; the offsetting Journal Entry was already posted at Step 6 ([[07-classification-doctype-branching]]). This step does NOT authorize, does NOT pay, does NOT create a Payment Entry — it asserts the JE is submitted, marks `payment_lifecycle_status = "Confirmed"`, and advances to [[13-bank-feed-reconciliation]] for the bank-feed match that closes it.
- **Stream R-employee (Expense Claim):** DEFERRED with `hrms` (the `hrms` app is absent on this bench — see [[07-classification-doctype-branching]] §3). The Expense-Claim → Payment-Entry payout path is specced as a phase-2 hook only.

## 3. Current state
Verified against the code on branch `russ/migrateToV16` (not memory). All live code is in `erpnext/accounts/doctype/document_capture/document_capture.py`; a parallel prototype lives in `erpnext/accounts/ap_closed_loop/walking_skeleton.py` (NOT the live path).

**A) Constants** (`document_capture.py:81-91`): `MOCK_PAYMENT_PROVIDER="mock_payment_provider"` (:81), `MOCK_PAYMENT_PREFIX="MOCK-PAY"` (:82), `MOCK_CLEARING_ACCOUNT_DEFAULT="_Test Bank - _TC"` (:83 — a **test** account; no real pilot/prod bank account is configured), `MOCK_PAYMENT_REMARK` (:84-86), lifecycle constants `PAYMENT_LIFECYCLE_NOT_REQUESTED/_CONFIRMED/_CLOSED/_BLOCKED` (:88-91). `MANAGER_APPROVAL_ROLE_DEFAULT="Accounts Manager"` (:79) is the authorization boundary.

**B) Core function** — `issue_mock_payment(capture, actor=None, paid_from=None, save=True) -> Document` (`document_capture.py:1426-1504`). Flow: coerce str→doc (:1436); `frappe.only_for(MANAGER_APPROVAL_ROLE_DEFAULT)` (:1441) — manager-role gate; guards `is_ready_for_payment` (:1443), PI exists (:1447), and the **existence-based idempotency guard** `if capture.payment_entry:` → raise `CapturePaymentError` (:1449-1452); submit PI if draft (:1454-1462); `pe = get_payment_entry("Purchase Invoice", pi.name, bank_account=mock_account)` (:1465); override `pe.paid_from`, `pe.reference_no = f"{MOCK_PAYMENT_PREFIX}-{capture.name}"` (:1467), `reference_date`, `custom_remarks=1`, `remarks=MOCK_PAYMENT_REMARK`; `pe.insert(ignore_permissions=True)` + `pe.submit()` (:1474-1475); build JSON `response` with `status="confirmed-mock"` (:1478-1489); write back `payment_entry`, `mock_payment_*`, `payment_lifecycle_status = _derive_payment_lifecycle_status(capture)` (:1498), clear `action_required` (:1499).

**C) Whitelisted entrypoint** — `issue_mock_payment_for(capture, paid_from=None) -> str` (`document_capture.py:1734-1744`): returns `pe.name`, then `cap._kick_next_step()` (terminal no-op today).

**D) Lifecycle derivation** — `_derive_payment_lifecycle_status(capture)` (`document_capture.py:1402-1423`): `Blocked` if `is_payment_blocked`; `"Not Requested"` if no PE; `"Closed"` if PI docstatus==1 AND PE docstatus==1 AND `outstanding_amount==0` AND PI status=="Paid"; else `"Confirmed"`. **The mock path drives straight to "Closed"** because the PE fully pays the PI synchronously — there is no intermediate "recorded-but-not-bank-cleared" state today.

**E) Predicates** — `is_ready_for_payment` (:1365-1375): `approval_status in {Auto Approved, Manager Approved}` AND `payment_readiness=="Ready for Payment"`. `is_payment_blocked` (:1378-1385): `approval_status=="Rejected"` OR `payment_readiness=="Blocked"`.

**F) THE CASCADE CONTRADICTION (highest-priority fix).** `_determine_next_step` **Step 4** (`document_capture.py:357-364`) already auto-enqueues `issue_mock_payment_for` whenever `approval_status in {Auto Approved, Manager Approved}` AND `payment_readiness=="Ready for Payment"` AND `not payment_entry` — gated **only** by the test flags `skip_ap_auto_progress` / `ap_auto_progress_enabled` (:308-313). **This auto-pays everything, which directly violates the phase-1 "human triggers payment" default.** This spec must gate Step 4 on the supplier's `auto_pay_eligible`.

**G) Error type** — `CapturePaymentError(frappe.ValidationError)` (:140-142).

**H) Bank-transaction seam** — `_bank_transaction_count_for_payment_entry(payment_entry)` (:1393-1399) and `build_closure_evidence`'s `closure_basis` invariant "Bank Transaction count must remain 0" (:1626-1630) are the seam [[13-bank-feed-reconciliation]] plugs into.

**I) Payment field set already present** on Document Capture (`document_capture.py:225-234`): `payment_entry` (Link Payment Entry), `mock_payment_provider/reference/status` (Data), `mock_payment_amount` (Float), `mock_payment_issued_at` (Datetime), `mock_payment_response` (LongText), `payment_lifecycle_status` (Literal `Not Requested|Confirmed|Closed|Blocked`). **Treat these as the existing closure-evidence surface — do not rename.**

**J) Walking skeleton (prototype, not live)** — `create_mock_payment_entry(pi, paid_from)` (`walking_skeleton.py:220-248`) uses status `"settled-mock"` (:244) vs the live `"confirmed-mock"` (:1481). A known divergence; out of this spec's build scope but flagged in §8.

**K) NOT PRESENT (greenfield for this spec):**
- **No `auto_pay_eligible` Custom Field** on Supplier (grep across `erpnext/` returns nothing). No "coding profile" doctype exists.
- **No `fixtures` key in `erpnext/hooks.py`** (grep: zero hits). Shipping a Supplier Custom Field via the `fixtures` mechanism is a **net-new pattern** for this fork.
- **No `issue_real_payment_for(capture, rail)` seam**; only mock is wired. No rail enum.
- **No Stream R / "already-paid no-op" payment function**; no `stream`/`classified_stream` field on the capture (that field is owned by [[02-intake-stream-tagging]] / [[07-classification-doctype-branching]] and does not exist yet). The capture is implicitly Stream I.
- **No explicit idempotency KEY**; idempotency today = the `if capture.payment_entry:` existence guard (:1449) + the enqueue-layer `deduplicate=True` / `job_id` (:400-401). No unique-key constraint on the PE insert.
- **No employee reimbursement / Expense Claim payout path** (deferred with `hrms`).

**Correction to the brief:** none. The code matches the brief at every cited line (`issue_mock_payment` :1426-1504, the cascade Step 4 :357-364, `get_payment_entry` consumed at :1465, the `only_for` gate :1441, the existence guard :1449). The one item to re-state precisely: the brief calls the existence guard "the idempotency guard" — it is a **guard, not a key**; it cannot survive a retried job that runs before the first commit (see §8 / Risk 5).

## 4. Upstream grounding
Mandatory grounding evidence. Each citation: URL + what it confirms + the quoted signature/section.

| # | URL | Confirms | Quoted signature / section |
|---|-----|----------|----------------------------|
| 1 | https://docs.frappe.io/erpnext/user/manual/en/payment-entry | **Payment Entry is the doctype that records a supplier payment against a Purchase Invoice**, and the **phase-1 human-trigger flow** is native: a human clicks Create → Payment on the submitted PI. Confirms `paid_from`/`paid_to` default from the Company form (the account the fork overrides), the Reference section links outstanding invoices, and **on submission the PI outstanding updates** — the `outstanding_amount==0` → status `Paid` transition `_derive_payment_lifecycle_status` (:1402) depends on. | "On submitting a document against which Payment Entry can be made, you will find the Payment option under the Create button. … The Account Paid To and Account Paid From will be fetched as set in the Company form. … On submission, outstanding will be updated in the Invoices." |
| 2 | https://docs.frappe.io/erpnext/user/manual/en/payment-order + erpnext/accounts/doctype/payment_order (in-repo source) | **Payment Order is the native ERPNext batch wrapper for bulk supplier disbursement** — the correct anchor for the phase-2 real ACH/check rail. It is **submittable**, carries a `references` child table, and exposes `make_payment_records` (groups/produces the Payment Entries + accounting records). **It does NOT document or generate ACH, NACHA, or bank files**, confirming real-rail **file** generation is **not** a built-in ERPNext capability and must be a fork/external-integration concern layered on top of the Payment Order (validates the phase-2 "does the bank support ACH origination" open question). | "A Payment Order is an internal document to record bulk payments against Suppliers." + `references` child, `make_payment_records` |
| 3 | https://docs.frappe.io/erpnext/user/manual/en/bank-account | **Bank Account links a company bank account to its GL Account** — the account used as `paid_from` on a Payment Entry. Grounds the requirement to replace the test-only `MOCK_CLEARING_ACCOUNT_DEFAULT="_Test Bank - _TC"` with a real configured company Bank Account's GL account for any pilot run. | "How to create a Bank Account … Link the General Ledger account set in 'Bank Accounts' in the Chart of Accounts … enabling 'Is the Default Account' will designate this Bank Account as the default for all journal transactions." |
| 4 | https://github.com/frappe/erpnext/blob/develop/erpnext/accounts/doctype/payment_entry/payment_entry.py | **Canonical source of `get_payment_entry`**, the whitelisted helper the fork calls at `document_capture.py:1465`. Signature **verified against the in-repo checked-out source** (`payment_entry.py:2858-2869`): the `bank_account` param seeds the `paid_from`/`paid_to` bank GL account; `payment_type` defaults via `set_party_type(dt)` to `Pay` for a Purchase Invoice. (The GitHub blob fetch paginated before the `def` line, so the upstream-URL citation is `verified=false`; the quoted signature is from the local source which is what ships.) | `@frappe.whitelist()` `def get_payment_entry(dt, dn, party_amount=None, bank_account=None, bank_amount=None, party_type=None, payment_type=None, reference_date=None, created_from_payment_request=False):` |
| 5 | https://docs.frappe.io/framework/v15/user/en/python-api/hooks | **`fixtures` registration** — how the Supplier `auto_pay_eligible` Custom Field ships with the app (the `fixtures` hook exports/imports DocType records, including `Custom Field`, filtered by criteria). Grounds the net-new fixtures pattern for this fork. | "`fixtures` … You can export records from any DocType as fixtures. … `fixtures = [{"dt": "Custom Field", "filters": [["name", "in", [ ... ]]]}]`" |
| 6 | https://docs.frappe.io/framework/v15/user/en/python-api/document#frappeonly_for | **`frappe.only_for(roles)` semantics** — throws `PermissionError` if the current user has none of the given roles; bypassed when `frappe.flags.in_test`/admin per framework rules. Grounds the human-trigger role boundary (:1441) AND the requirement to NOT call `only_for` on the system-worker auto-pay path. | "`frappe.only_for(roles, message=False)` — Raise an exception (`frappe.PermissionError`) if the current user does not have any of the given roles." |
| 7 | erpnext/accounts/doctype/payment_request/payment_request.py (in-repo source, v16) | **Native `Payment Request` was WEIGHED as the human-trigger surface and reasonably rejected for phase-1.** It is submittable; for a Purchase Invoice it DEFAULTS `payment_request_type="Outward"` (`:687`), and its `create_payment_entry` (`:347`) handles `reference_doctype=="Purchase Invoice"` (party_account = `ref_doc.credit_to`) by delegating to native `get_payment_entry`. **But** it is gateway-centric (`request_phone_payment` / `payment_url` / `set_as_paid` driven by gateway callbacks) and its `on_submit` does **NOT** auto-create a Payment Entry — adopting it adds a doctype + gateway-account config the mock path does not need. Confirms the custom human-trigger is a deliberate choice, not a silent reinvention (see §5.3 and D-12-9). | `def set_as_paid(...)`, `payment_request_type` default `"Outward"` for PI (`:687`), `create_payment_entry` handles `reference_doctype=="Purchase Invoice"` (`:347`) |

> **Version-verification note (build phase):** runtime frappe is v16 (per [[01-foundations-settings-async-idempotency]] §3-H, frappe 16.18.3); CLAUDE.md mandates v15 doc citations. Re-confirm `get_payment_entry`'s `bank_account`/`payment_type` params, `frappe.only_for`, and `pe.insert(ignore_permissions=True)` semantics against the installed frappe before finalizing. The `get_payment_entry` signature was read from the **shipping** local source, so it is authoritative for what runs.

## 5. Design

### 5.1 Data model

#### (A) NEW Custom Field on `Supplier` — `auto_pay_eligible` (the automation lever; opt-in, default OFF)
Shipped as a **Custom Field fixture** (not a Supplier core JSON edit), so it travels with the app. This establishes the first Supplier Custom Field fixture in the fork. **This flag is the automation lever of the spec:** flipping it ON for a trusted vendor moves that vendor's approved, in-policy invoices to a hands-free pay path. It defaults OFF only because the boundary it crosses is real money; the operating intent is to **grow the set of `auto_pay_eligible` suppliers** so the routine case needs no human — not to keep the flag off.

| fieldname | fieldtype | options / default | purpose |
|---|---|---|---|
| `auto_pay_eligible` | Check | default `0` | When `1`, an approved+ready Stream-I capture for this supplier may be paid **automatically** by the cascade (bypassing the human trigger). When `0` (the default), payment requires a human (Accounts Manager) click. Label: "Auto-Pay Eligible (AP Closed Loop)". `insert_after` a stable buying-section field (recommend `default_currency` or `payment_terms`; lock the anchor in §8 D-12-2). `dt="Supplier"`, `module="Accounts"`. |

Delivery: add a `fixtures` entry to `erpnext/hooks.py` (net-new key — see §3-K) filtered to this Custom Field, e.g. `{"dt": "Custom Field", "filters": [["name", "in", ["Supplier-auto_pay_eligible"]]]}`, and export the fixture JSON under `erpnext/accounts/` (the AP closed-loop module). **Net-new fixture plumbing (verified):** `erpnext/hooks.py` has **NO `fixtures` key today** (grep: zero hits — §3-K) and **NO `auto_pay_eligible` field exists anywhere** in `erpnext/` (grep: zero hits — §3-K), so this is the fork's **first** Supplier Custom Field fixture and the **first use of the `fixtures` hook** — both the key and the field are net-new. **Anchor must be verified at build time:** the recommended `insert_after="default_currency"` (D-12-2) assumes `default_currency` is a real field on the Supplier doctype — **confirm the anchor exists on Supplier before shipping** (read the Supplier DocType JSON / `frappe.get_meta("Supplier")`); if `default_currency` has moved or been renamed on v16, the Custom Field will fail to place. **Alternative home (noted, not chosen for phase-1):** a field on a per-supplier "coding profile" doctype if [[06-gl-coding-tax-costcenter]] introduces one — rejected for phase-1 to avoid a new cross-spec dependency; the Supplier Custom Field is self-contained.

#### (B) NEW field on `Document Capture` — `payment_rail_used` (audit, written at issuance)
| fieldname | fieldtype | options / default | purpose |
|---|---|---|---|
| `payment_rail_used` | Data | default empty; written `"mock"` at issuance | Records which rail issued the payment, for audit (`build_closure_evidence` + [[14-closure-audit-retention]]). Phase-1 always `"mock"`. **NOT** a Select with ACH/check/card options — the rail is a function arg until a real rail lands (see §8 D-12-3). Declare in the DocType JSON + the auto-generated `DF` block (`payment_rail_used: DF.Data | None`). |

#### (C) `payment_lifecycle_status` — add `"Bank Cleared"` value (Literal change; migrate-affecting)
Today the Literal is `["Not Requested", "Confirmed", "Closed", "Blocked"]` (`document_capture.py:232-234`). For real (async) rails the PE is *recorded* (`"Confirmed"`) before it is *bank-matched*. This spec **adds `"Bank Cleared"`** so the enum distinguishes:
- `Confirmed` = a Payment Entry is recorded in the ledger (PE submitted) but not yet matched to a bank transaction.
- `Bank Cleared` = the [[13-bank-feed-reconciliation]] match has landed (the true reconciliation).

| value | meaning | who sets it |
|---|---|---|
| `Not Requested` | no PE yet (unchanged) | this spec / today |
| `Confirmed` | PE recorded OR Stream-R offsetting JE submitted, not bank-matched | this spec |
| `Bank Cleared` | bank-feed match landed | [[13-bank-feed-reconciliation]] |
| `Closed` | retained for back-compat — PI fully paid in ledger (see §8 D-12-4) | today's `_derive_payment_lifecycle_status` |
| `Blocked` | payment blocked (unchanged) | today |

**Decision D-12-4 governs whether the mock path keeps emitting `Closed` or switches to `Confirmed`** so the mock loop also waits on [[13-bank-feed-reconciliation]]. Recommended: keep `Closed` for the synchronous mock-fully-paid case in phase-1 (no behavior regression for the existing closure tests), and reserve `Confirmed → Bank Cleared` for real async rails; revisit when [[13-bank-feed-reconciliation]] retires the "Bank Transaction count must remain 0" guardrail. **This is a Literal + JSON `options` change → migrate-affecting; sequence behind a `[post_model_sync]` note.**

#### (D) Idempotency key on the Payment Entry insert (via [[01-foundations-settings-async-idempotency]])
[[01-foundations-settings-async-idempotency]] ships `with_idempotency(key, fn)` + the `AP Posting Ledger` DocType + `idempotency.generate_key(...) -> sha256 hex`. This spec **consumes that primitive** rather than inventing a per-capture field. The Payment Entry creation is wrapped so a retried/duplicated job that runs before the first commit finds the recorded key and returns the existing PE instead of inserting a second one.

- **Key shape:** `generate_key("payment_entry", capture.name)` (deterministic, one PE per capture). This aligns with the existing `reference_no = "MOCK-PAY-{capture.name}"` shape but is computed by the shared helper so all v2 posting steps share one ledger.
- **No new per-capture `payment_idempotency_key` field is needed** if foundations' ledger is the store. **Fallback** (only if [[01-foundations-settings-async-idempotency]] slips): add `payment_idempotency_key` (Data, unique) to the capture and look the PE up by it before insert. Lock in §8 D-12-5.

#### (E) Stream R — no schema change
The no-op path reads `classified_stream` (Select `I`/`R`/`R-employee`, owned by [[07-classification-doctype-branching]] §5.1) and `journal_entry` (Link Journal Entry, also [[07-classification-doctype-branching]]). No new field here. If those fields have not landed, the controller treats every capture as Stream I (current behavior) — see §9.

#### Permissions
No new role on this surface. The human-trigger boundary stays `frappe.only_for("Accounts Manager")` (the `Accounts Manager` role, `MANAGER_APPROVAL_ROLE_DEFAULT`). The Supplier Custom Field inherits Supplier doctype permissions (a `Purchase Master Manager` / `Accounts Manager` maintains it). The auto-pay path runs in the **system-worker** context and is a trusted system action (no `only_for`) — see §5.3.

### 5.2 Endpoints
All whitelisted methods live in `erpnext.accounts.doctype.document_capture.document_capture`. Normalization convention mirrors the existing wrappers (`record_manager_decision_for` :1719-1731 coerces str→bool; `promote_to_purchase_invoice_for` :1686-1702 parses str/dict `defaults`): every entrypoint accepts the capture as a `str` name, coerces scalar string args, calls the pure function, reloads the capture, calls `_kick_next_step()`, and returns a `str`.

```python
@frappe.whitelist()
def issue_mock_payment_for(capture: str, paid_from: str | None = None) -> str:
    """EXISTING (document_capture.py:1734). Human-trigger mock payment.
    Unchanged signature; now delegated to by issue_real_payment_for(rail="mock").
    Returns the Payment Entry name."""

@frappe.whitelist()
def issue_real_payment_for(
    capture: str,
    rail: str = "mock",
    paid_from: str | None = None,
) -> str:
    """NEW. The phase-2 rail seam. Dispatch on `rail`:
      - "mock"  -> delegate to issue_mock_payment (the only wired rail in phase-1).
      - "ACH"   -> phase-2: enqueue/append to a Payment Order then emit NACHA. NOT WIRED.
      - "check" -> phase-2: check-print / positive-pay. NOT WIRED.
      - "card"  -> phase-2. NOT WIRED.
      - unknown -> raise CapturePaymentError.
    Each non-mock branch raises CapturePaymentError(f"rail {rail} is phase-2, not wired")
    so callers fail loud. Writes capture.payment_rail_used at issuance.
    Returns the Payment Entry name (mock) — non-mock branches never return.
    `rail` is coerced: rail = (rail or "mock").strip().lower()."""

@frappe.whitelist()
def confirm_already_paid_for(capture: str) -> str:
    """NEW. Stream-R no-op confirmation. Asserts the offsetting Journal Entry
    from [[07-classification-doctype-branching]] is docstatus==1, sets
    payment_lifecycle_status="Confirmed", creates NO Payment Entry, calls
    _kick_next_step() (advances toward [[13-bank-feed-reconciliation]]).
    Returns the capture name. Raises CapturePaymentError if the JE is not submitted."""
```

Pure (non-whitelisted) functions the wrappers call:
- `issue_mock_payment(capture, actor=None, paid_from=None, save=True) -> Document` — **EXISTING** (:1426). Changes in §5.3: wrap the PE create in `with_idempotency`; branch the `only_for` by caller context.
- `confirm_already_paid(capture, save=True) -> Document` — **NEW**, the Stream-R pure function (§5.3).
- `issue_real_payment_for` dispatch helper may be a thin module function `_dispatch_payment_rail(capture, rail, paid_from)`.

### 5.3 Logic

**(1) Phase-1 default — human-triggered PE (Stream I).** `issue_mock_payment` (:1426) stays the manual, manager-gated, single-button action. The behavioral change for phase-1 correctness is in the **cascade** (point 4), not in `issue_mock_payment` itself. Idempotency hardening (point 5) and the `only_for` context branch (point 6) are the two in-function changes.

> **Native `Payment Request` weighed and reasonably rejected for phase-1 (so the custom human-trigger is a deliberate choice, not a silent reinvention).** ERPNext ships a submittable `Payment Request` (`erpnext/accounts/doctype/payment_request/payment_request.py`) that already understands Purchase Invoices: it DEFAULTS `payment_request_type="Outward"` for a PI (`:687`), and its `create_payment_entry` (`:347`) handles `reference_doctype=="Purchase Invoice"` (party_account = `ref_doc.credit_to`) by delegating to the same native `get_payment_entry` the fork calls. It was considered as the phase-1 trigger surface and **rejected** because (a) it is **gateway-centric** — `request_phone_payment` / `payment_url` / `set_as_paid` are driven by external payment-gateway callbacks, none of which the mock path uses; and (b) its `on_submit` does **NOT** auto-create a Payment Entry (the PE is a separate explicit step), so adopting it would add a doctype **plus** gateway-account configuration the mock/human-trigger path does not need, with no phase-1 benefit. The fork's `issue_mock_payment` → `get_payment_entry` path is the lighter, self-contained choice. **Re-evaluate** `Payment Request` if/when a real gateway rail lands in phase-2 (it becomes the natural origination surface then) — see D-12-9.

**(2) Rail seam — `issue_real_payment_for(capture, rail="mock", paid_from=None)`.**
1. `rail = (rail or "mock").strip().lower()`.
2. If `rail == "mock"` → `pe = issue_mock_payment(capture, paid_from=paid_from)`; set `capture.payment_rail_used = "mock"`; persist; return `pe.name`.
3. If `rail in {"ach", "check", "card"}` → raise `CapturePaymentError(_("rail {0} is phase-2, not wired").format(rail))`.
4. Else (unknown) → raise `CapturePaymentError(_("Unknown payment rail {0}.").format(rail))`.
- **Persisted:** `payment_rail_used` for the mock branch; nothing for the raising branches (loud failure, no partial state).
- **Native batching anchor for the deferred real rail (affirmed):** the phase-2 ACH/check rail seam anchors on native **`Payment Order`** (`erpnext/accounts/doctype/payment_order` — submittable, with a `references` child table and `make_payment_records`). `Payment Order` is the correct surface to **group/batch** Payment Entries and produce the accompanying accounting records, but it does **NOT** generate NACHA/ACH bank files (confirmed citation #2). So when `rail in {"ACH", "check"}` is wired in phase-2, the build appends to a `Payment Order` for batching and grouping, and the **actual NACHA/ACH file generation remains net-new external integration** layered on top — `Payment Order` does not emit it.
- **Phase-2 dependency questions to record (NOT resolved now):** does the bank support ACH origination from the Mercury/SimpleFIN-connected account? Is there a check-printer for the check rail? Which rail is cheapest? ERPNext's Payment Order (citation #2) batches payments / groups PEs but does NOT generate NACHA/ACH files — real-rail file generation is a net-new integration.

**(3) Stream R no-op — `confirm_already_paid(capture)`.**
1. Coerce str→doc.
2. **Guard stream:** if `capture.classified_stream != "R"` → raise `CapturePaymentError(_("confirm_already_paid is Stream-R only; capture {0} is {1}.").format(...))`. (If `classified_stream` is absent because [[07-classification-doctype-branching]] has not landed, this path is unreachable — the cascade never routes here; see §9.)
3. **Assert the offsetting Journal Entry is submitted:** read `capture.journal_entry`; if missing → raise `CapturePaymentError(_("Stream-R capture {0} has no offsetting Journal Entry."))`. Read its `docstatus`; if `!= 1` → raise `CapturePaymentError(_("Offsetting Journal Entry {0} is not submitted."))`. (Spec 07 may also post a PI + Credit-Card-Clearing PE variant — accept either: assert whichever offsetting voucher the capture carries is `docstatus==1`.)
4. **Create NO Payment Entry.** Set `capture.payment_lifecycle_status = "Confirmed"` (NOT `Closed` — the [[13-bank-feed-reconciliation]] match closes it to `Bank Cleared`). Clear `action_required`.
5. Persist (when `save`). The whitelisted `confirm_already_paid_for` then calls `_kick_next_step()`, which advances toward bank-feed reconciliation.
- **Idempotency:** re-running on an already-Confirmed Stream-R capture is a safe no-op (re-asserts the JE is submitted, re-sets the same status); it does NOT need the posting ledger because it creates no document.

**(4) Cascade gate — the automation lever (`_determine_next_step` Step 4, :357-364).** Replace the unconditional Step-4 auto-pay (which trusts *every* supplier) with a **stream-aware, `auto_pay_eligible`-gated** branch that trusts the suppliers a controller has *explicitly* trusted. The trusted branch is the **goal state** (hands-free pay); the pause is the exception for not-yet-trusted vendors:
1. Resolve the capture's stream: `stream = capture.classified_stream` (fallback: treat as `"I"` when the field is absent — current behavior).
2. **Stream R branch:** if `stream == "R"` and the offsetting JE is submitted and `payment_lifecycle_status != "Confirmed"` → return `("confirm_already_paid_for", "auto: Stream-R no-op confirmation")`. (No PE; advance toward [[13-bank-feed-reconciliation]].)
3. **Stream I branch:** if approved (`approval_status in {Auto Approved, Manager Approved}`) AND `payment_readiness == "Ready for Payment"` AND `not payment_entry`:
   - Look up the linked supplier (`capture.matched_supplier` / `final_supplier`) and read `auto_pay_eligible`.
   - **If `auto_pay_eligible == 1`** → return `("issue_mock_payment_for", "auto: post-approval payment issuance (auto-pay supplier)")` — the cascade pays automatically.
   - **If `auto_pay_eligible == 0` (default)** → return `None` (PAUSE). The capture parks at `payment_readiness="Ready for Payment"`, `payment_lifecycle_status="Not Requested"` until a human (Accounts Manager) clicks the button (`issue_mock_payment_for` / `issue_real_payment_for`).
- **What persists:** nothing in the pause case (the cascade simply does not enqueue). In the auto-pay case, the enqueued `issue_mock_payment_for` does the writeback exactly as today.

**(5) Idempotency on the PE insert (Stream I).** Inside `issue_mock_payment`, **before** `get_payment_entry` (:1465), wrap the create-and-submit in `with_idempotency` from [[01-foundations-settings-async-idempotency]]:
1. `key = idempotency.generate_key("payment_entry", capture.name)`.
2. `pe_name = with_idempotency(key, lambda: _create_and_submit_mock_pe(capture, paid_from))`.
3. `with_idempotency` records `key` in `AP Posting Ledger` on first success and, on a second call with the same key, **returns the recorded PE name without inserting** — so a retried job before the first commit cannot double-insert. The existing `if capture.payment_entry:` guard (:1449) remains as the cheap first-line check; the ledger is the race-proof backstop. Pair with the existing `enqueue_after_commit=True` + `deduplicate=True` / `job_id` at the enqueue layer (:395-404).
- **Persisted:** the `AP Posting Ledger` row (owned by foundations) + the existing capture writeback. The Payment Entry's `reference_no = "MOCK-PAY-{capture.name}"` stays the human-readable correlation handle.

**(6) Authorization branch by caller context.** Preserve `frappe.only_for(MANAGER_APPROVAL_ROLE_DEFAULT)` (:1441) for the **human** trigger. The **auto-pay** path runs from the system-worker (`_run_cascade_step`), where the session user is the system user and `only_for("Accounts Manager")` would raise `PermissionError` — **the flag would be dead on arrival.** Branch:
1. Add an `actor`/context parameter (or read `frappe.session.user`): when the call originates from the cascade (trusted system action), **skip `only_for`**; when it originates from a direct UI/API call, **enforce `only_for`**.
2. Recommended mechanism (lock in §8 D-12-6): `issue_mock_payment(..., enforce_role: bool = True)`; the cascade wrapper passes `enforce_role=False`; the whitelisted `issue_mock_payment_for` / `issue_real_payment_for` pass `enforce_role=True`. The PE-create permission is already bypassed by `pe.insert(ignore_permissions=True)` (:1474) in both paths — only the function-level role gate needs the branch.

**(7) Lifecycle after payment.** After a mock PE submits and fully pays the PI, `_derive_payment_lifecycle_status` (:1402) returns `"Closed"` (synchronous mock). For a future real async rail where the PE is recorded but not yet bank-cleared, the intended status is `"Confirmed"`, flipping to `"Bank Cleared"` on the [[13-bank-feed-reconciliation]] match. Make explicit in the build: `"Closed"` today **conflates** "PI fully paid in ledger" with "reconciled"; the bank-feed match is the true reconciliation (§8 D-12-4).

### 5.4 Cascade & stream-awareness
- **Insertion point:** `_determine_next_step` Step 4 (`document_capture.py:357-364`) is replaced by the stream-aware, gated branch in §5.3-(4). This is the ONLY cascade change.
- **Stream I, `auto_pay_eligible=0` (default):** the cascade PAUSES after approval. A human triggers payment. This is the phase-1 default and the highest-priority correctness item (today it auto-pays — see §3-F).
- **Stream I, `auto_pay_eligible=1`:** the cascade AUTO-issues the PE (no human), then is terminal (`_kick_next_step` no-op today; [[13-bank-feed-reconciliation]] will add the next hop).
- **Stream R:** the cascade routes to `confirm_already_paid_for` (no PE), sets `Confirmed`, and the next hop is [[13-bank-feed-reconciliation]]. Step 11 is otherwise a no-op for Stream R per the plan.
- **Stream R-employee:** DEFERRED with `hrms` — routed to Manual Review by [[07-classification-doctype-branching]]; never reaches this step in phase-1.

### 5.5 Cross-cutting
- **Permissions / SoD:** the human-trigger `only_for("Accounts Manager")` is the authorization boundary; the auto-pay path is a trusted system action (§5.3-6). SoD on the *approval* leg lives in [[11-approval-sod-workflow]] (Stream I); this spec consumes its `Manager Approved` outcome and does not re-implement approval.
- **Idempotency:** PE insert wrapped via [[01-foundations-settings-async-idempotency]] `with_idempotency` + `AP Posting Ledger` (§5.3-5).
- **Async / enqueue:** the cascade hop is enqueued exactly as today (`_enqueue_next` :368-404; `enqueue_after_commit`, `deduplicate`, per-capture-per-step `job_id`); under `in_test` it runs `now=True`.
- **Observability:** emit an `AP Review Event` (via [[10-ap-review-observability]]) when a human overrides the auto-pay decision or when a Stream-R confirmation fails its JE-submitted assertion (root-cause vocabulary owned by [[10-ap-review-observability]]). Auto-pay vs manual is a tuning signal for the auto-rate dashboard.
- **Bank-feed handoff:** [[13-bank-feed-reconciliation]] CONSUMES this step's output regardless of manual-vs-auto, flipping `Confirmed → Bank Cleared`. `_bank_transaction_count_for_payment_entry` (:1393) and the `closure_basis` invariant (:1626-1630) are the seam.

## 6. Acceptance criteria

- **AC-12-1 (phase-1 default pause).** A Supplier with `auto_pay_eligible=0` and an approved+ready Stream-I capture does NOT auto-issue a Payment Entry via the cascade: `capture.payment_entry` is empty and `payment_lifecycle_status == "Not Requested"` after the cascade settles. (Positive — proves the §3-F fix.)
- **AC-12-2 (human trigger works).** Calling `issue_mock_payment_for(capture)` as an `Accounts Manager` on that same capture creates exactly one submitted Payment Entry, sets `capture.payment_entry`, writes `payment_rail_used="mock"`, and the PI reaches `outstanding_amount==0` / status `Paid`. (Positive.)
- **AC-12-3 (auto-pay supplier).** A Supplier with `auto_pay_eligible=1` and an approved+ready Stream-I capture DOES auto-issue the Payment Entry via the cascade (no human call): `capture.payment_entry` is set. (Positive.)
- **AC-12-4 (role guard on human path).** A non-`Accounts Manager` user calling `issue_mock_payment_for` raises `frappe.PermissionError` (from `only_for` :1441). (Negative.)
- **AC-12-5 (auto-pay path bypasses role).** The cascade-originated auto-pay (system-worker context) does NOT raise `PermissionError`, even though the session user lacks the `Accounts Manager` role. (Edge — proves the §5.3-6 branch.)
- **AC-12-6 (idempotency, no duplicate).** A second `issue_real_payment_for(capture, rail="mock")` (or `issue_mock_payment_for`) returns the SAME Payment Entry name and the count of Payment Entry references against the PI stays `== 1`. (Positive — strengthens the existing guard test which only asserts the raise.)
- **AC-12-7 (idempotency under retry race).** A simulated retried/duplicated enqueue of the payment step (same `job_id`, before commit) does not create two Payment Entries. (Edge.)
- **AC-12-8 (rail seam — mock parity).** `issue_real_payment_for(capture, rail="mock")` behaves identically to `issue_mock_payment` (same PE, same writeback, same `MOCK-PAY-` reference). (Positive.)
- **AC-12-9 (rail seam — phase-2 keys).** For each `rail in {"ACH", "check", "card"}`, `issue_real_payment_for` raises `CapturePaymentError` whose message says phase-2 / not wired, and creates NO Payment Entry. (Negative, per registered key.)
- **AC-12-10 (rail seam — unknown key).** `issue_real_payment_for(capture, rail="venmo")` raises `CapturePaymentError`. (Negative, unknown key.)
- **AC-12-11 (Stream R no-op).** A Stream-R capture (`classified_stream="R"`) with a submitted offsetting Journal Entry → `confirm_already_paid_for` sets `payment_lifecycle_status == "Confirmed"`, creates NO Payment Entry (`capture.payment_entry` empty), and the cascade advances toward [[13-bank-feed-reconciliation]]. (Positive.)
- **AC-12-12 (Stream R guard — JE not submitted).** A Stream-R capture whose offsetting Journal Entry is NOT `docstatus==1` (or is missing) → `confirm_already_paid` raises `CapturePaymentError`. (Negative.)
- **AC-12-13 (Custom Field default OFF).** A freshly created Supplier has `auto_pay_eligible == 0`. (Edge — fixture default-off.)
- **AC-12-14 (no Bank Transaction on mock).** Issuing a mock Payment Entry creates zero `Bank Transaction` / `Bank Transaction Payments` rows (the [[13-bank-feed-reconciliation]] guardrail still holds in phase-1). (Edge — regression guard.)

## 7. Tests

### 7.1 Automated
Extend `erpnext/accounts/doctype/document_capture/test_document_capture.py` (base `from frappe.tests import IntegrationTestCase`; `frappe.db.rollback()` in `tearDown`; mirror the existing payment suite at :1054-1153). Run:
`bench --site <site> run-tests --module erpnext.accounts.doctype.document_capture.test_document_capture`

Cases by public function:
- **Cascade auto-pay gate** (`_determine_next_step` / cascade):
  - POSITIVE: `auto_pay_eligible=0` supplier → cascade does NOT issue a PE (AC-12-1); subsequent explicit `issue_mock_payment_for` does (AC-12-2).
  - POSITIVE: `auto_pay_eligible=1` supplier → cascade DOES issue a PE (AC-12-3).
  - EDGE: fresh Supplier defaults `auto_pay_eligible==0` (AC-12-13).
- **Authorization** (`issue_mock_payment` / `issue_mock_payment_for`):
  - NEGATIVE: non-Accounts-Manager on the human path raises `frappe.PermissionError` (AC-12-4).
  - EDGE: cascade/system-worker auto-pay does not raise (AC-12-5).
- **Idempotency** (`issue_mock_payment` / `issue_real_payment_for`):
  - POSITIVE: second call returns the same PE name; PI has exactly one PE reference (AC-12-6) — strengthen the existing `test_issue_mock_payment_is_idempotent_guard` (:1114) to assert **no duplicate row**, not just the raise.
  - EDGE: simulated concurrent/retried enqueue creates only one PE (AC-12-7).
- **Rail seam** (`issue_real_payment_for`):
  - POSITIVE: `rail="mock"` parity with `issue_mock_payment` (AC-12-8).
  - NEGATIVE per key: `rail in {ACH, check, card}` → `CapturePaymentError` "phase-2" (AC-12-9).
  - NEGATIVE unknown: `rail="venmo"` → `CapturePaymentError` (AC-12-10).
- **Stream R no-op** (`confirm_already_paid` / `confirm_already_paid_for`):
  - POSITIVE: Stream-R capture + submitted JE → `Confirmed`, no PE, advances (AC-12-11).
  - NEGATIVE: offsetting JE not `docstatus==1` → raises (AC-12-12).
- **Regression (existing green must stay green):** re-run the :1054-1153 suite unchanged — labeled-PE writeback (`confirm-mock`), native PI `Paid`/`outstanding=0`, no Bank Transaction (AC-12-14), `MOCK-PAY` prefix + remark, not-requested status.

### 7.2 Clean-room test plan
`test/testplans/payment-execution-stream-i.md` (one file; confirm the slug does not collide with existing files in `test/testplans/`). One-line scope: **phase-1 human-triggered Payment Entry + `auto_pay_eligible` per-supplier gate + Stream-R no-op confirmation + the `issue_real_payment_for` rail seam (mock wired, ACH/check/card raise), executed through the desk UI / whitelisted API on a fresh bench with one real configured company Bank Account replacing `_Test Bank - _TC`, verified against the DB (Payment Entry docstatus, PI outstanding/status, `capture.payment_lifecycle_status`, Bank Transaction count==0).** Required sections per CLAUDE.md: feature-under-test; branch `russ/migrateToV16` + commit SHA; environment setup (bench + erpnext on a fresh site, configure ONE company Bank Account whose GL account is used as `paid_from`, note no real banking keys needed since only mock is wired); test-data prerequisites (a Supplier with `auto_pay_eligible` OFF and one ON, an approved+ready Document Capture with a submitted PI, a Stream-R capture with a submitted offsetting Journal Entry); numbered cases mirroring AC-12-1..14 with full `issue_mock_payment_for` / `issue_real_payment_for` / `confirm_already_paid_for` payloads; cleanup (delete created PE + PI + JE + captures, roll back); pass/fail checklist (one row per AC).

### 7.3 UI testing (Playwright MCP)
Browser-driven verification of the desk UI this slice adds, via the **Playwright MCP** server. These are the UI steps of the §7.2 clean-room runbook.
- **Prereq:** Playwright MCP per `test/testplans/BROWSER-TESTING-SETUP.md` (`claude mcp list` must list `playwright`; restart after registering). `.mcp.json` / `.playwright-mcp/` gitignored.
- **Evidence:** screenshots to `test/testplans/screenshots/payment-execution-stream-i/<name>.png` (committed; pass as `filename`).
- **Source of truth stays the DB:** after every UI write, verify via `bench --site <site> mariadb` / `bench … execute`, then delete UI-created data.

**Scenarios** (`route → action → expected UI → DB assertion`):
- An approved Stream-I capture for a supplier with `auto_pay_eligible` OFF → it pauses for a human; the form shows the "Issue Payment" action; click it → a `Payment Entry` is created + submitted and `payment_lifecycle_status` updates; screenshot → DB-assert the PE exists + the lifecycle value.
- A Stream-R already-paid capture → the payment step is a no-op (no "Issue Payment" action; the offsetting voucher already submitted); screenshot the absent/disabled action → DB-assert no new PE created.

**Not browser-testable in this slice** (covered by §7.1/§7.2): the idempotency-key wrap on the PE insert, and the deferred real ACH/NACHA rails (phase-2, external) — §7.1.

## 8. Open decisions

- **D-12-1 (cascade gate — the must-fix).** Should the cascade pay automatically by default? **Options:** (a) pause unless `auto_pay_eligible=1` (phase-1 plan default); (b) keep auto-pay-all (current code, violates the plan). **Recommended default: (a).** **Owner:** AP lead + Russ. **Must lock:** before this spec is built — it is the highest-priority correctness item; shipping (b) silently auto-pays every supplier.
- **D-12-2 (Custom Field anchor + delivery).** Where does `auto_pay_eligible` sit on Supplier, and via what mechanism? **Options:** Custom Field fixture (recommended) vs Supplier core JSON edit; `insert_after` `default_currency` vs `payment_terms` vs another stable buying field. **Recommended default:** Custom Field fixture via `hooks.py` `fixtures` (net-new key), `insert_after="default_currency"`. **Verify the anchor exists on Supplier at build time** (`frappe.get_meta("Supplier")` — `default_currency` must be a real field on v16, or the Custom Field will not place); fall back to `payment_terms` or another confirmed stable buying-section field if it has moved. **Owner:** Russ. **Must lock:** at build start (the fixture name `Supplier-auto_pay_eligible` must be stable for the filter, and the `insert_after` anchor must be confirmed present).
- **D-12-3 (rail storage).** Stored `payment_rail` Select on the capture, or function-arg-only + audit `payment_rail_used`? **Options:** (a) arg-only + `payment_rail_used` Data written at issuance (recommended — minimal, no ACH/check config doctypes in phase-1); (b) a `payment_rail` Select field on the capture. **Recommended default: (a).** **Owner:** AP lead. **Must lock:** before the rail seam is built.
- **D-12-4 (lifecycle: `Closed` vs `Confirmed`/`Bank Cleared` for mock).** Does the synchronous mock path emit `Closed` (today) or `Confirmed` (waiting on [[13-bank-feed-reconciliation]])? **Options:** (a) keep `Closed` for mock-fully-paid in phase-1, add `Bank Cleared` only for real async rails (recommended — no regression to existing closure tests); (b) switch mock to `Confirmed` so it too waits on the bank-feed match. **Recommended default: (a).** **Owner:** AP lead + reconciliation owner. **Must lock:** jointly with [[13-bank-feed-reconciliation]] when it retires the "Bank Transaction count must remain 0" guardrail (the v2 split-closure work).
- **D-12-5 (idempotency store).** Consume [[01-foundations-settings-async-idempotency]]'s `with_idempotency` + `AP Posting Ledger`, or add a per-capture `payment_idempotency_key` (Data, unique)? **Options:** (a) foundations ledger (recommended — one ledger for all posting steps); (b) per-capture field (fallback if foundations slips). **Recommended default: (a).** **Owner:** foundations owner + Russ. **Must lock:** after [[01-foundations-settings-async-idempotency]] lands; if it slips, fall back to (b) for this spec only.
- **D-12-6 (role-bypass mechanism for auto-pay).** How does the auto-pay path skip `only_for`? **Options:** (a) an `enforce_role: bool` param on `issue_mock_payment` (cascade passes `False`, whitelisted wrappers pass `True`) — recommended; (b) detect system-user via `frappe.session.user`; (c) wrap the auto-pay call in a privileged context. **Recommended default: (a)** (explicit and testable). **Owner:** Russ. **Must lock:** before the cascade gate is built — without it the `auto_pay_eligible` flag is dead on arrival.
- **D-12-7 (pilot `paid_from` account).** What replaces `MOCK_CLEARING_ACCOUNT_DEFAULT="_Test Bank - _TC"` for pilot runs? **Options:** (a) resolve from a configured company default Bank Account's GL (per citation #3); (b) a new `pilot_paid_from_account` Link in `AP Closed Loop Settings`; (c) keep hard-coded test account. **Recommended default: (b)** — a settings Link consumed by `issue_mock_payment` when `paid_from` is not passed, falling back to (a) the company default Bank Account. **Owner:** AP lead. **Must lock:** before any pilot run beyond unit tests.
- **D-12-8 (phase-2 real rail — record only).** Which real rail (ACH/check/card) is phase-2 priority, and does the bank support ACH origination from the Mercury/SimpleFIN-connected account? **Options:** ACH-first (Payment Order + NACHA), check-first (printer/positive-pay), card. **Recommended default:** RECORD ONLY — do not resolve in phase-1; the seam raises `CapturePaymentError` for all three. **Owner:** Russ + Bryan (banking). **Must lock:** at phase-2 kickoff, not now.
- **D-12-9 (native `Payment Request` as the trigger surface — weighed, deferred).** Should the payment trigger be built on native `Payment Request` instead of the custom `issue_mock_payment` → `get_payment_entry` path? **Options:** (a) keep the custom human-trigger for phase-1 (recommended) — `Payment Request` is gateway-centric (`request_phone_payment`/`payment_url`/`set_as_paid`) and its `on_submit` does not auto-create a Payment Entry, so it adds a doctype + gateway-account config the mock path does not need; (b) adopt `Payment Request` now; (c) adopt it in phase-2 as the origination surface once a real gateway rail lands (it natively defaults `payment_request_type="Outward"` for PI `:687` and its `create_payment_entry` `:347` already handles `reference_doctype=="Purchase Invoice"`). **Recommended default: (a) for phase-1, (c) for phase-2.** Recorded here so the custom trigger is a documented deliberate choice, not a silent reinvention. **Owner:** AP lead + Russ. **Must lock:** revisit at phase-2 real-rail kickoff (D-12-8), not now.

## 9. Dependencies & sequencing

**Depends on (must land first):**
- [[01-foundations-settings-async-idempotency]] — the shared `with_idempotency` + `AP Posting Ledger` + `idempotency.generate_key` primitive for the PE insert. Today's code has only the existence guard (`document_capture.py:1449`). **Fallback** if it slips: per-capture `payment_idempotency_key` field (D-12-5).
- [[02-intake-stream-tagging]] / [[07-classification-doctype-branching]] — the `classified_stream` discriminator AND the `journal_entry` Link that the Stream-R no-op asserts on. **Neither exists today** (grep: zero hits for `stream`/`classified_stream`/`journal_entry` on the capture). **Without them the controller treats every capture as Stream I (current behavior)** and the Stream-R branch is unreachable — a hard prerequisite for the no-op path, but the Stream-I human-trigger + `auto_pay_eligible` + rail-seam work can ship independently.
- [[07-classification-doctype-branching]] — also owns the offsetting Journal Entry (Stream R) and the `hrms`-deferred Expense-Claim payout (employee reimbursements, out of phase-1 scope here).

**Unblocks / feeds into:**
- [[13-bank-feed-reconciliation]] — CONSUMES this step's Payment Entry (manual or auto) and flips `Confirmed → Bank Cleared`; it plugs into `_bank_transaction_count_for_payment_entry` (:1393) and the `closure_basis` invariant (:1626-1630), and retires the phase-1 "Bank Transaction count must remain 0" guardrail for the split-closure work.
- [[14-closure-audit-retention]] — reads `payment_rail_used` and the final lifecycle status into the audit trail.
- Stream R advances directly from this step to [[13-bank-feed-reconciliation]] (Step 11 is a no-op for Stream R).

**Cross-cutting same-commit obligations:**
- `erpnext/hooks.py` `fixtures` (net-new key) for the Supplier `auto_pay_eligible` Custom Field.
- `docs/architecture/FORK-CHANGES.md` + `docs/architecture/FORK-CHANGES-PLAIN.md` MUST be updated in the same commit (change touches `document_capture/` scope + adds a Supplier Custom Field) — paired per CLAUDE.md.
- The clean-room test plan `test/testplans/payment-execution-stream-i.md` ships in the same commit.

**Estimated size:** **M** (per IMPLEMENTATION-PLAN units). The Stream-I human-trigger gate + rail seam + idempotency wrap is the bulk; the Stream-R no-op is small but blocked on [[02-intake-stream-tagging]]/[[07-classification-doctype-branching]]. If the stream-dependent work is deferred, the Stream-I-only slice is **S–M**.
