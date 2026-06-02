# Test plan — Spec 10: AP Review (Exception Handling) — instrumented feedback gate

## 1. Feature under test

Step 9 becomes an instrumented feedback gate:
- **Reject / reopen** — a clerk can bounce a non-promoted capture back to the vendor with a reason
  (`status = Rejected`, `action_required = 0`, an `AP Capture Rejection Log` child row) and later
  **reopen** it, restoring the exact stage it was rejected from. The trail is preserved across cycles.
- **`AP Review Event`** — every review action (confirm/correct, manager reject, route-to-review,
  reject/reopen) emits exactly one append-only event carrying a fixed-vocabulary `root_cause_tag`.
- **Weekly report + chart** — "AP Top Step 9 Root Causes" Query Report (`GROUP BY root_cause_tag`)
  and the "AP Review Root Causes" Group-By Dashboard Chart drive the auto-rate tuning loop.

Planning doc: `docs/spec/10-ap-review-observability.md`. Reconciliation: **Already-Paid (Stream R)**
captures emit a lighter event subset (no approval/rejection root causes); the capture-level reject
here is distinct from spec 11's PI-level Workflow reject.

## 2. Branch / commit

- **Branch:** `russ/migrateToV16`
- **Commit:** the commit adding the `AP Review Event` + `AP Capture Rejection Log` DocTypes
  (`git log --oneline -1` after checkout).

## 3. Environment setup

```bash
bench --site <site> migrate      # installs both DocTypes, the report + chart, and the rejection_log field
bench --site <site> set-config -g ocr_provider "Fake (Deterministic)"
bench build --app erpnext
bench start
```
- **Apps:** `frappe` (v16), `erpnext` (this fork), `payments`. No hrms, no third-party keys.
- Standard ERPNext test records (`_Test Supplier`, `_Test Item`, `_Test Company`, `_Test Warehouse - _TC`,
  `_Test Cost Center - _TC`, `_Test Account Cost for Goods Sold - _TC`).

## 4. Test data prerequisites

A capture parked at **Proposed** (upload a blank PDF → fake OCR runs). For the report case, emit a few
events first (correct a field, reject one capture) so `tabAP Review Event` has rows to group.

## 5. Numbered test cases

### A. Automated suites (authoritative)

**A-1. Reject/reopen + instrumentation.**
- **Action:** run `TestAPReviewGate` programmatically (bench-runner summary is swallowed on WSL):
  ```python
  import unittest
  from erpnext.accounts.doctype.ap_invoice_capture import test_ap_invoice_capture as m
  r = unittest.TextTestRunner(verbosity=2).run(
      unittest.TestLoader().loadTestsFromTestCase(m.TestAPReviewGate))
  print(r.testsRun, len(r.failures), len(r.errors))
  ```
- **Expected:** `Ran 14 tests … OK` (AC-10-1…8, 12…17).

**A-2. AP Review Event primitive.**
- **Action:** `bench --site <site> run-tests --module erpnext.accounts.doctype.ap_review_event.test_ap_review_event`.
- **Expected:** `Ran 4 tests … OK` (AC-10-9…11).

**A-3. Full-module regression.**
- **Action:** `bench --site <site> run-tests --module erpnext.accounts.doctype.ap_invoice_capture.test_ap_invoice_capture`.
- **Expected:** `Ran 185 tests … OK` (skipped=1). Proves the instrumentation wiring adds no regressions.

### B. Manual UI / behavioral cases

**B-1. Reject a capture (works + the exception path).**
- **Precondition:** a capture at `Proposed`.
- **Action:** call `reject_capture_for(capture, reason="bad scan", root_cause_tag="extraction_miss")`
  (or the desk Reject action).
- **Expected:** `status = Rejected`, `action_required = 0`, one `rejection_log` row (`action=Rejected`,
  `from_status=Proposed`), and one `AP Review Event` with `action_taken=rejected`.
- **DB assert:** `SELECT status FROM \`tabAP Invoice Capture\`` → `Rejected`; one row in
  `tabAP Capture Rejection Log`; one `tabAP Review Event`.

**B-2. Reject blocked when promoted (negative).**
- **Precondition:** a promoted capture (`promotion_status = Promoted`).
- **Action:** call `reject_capture_for`.
- **Expected:** raises `CaptureValidationError`; no rejection-log row, no event written.

**B-3. Reopen restores the stage (recovery).**
- **Precondition:** the B-1 rejected capture.
- **Action:** call `reopen_capture_for(capture, reason="vendor resent")`.
- **Expected:** `status` reverts to the rejected-from stage, `action_required = 1`, a `Reopened`
  log row appended (trail preserved).

**B-4. Rejected survives a re-save.**
- **Action:** after B-1, reload the capture and `save()` again.
- **Expected:** `status` stays `Rejected` (validate() short-circuit) — it is not re-derived.

**B-5. Weekly report renders.**
- **Action:** open `/app/query-report/AP Top Step 9 Root Causes`.
- **Expected:** rows grouped by `root_cause_tag` with Events / % of Total / Distinct Captures columns.

**B-6. Auto-rate chart renders.**
- **Action:** open the "AP Review Root Causes" Dashboard Chart.
- **Expected:** a Group-By (bar) chart of event counts by `root_cause_tag`.

## 6. Cleanup / rollback

- Automated suites roll back in `tearDown`.
- For manual cases delete the capture (cascades the `rejection_log` child rows), the linked
  `AP Review Event` rows, and any promoted Purchase Invoice. Verify with `bench … mariadb`.

## 7. Pass/fail summary template

| # | Case | Result |
|---|---|---|
| A-1 | Reject/reopen suite — `Ran 14 … OK` | [ ] |
| A-2 | AP Review Event suite — `Ran 4 … OK` | [ ] |
| A-3 | Full-module regression — `Ran 185 … OK` | [ ] |
| B-1 | Reject → Rejected + log row + event | [ ] |
| B-2 | Reject blocked when promoted | [ ] |
| B-3 | Reopen restores stage + trail | [ ] |
| B-4 | Rejected survives re-save | [ ] |
| B-5 | Weekly report renders grouped | [ ] |
| B-6 | Auto-rate chart renders | [ ] |
