# Test plan — Spec 13: Bank-Feed Match & dual-signal closure

## 1. Feature under test
The **external** close signal. ERPNext's native Bank Reconciliation matches a bank line to the
capture's Payment Entry; `reconcile_bank_for` reads that match and stamps `bank_cleared` +
`bank_transaction` + `payment_lifecycle_status='Bank Cleared'`. Closure is now **dual-signal**:
`closed = settled (internal: PI Paid + PE submitted) AND bank_cleared (external)`. The Phase-1
"no Bank Transaction" guardrail is retired. Live feed (native Plaid, decision #8) is deferred to
cutover; dev uses fixture Bank Transactions. Planning doc: `docs/spec/13-bank-feed-reconciliation.md`.

## 2. Branch / commit
`russ/migrateToV16`; commit adding `reconcile_bank_for` + the dual-signal `build_closure_evidence`.

## 3. Environment setup
`bench --site <site> migrate` (adds `bank_cleared`/`bank_transaction` + the lifecycle option). Payment
stays mock; bank feed mocked by fixture Bank Transactions.

## 4. Test data prerequisites
A settled capture (through mock payment, with a Payment Entry) + a `Bank Transaction` whose
`payment_entries` row references that PE.

## 5. Numbered test cases
### A. Automated
- **A-1.** `TestAPBankReconciliation` → `Ran 4 … OK` (settled-not-closed-without-match; dual-signal
  closed; reconcile sets cleared via a real Bank Transaction; guardrail retired).
- **A-2.** `TestAPInvoiceCaptureClosureEvidence` (updated for dual-signal) → OK.
- **A-3.** Full module → `Ran 217 … OK`.
### B. Manual UI
- **B-1.** A settled capture shows `Bank Cleared = unchecked`, `closed` evidence False.
- **B-2.** After the native bank reconciliation matches its Payment Entry, run `reconcile_bank_for`
  → `Bank Cleared` checked, `Bank Transaction` linked, lifecycle `Bank Cleared`, evidence `closed` True.

## 6. Cleanup / rollback
Automated suite rolls back. Delete fixture Bank Transactions / Bank Accounts for manual runs.

## 7. Pass/fail summary template
| # | Case | Result |
|---|---|---|
| A-1 | `TestAPBankReconciliation` — `Ran 4 … OK` | [ ] |
| A-3 | Full module — `Ran 217 … OK` | [ ] |
| B-1 | Settled but not bank-cleared → not closed | [ ] |
| B-2 | Bank match → bank_cleared → closed | [ ] |
