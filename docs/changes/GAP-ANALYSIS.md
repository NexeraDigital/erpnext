# Gap Analysis — `NewUpdates.md` 13-Step AP Workflow

> **Scope:** maps the proposed 13-step AP automation workflow (`docs/changes/NewUpdates.md`) against what already exists in this repo (upstream ERPNext + the AP Closed Loop pilot in this fork).
>
> **Color legend:**
> - 🟢 **EXISTS** — usable as-is from upstream or this fork
> - 🟡 **PARTIAL** — exists in some form but needs extension to meet the proposed behavior
> - 🔴 **NEW** — does not exist anywhere in the repo; requires fresh development
>
> Cross-references: `erpnext/hooks.py`, `erpnext/accounts/doctype/document_capture/document_capture.py` (fork), `erpnext/accounts/doctype/bank_reconciliation_tool/`, `erpnext/accounts/doctype/payment_entry/`, `erpnext/accounts/doctype/purchase_invoice/`, `erpnext/buying/doctype/supplier/`, `erpnext/stock/doctype/purchase_receipt/`.

---

## 0. Open Question Up-Front

The doc's lead-in raises one **architecture decision that must be made before any new code**:

> For already-paid card receipts (step 6), do we want to post as a direct Journal Entry or as a Purchase Invoice against a "Credit Card Clearing" account?

Both paths are buildable on existing ERPNext primitives — `Journal Entry` and `Purchase Invoice` both already exist as native doctypes with full GL posting. This decision is **policy**, not capability, and is unresolved.

---

## 1. Receipt / Invoice Intake

**Proposed:** Email PDF, scanned paper, phone-camera photo, or vendor portal pull lands as an attached record the moment it arrives.

| Sub-capability | Status | Where it lives |
|---|---|---|
| Manual upload → capture record | 🟢 EXISTS | `Document Capture` doctype + `create_capture_from_uploaded_file()` (this fork) |
| Supported format gating (PDF/PNG/JPG/JPEG) | 🟢 EXISTS | `SUPPORTED_EXTENSIONS` + `is_supported_format` in `document_capture.py` |
| Source file timestamp + traceability (filename, URL, received_at) | 🟢 EXISTS | `source_file` (Link → File), `source_file_url`, `source_filename`, `received_at` |
| Email-in intake (drop into a mailbox → auto-create capture) | 🔴 NEW | Frappe `Email Account` + custom inbound hook required |
| Vendor portal pull (push from a third-party portal) | 🔴 NEW | No integration today; would be a new ingestion adapter |
| Phone-camera mobile path | 🟡 PARTIAL | Frappe's mobile app uploads to `File` — wiring that to `create_capture_from_uploaded_file` is small glue |

**New dev:** email-in ingestion, vendor-portal pull, mobile capture glue. The pilot today is `INTAKE_MANUAL_UPLOAD` only — `intake_channel` is already a `Literal["Manual ERPNext Upload"]` but the enum was deliberately written to be extended.

---

## 2. Pre-Extraction Deduplication

**Proposed:** Exact file-hash AND fuzzy near-duplicate check against the last 90 days.

| Sub-capability | Status | Where it lives |
|---|---|---|
| Per-file SHA-256 of uploaded artifact | 🔴 NEW | Today the only `sha256` use is the deterministic OCR seed (`_hash_bytes` in `document_capture.py:404`). The capture does **not** persist a hash of the actual file bytes. |
| Frappe `File` hash field | 🟢 EXISTS | Frappe's core `File` doctype already stores `content_hash` — usable as the exact-match key |
| 90-day lookback dedupe query | 🔴 NEW | No code today scans prior captures or files for matches |
| Fuzzy near-duplicate (re-scans of the same physical receipt) | 🔴 NEW | No image-similarity / perceptual-hash logic anywhere in repo |
| Short-circuit + surface original record | 🔴 NEW | The capture lifecycle has no "duplicate of X" state |

**New dev:** the entire dedupe subsystem — content-hash index, fuzzy/perceptual-hash, a `Duplicate Of` link field on `Document Capture`, and a new `STATUS_DUPLICATE` in the lifecycle enum.

---

## 3. AI Extraction with Per-Field Confidence

**Proposed:** Real OCR returns per-field confidence (vendor, invoice no, date, line items, subtotal, tax, total, PO/account refs).

| Sub-capability | Status | Where it lives |
|---|---|---|
| Extraction call shape (capture → proposal payload) | 🟢 EXISTS | `run_fake_extraction()` + `proposed_*` fields + `ocr_raw_response` JSON column |
| Provider abstraction | 🟡 PARTIAL | `ocr_provider` and `FAKE_OCR_PROVIDER = "fake-deterministic-v1"` exist; only the fake is wired |
| Real provider integration (Azure DI, AWS Textract, Google Doc AI, vendor-specific) | 🔴 NEW | No real OCR client in repo |
| Per-field confidence | 🟡 PARTIAL | The fake returns `proposed_missing_fields` / `proposed_ambiguous_fields` as comma strings — sufficient as a binary "low-confidence flag" per field; a numeric per-field score field set does not exist |
| Line-item extraction | 🔴 NEW | Today extraction is **header-only** — there is no `Document Capture Item` child table. The walking skeleton/capture both build a single header-line PI item with `qty=1, rate=final_total_amount`. |
| Visible PO reference extraction | 🟡 PARTIAL | `purchase_order_reference` Link field exists, but nothing populates it from OCR — it's clerk-entered |
| Async via `frappe.enqueue` so UI doesn't block | 🔴 NEW | `run_fake_extraction` is synchronous today |

**New dev:** real OCR adapter, numeric per-field confidence scores (likely a new `Document Capture Confidence` child table or JSON column), line-item extraction → new `Document Capture Item` child doctype, async wrapper that enqueues `run_extraction(capture)` and writes back when done.

---

## 4. Supplier Resolution (3-tier match)

**Proposed:** Deterministic alias → fuzzy match → gated auto-create.

| Sub-capability | Status | Where it lives |
|---|---|---|
| Exact name match | 🟢 EXISTS | `_match_supplier()` in `document_capture.py` — checks `Supplier.name` then unique `supplier_name` |
| Match status enum (Matched/Unknown/Ambiguous) | 🟢 EXISTS | `SUPPLIER_MATCH_*` constants + `supplier_match_status` field |
| **Never auto-create supplier without a gate** | 🟢 EXISTS | Hard requirement encoded in `validate_for_purchase_invoice()` — Unknown emits `_("Supplier '{0}' is unknown — AP correction required (no auto-create).")` |
| Deterministic alias table ("AMZN Mktp US*4Z9" → "Amazon") | 🔴 NEW | No alias table doctype exists |
| Fuzzy match against existing suppliers | 🟡 PARTIAL | `rapidfuzz~=3.14.3` is already a declared dep in `pyproject.toml` but is not used for supplier matching anywhere |
| Gated "create new supplier" queue | 🔴 NEW | No `Supplier Creation Request` doctype today; manager-approval queue today only handles invoice approvals |

**New dev:** an `AP Supplier Alias` doctype (canonical name + variants), a fuzzy-match step using the already-installed `rapidfuzz`, and a new "supplier-creation queue" — likely a separate doctype with its own approval gate (per step 10's SoD requirement that vendor master changes follow a separate path).

---

## 5. GL Coding, Cost Center & Tax Assignment

**Proposed:** Expense account + cost center + tax populated automatically, ideally per-supplier.

| Sub-capability | Status | Where it lives |
|---|---|---|
| Native `Supplier` per-Company default payable account | 🟢 EXISTS | `Party Account` child table on `Supplier` |
| Default cost center, default expense account on Purchase Invoice line | 🟢 EXISTS | `Purchase Invoice Item.cost_center`, `expense_account` already exist; `_coalesce_defaults` in the pilot accepts them |
| Accounting Dimensions carry-through | 🟢 EXISTS | `accounting_dimension_doctypes` in `hooks.py` already includes `Purchase Invoice`, `Purchase Invoice Item`, `Journal Entry Account`, `Payment Entry`, etc. |
| Tax templates (purchase) | 🟢 EXISTS | `Purchase Taxes and Charges Template` |
| Per-supplier auto-coding map (supplier → default expense account, default cost center) | 🔴 NEW | No `AP Supplier Coding Profile` doctype exists; defaults today come from the call site, not from the supplier record |
| Cost center inferred from receipt location / card last-4 / supplier | 🔴 NEW | No location/card-last-4 awareness; `paid_from` is the only "card" signal and it's wired to bank account, not a card last-4 |
| Tax line populated from extracted tax + validated against supplier's tax profile | 🟡 PARTIAL | The infrastructure (taxes table on PI, tax templates) exists; *populating from extraction* is new because OCR doesn't extract tax today |

**New dev:** an `AP Supplier Coding Profile` doctype (or Custom Fields on `Supplier`) mapping supplier → default expense account, default cost center, default tax template; an inference layer that reads the extraction and picks among configured profiles; tax-template autoselect.

---

## 6. Document-Type Classification & Doctype Selection

**Proposed:** Branch to Purchase Invoice / Journal Entry / Expense Claim / Manual Review.

| Sub-capability | Status | Where it lives |
|---|---|---|
| Promote to `Purchase Invoice` (the unpaid-vendor-bill path) | 🟢 EXISTS | `promote_to_purchase_invoice()` in this fork |
| `Journal Entry` doctype + GL posting | 🟢 EXISTS | `erpnext/accounts/doctype/journal_entry/` (upstream, fully functional) |
| `Expense Claim` doctype | 🔴 NEW (within ERPNext) | Lives in the **separate `hrms` app** — see `erpnext/patches/v14_0/remove_hr_and_payroll_modules.py`. ERPNext core deliberately does not contain Expense Claim. |
| Classification logic / branching | 🔴 NEW | The capture's pipeline is single-doctype (only PI) — no classification stage between OCR review and promotion |
| "Other → manual review" route | 🟡 PARTIAL | `STATUS_NEEDS_CORRECTION` exists but is field-level; no doctype-level "needs human classification" state |

**New dev:** a classification stage (a `document_type` field on `Document Capture` with literal `"Unpaid Bill" | "Already Paid" | "Employee Reimbursement" | "Manual Review"`), three branching promotion functions (`promote_to_purchase_invoice` already exists; `promote_to_journal_entry` and `promote_to_expense_claim` are new), and an explicit dependency on `hrms` if Expense Claim is in scope.

---

## 7. Validation, Anomaly Detection & Three-Way Match

**Proposed:** Required-fields, totals consistency, vendor active, account valid, dedupe, **vendor bank-detail change detection**, amount-anomaly vs supplier history, **3-way match against PO + Goods Receipt** with tolerance.

| Sub-capability | Status | Where it lives |
|---|---|---|
| Required fields present check | 🟢 EXISTS | `MANDATORY_HEADER_FIELDS` + `validate_for_purchase_invoice()` |
| Totals consistent with line items | 🟡 PARTIAL | PI's `TaxesAndTotals` controller validates totals natively when a PI is inserted, but the *capture* doesn't pre-check (it's header-only) |
| Vendor active check | 🟢 EXISTS | `Supplier.disabled` field is honored by `Purchase Invoice.validate` |
| Expense account valid | 🟢 EXISTS | Native field validation on PI item |
| Pre-extraction duplicate check (step 2) | 🔴 NEW | (see step 2) |
| **Vendor bank-detail change since last payment** | 🔴 NEW | Frappe's `Version` doctype tracks all field changes — querying it for "supplier bank IBAN changed since last `Payment Entry`" is glue, but no such check exists today |
| **Amount-anomaly vs supplier 6-month rolling average** | 🔴 NEW | No anomaly-detection logic anywhere; `statsmodels` and `pandas` are declared deps but nothing in the AP path uses them |
| Three-way match (PI ↔ PO ↔ Purchase Receipt) | 🟡 PARTIAL | Quantity/amount roll-ups exist (`update_billing_status_in_pr`, `over_billing_allowance` from Accounts Settings — see `stock/doctype/purchase_receipt/purchase_receipt.py:1236`). What does NOT exist: a single explicit "three-way match" check that compares header amount against the linked PO amount AND the linked PR received-qty within a per-line tolerance and flags mismatches. ERPNext lets you create a PI from a PR (good) but the explicit three-way-match output ("matched/exception/flagged") is not surfaced as a doctype outcome. |
| PO-less / two-way matching | 🟢 EXISTS | `purchase_reference_status = "Non-PO / Not Applicable"` already classifies this |
| Tolerance config | 🟡 PARTIAL | `over_billing_allowance` (Accounts Settings) + per-item billing tolerance exist; per-supplier or per-policy tolerance does not |

**New dev:** vendor-bank-change detector (cross-references `Version` doctype against last-PE date), amount-anomaly engine (rolling 6-mo average over PI history per supplier; suggested implementation uses already-installed `pandas`), and an explicit three-way-match step with structured pass/fail output stored on the capture.

---

## 8. Confidence-Based Routing (Auto-Post vs Review Queue)

**Proposed:** All-fields-above-threshold + no validation flags → auto-post (still gated by approval); anything else → review queue with exception reason.

| Sub-capability | Status | Where it lives |
|---|---|---|
| Numeric threshold-based routing | 🟡 PARTIAL | Today the only numeric threshold is `AUTO_APPROVAL_THRESHOLD_DEFAULT = 1000.0` for the *amount* — not for OCR confidence |
| Auto-post path | 🟡 PARTIAL | `request_approval()` → `APPROVAL_STATUS_AUTO_APPROVED` exists; it triggers when *amount* is under threshold, not when confidence is high |
| Review queue | 🟢 EXISTS | `get_ap_lifecycle_rows()` + `get_manager_approval_queue()` already return queue rows with `action_required_reason` |
| Exception reason surfaced per item | 🟢 EXISTS | Every capture carries `action_required_reason` and `validation_result` text |
| Combined signal (per-field confidence ∧ validation flags) | 🔴 NEW | No combined-signal evaluator; today confidence and validation are independent |

**New dev:** a confidence-score evaluator (depends on step 3 producing real per-field scores), wired into the routing decision alongside the existing amount threshold.

---

## 9. AP Review (Exception Handling)

**Proposed:** Clerk corrects misread fields, resolves supplier ambiguity, finishes GL coding, or rejects back to vendor; rejection trail preserved.

| Sub-capability | Status | Where it lives |
|---|---|---|
| Correct misread field (clerk overrides proposal) | 🟢 EXISTS | `confirm_extracted_fields()` accepts a `corrections` dict |
| Resolve supplier ambiguity (re-validate after AP edit) | 🟢 EXISTS | `validate_for_purchase_invoice()` can be re-run |
| Reviewer + reviewed-at audit | 🟢 EXISTS | `reviewed_by`, `reviewed_at`, `review_notes` |
| Reject back to vendor with reason | 🟡 PARTIAL | `STATUS_REJECTED` exists in the enum but **no function transitions a capture into Rejected** — there is no `reject_capture()` API. The state is reachable only by direct DB writes today. |
| Rejection trail preserved | 🟢 EXISTS | Frappe `Version` doctype + `decision_notes` field already exist |
| Re-entry of corrected/rejected items | 🟡 PARTIAL | Re-running confirm/validate after correction works; there is no formal "reactivate this rejected capture" path |

**New dev:** a `reject_capture()` whitelisted method that transitions to `STATUS_REJECTED` with a reason; a `reopen_capture()` for the rejection-cycle case; ideally a `Capture Rejection Reason` log child table.

---

## 10. Approval Routing with Segregation of Duties

**Proposed:** Amount/department/cost-center/supplier-risk-driven approver selection; **SoD** (extractor ≠ approver above threshold; vendor-master changes follow separate approval path).

| Sub-capability | Status | Where it lives |
|---|---|---|
| Amount-threshold-driven approval routing | 🟢 EXISTS | `request_approval()` + `AUTO_APPROVAL_THRESHOLD_DEFAULT` + `APPROVAL_STATUS_PENDING_MANAGER` |
| Approver-role assignment | 🟢 EXISTS | `assigned_approver_role` field; defaults to `MANAGER_APPROVAL_ROLE_DEFAULT = "Accounts Manager"` |
| Approve / reject decision recording | 🟢 EXISTS | `record_manager_decision()` + `decision_by`, `decision_at`, `decision_notes` |
| Department-/cost-center-driven approval | 🔴 NEW | No multi-dimensional approval matrix today (only amount threshold) |
| Supplier-risk-profile-driven approval | 🔴 NEW | No risk profile on `Supplier` |
| **Segregation of Duties (extractor ≠ approver above threshold)** | 🔴 NEW | Today `request_approval()` and `record_manager_decision()` both default `actor = frappe.session.user` with no check that they differ from `reviewed_by` |
| **Vendor-master change approval path (especially bank details)** | 🔴 NEW | No workflow on `Supplier` in this repo; Frappe's `Workflow` doctype can host one but it isn't pre-configured |
| Native Frappe Workflow integration | 🟢 EXISTS (framework) | `frappe` ships a `Workflow` doctype + `Workflow State`/`Workflow Action` — usable to model the SoD chain without writing a new approval engine |

**New dev:** SoD validator in `request_approval` and `record_manager_decision` (reject if `actor == reviewed_by` and amount > SoD threshold), a configurable approval matrix doctype, and either (a) a Workflow on `Supplier` covering bank-detail changes or (b) a custom `Supplier Master Change Request` doctype with its own approval gate.

---

## 11. Payment Execution

**Proposed:** Payment Entry via configured rail (ACH/check/card) for unpaid bills; no-op for already-paid card receipts; Expense Claim → Payment Entry for reimbursements.

| Sub-capability | Status | Where it lives |
|---|---|---|
| Create + submit `Payment Entry` against a PI | 🟢 EXISTS | `issue_mock_payment()` in this fork; `get_payment_entry()` helper in upstream |
| **MOCK labeling** for pilot | 🟢 EXISTS | `MOCK_PAYMENT_PROVIDER`, `MOCK_PAYMENT_PREFIX`, `MOCK_PAYMENT_REMARK` |
| Already-paid-receipt no-op (advance to step 12) | 🔴 NEW | Today every approved capture issues a Payment Entry — there is no "skip payment, already paid" branch |
| Expense Claim payout | 🔴 NEW | Depends on `hrms` (see step 6) |
| Real ACH rail (NACHA file / bank API) | 🔴 NEW | `Payment Order` doctype exists upstream but no real NACHA/ACH file generation in this repo |
| Real check printing | 🟡 PARTIAL | Upstream has `Cheque Print Template` doctype but no end-to-end check rail |
| Real card rail | 🔴 NEW | No card-rail integration |
| Idempotency key on insert | 🔴 NEW | `Payment Entry` today is created from PI via the helper; nothing carries an idempotency key across retries |

**New dev:** the "already paid, skip payment" branch (only fires when classification = Already Paid, posting a Journal Entry instead per the open question), real ACH/check rails, and idempotency keys on every downstream insert (`Supplier`, `Purchase Invoice`, `Payment Entry`, `Journal Entry`).

---

## 12. Bank-Feed Match & Reconciliation

**Proposed:** Card txns match JEs; ACH/check disbursements match PEs; exact-amount + date-window primary; party-name fuzzy is a hint; mock during dev.

| Sub-capability | Status | Where it lives |
|---|---|---|
| `Bank Transaction` doctype | 🟢 EXISTS | `erpnext/accounts/doctype/bank_transaction/` |
| `Bank Statement Import` (CSV / MT940) | 🟢 EXISTS | `erpnext/accounts/doctype/bank_statement_import/` + `mt-940` is a declared dep |
| **Plaid integration** | 🟢 EXISTS | `erpnext/erpnext_integrations/doctype/plaid_settings/` + `plaid-python` dep + scheduled `automatic_synchronization` (hourly_maintenance) |
| `Bank Reconciliation Tool` (UI + matching engine) | 🟢 EXISTS | `erpnext/accounts/doctype/bank_reconciliation_tool/` — `get_matching_queries` hook is in `hooks.py` |
| Exact-amount + date-window matching | 🟢 EXISTS | Built into `Bank Reconciliation Tool` matching queries |
| Fuzzy party-name match as hint | 🟡 PARTIAL | The tool's match ranking is upstream code; whether it's "hint only" vs "auto-clear" is a configuration concern |
| `Bank Clearance` (for cleared check/draft cycles) | 🟢 EXISTS | `erpnext/accounts/doctype/bank_clearance/` |
| **AP Closed Loop fork posture** | ⚠️ DELIBERATE NON-USE | The fork explicitly does **not** create Bank Transactions and tests assert this. The proposed step 12 *adds* the reconciliation handshake that the fork intentionally avoided. |
| Mock bank-transaction fixtures that mirror real feed shape | 🔴 NEW | Today the fork only asserts `Bank Transaction` count is unchanged; it doesn't generate fixtures |

**New dev:** mock bank-transaction fixture generator that shapes JSON identical to Plaid + MT940 feed output, and a tightening of the existing `Bank Reconciliation Tool` matching policy ("exact amount + date window primary; fuzzy name = hint only"). The actual reconciliation engine is upstream and reusable.

---

## 13. Closure & Audit Trail

**Proposed:** Invoice + Payment + GL entries + bank-match linked, closed, version-history retained 7 years, trial-balance drift detected vs prior period.

| Sub-capability | Status | Where it lives |
|---|---|---|
| Native closure derivation (PI submitted, PE submitted, outstanding=0, status=Paid) | 🟢 EXISTS | `build_closure_evidence()` + `_derive_payment_lifecycle_status()` |
| GL Entries linked to PI + PE | 🟢 EXISTS | `_gl_entries_for_vouchers()` and `native.gl_entries` payload |
| **Bank-transaction-match link** in closure evidence | 🟡 PARTIAL | `bank_transaction_count` is reported, but the linked-to-bank-txn step is not part of the pilot's closure (by design — see step 12) |
| Trial-balance drift check against prior period | 🟡 PARTIAL | `Period Closing Voucher` + `Account Closing Balance` upstream snapshot the prior period; *automated drift comparison* is not a built-in check |
| Frappe `Version` field-level history | 🟢 EXISTS (framework) | `frappe.types.Version` doctype is automatic for any DocType with `track_changes` enabled |
| Attachment retention 7 years | 🟡 PARTIAL | Frappe `File` retention is per-site policy; no built-in TTL on `File` |
| Single-record audit retrieval (image → extraction → validation → approval → payment → bank-match → posting) | 🟢 EXISTS | The capture record links to PI + PE; `build_closure_evidence()` returns the full payload in one call |

**New dev:** the bank-match link inside closure evidence (`capture.bank_transaction` field + populate from reconciliation), an automated **trial-balance drift report** that compares current vs `Account Closing Balance`, and a 7-year file-retention policy (could be implemented as a scheduler job that flags/archives instead of deleting).

---

## Cross-Cutting Engineering Concerns

| Concern | Status | Where it lives |
|---|---|---|
| `frappe.enqueue` background-job infrastructure | 🟢 EXISTS (framework) | Used heavily upstream (`accounts/utils.py`, `repost_payment_ledger`, `process_subscription`, etc.); **not used by the AP Closed Loop pilot yet** |
| Idempotency keys on downstream posts | 🔴 NEW | `Purchase Invoice`, `Payment Entry`, `Journal Entry`, `Supplier` inserts in the pilot have no idempotency keys; a retry after a transient failure could double-post |
| Per-field confidence persistence | 🔴 NEW | Today missing/ambiguous is recorded as comma-separated text in `proposed_missing_fields` / `proposed_ambiguous_fields`. A numeric per-field score model is new. |
| `rapidfuzz` already a dep | 🟢 EXISTS | Available for fuzzy supplier match, fuzzy bank-party match |
| `pandas` / `statsmodels` already deps | 🟢 EXISTS | Available for amount-anomaly rolling-window analysis |
| `mt-940` already a dep | 🟢 EXISTS | Bank statement parsing |
| `plaid-python` already a dep | 🟢 EXISTS | Plaid integration ready |
| `pypdf` (used by tests) | 🟢 EXISTS | Available for PDF text extraction if a fallback is ever needed |

---

## Summary Scorecard

| Step | EXISTS | PARTIAL | NEW | Net effort |
|--:|:--|:--|:--|:--|
| 1. Intake | manual upload + capture record | mobile glue | email-in, vendor portal | **S** |
| 2. Dedup | Frappe `File.content_hash` available | — | exact-hash lookup + fuzzy + duplicate state | **M** |
| 3. AI extraction | provider abstraction + proposal payload + async-enqueue infra | header proposal shape | real OCR adapter, per-field confidence, line items, async wrapper | **L** |
| 4. Supplier resolution | exact match + gated no-auto-create + `rapidfuzz` dep | — | alias table + fuzzy match step + supplier-creation queue | **M** |
| 5. GL coding | native PI/Supplier/Acct-Dim plumbing | extraction-side tax | per-supplier coding profile + tax autoselect + location/card inference | **M** |
| 6. Doctype classification | PI promote path + JE + (no Expense Claim) | — | classification field + JE-branch + Expense Claim (hrms dep) + manual-review state | **L** |
| 7. Validation + anomaly + 3WM | required fields + active vendor + per-item billing tolerance | totals consistency, tolerance config | bank-change detector, amount-anomaly, explicit 3WM | **L** |
| 8. Confidence-based routing | amount-threshold routing + review queue + exception reasons | — | confidence-score evaluator + combined signal | **S** (once step 3 lands) |
| 9. AP review | correct/reviewed-by/notes | rejected-reentry | `reject_capture()`, reopen, rejection log | **S** |
| 10. Approval + SoD | amount-threshold approval + decision recording + Frappe `Workflow` available | — | SoD validator + matrix + Supplier change workflow | **M** |
| 11. Payment exec | `Payment Entry` + mock labeling | check templates | already-paid no-op branch + real rails (ACH/check/card) + idempotency keys + Expense Claim payout | **L** |
| 12. Bank reconciliation | `Bank Transaction` + `Plaid` + `Bank Reconciliation Tool` + `Bank Statement Import` + `Bank Clearance` | match-policy tightening | mock-feed fixtures + reconciliation linkage on capture | **M** |
| 13. Closure + audit | native closure derivation + Frappe `Version` + closure-evidence builder | trial-balance drift, attachment retention | bank-match link inside evidence + automated TB drift check + 7-year retention policy | **M** |

**Top-of-stack net build (effort-weighted):**
1. **Real OCR with per-field confidence** (step 3) — gates steps 7, 8.
2. **Document-type classification + JE / Expense Claim branches** (step 6) — gates step 11's no-op path.
3. **Deduplication** (step 2) — small footprint but a hard requirement before anything goes "auto-post".
4. **Three-way match + amount anomaly + bank-detail change detector** (step 7) — depends on accumulated PI history and bank-detail diffing.
5. **Bank reconciliation linkage into capture** (steps 12 + 13) — explicitly reverses the fork's current "no Bank Transaction" stance and needs a guardrail rewrite.

**Bottom-of-stack reuse (low net build):**
- Bank reconciliation tool, Plaid sync, Bank Statement Import (MT940/CSV).
- Native Purchase Invoice, Payment Entry, Journal Entry, GL Entry, Payment Ledger Entry.
- Accounting Dimensions plumbing.
- Frappe `Workflow`, `Version`, `File` doctypes.
- `rapidfuzz`, `pandas`, `statsmodels`, `mt-940`, `plaid-python`, `pypdf` already installed.

---

## What This Means for the Pilot's Stated Guardrails

The current fork enforces:

1. No `Bank Transaction` created.
2. No custom `closed` flag.
3. All payment artifacts visibly labeled MOCK.
4. Nothing silently progresses.

**Step 12's bank-feed match directly conflicts with guardrail #1.** The proposed workflow *requires* `Bank Transaction` to be the closure signal. Either:
- the guardrail is relaxed for Phase 2 (the docstring of `document_capture.py` makes #1 a Phase-1 commitment), or
- the closure model splits into "settled" (today's derived state) and "bank-cleared" (new, off the matched `Bank Transaction`).

Guardrails #2, #3, #4 are compatible with the proposed workflow without change. The MOCK labeling can simply move from the payment provider to a mock bank-feed source in step 12.
