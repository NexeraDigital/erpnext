# Test plan — Spec 14: Closure & Audit Trail (pilot)

## 1. Feature under test
Closure is **derived, not declared**, and audit-readiness is **automated**. This pilot slice adds,
on top of spec 13's dual-signal closure (`closed = settled AND bank_cleared`):
- **`build_audit_trail_for(capture)`** — one composite of the full closure evidence (image → OCR →
  validation → gates → approval → payment → bank-match → dual-signal closure) **plus** the Frappe
  `Version` field-level history (`{version, by, at, changes:[{field,from,to}]}`). Whitelisted as
  `build_audit_trail_for_capture`. Read-only; nothing is stored.
- **`enforce_retention_policy()`** — a flag-only 7-year IRS retention scan (`AP_RETENTION_YEARS=7`).
  Finds captures with `received_at` past the window, logs them, and **NEVER deletes**. Registered on
  the **monthly** scheduler.
- **`Accounts Payable Trial Balance Drift`** Query Report — pilot listing of current AP-control-account
  (Creditors / Credit-Card-Clearing / Unmapped-Card-Spend) GL balances.

Planning doc: `docs/spec/14-closure-audit-retention.md`. **Pilot scope = 7/16 ACs**; the richer
ACs (populated `bank_match` sub-fields, blocked-lifecycle/Stream-R, PCV-snapshot drift,
Notification/`archive_pending` retention + config, print format) are deferred — TODO T-019..T-022.

## 2. Branch / commit
`russ/migrateToV16`; the commit adding `build_audit_trail_for` + `enforce_retention_policy` + the
TB-drift report (and the v16 `ignore_version` test parity fixes).

## 3. Environment setup
`bench --site <site> migrate` (registers the report and the monthly scheduler entry). Payment stays
mock; bank feed mocked by fixture Bank Transactions (as in spec 13).

> **v16 note.** Frappe v16 defaults `ignore_version = frappe.in_test`, so Version rows are suppressed
> under `bench run-tests`. Audit-critical saves force `ignore_version=False`; tests that depend on a
> Version create one explicitly. In production (`in_test` False) versions are written normally.

## 4. Test data prerequisites
A settled capture (through mock payment, with a Payment Entry). For the history assertion, one tracked
save with `ignore_version=False`. For retention, a capture whose `received_at` is backdated > 7 years.

## 5. Numbered test cases
### A. Automated
- **A-1.** `TestAPClosureAudit` → `Ran 6 … OK`:
  - audit composite returns the full key-set + non-empty `creation asc` history (AC-14-1/2);
  - unknown capture raises `DoesNotExistError` (AC-14-3);
  - no-PE capture → unmatched `bank_match`, not settled/closed, no throw (AC-14-4);
  - whitelisted-by-name matches by-doc;
  - retention flags a > 7-year capture **without deleting** and excludes a recent one (AC-14-13/14).
- **A-2.** `TestAPInvoiceCaptureClosureEvidence` / `TestAPBankReconciliation` (dual-signal) → OK (AC-14-5).
- **A-3.** Full module → `Ran 223 … OK`.

### B. Manual UI
- **B-1.** Open a closed/bank-cleared capture → `payment_lifecycle_status = Bank Cleared`, the bank
  reconciliation section shows `Bank Cleared` checked + the linked `Bank Transaction`.
- **B-2.** Reports → **Accounts Payable Trial Balance Drift** → renders one row per AP-control account
  with its current Dr−Cr balance and GL-entry count.

## 6. Cleanup / rollback
Automated suite rolls back. For manual runs, delete fixture Bank Transactions / Bank Accounts; the
retention scan deletes nothing, so no cleanup is needed for it.

## 7. Pass/fail summary template
| # | Case | Result |
|---|---|---|
| A-1 | `TestAPClosureAudit` — `Ran 6 … OK` | [ ] |
| A-3 | Full module — `Ran 223 … OK` | [ ] |
| B-1 | Closed capture shows Bank Cleared + linked Bank Transaction | [ ] |
| B-2 | TB-drift report renders AP-control balances | [ ] |
