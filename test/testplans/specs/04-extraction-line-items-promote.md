# Test Plan — Line-Item Extraction & Line-Aware Promote (spec 04)

> Clean-room runbook for the **line items** half of spec 04
> (`docs/spec/04-extraction-confidence-line-items.md`). Companion:
> `extraction-per-field-confidence.md`.

## 1. Feature under test

The extractor now pulls **line items** (description / qty / rate / amount, plus a
visible PO ref) into the `Document Capture Item` child table, and surfaces
subtotal/tax on the capture. When a clerk **promotes** a validated capture
(Stream I), the Purchase Invoice gets **one item row per capture line** (instead
of a single header line), with `po_reference`/`pr_reference` mapped to PI Item
`purchase_order`/`purchase_receipt`. If the line amounts don't reconcile to the
invoice total (within 0.01), promote **raises** and flags `action_required`
instead of booking a wrong payable. A capture with no lines keeps the old
single-header-line behaviour.

## 2. Branch / commit

- **Branch:** `russ/migrateToV16` · working tree. Verify
  `erpnext/accounts/doctype/document_capture_item/` exists and `AP Invoice
  Capture` has a `line_items` table field.

## 3. Environment setup

```bash
bench --site <test-site> migrate
```
- frappe v16 + this erpnext fork.
- **For TC-1's automated line:** pin `AP Closed Loop Settings → OCR Provider =
  Fake (Deterministic)` (record + restore the prior value).
- **For TC-2 (real lines):** Anthropic provider + key per the companion plan.
- **Promote prerequisites:** `AP Closed Loop Settings → Promote Defaults` set
  (Default Company / Item Code / Expense Account / Cost Center), or pass them in
  the Promote dialog. The pilot test fixtures are `_Test Company` / `_Test Item` /
  `_Test Cost Center - _TC`.

## 4. Test data prerequisites

- A **multi-line** invoice fixture whose lines sum to its printed total. Use
  `test/invoices/ocr-extraction/invoice_01.pdf` (2 lines) — record its SHA-256
  (`sha256sum`). For the negative case you will hand-edit a capture's lines so they
  no longer sum to the total.
- A `Supplier` matching the invoice vendor so the capture can validate + promote
  (the pilot uses `_Test Supplier`).
- A System Manager / Accounts Manager login.

## 5. Numbered test cases

### TC-1 — Automated suites
- **Action:**
  ```bash
  bench --site <test-site> run-tests --module erpnext.accounts.doctype.document_capture.test_document_capture
  ```
- **Expected:** `88 OK` (1 skipped = poppler PDF dedupe test). Includes
  `test_write_back_builds_confidence_and_line_rows`, `test_promote_creates_one_pi_item_per_line`,
  `test_promote_reconciles_pretax_lines_plus_tax`, `test_promote_reconciliation_mismatch_raises`,
  `test_promote_mismatch_not_rescued_by_partial_tax`, and the unchanged
  `test_promote_creates_native_purchase_invoice` (header-line fallback).
- **Pass/fail:** PASS iff green.

### TC-2 — Real extraction populates line items
- **Precondition:** Anthropic provider + key (companion §3).
- **Action:** upload the multi-line `invoice_01.pdf`, run extraction.
- **Expected:** the capture's **Line Items** grid has one row per printed line
  (description/qty/rate/amount), and `Subtotal Amount` / `Tax Amount` are set.
- **DB check:**
  ```bash
  bench --site <test-site> mariadb -e "SELECT description, qty, rate, amount FROM \`tabDocument Capture Item\` WHERE parent='<name>'\\G"
  bench --site <test-site> mariadb -e "SELECT subtotal_amount, tax_amount FROM \`tabDocument Capture\` WHERE name='<name>'\\G"
  ```
- **Pass/fail:** PASS iff one row per line + subtotal/tax populated.

### TC-3 — Line-aware promote → one PI item per line
- **Precondition:** the TC-2 capture is reviewed (Confirm Fields) and validated
  (matched supplier).
- **Action:** click **Promote** with the promote defaults.
- **Expected:** the created Purchase Invoice has the **same number of item rows** as
  the capture has lines; the per-line amounts reconcile to the invoice total within
  0.01 — **tax-aware**: for a taxed invoice the pre-tax lines sum to the subtotal and
  `sum(lines) + tax_amount` must equal the total (a naive `sum(lines) == total` would
  wrongly block taxed invoices); any line `po_reference` lands on PI Item `purchase_order`.
- **DB check:**
  ```bash
  bench --site <test-site> mariadb -e "SELECT pii.description, pii.qty, pii.rate, pii.amount, pii.purchase_order FROM \`tabPurchase Invoice Item\` pii JOIN \`tabDocument Capture\` c ON c.purchase_invoice = pii.parent WHERE c.name='<name>'\\G"
  ```
- **Pass/fail:** PASS iff PI item count == capture line count and amounts reconcile.

### TC-4 — Reconciliation mismatch is blocked (negative)
- **Action:** on a validated capture, edit one line's amount (via the form or
  `bench … execute`) so the lines no longer sum to `final_total_amount`, then Promote.
- **Expected:** Promote **fails** with a "line items … do not reconcile" error; the
  capture is **not** promoted (`promotion_status != Promoted`, no Purchase Invoice)
  and `action_required = 1` with a reconciliation reason.
- **DB check:**
  ```bash
  bench --site <test-site> mariadb -e "SELECT promotion_status, purchase_invoice, action_required, action_required_reason FROM \`tabDocument Capture\` WHERE name='<name>'\\G"
  ```
- **Pass/fail:** PASS iff promote is blocked and the capture is flagged, with no PI created.

### TC-5 — Header-line fallback unchanged (regression)
- **Action:** create/validate a capture with **no** line items (e.g. a receipt the
  model didn't itemize), then Promote.
- **Expected:** exactly **one** PI item row (`item_code` = the default, `qty = 1`,
  `rate = final_total_amount`).
- **Pass/fail:** PASS iff exactly one item row at the invoice total.

## 6. Cleanup / rollback

- Cancel + delete any Purchase Invoices created in TC-3/TC-5, then delete the
  captures and their `File` records.
- Restore `OCR Provider` if changed for TC-1.

## 7. Pass/fail summary template

| Case | What | Result |
|---|---|---|
| TC-1 | Automated (86 OK) | [ ] |
| TC-2 | Real extraction → one line row per printed line + subtotal/tax | [ ] |
| TC-3 | Promote → one PI item per line, totals reconcile, PO mapped | [ ] |
| TC-4 | Reconciliation mismatch blocks promote + flags capture | [ ] |
| TC-5 | No-lines capture → single header item row (unchanged) | [ ] |

**Overall:** [ ] PASS  [ ] FAIL — notes: ______
