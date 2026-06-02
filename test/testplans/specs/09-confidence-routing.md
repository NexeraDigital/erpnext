# Test plan — Spec 09: Confidence-Based Routing (Auto-Advance vs Needs-Review Queue)

## 1. Feature under test

`request_approval` now decides routing on a **three-axis combined signal** instead of amount alone:
1. **amount** vs the canonical `auto_post_amount_threshold` setting,
2. **confidence** — every mandatory header field (`supplier`, `supplier_invoice_no`, `invoice_date`,
   `total_amount`, `currency`) must be above threshold (spec-04 `is_above_threshold`),
3. **flags** — `validation_status == Validated` and no open spec-08 gate failure.

**User-visible behavior:** a clean+confident capture auto-advances unchanged (Auto Approved at/under
threshold, Pending Manager over it). **Any** low-confidence mandatory field or open flag parks the
capture at the new **`Needs Review`** approval state with the *specific* failing field/flag named in
`routing_reason` (and `action_required = 1`). A clerk fixes the issue and calls
`reroute_after_review_for` to send it back through. Planning doc: `docs/spec/09-confidence-routing.md`.

**Reconciliations to know before testing:** (a) **Already-Paid (Stream R)** captures post via spec 07's
`promote_already_paid` and the cascade *skips* approval — they never reach `request_approval`.
(b) **`AP Review Event`** (spec 10) is not installed yet; its emission is a guarded seam (routing still
completes without it).

## 2. Branch / commit

- **Branch:** `russ/migrateToV16`
- **Commit:** the commit adding `APPROVAL_STATUS_NEEDS_REVIEW` + `_evaluate_routing_signals`
  (`git log --oneline -1` after checkout).

## 3. Environment setup

```bash
bench --site <site> migrate                  # installs the "Needs Review" Select option
bench --site <site> set-config -g ocr_provider "Fake (Deterministic)"   # tests use run_fake_extraction directly
bench start
```
- **Apps:** `frappe` (v16), `erpnext` (this fork), `payments`. No hrms, no third-party keys.
- Standard ERPNext test records (`_Test Company`, `_Test Supplier`, `_Test Item`,
  `_Test Warehouse - _TC`, `_Test Cost Center - _TC`, `_Test Account Cost for Goods Sold - _TC`).
- Optionally set `AP Closed Loop Settings.auto_post_amount_threshold` (defaults to 1000.0).

## 4. Test data prerequisites

For the manual cases, create a promoted Stream-I capture via the desk (or the spec-04 promote helper):
fake-extract a blank PDF → confirm with `supplier=_Test Supplier`, a `total_amount`, `currency=INR` →
validate → promote. The fake extractor populates all five confidence rows at 0.95 (above threshold).
To simulate a low-confidence field, edit one `field_confidences` row's `is_above_threshold` to 0
(via `bench … mariadb` or `bench … execute frappe.db.set_value`).

## 5. Numbered test cases

### A. Automated suite (authoritative)

**A-1. Spec-09 routing suite.**
- **Action:** run the class programmatically (the bench-runner summary line is swallowed on this WSL bench):
  ```python
  import unittest
  from erpnext.accounts.doctype.ap_invoice_capture import test_ap_invoice_capture as m
  r = unittest.TextTestRunner(verbosity=2).run(
      unittest.TestLoader().loadTestsFromTestCase(m.TestAPInvoiceCaptureConfidenceRouting))
  print(r.testsRun, len(r.failures), len(r.errors))
  ```
- **Expected:** `Ran 15 tests … OK` (15 tests cover AC-09-1…14).
- **Pass/fail:** PASS iff all 15 green.

**A-2. Full-module regression.**
- **Action:** `bench --site <site> run-tests --module erpnext.accounts.doctype.ap_invoice_capture.test_ap_invoice_capture`.
- **Expected:** `Ran 171 tests … OK` (skipped=1: poppler/PDF perceptual).
- **Pass/fail:** PASS iff `OK` and count ≥ 171 — proves the confidence gate adds no false reroutes.

### B. Manual UI / behavioral cases

**B-1. Clean + under-threshold → auto-approves (works).**
- **Precondition:** a promoted Stream-I capture, `final_total_amount ≤ threshold`, all confidence rows above.
- **Action:** run **Request Approval** (or the cascade reaches Step 3).
- **Expected:** `approval_status = Auto Approved`, `action_required = 0`, `routing_reason` mentions auto-approve.
- **Pass/fail:** PASS iff Auto Approved with no manual stop.

**B-2. Low-confidence field → Needs Review (failure path).**
- **Precondition:** same capture, but set the `invoice_date` confidence row `is_above_threshold = 0`.
- **Action:** run **Request Approval**.
- **Expected:** `approval_status = Needs Review`, `action_required = 1`, `routing_reason` contains
  `invoice_date`; **not** Auto Approved; no payment readiness.
- **Pass/fail:** PASS iff parked at Needs Review naming the field.

**B-3. Re-route after fixing (recovery).**
- **Precondition:** the B-2 capture in Needs Review.
- **Action:** restore the `invoice_date` confidence row to above threshold, then call
  `reroute_after_review_for(capture)`.
- **Expected:** routes again — `Auto Approved` (≤ threshold) or `Pending Manager` (> threshold).
  Calling `reroute_after_review_for` while still flagged raises an error.
- **Pass/fail:** PASS iff the cleared capture re-routes and an uncleared one is refused.

**B-4. Over-threshold + clean → Pending Manager (unchanged).**
- **Precondition:** promoted Stream-I capture, `final_total_amount > threshold`, all confidence above.
- **Action:** run **Request Approval**.
- **Expected:** `approval_status = Pending Manager`, `assigned_approver_role = Accounts Manager`,
  `action_required = 1`.
- **Pass/fail:** PASS iff Pending Manager.

## 6. Cleanup / rollback

- Automated suite rolls back in `tearDown`.
- For manual cases delete the AP Invoice Capture and its draft Purchase Invoice; verify with
  `bench … mariadb` that no stray rows remain. Reset `auto_post_amount_threshold` if changed.

## 7. Pass/fail summary template

| # | Case | Result |
|---|---|---|
| A-1 | Routing suite — `Ran 15 … OK` | [ ] |
| A-2 | Full-module regression — `Ran 171 … OK` | [ ] |
| B-1 | Clean + under-threshold → Auto Approved | [ ] |
| B-2 | Low-confidence field → Needs Review (names field) | [ ] |
| B-3 | Re-route after fix → routes; uncleared refused | [ ] |
| B-4 | Over-threshold + clean → Pending Manager | [ ] |
