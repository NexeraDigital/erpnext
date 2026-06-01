# Test Plan — Per-Field Extraction Confidence (spec 04)

> Clean-room runbook for the **numeric per-field confidence** half of spec 04
> (`docs/spec/04-extraction-confidence-line-items.md`). Executable by a fresh
> instance with no prior context. Companion: `extraction-line-items-promote.md`.

## 1. Feature under test

The Anthropic extractor now **keeps** the numeric per-field confidence it already
computes (it used to discard it). Each extracted field gets a row in the
`AP Invoice Capture Confidence` child table with the score, a derived
`is_above_threshold` flag, and a `score_source` (`Model` vs `Derived-Mapping`).
Thresholds resolve as `field_thresholds[field]` → the canonical
`ocr_confidence_threshold` (no second scalar). The raw scores are also mirrored
into `ocr_raw_response`, which must contain **no credentials**.

## 2. Branch / commit

- **Branch:** `russ/migrateToV16` · working tree (apply spec-04 if absent). Verify
  `erpnext/accounts/doctype/ap_invoice_capture_confidence/` exists and
  `AP Invoice Capture` has a `field_confidences` table field.

## 3. Environment setup

```bash
bench --site <test-site> migrate   # creates the two child DocTypes + parent fields
```
- frappe v16 + this erpnext fork.
- **Real provider:** set `AP Closed Loop Settings → OCR Provider = Anthropic Claude`
  and configure an Anthropic API key in **AI Provider Settings**
  (`/app/ai-provider-settings`). **The human operator supplies the key** — it is
  entered in that form only, never committed and never echoed.
- **Thresholds:** set `OCR Confidence Threshold = 0.70`; optionally set
  `Per-Field Confidence Thresholds` (the `field_thresholds` JSON) to
  `{"supplier": 0.95}` to exercise a per-field override.

## 4. Test data prerequisites

- A multi-field invoice fixture with a clearly legible total and a harder-to-read
  field. Use `test/invoices/ocr-extraction/invoice_01.pdf` (modern, EUR; ground
  truth in `invoice_01.json`) or any real supplier invoice PDF.
  - SHA-256: compute with `sha256sum test/invoices/ocr-extraction/invoice_01.pdf`
    and record it in the run log so the executor confirms the same bytes.
- A System Manager / Accounts Manager login.

## 5. Numbered test cases

### TC-1 — Automated suites (no API key)
- **Action:**
  ```bash
  bench --site <test-site> run-tests --module erpnext.accounts.ap_closed_loop.extractors.test_extractors
  bench --site <test-site> run-tests --module erpnext.accounts.ap_closed_loop.extractors.test_anthropic
  bench --site <test-site> run-tests --module erpnext.accounts.doctype.ap_closed_loop_settings.test_ap_closed_loop_settings
  ```
- **Expected:** `19 OK`, `26 OK` (1 skipped = live API), `17 OK`.
- **Pass/fail:** PASS iff green.

### TC-2 — Real extraction populates confidence rows
- **Precondition:** Anthropic provider + key configured (§3).
- **Action:** upload `invoice_01.pdf` at `/app/ap-invoice-capture/new`, Save, and let
  the extraction cascade run (or call
  `bench --site <test-site> execute erpnext.accounts.doctype.ap_invoice_capture.ap_invoice_capture.run_extraction --kwargs "{'capture':'<name>'}"`).
- **Expected:** the capture's **Field Confidences** grid has one row per header field
  (supplier / supplier_invoice_no / invoice_date / total_amount / currency), each with
  a numeric `confidence` and `score_source = Model`.
- **DB check:**
  ```bash
  bench --site <test-site> mariadb -e "SELECT field_name, confidence, is_above_threshold, score_source FROM \`tabAP Invoice Capture Confidence\` WHERE parent='<name>'\\G"
  ```
- **Pass/fail:** PASS iff one Model row per header field with a 0–1 score.

### TC-3 — Threshold boundary + per-field override
- **Action:** with `OCR Confidence Threshold = 0.70` and `field_thresholds =
  {"supplier": 0.95}`, inspect the rows from TC-2.
- **Expected:** a field scoring ≥ 0.70 has `is_above_threshold = 1`; one < 0.70 has
  `0`; `supplier` is judged against `0.95` (so a 0.92 supplier reads `0` even though
  it clears the 0.70 scalar).
- **Pass/fail:** PASS iff the derived flag matches the resolved per-field threshold.

### TC-4 — No credentials in the audit copy
- **Action:**
  ```bash
  bench --site <test-site> mariadb -e "SELECT ocr_raw_response FROM \`tabAP Invoice Capture\` WHERE name='<name>'\\G"
  ```
- **Expected:** the JSON contains `confidence` and `lines` keys but **no**
  `api_key` / `x-api-key` / `sk-ant` / `authorization` substring anywhere.
- **Pass/fail:** PASS iff no credential appears.

## 6. Cleanup / rollback

- Delete the capture(s) created in TC-2 and their uploaded `File` records.
- Reset `field_thresholds` and restore `OCR Provider` to its pre-test value.
- Never leave a real API key in a shared site beyond the test window.

## 7. Pass/fail summary template

| Case | What | Result |
|---|---|---|
| TC-1 | Automated (19 / 26 / 17 OK) | [ ] |
| TC-2 | Real extraction → one Model confidence row per header field | [ ] |
| TC-3 | is_above_threshold honors per-field override + boundary | [ ] |
| TC-4 | ocr_raw_response carries scores but no credential | [ ] |

**Overall:** [ ] PASS  [ ] FAIL — notes: ______
