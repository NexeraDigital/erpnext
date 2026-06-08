# Test Plan — Lean Mode (Document Capture)

## 1. Feature under test
A single `lean_mode` Check on **AP Closed Loop Settings** (default OFF) reshapes the
Document Capture form and cascade to a receipt-focused loop. When ON: the form **hides** the
Intake Classification, Validation Gates, Approval & Routing, and Mock Payment sections (plus
the document-type classifier internals and PO/PR-reference fields), and the cascade **skips**
the spec-08 gates and the approval + payment steps — a posted Purchase Invoice is the terminal
pre-close state ("posted, awaiting bank-feed match"). OFF = the full workflow, byte-for-byte
unchanged. See `docs/architecture/FORK-CHANGES.md §35`.

## 2. Branch / commit
Branch `russ/migrateToV16`. Apply to the commit that adds FORK-CHANGES §35.

## 3. Environment setup
- A bench with this `erpnext` app installed on a site (e.g. `erpnext.localhost`).
- `bench --site <site> migrate` (adds the `lean_mode` field).
- Log in as a user with the **Accounts Manager** + **System Manager** roles.
- No third-party keys required (lean-mode logic is provider-agnostic).

## 4. Test data prerequisites
- At least one Document Capture at status **Confirmed**, `document_type = Unpaid Bill`
  (so the gate/approval sections would otherwise render). Any existing capture works; or
  create one through the normal intake → OCR → confirm flow.

## 5. Test cases

### TC-1 — Getter default + toggle (automated)
- **Action:** `bench --site <site> run-tests --module erpnext.accounts.doctype.ap_closed_loop_settings.test_ap_closed_loop_settings --test test_lean_mode_getter`
- **Expected:** `Ran 1 test … OK`. Default/blank → False; `lean_mode=1` → True.
- **Pass/fail:** OK printed.

### TC-2 — Cascade skips gates + approval/payment (automated)
- **Action:** `bench --site <site> run-tests --module erpnext.accounts.doctype.document_capture.test_document_capture --test test_lean_skips_validation_gates --test test_lean_skips_approval_and_payment_routing`
- **Expected:** `Ran 2 tests … OK`. Lean ON → gate `*_checked_at` stay None and
  `_determine_next_step` returns None on a promoted Unpaid Bill; lean OFF → gates stamp
  `checked_at` and routing returns `request_approval_for`.
- **Pass/fail:** OK printed.

### TC-3 — Regression unchanged with lean OFF (automated)
- **Precondition:** `lean_mode = 0` (and provider=fake, auto-confirm off, classifier=Rule to
  avoid dev-singleton drift — see T-023).
- **Action:** run the full `test_document_capture` and `test_ap_closed_loop_settings` modules.
- **Expected:** `Ran 245 tests … OK (skipped=1)` and `Ran 21 tests … OK`.
- **Pass/fail:** both OK.

### TC-4 — Form hides heavy sections when lean ON (browser)
- **Precondition:** set `lean_mode = 1` in AP Closed Loop Settings; `bench --site <site> clear-cache`.
- **Action:** hard-reload a Confirmed Unpaid Bill capture at `/app/document-capture/<name>`.
- **Expected:** `frappe.boot.ap_lean_mode === true`; the **Intake Classification**,
  **Validation Gates**, **Approval & Routing**, and **Mock Payment** sections are absent; the
  **OCR**, **Extraction Detail**, **GL Coding**, **Posting (Purchase Invoice)**, and
  **Bank-Feed Reconciliation** sections remain; the **PO reference** field is hidden;
  **Document Type** stays visible. No console errors.
- **Pass/fail:** the four sections are hidden, the kept sections show, no console error.
  Evidence: `test/testplans/screenshots/lean-document-capture/lean-on-form-hidden-sections.png`.

### TC-5 — Full form returns when lean OFF (browser)
- **Precondition:** set `lean_mode = 0`; `clear-cache`.
- **Action:** hard-reload the same capture.
- **Expected:** `frappe.boot.ap_lean_mode === false`; all four sections are visible again.
- **Pass/fail:** all sections render. Evidence:
  `test/testplans/screenshots/lean-document-capture/lean-off-full-form.png`.

## 6. Cleanup / rollback
- Reset `lean_mode` to its prior value (default 0). No data migration; existing captures are
  unaffected (lean mode is presentational + routing). `clear-cache` after toggling.

## 7. Pass/fail summary template
| Case | Pass? |
|---|---|
| TC-1 getter | [ ] |
| TC-2 cascade skips | [ ] |
| TC-3 regression (lean OFF) | [ ] |
| TC-4 form hides (lean ON) | [ ] |
| TC-5 form returns (lean OFF) | [ ] |
