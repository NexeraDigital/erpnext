# Test plan — Spec 12: Payment Execution (auto-pay opt-in per vendor)

## 1. Feature under test

Payment moves real money, so the safe default is **human-triggered**; the automation lever is the
per-supplier **`auto_pay_eligible`** Custom Field (default OFF). When checked, an approved AP-capture
Purchase Invoice for that supplier is **auto-paid** by the cascade (hands-free); every other vendor
pauses at `payment_readiness = Ready` for a human `issue_mock_payment` "Pay" click. Stream-R
already-paid captures skip payment entirely (spec 07). The real external rail (`issue_real_payment_for`)
is deferred to phase 2. Planning doc: `docs/spec/12-payment-execution.md`.

## 2. Branch / commit
`russ/migrateToV16`; commit adding `_seed_supplier_custom_fields` + the Step-4 `_auto_pay_eligible` gate.

## 3. Environment setup
```bash
bench --site <site> migrate     # adds the Supplier auto_pay_eligible Custom Field
bench --site <site> set-config -g ocr_provider "Fake (Deterministic)"
bench start
```
Payment is still **mock** (`MOCK-PAY-` Payment Entries; no real banking).

## 4. Test data prerequisites
A supplier (toggle its **Auto-Pay Eligible (AP)** checkbox) and a capture for it that promotes to a
≤-threshold (auto-approved) Purchase Invoice.

## 5. Numbered test cases

### A. Automated
- **A-1.** `TestAPPaymentAutoPay` → `Ran 2 … OK` (eligible vendor auto-pays; non-eligible pauses at Ready
  then a manual Pay works).
- **A-2.** `TestAPInvoiceCaptureAutoProgress` (auto-pay path) → green with the vendor marked eligible.
- **A-3.** Full module → `Ran 213 … OK` (zero regressions).

### B. Manual UI
- **B-1 (lever).** Open a Supplier → the **Auto-Pay Eligible (AP)** checkbox is present (default unchecked).
- **B-2 (pause).** With the vendor **un**-checked, drive a small capture to approved → it stops at
  `payment_readiness = Ready` with **no** Payment Entry; click **Issue Mock Payment** → a `MOCK-PAY-…`
  Payment Entry is created.
- **B-3 (auto-pay).** Check the vendor's **Auto-Pay Eligible**, drive a small capture to approved → it is
  auto-paid (Payment Entry created, `payment_lifecycle_status = Closed`) with no human click.

## 6. Cleanup / rollback
Automated suite rolls back. For manual cases cancel/delete the Payment Entry + Purchase Invoice + capture;
uncheck the Supplier flag.

## 7. Pass/fail summary template
| # | Case | Result |
|---|---|---|
| A-1 | `TestAPPaymentAutoPay` — `Ran 2 … OK` | [ ] |
| A-3 | Full module — `Ran 213 … OK` | [ ] |
| B-1 | Auto-Pay Eligible checkbox present | [ ] |
| B-2 | Non-eligible pauses; manual Pay works | [ ] |
| B-3 | Eligible vendor auto-pays | [ ] |
