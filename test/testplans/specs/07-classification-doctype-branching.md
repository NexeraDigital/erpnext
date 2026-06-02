# Test Plan — Document-Type Classification & Doctype Branching (spec 07)

> Clean-room runbook for **spec 07** (`docs/spec/07-classification-doctype-branching.md`). Executable by a fresh Claude instance with no prior context on a clean bench. No external keys — pin Fake OCR. Built on **Option C (Already Paid → Purchase Invoice with `is_paid=1`)**.

## 1. Feature under test

A confirmed capture is classified into a `document_type` (Unpaid Bill / Already Paid / Employee Reimbursement / Manual Review) and routed to the right posting doctype: **Unpaid Bill → Purchase Invoice**, **Already Paid → PI with `is_paid=1`** (one submitted PI books the expense and its payment), **Employee Reimbursement → Manual Review** (the Expense Claim doctype ships with hrms, absent on this bench), **stream conflict → Manual Review**. A clerk override always wins. User-visible change: a Document-Type Classification section on `AP Invoice Capture`, a new `Manual Review` status, and an `Employee Supplier Group` setting.

## 2. Branch / commit

- **Branch:** `russ/migrateToV16` · working tree. Sanity: `classify_document_type` / `promote_already_paid` defined in `ap_invoice_capture.py`; `get_already_paid_config` in `ap_closed_loop_settings.py`; `document_type` field on the capture; `Manual Review` in the status options.

## 3. Environment setup

```bash
bench --site <test-site> migrate   # adds document_type + the classification fields,
                                    # the Manual Review status, and employee_supplier_group
```
- frappe v16 + this erpnext fork. **Pin Fake OCR.** **hrms is expected to be absent** — the Employee path *intentionally* lands in Manual Review (installing hrms makes the reserved `expense_claim` field linkable; that's a future-state note, not a step).

## 4. Test data prerequisites

- A System Manager / Accounts Manager login.
- `AP Closed Loop Settings` with `default_company`, `default_expense_account`, `default_cost_center`, and **Credit Card Clearing Account** (`credit_card_clearing_account`) set (e.g. a bank/cash account like `_Test Bank - _TC`) — this is the paid-from account for the is-paid PI.
- A Supplier Group configured as **Employee Supplier Group** and a Supplier in it (for the employee case).
- Two captures: one whose OCR text/`source_context` contains a card marker (`paid by Visa ****1234`), one with a plain bill description.

## 5. Numbered test cases

### TC-1 — Automated suite (pin Fake first)
- **Action:** `bench --site <site> run-tests --module erpnext.accounts.doctype.ap_invoice_capture.test_ap_invoice_capture`
- **Expected:** `Ran 134 tests … OK (skipped=1)` (the `TestAPInvoiceCaptureDocumentTypeBranching` class covers AC-07-1..14).
- **Pass/fail:** PASS iff green.

### TC-2 — Classify Already Paid (works)
- **Action:** create a capture whose `source_context`/OCR text is `Receipt — paid by Visa ****1234`, Confirm it, then run classification (cascade or the classify action).
- **Expected (form):** `Document Type = Already Paid`, `Classified Stream = R`, `Detected Last 4 = 1234`, `Card Charge Marker` populated.
- **DB check:** `SELECT document_type, classified_stream, detected_last4 FROM \`tabAP Invoice Capture\` WHERE name='<APIC>'\G`
- **Pass/fail:** PASS iff classified Already Paid with the marker captured.

### TC-3 — Already Paid posts an is_paid Purchase Invoice (works)
- **Action:** on the Already-Paid capture (supplier resolved), promote it (the already-paid posting). Then submit the resulting PI.
- **Expected:** a Purchase Invoice with `is_paid=1`, `cash_bank_account` = the Credit Card Clearing account, `paid_amount` = the total; `capture.purchase_invoice` set. On submit, the GL has both the supplier (invoice) legs and a **bank-account leg** (the payment).
- **DB check:** `SELECT is_paid, cash_bank_account, paid_amount FROM \`tabPurchase Invoice\` WHERE name='<PI>'` and `SELECT account, debit, credit FROM \`tabGL Entry\` WHERE voucher_no='<PI>'`.
- **Pass/fail:** PASS iff the is-paid PI posts both GL layers.

### TC-4 — Unpaid Bill routes to the Purchase Invoice path (works)
- **Action:** a plain-bill capture (no marker, ordinary supplier), Confirm + classify.
- **Expected:** `Document Type = Unpaid Bill`, `Classified Stream = I`; it proceeds through the normal validate → promote PI path.
- **Pass/fail:** PASS iff classified Unpaid Bill.

### TC-5 — Stream conflict → Manual Review (guard)
- **Action:** a capture the intake tagged as Invoice (`stream = Invoice (I)`) but whose text shows a `paid by Visa ****1234` card marker; classify.
- **Expected:** `Document Type = Manual Review`, `Status = Manual Review`, `Stream Tag Agreement = Disagree`, `Action Required = 1` with a reason naming the conflict. The capture halts (no auto-posting).
- **Pass/fail:** PASS iff the disagreement routes to review and records the signal.

### TC-6 — Employee Reimbursement → Manual Review (hrms absent)
- **Action:** a capture whose matched supplier is in the Employee Supplier Group; classify.
- **Expected:** `Document Type = Employee Reimbursement`, `Status = Manual Review`, an action-required reason naming the hrms dependency, and **no** `expense_claim` link (it's a Data placeholder).
- **Pass/fail:** PASS iff routed to Manual Review with the hrms note.

### TC-7 — Clerk override wins
- **Action:** on the Already-Paid capture (card marker present), set `Classification Override = Unpaid Bill` and re-run classify.
- **Expected:** `Document Type = Unpaid Bill`, `Classification Source = clerk-override`.
- **Pass/fail:** PASS iff the override beats the heuristic.

### TC-8 — Guards (negative)
- Promote an Already-Paid capture through the **standard** PI path → rejected (`document_type` guard).
- Promote a non-Already-Paid capture through the already-paid path → rejected.
- Already-paid promote with **no Credit Card Clearing account** configured → rejected, no PI created.
- A second already-paid promote on an already-promoted capture → rejected.
- **Pass/fail:** PASS iff each guard fires.

## 6. Cleanup / rollback

- Delete test `Purchase Invoice` (cancel first if submitted), `AP Invoice Capture`, Suppliers, and the Supplier Group created.
- Clear the test `Employee Supplier Group` / `Credit Card Clearing Account` settings; restore OCR Provider.

## 7. Pass/fail summary template

| Test | Description | Result |
|---|---|---|
| TC-1 | Automated suite (134 OK) | [ ] |
| TC-2 | Classify Already Paid + marker | [ ] |
| TC-3 | Already Paid → is_paid PI, both GL layers | [ ] |
| TC-4 | Unpaid Bill → PI path | [ ] |
| TC-5 | Stream conflict → Manual Review + Disagree signal | [ ] |
| TC-6 | Employee → Manual Review (hrms absent) | [ ] |
| TC-7 | Clerk override wins | [ ] |
| TC-8 | Guards (4) all fire | [ ] |

**Overall:** [ ] PASS / [ ] FAIL — notes:
