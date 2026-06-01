# Test Plan — Pre-Extraction Deduplication (exact + perceptual)

> Clean-room runbook for **spec 03** (`docs/spec/03-deduplication.md`). Executable by a fresh Claude instance with **no prior context** on a clean bench. The exact-hash firewall works on any bench; the perceptual (near-duplicate) path additionally needs the `poppler` system binary + `imagehash`/`pdf2image` — flagged below as the #1 install risk.

## 1. Feature under test

Before any billable OCR runs, every freshly-intaken `AP Invoice Capture` is checked against the last 90 days for a duplicate. Two checks: an **exact file-hash** match (re-upload of identical bytes → the capture is marked **`Duplicate`**, linked to the original via `duplicate_of`, and the cascade stops with **no OCR cost**) and a **perceptual near-duplicate** match (a re-scan/re-photo of the same document → the capture is **flagged** `action_required` "suspected near-duplicate" but stays `Pending Review` and still gets OCR'd — a human confirms). It is **stream-agnostic**. The check runs as a pre-OCR **Step-0** hop on the existing async cascade. Native ERPNext `check_supplier_invoice_uniqueness` is a complementary, post-OCR backstop (off by default) — see spec §3.1.

## 2. Branch / commit

- **Branch:** `russ/migrateToV16` · working tree (apply the spec-03 changes if not present). Verify `detect_duplicates_for` / `run_dedupe_for` exist in `erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.py` and the `Duplicate` status option exists on `AP Invoice Capture`.

## 3. Environment setup

```bash
bench --site <test-site> migrate   # adds content_hash / perceptual_hash / duplicate_of /
                                    # duplicate_detected_at + the Duplicate status; adds the
                                    # dedupe Settings fields; after_migrate backfills
                                    # dedupe_enabled=1 / dedupe_window_days=90 / dedupe_phash_max_distance=6
```

- frappe v16 + this erpnext fork. **No external API keys** are needed — pin the deterministic OCR provider for the automated line: set `AP Closed Loop Settings.ocr_provider = "Fake (Deterministic)"` first (record + restore the prior value).
- **Perceptual path only (TC-4) — the #1 install risk.** `pdf2image` shells out to the **poppler** system binary, which is **NOT** on a stock dev bench (`which pdftoppm` returns nothing). To exercise near-duplicate detection install **both**:
  ```bash
  ./env/bin/pip install imagehash pdf2image      # Pillow is ALREADY present via Frappe — do NOT reinstall it
  sudo apt-get install -y poppler-utils          # provides pdftoppm / pdfinfo
  pdftoppm -v                                     # verify poppler is on PATH
  ```
  If poppler is absent, dedupe **degrades to exact-only** (TC-1/2/3 still pass; TC-4 is N/A — the system never produces a perceptual_hash).

## 4. Test data prerequisites

- A System Manager / Accounts Manager login for the UI cases.
- A single supported PDF, e.g. `invoice_acme_001.pdf` (any valid PDF). You will upload it twice (byte-identical) for the exact case.
- For TC-4: a **re-rendered** variant of the same invoice — same visual content, **different bytes** (e.g. open the PDF and re-export/print-to-PDF, or re-scan the printout). Record the SHA-256 of each file so the executor can confirm the two are byte-different:
  ```bash
  sha256sum invoice_acme_001.pdf invoice_acme_001_rescan.pdf
  ```
- A clearly different invoice `invoice_globex_002.pdf` for the negative case.

## 5. Numbered test cases

### TC-1 — Automated suites (no poppler needed)
- **Action:** (pin the Fake provider first)
  ```bash
  bench --site <test-site> run-tests --module erpnext.accounts.doctype.ap_invoice_capture.test_ap_invoice_capture
  bench --site <test-site> run-tests --module erpnext.accounts.doctype.ap_closed_loop_settings.test_ap_closed_loop_settings
  ```
- **Expected:** `79 OK` and `16 OK` respectively. The first includes `TestAPInvoiceCaptureDedup` (AC-03-1..10) + `TestAPInvoiceCaptureDedupCascade` (AC-03-12); the second includes `test_get_dedupe_config` (AC-03-11).
- **Pass/fail:** PASS iff both green.

### TC-2 — Exact re-upload → Duplicate, no OCR (AC-03-1, AC-03-12)
- **Precondition:** dedupe enabled (default).
- **Action:** at `/app/ap-invoice-capture/new` (or list **Upload**) upload `invoice_acme_001.pdf`, **Save**. Wait for the cascade to settle (it reaches **Proposed**). Then upload **the same file bytes again**, Save.
- **Expected (form, 2nd capture):** `Status = Duplicate`; a `Duplicate Of` link pointing to the first capture; `Action Required` checked with reason `Exact duplicate of APIC-…`. The OCR proposal section is empty (`OCR Status = Not Extracted`).
- **DB check:**
  ```bash
  bench --site <test-site> mariadb -e "SELECT name, status, duplicate_of, ocr_status, content_hash FROM \`tabAP Invoice Capture\` WHERE source_filename='invoice_acme_001.pdf' ORDER BY creation\\G"
  ```
  The two rows share `content_hash`; the **second** has `status='Duplicate'`, `duplicate_of` = the first's name, `ocr_status='Not Extracted'`.
- **Also assert no OCR cost:** no Integration Request was written for the second capture (the Fake provider writes none anyway; under a real provider, confirm none exists):
  ```bash
  bench --site <test-site> mariadb -e "SELECT count(*) FROM \`tabIntegration Request\` WHERE reference_docname='<2nd-capture-name>'"
  ```
  Expect `0`.
- **Pass/fail:** PASS iff the 2nd capture is `Duplicate`, linked, and never extracted.

### TC-3 — Different invoice → normal flow (AC-03-3)
- **Action:** upload `invoice_globex_002.pdf`, Save.
- **Expected:** `Status` proceeds to **Proposed** (not Duplicate); `duplicate_of` empty; `duplicate_detected_at` set (dedupe ran and found nothing).
- **DB check:** `status='Proposed'`, `duplicate_of` NULL, `duplicate_detected_at` NOT NULL.
- **Pass/fail:** PASS iff it flows normally with no duplicate flag.

### TC-4 — Near-duplicate re-scan → suspected, NOT auto-closed (AC-03-6) — *requires poppler*
- **Precondition:** poppler + imagehash + pdf2image installed (§3); restart the bench workers so they pick up the new deps.
- **Action:** upload `invoice_acme_001_rescan.pdf` (visually the same invoice as TC-2's, different bytes), Save.
- **Expected (form):** `Action Required` checked with reason `Suspected near-duplicate of APIC-… (visual match)`; `Status` is **NOT** `Duplicate` (stays in the normal lifecycle and still gets OCR'd → Proposed); `Duplicate Of` is **empty**.
- **DB check:**
  ```bash
  bench --site <test-site> mariadb -e "SELECT name, status, action_required, action_required_reason, perceptual_hash, duplicate_of FROM \`tabAP Invoice Capture\` WHERE source_filename='invoice_acme_001_rescan.pdf'\\G"
  ```
  `action_required=1`, reason mentions "near-duplicate", `status != 'Duplicate'`, `duplicate_of` NULL, `perceptual_hash` populated.
- **Pass/fail:** PASS iff flagged-but-not-blocked, no `duplicate_of`. **If poppler is absent:** mark N/A and confirm the capture instead flowed normally (exact-only degradation) with `perceptual_hash` empty.

### TC-5 — Window scoping (AC-03-2)
- **Action:** lower the window: `AP Closed Loop Settings → Deduplication → Dedupe Window (Days) = 1`, Save. In the console, backdate the TC-2 original beyond the window and re-upload identical bytes:
  ```bash
  bench --site <test-site> console
  >>> import frappe
  >>> from frappe.utils import add_to_date, now_datetime
  >>> frappe.db.set_value("AP Invoice Capture", "<TC-2 original name>", "received_at", add_to_date(now_datetime(), days=-5))
  >>> frappe.db.commit()
  ```
  Then upload `invoice_acme_001.pdf` again via the UI.
- **Expected:** the new upload is **NOT** flagged (the only prior match is older than the 1-day window) → `Status` proceeds to Proposed.
- **Pass/fail:** PASS iff the out-of-window match does not flag. **Restore `Dedupe Window (Days)` to 90 afterward.**

### TC-6 — Kill switch (AC-03-9)
- **Action:** uncheck `AP Closed Loop Settings → Deduplication → Enable Deduplication`, Save. Upload `invoice_acme_001.pdf` once more.
- **Expected:** no dedupe runs — the capture goes straight to OCR; `duplicate_detected_at` stays empty even on a byte-identical re-upload.
- **Pass/fail:** PASS iff dedupe is fully skipped. **Re-check Enable Deduplication afterward.**

## 6. Cleanup / rollback

- The automated suites (TC-1) roll back per test. Delete every `AP Invoice Capture` created through the UI in TC-2..6 (`/app/ap-invoice-capture`) **and** the uploaded `File` records (`/app/file`).
- Restore `ocr_provider` to its pre-test value; restore `Dedupe Window (Days)` to 90 and re-check `Enable Deduplication` if TC-5/TC-6 changed them.
- Leave poppler/imagehash/pdf2image installed if you want the perceptual path live; otherwise no rollback is needed for them.

## 7. Pass/fail summary template

| Case | What | Result |
|---|---|---|
| TC-1 | Automated suites (79 / 16 OK) | [ ] |
| TC-2 | Exact re-upload → Duplicate, linked, no OCR | [ ] |
| TC-3 | Different invoice → normal flow, no flag | [ ] |
| TC-4 | Near-duplicate → suspected, NOT auto-closed (*poppler*) | [ ] / N/A |
| TC-5 | Out-of-window match → not flagged | [ ] |
| TC-6 | Kill switch → dedupe skipped | [ ] |

**Overall:** [ ] PASS  [ ] FAIL — notes: ______

### 7.3 UI testing (Playwright MCP)
The UI scenarios above (TC-2 duplicate-warning form state; TC-4 suspected-near-duplicate banner) are the browser-driven steps. Drive them via the Playwright MCP per `test/testplans/BROWSER-TESTING-SETUP.md`; save screenshots to `test/testplans/screenshots/pre-extraction-dedup/<name>.png` (committed). After every UI write, verify the row in `mariadb` (the DB is the source of truth) and delete UI-created test data. **Pure server-side logic** — the 90-day lookback query and `_compute_phash` rasterization — is covered by §7.1 automated tests, not the browser.
