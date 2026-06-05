# Test Plan — OCR Phase 1: Provider Adapter (no behavior change)

> **Audience:** Cloud-hosted Claude instance executing tests on a clean ERPNext bench, with no prior context about this repo. Treat this as a runbook.
>
> **Test plan rule:** per `CLAUDE.md` "Test plans (mandatory for every feature)".

---

## 1. Feature under test

**Phase 1 of the real-OCR work** introduces an `OCRProvider` adapter so the deterministic fake extractor and a future real provider (Anthropic Claude, Phase 2) are interchangeable — **with zero behavior change** in Phase 1.

What changed:
- New package `erpnext/accounts/ap_closed_loop/extractors/`:
  - `base.py` — `OCRProvider` ABC + `ExtractionResult` dataclass + `PROPOSAL_KEYS`
  - `fake.py` — `FakeExtractor(OCRProvider)`, wrapping the existing deterministic proposal logic
  - `registry.py` — `get_extractor(name="fake") -> OCRProvider`
- `erpnext/accounts/doctype/document_capture/document_capture.py`:
  - The function previously named `run_fake_extraction` is now `run_extraction`, and it produces the proposal by calling `get_extractor("fake").extract(...)` instead of inline logic. **All field-writing, status transitions, `ocr_raw_response` construction, and the human-review pause are unchanged.**
  - `run_fake_extraction = run_extraction` is kept as a module-level backward-compatible alias (the test suite and the cascade call it by name).
  - The proposal helpers (`_detect_simulation_markers`, `_propose_for_seed`, `_seed_for_capture`) still live in `document_capture.py`; `FakeExtractor` imports them lazily.

**What did NOT change:** the cascade, the DocType schema, the `proposed_*`/`final_*` field semantics, the OCR-review pause, and the existing test files (not a single test was modified). Phase 1 is a pure structural seam.

Context (don't need to read to execute): `docs/planning/real-ocr-implementation-plan.md` §8 Phase 1.

---

## 2. Branch / commit

- **Branch:** `russ/migrateToV16` on `origin` = `https://github.com/NexeraDigital/erpnext.git`
- **Locate the Phase 1 commit:** `git log --oneline -- erpnext/accounts/ap_closed_loop/extractors/base.py` (the commit that adds the `extractors/` package).
- **Frappe app:** `version-16`, minimum `v16.18.3`.

---

## 3. Environment setup

A clean ERPNext bench with the standard test fixtures intact. From scratch:

```bash
cd ~
bench init --python python3.14 --frappe-branch version-16 frappe-bench-ocr-test
cd frappe-bench-ocr-test
bench get-app https://github.com/NexeraDigital/erpnext.git --branch russ/migrateToV16
bench new-site ocr-test.localhost \
  --mariadb-root-password '<your-mariadb-root-password>' \
  --admin-password admin \
  --install-app erpnext
```

If the `AI` module DocType from Phase 0 needs registering (only relevant if you also run Phase 0 tests):

```bash
bench --site ocr-test.localhost console <<'PY'
import frappe
if not frappe.db.exists("Module Def", "AI"):
    frappe.get_doc({"doctype":"Module Def","module_name":"AI","app_name":"erpnext","custom":0}).insert(ignore_permissions=True)
    frappe.db.commit()
PY
bench --site ocr-test.localhost migrate
```

> **Important — fixture note:** the AP test suites depend on ERPNext's standard `_Test *` records (`_Test Company`, `_Test Supplier`, `_Test Item`, `_Test Cost Center - _TC`, etc.), created by ERPNext's `before_tests` bootstrap on first `run-tests`. On a **freshly created** site this bootstraps automatically. (If you instead *reinstall* an existing site, those fixtures can be lost and fail to re-seed — symptom: `LinkValidationError: Could not find Supplier: _Test Supplier` in `setUpClass`, `Ran 0 tests`. If you hit that, create the site fresh rather than reinstalling.)

---

## 4. Test data prerequisites

None beyond the standard ERPNext test fixtures (auto-created on first `run-tests`). No users or custom records needed.

---

## 5. Numbered test cases

### TC-1 — Existing walking-skeleton suite passes unchanged

- **Action:**
  ```bash
  bench --site ocr-test.localhost run-tests \
    --module erpnext.accounts.ap_closed_loop.test_walking_skeleton
  ```
- **Expected:** all tests pass, final line `OK`, exit 0. (These tests were not modified by Phase 1.)
- **Pass:** suite green.

### TC-2 — Existing Document Capture suite passes unchanged

- **Action:**
  ```bash
  bench --site ocr-test.localhost run-tests \
    --module erpnext.accounts.doctype.document_capture.test_document_capture
  ```
- **Expected:** all ~66 tests pass, `OK`, exit 0. This is the primary proof: this suite calls `run_fake_extraction` (now the alias) 14+ times, including with `simulate_missing=`, and asserts on `proposed_*` fields, statuses, and the full cascade.
- **Pass:** suite green with no test-file modifications.

### TC-3 — Registry resolves the fake provider

- **Action:**
  ```bash
  bench --site ocr-test.localhost console <<'PY'
  from erpnext.accounts.ap_closed_loop.extractors.registry import get_extractor
  print("NAME:", get_extractor("fake").name())
  PY
  ```
- **Expected:** prints `NAME: fake-deterministic-v1`.
- **Pass:** exact match.

### TC-4 — Unknown provider raises ValueError

- **Action:**
  ```bash
  bench --site ocr-test.localhost console <<'PY'
  from erpnext.accounts.ap_closed_loop.extractors.registry import get_extractor
  try:
      get_extractor("does-not-exist")
      print("RESULT: no error (FAIL)")
  except ValueError as e:
      print("RESULT: ValueError OK —", str(e)[:60])
  PY
  ```
- **Expected:** prints `RESULT: ValueError OK — ...`.
- **Pass:** ValueError raised.

### TC-5 — Backward-compat alias identity

- **Action:**
  ```bash
  bench --site ocr-test.localhost console <<'PY'
  from erpnext.accounts.doctype.document_capture import document_capture as m
  print("ALIAS:", m.run_fake_extraction is m.run_extraction)
  PY
  ```
- **Expected:** prints `ALIAS: True`.
- **Pass:** `run_fake_extraction` is the same object as `run_extraction`.

### TC-6 — Extraction produces a deterministic proposal through the adapter

- **Action:**
  ```bash
  bench --site ocr-test.localhost console <<'PY'
  import frappe, json
  frappe.set_user("Administrator")
  def mk():
      c = frappe.new_doc("Document Capture")
      c.source_filename = "tc6_invoice.pdf"; c.file_extension="pdf"
      c.intake_channel="Manual ERPNext Upload"; c.is_supported_format=1
      c.source_file_url="/private/files/tc6.pdf"; c.received_at=frappe.utils.now_datetime()
      return c
  from erpnext.accounts.doctype.document_capture.document_capture import run_extraction
  d1 = run_extraction(mk(), save=False)
  d2 = run_extraction(mk(), save=False)
  print("PROVIDER:", d1.ocr_provider)
  print("STATUS:", d1.ocr_status)
  print("HAS_SUPPLIER:", bool(d1.proposed_supplier))
  print("HAS_INVOICE_NO:", bool(d1.proposed_supplier_invoice_no))
  print("DETERMINISTIC:", d1.proposed_supplier==d2.proposed_supplier and d1.proposed_total_amount==d2.proposed_total_amount)
  raw = json.loads(d1.ocr_raw_response)
  print("RAW_PROVIDER:", raw["provider"])
  PY
  ```
- **Expected:** `PROVIDER: fake-deterministic-v1`, `STATUS: Proposed`, `HAS_SUPPLIER: True`, `HAS_INVOICE_NO: True`, `DETERMINISTIC: True`, `RAW_PROVIDER: fake-deterministic-v1`.
- **Pass:** all lines match.

### TC-7 — `simulate_missing` still honored through the adapter

- **Action:**
  ```bash
  bench --site ocr-test.localhost console <<'PY'
  import frappe
  frappe.set_user("Administrator")
  c = frappe.new_doc("Document Capture")
  c.source_filename="tc7.pdf"; c.file_extension="pdf"; c.intake_channel="Manual ERPNext Upload"
  c.is_supported_format=1; c.source_file_url="/private/files/tc7.pdf"; c.received_at=frappe.utils.now_datetime()
  from erpnext.accounts.doctype.document_capture.document_capture import run_extraction
  d = run_extraction(c, save=False, simulate_missing=["total_amount","currency"])
  print("CURRENCY_NONE:", d.proposed_currency is None)
  print("MISSING_FIELDS:", d.proposed_missing_fields)
  PY
  ```
- **Expected:** `CURRENCY_NONE: True`, and `MISSING_FIELDS` contains both `currency` and `total_amount`.
- **Pass:** both fields flagged missing and currency stripped.

### TC-8 — Unsupported format still raises

- **Action:**
  ```bash
  bench --site ocr-test.localhost console <<'PY'
  import frappe
  frappe.set_user("Administrator")
  c = frappe.new_doc("Document Capture")
  c.source_filename="bad.gif"; c.file_extension="gif"; c.intake_channel="Manual ERPNext Upload"
  c.is_supported_format=0; c.source_file_url="/private/files/bad.gif"; c.received_at=frappe.utils.now_datetime()
  from erpnext.accounts.doctype.document_capture.document_capture import run_extraction, OCRExtractionError
  try:
      run_extraction(c, save=False); print("RESULT: no error (FAIL)")
  except OCRExtractionError: print("RESULT: OCRExtractionError OK")
  PY
  ```
- **Expected:** prints `RESULT: OCRExtractionError OK`.
- **Pass:** the unsupported-format guard still fires (proves the guard wasn't lost in the refactor).

---

## 6. Cleanup / rollback

The console probes (TC-6/7/8) use `save=False` and create no persistent records — nothing to clean. The test suites (TC-1/2) roll back per-test. To reset entirely:

```bash
bench drop-site ocr-test.localhost --mariadb-root-password '<your-mariadb-root-password>'
```

---

## 7. Pass / fail summary

```
Test plan: OCR Phase 1 — Provider Adapter
Branch:    russ/migrateToV16
Commit:    <git rev-parse HEAD of apps/erpnext>
Date:      <YYYY-MM-DD>
Tester:    <agent / VM id>

  [ ] TC-1  walking-skeleton suite passes unchanged
  [ ] TC-2  Document Capture suite passes unchanged (~66 tests)
  [ ] TC-3  registry resolves fake provider -> "fake-deterministic-v1"
  [ ] TC-4  unknown provider raises ValueError
  [ ] TC-5  run_fake_extraction IS run_extraction (alias)
  [ ] TC-6  deterministic proposal through the adapter
  [ ] TC-7  simulate_missing honored through the adapter
  [ ] TC-8  unsupported format still raises OCRExtractionError

Overall result:  [ ] PASS   [ ] FAIL
Notes:
  <free text>
```

Return the checklist plus raw `run-tests` output for TC-1 and TC-2.

---

## 8. Notes for the executor

- **The whole point of Phase 1 is "no behavior change."** TC-1 and TC-2 passing with **zero test-file edits** is the load-bearing evidence. TC-3–TC-8 confirm the seam is wired correctly.
- If TC-1/TC-2 fail with `Could not find Supplier: _Test Supplier` in `setUpClass` (`Ran 0 tests`), that is an environment fixture-bootstrap problem, **not** a Phase 1 regression — create the site fresh (don't reinstall) and retry. To confirm it's environmental, `git stash` the change to `document_capture.py` and re-run: the baseline fails identically.
