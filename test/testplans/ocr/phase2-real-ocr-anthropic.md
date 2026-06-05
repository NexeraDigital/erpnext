# Test Plan — OCR Phase 2: Anthropic Claude Extractor

> **Audience:** Cloud-hosted Claude instance executing tests on a clean ERPNext bench, with no prior context about this repo. Treat as a runbook.
>
> **Rule:** per `CLAUDE.md` "Test plans (mandatory for every feature)".

---

## 1. Feature under test

**Phase 2** adds a real OCR provider, `AnthropicExtractor`, that reads an uploaded invoice (PDF / PNG / JPG) and asks Anthropic Claude to extract the header fields (supplier, invoice number, date, total, currency) via the Messages API with a **forced tool call** for structured output.

- New: `erpnext/accounts/ap_closed_loop/extractors/anthropic.py` — `AnthropicExtractor(OCRProvider)`, registered in the registry under key `"anthropic"`.
- The provider reads the file bytes from the capture's linked `File`, sends a document block (PDF) or image block (PNG/JPG) **before** the prompt text, forces the `extract_invoice_fields` tool, and maps the tool result into the same `ExtractionResult` the fake provider returns.
- API key comes from Phase 0's `AI Provider Settings` via `get_ai_credentials("anthropic")`. Model defaults to `claude-haiku-4-5-20251001`.
- Confidence below a threshold (default 0.70) flags a field as ambiguous; a null value flags it missing.

**Not in Phase 2** (later phases): no Sonnet fallback (Phase 4), no `Integration Request` audit logging (Phase 5), and the provider is **not yet wired into the live cascade** via settings (Phase 3). It's invoked directly (registry / smoke test). The pilot still defaults to the `fake` provider until Phase 3.

Context: `docs/planning/real-ocr-implementation-plan.md` §8 Phase 2, and `docs/planning/ocr-provider-choice-claude.md`.

---

## 2. Branch / commit

- **Branch:** `russ/migrateToV16` on `origin` = `https://github.com/NexeraDigital/erpnext.git`
- **Locate:** `git log --oneline -- erpnext/accounts/ap_closed_loop/extractors/anthropic.py`
- **Frappe:** `version-16`, min `v16.18.3`.

---

## 3. Environment setup

```bash
cd ~
bench init --python python3.14 --frappe-branch version-16 frappe-bench-ocr2
cd frappe-bench-ocr2
bench get-app https://github.com/NexeraDigital/erpnext.git --branch russ/migrateToV16
bench new-site ocr2.localhost \
  --mariadb-root-password '<your-mariadb-root-password>' \
  --admin-password admin \
  --install-app erpnext
bench --site ocr2.localhost install-app payments      # AP fixtures need the Payment Gateway DocType

# Register the AI module DocType (new module added post-install)
bench --site ocr2.localhost console <<'PY'
import frappe
if not frappe.db.exists("Module Def", "AI"):
    frappe.get_doc({"doctype":"Module Def","module_name":"AI","app_name":"erpnext","custom":0}).insert(ignore_permissions=True)
    frappe.db.commit()
PY
bench --site ocr2.localhost migrate
```

### 3.1 Python dependency
Phase 2 adds the `anthropic` SDK to `erpnext/pyproject.toml`. Ensure it's installed:
```bash
bench setup requirements        # or: ./env/bin/pip install "anthropic>=0.40.0"
./env/bin/python -c "import anthropic; print(anthropic.__version__)"   # expect >= 0.40
```

### 3.2 API key (required only for the LIVE test cases — TC-7/TC-8)
The unit tests (TC-1–TC-6) mock the client and need **no key**. For the live tests:
- **How the human operator obtains a key:** create one at `https://console.anthropic.com` → API Keys. **Never put the key in this repo, a commit, or a screenshot.**
- Store it via the desk: log in as Administrator at `http://ocr2.localhost:8000/app/ai-provider-settings`, paste into **Anthropic API Key**, Save. (Or via `bench console`: set `AI Provider Settings.anthropic_api_key` and `.save()`.)
- Live tests are **opt-in**: they only run when `ENABLE_LIVE_OCR_TESTS=1` is exported AND a key is configured; otherwise they skip.

---

## 4. Test data prerequisites

- **Unit tests:** none (mocked).
- **Live tests:** one invoice file on the site. Either upload any real invoice PDF via the desk, or generate a synthetic one. A synthetic PNG invoice with known values is sufficient — include legible lines for Supplier, Invoice No, Invoice Date, Total, and Currency.

---

## 5. Numbered test cases

### TC-1 — Mocked unit suite passes (no network, no key)
- **Action:**
  ```bash
  bench --site ocr2.localhost run-tests \
    --module erpnext.accounts.ap_closed_loop.extractors.test_anthropic
  ```
- **Expected:** `OK (skipped=1)` — 14 pass, the 1 live test skips (no `ENABLE_LIVE_OCR_TESTS`). Exit 0.
- **Pass:** all non-live tests green; live test skipped, not failed.

### TC-2 — Registry resolves the anthropic provider
- **Action:**
  ```bash
  bench --site ocr2.localhost console <<'PY'
  from erpnext.accounts.ap_closed_loop.extractors.registry import get_extractor
  print("NAME:", get_extractor("anthropic").name())
  PY
  ```
- **Expected:** `NAME: anthropic`.
- **Pass:** exact match.

### TC-3 — Fake provider is still the default (Phase 2 didn't flip the pilot to live)
- **Action:**
  ```bash
  bench --site ocr2.localhost console <<'PY'
  from erpnext.accounts.ap_closed_loop.extractors.registry import get_extractor
  print("DEFAULT:", get_extractor().name())
  PY
  ```
- **Expected:** `DEFAULT: fake-deterministic-v1`.
- **Pass:** the no-arg default is still the fake provider.

### TC-4 — Phase 1 extractor suite still green (no regression)
- **Action:**
  ```bash
  bench --site ocr2.localhost run-tests \
    --module erpnext.accounts.ap_closed_loop.extractors.test_extractors
  ```
- **Expected:** `OK`, 15 tests.
- **Pass:** green.

### TC-5 — Existing AP suites still green (no regression)
- **Action:**
  ```bash
  bench --site ocr2.localhost run-tests --module erpnext.accounts.ap_closed_loop.test_walking_skeleton
  bench --site ocr2.localhost run-tests --module erpnext.accounts.doctype.document_capture.test_document_capture
  ```
- **Expected:** both `OK` (4 and ~66). If they fail in `setUpClass` with `Could not find Supplier/Customer: _Test ...`, that's the fixture-bootstrap environment issue — create the site fresh (don't reinstall) and ensure `payments` is installed.
- **Pass:** both green.

### TC-6 — Missing key raises a clear, key-free error (negative path)
- **Preconditions:** ensure no key is set:
  ```bash
  bench --site ocr2.localhost console <<'PY'
  from frappe.utils.password import remove_encrypted_password
  import frappe
  remove_encrypted_password("AI Provider Settings","AI Provider Settings","anthropic_api_key")
  frappe.db.commit()
  PY
  ```
- **Action:** instantiate the extractor with no injected client and attempt a real extract (it will try to build a client from credentials):
  ```bash
  bench --site ocr2.localhost console <<'PY'
  from erpnext.accounts.ap_closed_loop.extractors.anthropic import AnthropicExtractor
  from erpnext.ai.credentials import AICredentialsNotConfigured
  try:
      AnthropicExtractor()._get_client()
      print("RESULT: no error (FAIL)")
  except AICredentialsNotConfigured as e:
      print("RESULT: AICredentialsNotConfigured OK; message contains key?", "sk-ant" in str(e))
  PY
  ```
- **Expected:** `RESULT: AICredentialsNotConfigured OK; message contains key? False`.
- **Pass:** the right exception, and the message does not contain a key.

### TC-7 — LIVE: real extraction returns a schema-valid result (opt-in)
- **Preconditions:** key configured (§3.2); a PDF/PNG invoice File exists on the site; `ENABLE_LIVE_OCR_TESTS=1`.
- **Action:**
  ```bash
  ENABLE_LIVE_OCR_TESTS=1 bench --site ocr2.localhost run-tests \
    --module erpnext.accounts.ap_closed_loop.extractors.test_anthropic \
    --test test_live_extraction
  ```
- **Expected:** 1 test passes (not skipped). It asserts the call succeeds and all five logical keys (`supplier`, `supplier_invoice_no`, `invoice_date`, `total_amount`, `currency`) are present in the proposal. It deliberately does NOT assert specific values (model output varies).
- **Pass:** test passes (not skipped, not failed).

### TC-8 — LIVE: end-to-end extraction of a known invoice (manual accuracy check)
- **Preconditions:** same as TC-7. Upload (or generate) an invoice with **known** values — e.g. Supplier "Northwind Traders Ltd", Invoice No "NW-2026-00417", Date 2026-03-18, Total 1275.00, Currency EUR.
- **Action:** run the bench smoke helper against that file:
  ```bash
  bench --site ocr2.localhost execute \
    erpnext.accounts.ap_closed_loop.extractors.anthropic.smoke_test \
    --kwargs '{"file_name": "<File docname of the invoice>"}'
  ```
- **Expected:** the returned `proposal` matches the known values (supplier, invoice no, date as `YYYY-MM-DD`, total as a number, currency as a 3-letter code). `usage` shows non-zero input/output tokens; `model` is `claude-haiku-4-5-20251001`.
- **Pass:** all five fields match the known invoice within reason (minor punctuation/whitespace differences in supplier name are acceptable; numbers and codes must match).

---

## 6. Cleanup / rollback
- Remove any test key:
  ```bash
  bench --site ocr2.localhost console <<'PY'
  from frappe.utils.password import remove_encrypted_password
  import frappe
  remove_encrypted_password("AI Provider Settings","AI Provider Settings","anthropic_api_key")
  frappe.db.commit()
  PY
  ```
- Delete any uploaded invoice File fixtures.
- Drop the site: `bench drop-site ocr2.localhost --mariadb-root-password '<pw>'`.

---

## 7. Pass / fail summary

```
Test plan: OCR Phase 2 — Anthropic Claude Extractor
Branch:    russ/migrateToV16
Commit:    <git rev-parse HEAD of apps/erpnext>
Date:      <YYYY-MM-DD>
Tester:    <agent / VM id>

  [ ] TC-1  mocked unit suite passes (14 pass, 1 live skipped)
  [ ] TC-2  registry resolves "anthropic"
  [ ] TC-3  fake is still the no-arg default
  [ ] TC-4  Phase 1 extractor suite green (15)
  [ ] TC-5  existing AP suites green (4 + ~66)
  [ ] TC-6  missing key -> AICredentialsNotConfigured, no key in message
  [ ] TC-7  LIVE schema-valid result (opt-in)        [ ] skipped (no key)
  [ ] TC-8  LIVE known-invoice accuracy (opt-in)      [ ] skipped (no key)

Overall result:  [ ] PASS   [ ] FAIL
Notes:
```

Return the checklist plus raw `run-tests` output for TC-1, TC-4, TC-5, and (if run) TC-7.

---

## 8. Cost note for the executor
The live tests (TC-7/TC-8) make real Anthropic API calls billed to the configured key. Each is a single Haiku call on a one-page document (~1.5–2k tokens, well under $0.01). Do not loop them. The mocked suite (TC-1–TC-6) is free and is the primary regression guard.
