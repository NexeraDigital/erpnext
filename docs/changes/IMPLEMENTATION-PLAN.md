# Implementation Plan — AP Closed Loop Phase 2 (Full 13-Step Workflow)

> **Inputs:** `docs/changes/NewUpdates.md` (target workflow), `docs/changes/GAP-ANALYSIS.md` (what exists vs what's new), `docs/ARCHITECTURE.md` (system shape), `docs/FORK-CHANGES.md` (Phase 1 deliverables).
>
> **Scope of this plan:** every step required to move from the current Phase 1 walking-skeleton pilot to the full closed-loop production workflow described in `NewUpdates.md`. Phase 1 already covers manual intake → fake OCR → AP review → validation → PI promotion → mock-labeled Payment Entry → derived closure evidence. This plan adds dedupe, real OCR, line items, doctype classification, three-way match + anomaly + bank-detail change, SoD-aware approval, real payment rails, real bank-feed reconciliation, and audit-ready closure.
>
> **Working assumption:** vertical slices, one PR per slice, each slice ends green tests + a desk-visible artifact. The fork already operates this way (8 commits = 8 slices in Phase 1) so we keep the cadence.
>
> **Estimation units:** **S** ≈ 1–2 dev days, **M** ≈ 3–5 dev days, **L** ≈ 1–2 dev weeks, **XL** ≈ 3–4 dev weeks.

---

## 0. Pre-Flight Decisions (Must Resolve Before Slice 1)

These cannot be deferred — they shape doctype field sets and downstream branching:

| # | Decision | Recommended default | Owner | Lock date |
|---|---|---|---|---|
| D1 | **Already-paid card receipts: direct Journal Entry vs Purchase Invoice + "Credit Card Clearing"?** (From `NewUpdates.md` lead-in.) | **PI + Credit Card Clearing** — keeps vendor in AP aging and spend-by-supplier reports as a one-time cost. Direct JE is simpler but blinds the standard reports. | Product / Controller | Before slice E1 |
| D2 | **Expense Claim in scope (step 6 third branch)?** Frappe ships it in the separate `hrms` app — adding it means a new app dep. | **Defer to Phase 3.** Phase 2 ships PI + JE branches; "Employee Reimbursement" classification routes to manual review until `hrms` is installed. | Product | Before slice F1 |
| D3 | **Bank Transaction creation: Phase-1 guardrail says "never". Step 12 requires it.** | **Explicitly retire the guardrail for Phase 2** and replace it with a split closure model: `settled` (today's derivation) + `bank_cleared` (new, off the matched Bank Transaction). The MOCK-labeling guardrail moves to the *mock bank feed source*, not to "no bank transactions exist". | Architecture | Before slice I1 |
| D4 | **OCR provider choice.** | **Azure Document Intelligence** (per-field confidence native, prebuilt Invoice model, US-region available). Alternative: AWS Textract `AnalyzeExpense`. Pick exactly one for Phase 2; the `OCR Provider` doctype below makes a second one a config change. | Architecture | Before slice C1 |
| D5 | **Real payment rail for Phase 2.** | **NACHA-format ACH file + manual upload to bank portal** for slice K1; deferred real bank-API rail to Phase 3. Check printing and card-rail are explicitly out of Phase 2. | Controller / Treasury | Before slice K1 |
| D6 | **Dedupe lookback window.** `NewUpdates.md` says 90 days. | **Accept 90 days, configurable in `AP Settings`.** | Product | Before slice B1 |
| D7 | **Confidence threshold per field.** | **Default 0.80 per field, configurable per field in `AP Settings`.** Auto-post requires *all* mandatory fields ≥ threshold AND zero validation flags. | Product / AP Lead | Before slice G1 |
| D8 | **SoD threshold.** Above what amount does `actor != reviewed_by` become hard? | **$0 (always enforced)** for Phase 2 — simpler than tiered. AP Lead can opt out via a single `AP Settings` toggle in pilot deployments. | Controls | Before slice J1 |

A short ADR is appended to `docs/changes/` for each decision the moment it's made (one file per decision, `ADR-<n>-<slug>.md`).

---

## 1. Architecture Overlay

### 1.1 New singletons / settings doctypes

| Doctype | Type | Purpose |
|---|---|---|
| `AP Settings` | Single | Dedupe window (D6), per-field confidence thresholds (D7), SoD threshold (D8), Credit Card Clearing account (D1), OCR provider selector (D4), feature flags |
| `OCR Provider` | Configurable | Provider record (`name`, `kind ∈ {Azure DI, AWS Textract, Fake}`, credentials child, model name, region). Selected by name from `AP Settings`. |
| `AP Supplier Alias` | Master | `canonical_supplier` (Link → Supplier) + `alias_pattern` (Data, supports `*` glob) + `match_type ∈ {exact, glob, regex}` + audit fields |
| `AP Supplier Coding Profile` | Master | Per-supplier defaults: expense account, cost center, tax template, payment terms template, accounting dimensions |
| `AP Capture Document Type` | Enum-as-doctype | Optional richer enum if we want per-tenant additions; otherwise plain `Literal["Unpaid Bill", "Already Paid", "Employee Reimbursement", "Manual Review"]` on capture |
| `Supplier Master Change Request` | Submittable | Holds pending bank-detail / IBAN / payment-terms changes; routed to a separate approver per D8/step 10 |

### 1.2 New child tables on `Document Capture`

| Child table | Purpose |
|---|---|
| `Document Capture Item` | Line items from OCR + clerk-edited finals. Mirrors `Purchase Invoice Item`'s narrow shape: item description (free text), qty, rate, amount, tax amount, expense account, cost center, PO reference, PR reference. |
| `Document Capture Confidence` | Per-field numeric confidence (float 0-1) returned by the OCR provider. Keyed by `field_name` (e.g. `supplier`, `invoice_no`, `total`, `line_1_rate`). Used by slice G1. |
| `AP Capture Rejection Log` | Rejection reasons and reopen history. |

### 1.3 New fields on existing `Document Capture`

| Field | Purpose | Slice |
|---|---|---|
| `content_hash` (Data, indexed) | SHA-256 of the original file bytes | B1 |
| `perceptual_hash` (Data, indexed) | pHash of rasterized first page | B1 |
| `duplicate_of` (Link → Document Capture) | Set when dedupe finds a prior match | B1 |
| `document_type` (`Literal[...]`) | Result of classification (D2 — three values in Phase 2) | F1 |
| `three_way_match_status` (`Literal["Not Applicable", "Matched", "Exception"]`) | Phase-2 explicit 3WM output | H1 |
| `three_way_match_result` (SmallText) | Human-readable 3WM diff | H1 |
| `anomaly_status` (`Literal["Not Checked", "Within Range", "Anomalous"]`) | Rolling-avg outcome | H2 |
| `anomaly_result` (SmallText) | Anomaly explanation (mean, stddev, current, factor) | H2 |
| `vendor_bank_change_detected` (Check) | Flag from Version diff vs last PE | H3 |
| `sod_check_status` (`Literal["Not Applicable", "Passed", "Blocked"]`) | SoD outcome | J1 |
| `journal_entry` (Link → Journal Entry) | For Already-Paid branch | F1 |
| `expense_claim` (Link → Expense Claim) | For Reimbursement branch (deferred Phase 3 per D2; field reserved) | F1 |
| `bank_transaction` (Link → Bank Transaction) | Set when slice I1 reconciliation matches | I1 |
| `bank_cleared` (Check) | Phase-2 second closure signal | I1 |
| `idempotency_key` (Data, indexed) | Per-step keys for retry-safe downstream posts | A1 |

### 1.4 New whitelisted endpoints (additions to `document_capture.py`)

```
detect_duplicates_for(capture)                                      # B1
run_extraction_for(capture, provider=None)                          # C1 — async-enqueued
classify_document_type_for(capture, override=None)                  # F1
match_supplier_for(capture)                                         # D1
apply_coding_profile_for(capture)                                   # E1
three_way_match_for(capture)                                        # H1
detect_amount_anomaly_for(capture)                                  # H2
detect_vendor_bank_change_for(capture)                              # H3
promote_to_journal_entry_for(capture)                               # F2
promote_to_expense_claim_for(capture)                               # F3 (Phase 3)
reject_capture_for(capture, reason)                                 # J0
reopen_capture_for(capture, reason)                                 # J0
issue_real_payment_for(capture, rail)                               # K1
ingest_bank_transaction_match_for(bank_transaction)                 # I1
build_audit_trail_for(capture)                                      # L1
```

### 1.5 New scheduler hooks

| Cadence | Job | Slice |
|---|---|---|
| `cron 0/5 * * * *` | `document_capture.process_extraction_queue` (drains async OCR queue) | C1 |
| `daily_maintenance` | `ap_settings.refresh_anomaly_baselines` (precomputes supplier rolling averages) | H2 |
| `hourly_maintenance` | `ap_settings.archive_old_captures` (7-year retention policy, no deletes — flags for cold storage) | L2 |

### 1.6 New report

`Accounts Payable Trial Balance Drift` (slice L2) — compares current GL Entry rollup vs prior `Account Closing Balance` snapshot at the Creditors / Credit Card Clearing accounts.

---

## 2. Phase Map

The plan is 12 vertical slices grouped into 6 phases. Each phase ends in a deploy-ready state. The order is dependency-driven: anything that gates auto-post (steps 2, 3, 7) lands before auto-post (step 8); anything that gates payment (steps 6, 10) lands before payment (step 11); anything that gates closure (step 12) lands before audit (step 13).

```
Phase A — Foundations              ◀─── prerequisites for everything
  A1 — AP Settings + idempotency keys + async wrapper

Phase B — Intake hardening
  B1 — Dedupe (exact + perceptual)
  B2 — Email/portal ingestion adapters

Phase C — Real OCR + line items
  C1 — OCR provider abstraction + Azure DI adapter + async pipeline + per-field confidence
  C2 — Line-item child table + line extraction

Phase D — Supplier intelligence
  D1 — Alias table + fuzzy match using rapidfuzz
  D2 — Supplier creation request gate

Phase E — Auto-coding
  E1 — Coding profile doctype + apply step + tax-template autoselect

Phase F — Doctype classification + branches
  F1 — Classify + PI branch refactor
  F2 — Already-Paid branch (PI + Credit Card Clearing per D1; or JE if D1 flips)
  F3 — Reimbursement branch placeholder (Phase 3)

Phase G — Confidence + validation routing
  G1 — Combined-signal routing (per-field confidence ∧ validation flags)

Phase H — Validation deep gates
  H1 — Three-way match (PO + PR + tolerance)
  H2 — Amount anomaly (pandas-driven rolling avg)
  H3 — Vendor bank-detail change detector

Phase I — Real bank reconciliation
  I1 — Bank-transaction match into capture, dual closure signal (settled + bank_cleared)
  I2 — Mock bank-feed fixtures + reconciliation test harness

Phase J — Approval + SoD
  J0 — Reject / reopen lifecycle
  J1 — SoD validator + matrix + Supplier Master Change Request workflow

Phase K — Payment execution
  K1 — Real ACH (NACHA file) rail with idempotency
  K2 — Already-Paid no-op branch + payment-skip path

Phase L — Audit + retention
  L1 — Single-record audit-trail endpoint
  L2 — Trial-balance drift report + 7-year retention scheduler
```

---

## 3. Phase A — Foundations

### Slice A1 · `AP Settings` + idempotency keys + async wrapper · **M**

**Why first.** Every subsequent slice writes to settings, retries safely, or enqueues. Without these primitives we re-invent them per slice and end up inconsistent.

**Deliverables.**
- New singleton doctype `AP Settings`:
  - `dedupe_window_days` (Int, default 90)
  - `per_field_confidence_threshold` (Float, default 0.80)
  - `field_thresholds` (JSON, per-field overrides)
  - `sod_threshold_amount` (Float, default 0)
  - `enforce_sod` (Check, default 1)
  - `credit_card_clearing_account` (Link → Account)
  - `ocr_provider` (Link → OCR Provider)
  - `auto_post_amount_threshold` (Float — replaces hard-coded `AUTO_APPROVAL_THRESHOLD_DEFAULT = 1000.0`)
- New helper module `erpnext/accounts/doctype/document_capture/idempotency.py`:
  - `generate_key(capture_name, step_name) -> str` — deterministic SHA-256 of `(capture_name, step_name, settings_version)`
  - `with_idempotency(key, fn)` decorator — checks a new `AP Posting Ledger` doctype before insert; if `key` exists, returns the prior result instead of re-posting
- New helper module `erpnext/accounts/doctype/document_capture/async_runner.py`:
  - `enqueue_step(capture, step_name, kwargs)` wraps `frappe.enqueue` with queue selection (`short` for matching, `long` for OCR), retry policy (3× exponential backoff, dead-letter to capture's `action_required_reason`), and idempotency key emission

**Acceptance criteria.**
- AC-A1-1: `AP Settings` is creatable, all defaults installed by an install patch.
- AC-A1-2: Submitting the same `(capture, step)` twice posts the downstream doc exactly once.
- AC-A1-3: A simulated OCR failure surfaces as `action_required_reason` and does not block other captures.
- AC-A1-4: Existing Phase 1 hard-coded threshold (`AUTO_APPROVAL_THRESHOLD_DEFAULT`) reads from `AP Settings` when the singleton exists; falls back to 1000.0 otherwise.

**Tests.**
- `test_ap_settings.py` — defaults, override, JSON field thresholds round-trip.
- `test_idempotency.py` — concurrent retries don't double-post; uses `frappe.db.savepoint`.
- `test_async_runner.py` — enqueue + wait, retry, dead-letter.

**Risk / rollback.** Pure additive. Feature-flag any reads from `AP Settings` in Phase 1 code paths so the existing test suite stays green.

---

## 4. Phase B — Intake Hardening

### Slice B1 · Deduplication (exact + perceptual) · **M**

**Deliverables.**
- Add `content_hash` (Data, Indexed) to `Document Capture` and populate on `validate` from the linked `File`'s `content_hash` (Frappe already computes it on upload).
- Add `perceptual_hash` (Data, Indexed). Compute pHash of the first page using `imagehash` + `pdf2image` (new deps: `imagehash>=4.3`, `pdf2image>=1.16`, `Pillow>=10`).
- Add `duplicate_of` (Link → Document Capture) and new `STATUS_DUPLICATE` enum value.
- New whitelisted method `detect_duplicates_for(capture)`:
  - Window = `AP Settings.dedupe_window_days`.
  - Exact match on `content_hash` short-circuits with `STATUS_DUPLICATE`.
  - Hamming distance ≤ 6 on `perceptual_hash` flags as **suspected** duplicate (sets `action_required_reason`, doesn't auto-close).
- Wire `detect_duplicates_for` into the `validate` flow when the capture transitions from `Pending Review` → `Proposed`.

**Acceptance criteria.**
- AC-B1-1: Re-uploading the same PDF surfaces the original record and prevents extraction.
- AC-B1-2: A re-scan of the same physical receipt (different bytes, similar image) is flagged as suspected duplicate with action_required = 1.
- AC-B1-3: Two genuinely different invoices are not flagged.
- AC-B1-4: Configurable lookback is respected; a duplicate older than the window is ignored.

**Tests.** Uses `pypdf` + `Pillow` to generate fixture pairs (identical, near-identical via re-rasterization, distinct).

**Risk.** pHash false positives on legitimate identical-template-different-data invoices (e.g. monthly Amazon subscriptions). Mitigated by combining pHash with body-text fingerprint (extracted on first OCR pass) before auto-closure in slice C1.

### Slice B2 · Email + portal ingestion adapters · **S**

**Deliverables.**
- New `Email Account` integration: configure a dedicated AP mailbox; Frappe's existing email-in hook fires `document_capture.create_capture_from_email(email_doc)`.
- New whitelisted endpoint `create_capture_from_email(email_doc)` — iterates Communication attachments, creates one capture per supported attachment.
- New (placeholder) adapter `erpnext/accounts/ap_closed_loop/portal_pull.py` — abstract base + `register_portal_adapter` decorator. No concrete adapters in Phase 2 — wired in Phase 3.

**Acceptance criteria.**
- AC-B2-1: Forwarding a PDF invoice to the configured mailbox creates a capture in `Pending Review` linked to the source `Communication`.
- AC-B2-2: Multi-attachment emails produce one capture per supported attachment; unsupported attachments are logged and skipped.
- AC-B2-3: The `Communication` referenced from the capture renders the original message body for AP context.

---

## 5. Phase C — Real OCR + Line Items

### Slice C1 · OCR provider abstraction + Azure DI adapter + async + per-field confidence · **L**

**Deliverables.**
- New doctype `OCR Provider` (configurable). Fields: `provider_name`, `kind` (Literal `Azure DI` | `AWS Textract` | `Fake`), `endpoint_url`, `region`, `model_name`, `credentials_secret` (Password), `default_for_company` (Link).
- New module `erpnext/accounts/ap_closed_loop/ocr/` with:
  - `base.py` — `OCRClient` protocol: `extract(file_url) -> OCRResult` where `OCRResult` exposes `proposal: dict` AND `confidence: dict[str, float]` AND `raw: dict`.
  - `fake.py` — wraps the existing `_propose_for_seed()` and assigns `confidence` from `proposed_missing_fields`/`proposed_ambiguous_fields` (1.0 baseline, 0.0 for missing, 0.5 for ambiguous).
  - `azure.py` — calls Azure Document Intelligence `prebuilt-invoice` model; maps response fields to our schema; reads `field.confidence` directly.
  - `factory.py` — `get_ocr_client()` reads `AP Settings.ocr_provider`.
- Replace synchronous `run_fake_extraction` with `run_extraction` that:
  - Enqueues via `async_runner.enqueue_step(capture, "ocr")`.
  - On completion, writes `proposed_*` + `Document Capture Confidence` rows + `ocr_raw_response` JSON.
- Add `Document Capture Confidence` child table with `field_name`, `confidence` (Float 0-1), `is_above_threshold` (Check, computed against `AP Settings.field_thresholds` falling back to `per_field_confidence_threshold`).
- Keep `run_fake_extraction_for` as a thin wrapper for tests.

**Acceptance criteria.**
- AC-C1-1: Selecting `Azure DI` in `AP Settings` and uploading a PDF produces `proposed_*` values plus a `confidence` child table populated from the Azure response.
- AC-C1-2: Switching `AP Settings.ocr_provider` to a `Fake` provider record yields the deterministic Phase 1 proposal — existing Phase 1 tests still pass.
- AC-C1-3: An OCR call that fails three times routes to `action_required_reason = "OCR failed: <provider> <code> after 3 retries"`.
- AC-C1-4: Azure credentials never appear in `ocr_raw_response` (redacted before persisting).

**Tests.** Two suites: `test_ocr_fake_pathway.py` (Phase 1 behavior preserved) + `test_ocr_azure_pathway.py` (mocks the Azure SDK).

**Risk.** Azure SDK eats request bodies — confirm we can replay locally from the cached raw response.

### Slice C2 · Line-item child table + line extraction · **M**

**Deliverables.**
- New child doctype `Document Capture Item`. Fields: `description`, `qty`, `rate`, `amount`, `tax_amount`, `expense_account`, `cost_center`, `po_reference` (Link → Purchase Order), `pr_reference` (Link → Purchase Receipt), `confidence_summary` (Data, computed).
- Extend `OCRResult` to carry `lines: list[dict]`.
- `promote_to_purchase_invoice` switches from "single header line at total" to "one PI item per capture item" when lines are present; falls back to header-line when not.
- The Phase 1 deterministic fake gains a `simulate_lines` flag so existing tests don't break by default.

**Acceptance criteria.**
- AC-C2-1: A multi-line invoice produces N capture items with confidence rows per `line_<i>_<field>`.
- AC-C2-2: Promoting a multi-line capture creates a PI with N item rows; totals reconcile to `final_total_amount` within 0.01.
- AC-C2-3: Promoting a no-line capture still produces a single-item PI (Phase 1 backward compat).
- AC-C2-4: Each capture item with a `po_reference` populates the PI item's PO link (this unlocks Slice H1's three-way match).

---

## 6. Phase D — Supplier Intelligence

### Slice D1 · Alias table + fuzzy match · **M**

**Deliverables.**
- New master doctype `AP Supplier Alias`. One alias per row; `canonical_supplier` (Link → Supplier, required), `alias_pattern` (Data), `match_type` (`exact | glob | regex`).
- Extend `_match_supplier()` to a three-tier strategy:
  1. Exact match on alias pattern.
  2. `rapidfuzz` token-set-ratio ≥ 90 against `Supplier.supplier_name` set.
  3. Unique match → Matched; multiple hits ≥ 90 → Ambiguous; no hit ≥ 90 → Unknown.
- Add `supplier_match_confidence` (Float) field to capture; carries the highest fuzzy score for the chosen match.

**Acceptance criteria.**
- AC-D1-1: An alias `"AMZN Mktp US*"` (glob) catches `"AMZN Mktp US*4Z9"` and resolves to canonical `"Amazon"`.
- AC-D1-2: A misspelling within 90% token-set-ratio of an existing supplier resolves Matched.
- AC-D1-3: Two suppliers tied within 90% emit `Ambiguous` with both names in `validation_result`.
- AC-D1-4: No prior alias and no fuzzy hit ≥ 90 emits `Unknown`.

**Tests.** A 12-row fixture of supplier-name variants captures realistic noise (suffixes, payment-processor prefixes, OCR-misread digits).

### Slice D2 · Supplier creation request gate · **M**

**Deliverables.**
- New submittable doctype `Supplier Master Change Request`. Workflow states: Draft → Pending Approval → Approved → Posted.
  - Fields: `change_type` (`Create` | `Update Bank Details` | `Update Payment Terms` | `Disable`), `requested_supplier_name`, `proposed_payload` (JSON), `evidence_capture` (Link → Document Capture, optional), `approver_role`, `decision_by`, `decision_at`.
- When `_match_supplier()` returns Unknown AND OCR `supplier` confidence ≥ threshold AND `AP Settings.auto_request_supplier_creation = 1`, create a Draft `Supplier Master Change Request` and link it from the capture (new field `supplier_change_request`).
- Approved request creates the Supplier (`Submit` action) and re-runs validation on the linked capture.
- Frappe `Workflow` doctype is used — no custom approval engine.

**Acceptance criteria.**
- AC-D2-1: Unknown supplier with high confidence creates a Draft request; capture stays Blocked.
- AC-D2-2: Approving the request posts the new Supplier and unblocks the capture (auto-re-validate).
- AC-D2-3: Rejecting the request keeps the capture Blocked with the request linked in `validation_result`.
- AC-D2-4: A Bank-Details change request *cannot* be approved by the user who created the linked AP capture (this lays the groundwork for slice J1's SoD).

---

## 7. Phase E — Auto-Coding

### Slice E1 · Coding profile + tax-template autoselect · **M**

**Deliverables.**
- New master doctype `AP Supplier Coding Profile`: `supplier` (Link, unique), `default_expense_account`, `default_cost_center`, `default_purchase_tax_template`, `default_payment_terms_template`, `default_accounting_dimensions` (Table of dimension+value).
- Extend the promotion + JE branches (slices F1, F2) to read this profile when promoting; falls back to caller-supplied defaults; falls back to `_Test*` only in tests.
- New whitelisted `apply_coding_profile_for(capture)` for re-running coding after a corrected supplier match.

**Acceptance criteria.**
- AC-E1-1: A capture for a supplier with a profile auto-populates expense account, cost center, tax template on promotion without any caller-supplied defaults.
- AC-E1-2: Editing the profile and re-running `apply_coding_profile_for` updates the draft PI but never a submitted PI.
- AC-E1-3: A capture for a supplier without a profile prompts the clerk for coding before promotion.

---

## 8. Phase F — Classification + Branches

### Slice F1 · Classification + PI branch refactor · **M**

**Deliverables.**
- Add `document_type` field on `Document Capture`: `Literal["Unpaid Bill", "Already Paid", "Employee Reimbursement", "Manual Review"]`.
- New whitelisted `classify_document_type_for(capture, override=None)`:
  - Rule 1: If capture metadata includes a card-charge marker (extracted by OCR — slice C2 surfaces "paid by Visa ****1234" lines) → `Already Paid`.
  - Rule 2: If supplier matches an "employee" supplier group → `Employee Reimbursement`.
  - Rule 3: Otherwise → `Unpaid Bill`.
  - `override` always wins (clerk classification).
- Refactor `promote_to_purchase_invoice` to assert `document_type == "Unpaid Bill"`.

**Acceptance criteria.**
- AC-F1-1: A card receipt with `"paid by"` marker classifies as `Already Paid`.
- AC-F1-2: Clerk override forces classification regardless of rules.
- AC-F1-3: `promote_to_purchase_invoice` raises `CapturePromotionError` if `document_type != "Unpaid Bill"`.

### Slice F2 · Already-Paid branch (PI + Credit Card Clearing per D1) · **M**

**Deliverables.**
- New whitelisted `promote_to_already_paid_invoice_for(capture)`:
  - Requires `document_type == "Already Paid"` and `AP Settings.credit_card_clearing_account` configured.
  - Inserts and **submits** a `Purchase Invoice` with payment terms = "paid", paid_to_account = Credit Card Clearing.
  - Inserts and submits the offsetting `Payment Entry` (or `Journal Entry` if D1 flipped to JE — the function is one decision point, swap-friendly).
- The capture's closure derivation reuses `build_closure_evidence` but `closure_basis` reflects the Credit-Card-Clearing path.

**Acceptance criteria.**
- AC-F2-1: An Already-Paid capture posts a PI + offsetting PE; the supplier appears in `Accounts Payable Summary` for that period at the gross amount.
- AC-F2-2: After bank reconciliation in slice I1 matches the actual card transaction to the Credit Card Clearing line, the clearing account zeros out.
- AC-F2-3: GL effect is zero net liability on the Creditors account after both vouchers post.

### Slice F3 · Reimbursement placeholder · **S** (Phase 2 closes here)

**Deliverables.**
- `document_type = "Employee Reimbursement"` routes to `Manual Review` with `action_required_reason = "Employee Reimbursement requires hrms.expense_claim — Phase 3"`.
- `expense_claim` link field reserved; no logic wired.

---

## 9. Phase G — Confidence-Based Routing

### Slice G1 · Combined-signal routing · **M**

**Deliverables.**
- Extend `request_approval` to a two-axis evaluator:
  - Axis 1: amount vs `AP Settings.auto_post_amount_threshold`.
  - Axis 2: all-mandatory-field confidences ≥ threshold (from confidence child table) AND zero open validation flags.
- Decision matrix:

  | Axis 1 (amount) | Axis 2 (confidence + validation) | Outcome |
  |---|---|---|
  | ≤ threshold | clean | Auto Approved + Auto Posted |
  | ≤ threshold | flagged | Review Queue |
  | > threshold | clean | Pending Manager (skip clerk re-review) |
  | > threshold | flagged | Review Queue → Pending Manager after clerk clears |

- Surface the reason in `routing_reason` (already exists, gets richer text).

**Acceptance criteria.**
- AC-G1-1: A capture with all-high confidence and amount ≤ threshold auto-posts the PI.
- AC-G1-2: A capture with low confidence on `total_amount` goes to Review Queue with `routing_reason` naming the field.
- AC-G1-3: An over-threshold but clean capture skips the Confirmed/Validated clerk gates if `AP Settings.fast_path_high_confidence = 1`.

---

## 10. Phase H — Deep Validation Gates

### Slice H1 · Three-way match · **L**

**Deliverables.**
- New function `three_way_match_for(capture)`:
  - For each capture item with a `po_reference`:
    - Read PO item qty + rate.
    - Read accumulated PR item received_qty from `tabPurchase Receipt Item` filtered to that PO line.
    - Apply tolerance from `AP Settings` (`qty_tolerance_pct`, `amount_tolerance_pct`) — defaults 0/0 (strict); per-supplier overrides via `AP Supplier Coding Profile`.
  - Output: `Matched` if all lines match within tolerance; `Exception` otherwise with a per-line diff in `three_way_match_result`.
- Populate `three_way_match_status` on the capture.
- Wired into the validation step: `Exception` adds an issue to `validation_result` and blocks promotion until cleared by an AP clerk override + audit row.

**Acceptance criteria.**
- AC-H1-1: A PI capture with all lines matching PO + PR within tolerance gets `Matched`.
- AC-H1-2: A PI capture whose total exceeds PO line by > tolerance gets `Exception` with a diff message naming the line.
- AC-H1-3: A PO-less invoice gets `Not Applicable`.
- AC-H1-4: A clerk override transitions `Exception` → `Matched (Override)` and records `decision_by`, `decision_at`, `decision_notes`.

**Risk.** PO/PR tables are large; matching must be indexed (`po_detail` / `purchase_order_item` already indexed in upstream). Confirm with EXPLAIN ANALYZE on a 1M-row PR table before merging.

### Slice H2 · Amount anomaly detection · **M**

**Deliverables.**
- New `detect_amount_anomaly_for(capture)`:
  - Pull last 6 months of submitted PI grand totals for `matched_supplier`.
  - Compute mean + stddev via `pandas` (already a dep).
  - If `abs(total - mean) > 3 * stddev` AND sample size ≥ 5 → `Anomalous`.
  - If sample size < 5 → `Insufficient History` (records but doesn't block).
  - Populate `anomaly_status` + `anomaly_result` (e.g. `"Total 18,400 USD vs 6-mo mean 5,200 ± 700 (z=18.9)"`).
- Daily scheduler `ap_settings.refresh_anomaly_baselines` caches per-supplier mean+stddev so per-capture checks are O(1).
- Anomalous captures are added to the review queue with `action_required_reason = "Amount anomaly: …"`.

**Acceptance criteria.**
- AC-H2-1: 6 prior invoices of ~$5k each followed by a new $50k invoice triggers `Anomalous`.
- AC-H2-2: A supplier with 2 prior invoices yields `Insufficient History` (no block).
- AC-H2-3: A new $5.2k invoice in the same supplier sequence does not trigger.
- AC-H2-4: The baseline refresh job completes for 10k suppliers in < 60s.

### Slice H3 · Vendor bank-detail change detector · **S**

**Deliverables.**
- New `detect_vendor_bank_change_for(capture)`:
  - Reads `Version` records for the matched `Supplier` since the last submitted `Payment Entry` against that supplier.
  - If any change touches the supplier's bank fields (`bank_name`, `bank_account_no`, `iban`, `swift`), set `vendor_bank_change_detected = 1`.
  - Adds the issue to `validation_result` and blocks promotion until a `Supplier Master Change Request` (D2) of type `Update Bank Details` exists and is `Approved` AND was approved by someone other than the AP clerk on this capture.
- Surface change details in `validation_result` for the clerk.

**Acceptance criteria.**
- AC-H3-1: Changing a Supplier's IBAN and then promoting a capture for that Supplier fires the check and blocks.
- AC-H3-2: With an Approved `Update Bank Details` request linked, the block clears.
- AC-H3-3: A self-approved request still blocks (covered by D2's SoD test, asserted here too for safety).

---

## 11. Phase I — Real Bank Reconciliation

### Slice I1 · Bank-transaction match + dual closure · **L**

**Pre-flight.** D3 retires the Phase-1 "no Bank Transaction" guardrail. Update the docstrings on `walking_skeleton.py` and `document_capture.py` *in the same PR* to reflect the new closure model.

**Deliverables.**
- Add `bank_transaction` (Link → Bank Transaction) and `bank_cleared` (Check) to `Document Capture`.
- New whitelisted `ingest_bank_transaction_match_for(bank_transaction)`:
  - Called by an extension to ERPNext's `get_matching_queries` hook — when a Bank Transaction is reconciled to a Payment Entry linked from a capture, write back to the capture.
  - Sets `bank_cleared = 1` and `bank_transaction = bank_txn.name`.
- Extend `build_closure_evidence`:
  - Split top-level boolean into `settled` (today's derivation) and `bank_cleared` (new).
  - Add `bank_match` block: `{ bank_transaction, date, amount, reconciled_by, reconciled_at }`.
  - `closure_basis` text describes both signals.
- Adjust `payment_lifecycle_status` derivation:
  - `Closed (Settled)` — old definition.
  - `Closed (Bank Cleared)` — settled AND bank_cleared.

**Acceptance criteria.**
- AC-I1-1: A capture's settled state does not change on bank reconciliation.
- AC-I1-2: Reconciling the linked PE's Bank Transaction sets `bank_cleared = 1` and `closure_basis` mentions both signals.
- AC-I1-3: `Closed (Bank Cleared)` only fires when both signals are true.
- AC-I1-4: The old Phase-1 tests asserting `bank_transaction_count == 0` are updated to assert the new dual state instead, in the same PR.

### Slice I2 · Mock bank-feed fixtures + reconciliation harness · **M**

**Deliverables.**
- New fixtures module `erpnext/accounts/ap_closed_loop/mock_bank_feed.py`:
  - Builds `Bank Transaction` records that match a given PE on amount + date + party name suffix.
  - Records carry a `description` field tagged `"MOCK FEED — pilot fixture"`.
- Test harness `test_mock_bank_feed_reconciliation.py` drives an end-to-end capture → PI → PE → mock-feed Bank Transaction → reconciliation → `bank_cleared = 1`.
- `MOCK_PAYMENT_REMARK` is *not* changed — the mock label is now on the *feed source*, not on PE.

**Acceptance criteria.**
- AC-I2-1: End-to-end test cycle ends with both `settled` and `bank_cleared` true and the capture's closure evidence carrying the matched Bank Transaction.
- AC-I2-2: Mock fixtures are clearly tagged in production data, never colliding with real Plaid output.

---

## 12. Phase J — Approval + SoD

### Slice J0 · Reject / reopen lifecycle · **S**

**Deliverables.**
- New whitelisted `reject_capture_for(capture, reason)`:
  - Allowed from any non-terminal state except `Promoted`.
  - Writes to `AP Capture Rejection Log` child table.
  - Status → `Rejected`, `action_required = 0` (terminal until reopened).
- New whitelisted `reopen_capture_for(capture, reason)`:
  - Allowed only from `Rejected`.
  - Adds a "Reopened" row to the rejection log.
  - Status reverts to the prior captured stage (logged on rejection).

**Acceptance criteria.**
- AC-J0-1: Rejecting a Pending Review capture moves it to Rejected with the reason persisted.
- AC-J0-2: Reopening returns it to Pending Review and keeps history.
- AC-J0-3: You cannot reject a Promoted capture (Capture has handed off to PI lifecycle).

### Slice J1 · SoD validator + matrix + Supplier change workflow · **L**

**Deliverables.**
- Extend `request_approval` and `record_manager_decision`:
  - If `AP Settings.enforce_sod = 1` and `actor == capture.reviewed_by` and (amount > `sod_threshold_amount` OR `change_type ∈ bank-related`), raise `CaptureApprovalError`.
- New optional doctype `AP Approval Matrix` (rule rows: amount range, department, cost-center, supplier risk → approver role / user). When present, drives `assigned_approver_role`.
- Wire D2's `Supplier Master Change Request` workflow so bank-detail changes route to a **distinct** approver role (`Treasury Approver`) configurable in `AP Settings`.
- `sod_check_status` populated per slice; surfaced in the audit trail (L1).

**Acceptance criteria.**
- AC-J1-1: An attempt by the AP clerk who reviewed the capture to also approve it (above SoD threshold) raises `CaptureApprovalError`.
- AC-J1-2: Approving a Bank-Details change as the same user who logged the linked invoice raises an error.
- AC-J1-3: The Approval Matrix correctly routes a $25k IT-cost-center invoice to the IT manager.

---

## 13. Phase K — Payment Execution

### Slice K1 · NACHA ACH file rail · **L**

**Deliverables.**
- New utility `erpnext/accounts/ap_closed_loop/payment_rails/nacha.py`:
  - Reads a batch of approved PE drafts (still draft because we don't submit until file is generated).
  - Builds a NACHA file (PPD or CCD as configured per supplier).
  - Returns the file + a `Payment Order` (existing upstream doctype) wrapper.
- New whitelisted `issue_real_payment_for(capture, rail="ACH")`:
  - Same preconditions as the mock issuance.
  - For `ACH`, drafts PE, attaches to a fresh or open `Payment Order`, generates NACHA on order submission, marks PE as submitted with `reference_no = NACHA file batch ID`.
  - Idempotency key (slice A1) is `(capture.name, "real_payment", AP Settings version)`.
- `mock` rail stays available (renamed `issue_mock_payment_for`'s docs to "pilot-only").

**Acceptance criteria.**
- AC-K1-1: A batch of 5 approved captures produces a single valid NACHA file with 5 entries; the file passes NACHA validators on test data.
- AC-K1-2: Re-running with the same idempotency key returns the same `Payment Order` without re-posting PEs.
- AC-K1-3: A failure mid-batch (e.g. missing bank routing) rolls back to draft PEs and does not produce a partial file.
- AC-K1-4: The NACHA file never includes a supplier whose bank-detail change is pending or unapproved (cross-check against D2 + H3).

**Risk.** NACHA format is finicky (record-length 94, file balancing, hash totals). Mitigation: use `nacha-files`-style library or a well-tested vendored implementation; fixture-driven tests cover every NACHA validator's edge case.

### Slice K2 · Already-Paid no-op + payment-skip path · **S**

**Deliverables.**
- For `document_type == "Already Paid"`, `issue_real_payment_for` short-circuits, asserts the offsetting PE/JE from F2 is already submitted, and sets `payment_lifecycle_status` directly to `Confirmed` (the bank-feed match in I1 closes it to `Closed (Bank Cleared)`).

**Acceptance criteria.**
- AC-K2-1: Calling `issue_real_payment_for` on an Already-Paid capture is a no-op and returns the existing PE.
- AC-K2-2: A capture cannot reach K2 without F2 having submitted the offsetting voucher (guard in code).

---

## 14. Phase L — Audit + Retention

### Slice L1 · Single-record audit trail endpoint · **S**

**Deliverables.**
- New whitelisted `build_audit_trail_for(capture)`:
  - Returns `build_closure_evidence(capture)` + a `history` block enumerated from Frappe `Version` for: the capture itself, the linked PI, PE, JE, Bank Transaction, Supplier Master Change Request, and rejection log.
  - Adds `gates` block summarizing each validation gate's outcome: dedupe, OCR confidence, supplier match, three-way match, anomaly, bank-change, SoD.
- A read-only print format `AP Audit Trail` renders the JSON as a single PDF.

**Acceptance criteria.**
- AC-L1-1: Calling the endpoint on a fully closed capture returns a payload with every gate result + the full chain of voucher names + a chronologically ordered change log.
- AC-L1-2: The print format renders without truncation for a 12-line invoice with a rejection-and-reopen history.

### Slice L2 · Trial-balance drift + 7-year retention · **M**

**Deliverables.**
- New report `Accounts Payable Trial Balance Drift`:
  - Compares current Creditors + Credit Card Clearing balances against the latest `Account Closing Balance` snapshot, broken down by supplier.
  - Surfaces any non-zero drift exceeding a configurable cents-level threshold.
- New scheduler job `ap_settings.archive_old_captures` (hourly_maintenance):
  - For captures + linked Files older than 7 years and not yet archived, set `archive_pending = 1` and emit a Notification to the AP role. Phase 2 does *not* delete; it flags. Cold-storage handoff is Phase 3.

**Acceptance criteria.**
- AC-L2-1: A synthetic 1¢ drift on Creditors is detected by the report.
- AC-L2-2: A capture older than 7 years gets `archive_pending = 1` and a Notification fires.
- AC-L2-3: No `File` is deleted by the scheduler in Phase 2.

---

## 15. Cross-Cutting Engineering

These apply across every slice:

| Concern | Standard |
|---|---|
| **Idempotency** | Every downstream `Supplier`/`Purchase Invoice`/`Payment Entry`/`Journal Entry`/`Bank Transaction` insert uses a key from `idempotency.generate_key`. The `AP Posting Ledger` doctype is the dedupe surface. |
| **Async** | OCR (C1), Anomaly baseline refresh (H2), NACHA generation (K1), audit-trail PDF render (L1) all use `async_runner.enqueue_step`. UI never blocks on these. |
| **Observability** | Each whitelisted method emits a `Capture Event` row (lightweight log child table; could reuse Frappe's Activity Log if cardinality fits). |
| **Permissions** | Stick to native Role permissions. New roles: `AP Clerk`, `Accounts Manager` (already exists), `Treasury Approver`, `Auditor (Read Only)`. |
| **Migrations** | Each slice that changes existing data ships a numbered patch under `erpnext/patches/v17_0/`; `patches.txt` updated. |
| **Backwards compatibility** | Phase 1 tests must keep passing through the end of Phase G (no breaking changes). Phase H+ updates Phase 1 docstrings + the two tests that assert `bank_transaction_count == 0`. |
| **Secret handling** | OCR provider credentials live in Frappe `Password` fields (encrypted at rest). Never logged. NACHA bank credentials never leave the bench host. |
| **Test data** | Each slice contributes one or more fixtures to `erpnext/accounts/ap_closed_loop/fixtures/`. A `before_tests` extension installs them. |

---

## 16. Sequencing & Dependency Matrix

```
A1 ─┬─► B1 ─┬─► C1 ─► C2 ─┬─► E1 ─┬─► F1 ─┬─► F2 ─┐
    │       │              │       │       └──► F3 (placeholder)
    │       └─► B2         │       │
    │                      │       └─► G1 ◄────────────┐
    │       ┌──────────────┘                           │
    │       │                                          │
    │       ▼                                          │
    │      D1 ─► D2                                    │
    │              │                                   │
    │              ▼                                   │
    │             H3 ◄──┐                              │
    │                   │                              │
    │     ┌── H1 ◄──────┤                              │
    │     │             │                              │
    │     └── H2 ◄──────┘                              │
    │                                                  │
    └─► J0 ─► J1 ──────────────────────────────────────┤
                                                       │
                                                       ▼
                                                       K1 ─► K2
                                                              │
                                                              ▼
                                       I1 ─► I2 ──────────► L1 ─► L2
```

**Critical path** (longest no-parallel chain):
`A1 → C1 → C2 → F1 → G1 → H1 → I1 → K1 → L1 → L2` ≈ **9–11 weeks** at one engineer.

**Parallelizable forks once A1 is in:**
- B1/B2 (intake)
- D1/D2 (supplier)
- H2/H3 (deep gates) can land in parallel with H1
- J0 can land alongside any phase F slice
- I2 only after I1; L2 only after L1

With **2 engineers** the path collapses to **6–7 weeks**. With **3 engineers** the bottleneck is C1 (real OCR integration) and K1 (NACHA) — both ≈ L-sized, hard to split.

---

## 17. Definition of Done — Phase 2

Phase 2 is shippable to a pilot tenant when **all** of the following are true:

1. A real invoice (PDF) submitted via the desk or AP mailbox produces a capture in ≤ 15s with OCR proposal + per-field confidence.
2. Auto-post path (clean + under threshold) reaches a submitted PI + submitted PE + matched Bank Transaction with zero human touches.
3. A duplicate re-upload is blocked at intake.
4. An unknown supplier creates a `Supplier Master Change Request` and the capture is gated on its approval.
5. A bank-detail change to an existing supplier blocks the next capture for that supplier until a separate `Update Bank Details` request is approved by a non-AP user.
6. Three-way-match exceptions, amount anomalies, and confidence drops correctly land in the review queue with clear `action_required_reason`.
7. An ACH batch of approved captures produces a valid NACHA file; the same batch is reproducible by idempotency key.
8. A fully closed capture's `build_audit_trail_for` returns a complete payload and renders to a single audit PDF.
9. The trial-balance drift report shows zero drift on a closed test period.
10. All Phase 1 tests still pass (or have been explicitly updated for D3, in the I1 PR).

---

## 18. Out of Scope (Phase 3)

Carry-over backlog:
- Expense Claim (`hrms` integration) — F3 unfinished branch.
- Real bank-API rail (replacing NACHA file upload) — K1's deferred half.
- Vendor portal pull adapters — B2 abstract base only.
- Cold-storage handoff for 7-year attachments — L2 only flags today.
- Card-rail real payments (corporate-card recon beyond the F2 Credit-Card-Clearing path).
- A workspace + desk client scripts wrapping all of the whitelisted methods (Phase 2 ships endpoints; Phase 3 ships UX).
- Multi-currency invoice handling beyond ERPNext defaults (Phase 2 inherits whatever PI handles; explicit FX-anomaly detection is Phase 3).

---

## 19. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Azure DI confidence calibration differs from our 0.80 default → too many false positives | Calibrate against a 50-invoice sample drawn from a real AP mailbox before slice G1 ships; treat 0.80 as a starting value, not a hard requirement |
| Three-way-match query times on large PR tables | Index audit before H1 merges; add a `purchase_order_item.po_no` index if EXPLAIN ANALYZE shows table scans |
| NACHA validator drift between banks | Generate file against two bank validators (e.g. Chase + BofA test endpoints) in CI before K1 merges |
| `imagehash` / `pdf2image` system-dep surprise (poppler binary) | Document the dep clearly in pilot install scripts; provide a Docker layer reference in `frappe_docker` |
| Phase-1 closure guardrail removal silently breaks pilot tenants | D3 lock requires explicit ADR + a single PR that updates docstrings + tests + ships I1 together |
| OCR cost spike (per-page invoice) | Per-tenant monthly cap in `AP Settings.ocr_monthly_budget_usd`; soft-stop with notification when 80% hit |
| Supplier creation requests pile up | New scheduler alert when queue depth > 50 unapproved older than 24h |

---

## 20. Phase 2 Project-Memory Updates

The fork's `AGENTS.md` points to an Obsidian vault as canonical project state. As Phase 2 starts, update:

- `00 - Project State.md` — pivot active slice from Phase 1 closure to A1.
- `01 - Architecture Decisions.md` — add D1–D8 ADR pointers.
- `02 - Vertical Slice Plan.md` — replace Phase 1 slice list with the 18 slices in this plan.
- `04 - Acceptance Criteria Matrix.md` — add all AC-A1-* through AC-L2-* IDs.
- `06 - Claude-Codex Handoff.md` — re-bound the executor to Phase 2 slices.

GitHub: open a new epic `NexeraDigital/erpnext#10` "AP Closed Loop Phase 2 — Full 13-Step Workflow", reference D1–D8 ADRs in the description, and create one issue per slice (A1–L2 = 18 issues). Mirror the Phase-1 PR-per-slice cadence.
