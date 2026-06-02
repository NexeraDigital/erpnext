# Test plan — Spec 08: Validation Gates (Three-Way Match · Amount Anomaly · Vendor Bank-Change)

## 1. Feature under test

Three **stream-aware** validation gates that run automatically when an AP Invoice Capture is
validated (`validate_for_purchase_invoice`), plus one promotion-time re-check:

1. **Three-way match** — invoiced qty/amount vs the referenced Purchase Order's cumulative
   `received_qty` + ordered amount, within configurable tolerances. Statuses: `Not Checked`,
   `Not Applicable`, `Matched`, `Exception`, `Matched (Override)`.
2. **Amount anomaly** — capture total vs the supplier's rolling submitted-PI history
   (`> multiple × mean` OR `> sigma × stddev`); `Insufficient History` below a min sample.
3. **Vendor bank-change** — a watched bank field changed *after* the supplier's last submitted
   Payment Entry (read from native `Version` audit). Blocks **promotion** until an approved
   Update-Bank-Details request lifts it.

**User-visible behavior:** on **Stream I** (invoice / unclassified) a failing gate sets the
capture to `validation_status = "Blocked"`, `action_required = 1`, with the reason in
`validation_result`, and (for a detected bank change) makes promotion raise
`CapturePromotionError`. On **Stream R** (already-paid receipt) the gates are recorded on the
capture but **never block**. An AP user can override a 3WM Exception with a typed reason.

Planning context: `docs/spec/08-validation-gates.md`. Do not restate it here.

## 2. Branch / commit

- **Branch:** `russ/migrateToV16`
- **Commit:** the commit that adds the `AP Supplier Anomaly Baseline` DocType and the
  `validation_gates_section` fields to `AP Invoice Capture` (run `git log --oneline -1` after
  checkout and record it here).

## 3. Environment setup

```bash
# From a clean bench with the branch checked out:
bench get-app erpnext <this-fork-url> --branch russ/migrateToV16   # if not already present
bench --site <site> install-app erpnext                            # if a fresh site
bench --site <site> migrate                                        # installs the new DocType + fields
bench --site <site> set-config -g ocr_provider "Fake (Deterministic)"  # optional; tests use run_fake_extraction directly
bench build --app erpnext
bench start
```

- **Apps required:** `frappe` (v16), `erpnext` (this fork), `payments`. **hrms is NOT required.**
- **No third-party API keys** are needed — the automated suite uses the deterministic Fake OCR
  path; the gates themselves call no external service.
- The site must have the standard ERPNext **test records** available (`_Test Company`,
  `_Test Supplier`, `_Test Item`, `_Test Warehouse - _TC`, `_Test Cost Center - _TC`,
  `_Test Account Cost for Goods Sold - _TC`, `_Test Bank - _TC`, `Creditors - _TC`). These are
  created automatically by the test runner; for manual UI cases create equivalents.

## 4. Test data prerequisites

The automated suite builds everything it needs and rolls back. For the **manual UI cases** in
§5.B, pre-create:

- A submitted **Purchase Order** to `_Test Supplier`: item `_Test Item`, qty 10, rate 100
  (ordered amount 1000). Set its PO-item `received_qty` to 10
  (`bench --site <site> execute frappe.db.set_value --args '["Purchase Order Item","<row>","received_qty",10]'`
  or receive it via a Purchase Receipt).
- A confirmed **AP Invoice Capture** for `_Test Supplier` referencing that PO (Phase-1 promote
  helper or the desk form), `final_total_amount = 1100`, one line qty 10 rate 110.

## 5. Numbered test cases

### A. Automated suite (authoritative)

**A-1. Spec-08 gate suite.**
- **Action:**
  ```bash
  bench --site <site> run-tests --module erpnext.accounts.doctype.ap_invoice_capture.test_ap_invoice_capture --test TestAPInvoiceCaptureValidationGates
  ```
  > If the bench runner's summary line is swallowed by your terminal, run the class
  > programmatically inside `bench console`:
  > ```python
  > import unittest
  > from erpnext.accounts.doctype.ap_invoice_capture import test_ap_invoice_capture as m
  > r = unittest.TextTestRunner(verbosity=2).run(
  >     unittest.TestLoader().loadTestsFromTestCase(m.TestAPInvoiceCaptureValidationGates))
  > print(r.testsRun, len(r.failures), len(r.errors))
  > ```
- **Expected:** `Ran 22 tests … OK` (testsRun=22, failures=0, errors=0).
- **Pass/fail:** PASS iff all 22 green. 21 map to AC-08-1 … AC-08-21; the 22nd
  (`test_ac_08_16b_promotion_recheck_after_clean_validation`) covers the AC-08-16 re-check.

**A-2. Full-module regression (blast radius — AC-08-21).**
- **Action:** same command without `--test` (whole `test_ap_invoice_capture` module).
- **Expected:** `Ran 156 tests … OK` (skipped=1: the poppler/PDF perceptual test).
- **Pass/fail:** PASS iff `OK` and count ≥ 156 with zero failures/errors — proves the gates add
  no false blocks to the pre-spec-08 happy paths.

### B. Manual UI / behavioral cases

**B-1. 3WM Exception blocks a Stream-I invoice (works + failure).**
- **Precondition:** the §4 capture (invoiced 1100 vs PO ordered 1000, tolerances 0).
- **Action:** open the capture in the desk, run **Validate** (or call
  `erpnext.accounts.doctype.ap_invoice_capture.ap_invoice_capture.validate_for_purchase_invoice`).
- **Expected:** Validation Gates section shows **Three-Way Match Status = Exception**;
  `validation_status = Blocked`; `action_required = 1`; `validation_result` contains
  "Three-way match exception".
- **Pass/fail:** PASS iff Exception + Blocked.

**B-2. 3WM override clears the block.**
- **Action:** call `override_three_way_match_for(capture, notes="Approved variance per PO amendment")`
  (whitelisted) or the desk override action.
- **Expected:** **Three-Way Match Status = Matched (Override)**; `3WM Override By` / `At` / `Notes`
  populated; after the automatic re-validate, the capture is no longer Blocked on 3WM. An empty
  notes string is rejected (`CaptureValidationError`).
- **Pass/fail:** PASS iff status flips to `Matched (Override)` and the block lifts.

**B-3. Amount anomaly blocks (works + failure).**
- **Precondition:** a supplier with ≥5 submitted PIs averaging ~5,000; a capture for that supplier
  with `final_total_amount = 18400`.
- **Action:** Validate.
- **Expected:** **Anomaly Status = Anomalous**, `anomaly_result` shows the total vs mean ± stddev;
  Blocked.
- **Pass/fail:** PASS iff Anomalous + Blocked. (A within-range total → `Normal`, not blocked.)

**B-4. Vendor bank-change blocks promotion (anti-fraud, works + failure).**
- **Precondition:** a supplier with a default Bank Account and one submitted Payment Entry; then
  change `Bank Account.iban` and save.
- **Action:** Validate, then attempt **Promote to Purchase Invoice**.
- **Expected:** **Vendor Bank Change Detected = 1**, Blocked, and promotion raises
  `CapturePromotionError` ("an approved Update-Bank-Details request is required"). After a Posted
  `Supplier Master Change Request` (type *Update Bank Details*) decided by a different user,
  promotion is allowed.
- **Pass/fail:** PASS iff detection blocks promotion and the approved request lifts it.

**B-5. Stream R short-circuits all gates.**
- **Precondition:** a Stream R capture with a deliberately bad PO match + a huge total.
- **Action:** Validate.
- **Expected:** 3WM = `Not Applicable`; anomaly recorded but **no** issue; `validation_status =
  Validated` (not blocked).
- **Pass/fail:** PASS iff Stream R validates despite gate "failures".

## 6. Cleanup / rollback

- The automated suite rolls back in `tearDown` — nothing persists.
- For manual cases, delete the created AP Invoice Capture, its draft Purchase Invoice (if
  promoted), the Purchase Order / Purchase Receipt, the Payment Entry, the Bank/Bank Account, and
  any `Supplier Master Change Request` and `AP Supplier Anomaly Baseline` rows you created. Verify
  with `bench --site <site> mariadb` that no stray rows remain.
- `AP Supplier Anomaly Baseline` rows are a derived cache and are safe to delete; the daily
  scheduler (`refresh_anomaly_baselines`) rebuilds them.

## 7. Pass/fail summary template

| # | Case | Result |
|---|---|---|
| A-1 | Gate suite — `Ran 22 … OK` | [ ] |
| A-2 | Full-module regression — `Ran 156 … OK` | [ ] |
| B-1 | 3WM Exception blocks Stream-I | [ ] |
| B-2 | 3WM override → Matched (Override), block lifts | [ ] |
| B-3 | Anomaly Anomalous blocks | [ ] |
| B-4 | Bank-change blocks promotion; approval lifts | [ ] |
| B-5 | Stream R short-circuits gates | [ ] |
