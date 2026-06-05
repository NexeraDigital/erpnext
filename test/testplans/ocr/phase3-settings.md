# Test Plan — OCR Phase 3: Settings-Driven Provider Selection

> **Audience:** Cloud-hosted Claude instance on a clean ERPNext bench, no prior context. Runbook.
> **Rule:** per `CLAUDE.md` "Test plans".

---

## 1. Feature under test

**Phase 3** wires the OCR provider into `AP Closed Loop Settings` so an operator chooses it — this is the phase that **turns real OCR on in the live workflow**.

- New fields on `AP Closed Loop Settings`: `ocr_provider` (Select: *Fake (Deterministic)* / *Anthropic Claude*, required, default Fake), `ocr_model`, `ocr_fallback_model` (reserved for Phase 4), `ocr_confidence_threshold` (default 0.70), `ocr_max_file_mb` (default 25, enforced in Phase 6), `ocr_force_reextract`.
- `validate()`: selecting *Anthropic Claude* with no key in `AI Provider Settings` is rejected with a message pointing to that form (never echoing a key); out-of-range confidence is rejected.
- `get_ocr_config()` resolves the human-readable provider label to a registry key and reads model + threshold, defaulting to `fake` when unset.
- `run_extraction` now reads `get_ocr_config()` and dispatches to the configured provider/model/threshold instead of a hardcoded `fake`.

**Not in Phase 3:** no Sonnet fallback (Phase 4), no audit log (Phase 5), no file-size enforcement yet (Phase 6 — the field exists but is not enforced).

Context: `docs/planning/real-ocr-implementation-plan.md` §4.2, §8 Phase 3.

---

## 2. Branch / commit
- **Branch:** `russ/migrateToV16` (`origin` = `https://github.com/NexeraDigital/erpnext.git`)
- **Locate:** `git log --oneline -- erpnext/accounts/doctype/ap_closed_loop_settings/`
- **Frappe:** `version-16`, min `v16.18.3`.

---

## 3. Environment setup

Same as the Phase 2 plan (`real-ocr-anthropic.md` §3): fresh bench, `bench get-app` the fork, new site with erpnext, `install-app payments`, register the `AI` Module Def, `bench migrate`. Phase 3 adds DocType fields, so **`bench migrate` must be run** so they sync.

For the validation tests (TC-3/TC-4) you need to toggle the Anthropic key on/off in `AI Provider Settings` — see §3.2 of the Phase 2 plan for how the human operator obtains and stores a key. **Never put a key in the repo.**

---

## 4. Test data prerequisites
None beyond standard fixtures. No real key needed for the automated suite (the live-routing path is covered by Phase 2's own live test; Phase 3 tests dispatch with mocks).

---

## 5. Numbered test cases

### TC-1 — Phase 3 settings suite passes
```bash
bench --site <site> run-tests \
  --module erpnext.accounts.doctype.ap_closed_loop_settings.test_ap_closed_loop_settings
```
**Expected:** `OK`, 8 tests. **Pass:** green. (These tests are transaction-scoped and must NOT leave the live `ocr_provider` changed or wipe any configured key — see §8.)

### TC-2 — New fields exist on the DocType
```bash
bench --site <site> mariadb -e \
  "SELECT fieldname FROM tabDocField WHERE parent='AP Closed Loop Settings' AND fieldname LIKE 'ocr%'"
```
**Expected:** rows for `ocr_provider`, `ocr_model`, `ocr_fallback_model`, `ocr_confidence_threshold`, `ocr_max_file_mb`, `ocr_force_reextract` (+ section/column breaks). **Pass:** all present.

### TC-3 — Selecting Anthropic without a key is rejected
- **Precondition:** no Anthropic key in `AI Provider Settings`.
- **Action:** open `/app/ap-closed-loop-settings`, set **OCR Provider** = *Anthropic Claude*, Save.
- **Expected:** save fails with a validation error naming **AI Provider Settings** as where to set the key. No key value appears in the message.
- **Pass:** rejected with the right, key-free message.

### TC-4 — Selecting Anthropic with a key saves
- **Precondition:** a valid (or even placeholder) Anthropic key stored in `AI Provider Settings`.
- **Action:** set **OCR Provider** = *Anthropic Claude*, Save.
- **Expected:** saves without error.
- **Pass:** saved; the form shows Anthropic Claude selected.

### TC-5 — Default routing is still Fake (no surprise live calls)
```bash
bench --site <site> console <<'PY'
from erpnext.accounts.doctype.ap_closed_loop_settings.ap_closed_loop_settings import get_ocr_config
print("PROVIDER:", get_ocr_config()["provider"])
PY
```
**Expected:** `PROVIDER: fake` on a site where the operator hasn't switched to Anthropic. **Pass:** `fake`.

### TC-6 — End-to-end live routing (opt-in, needs a real key)
- **Precondition:** real Anthropic key stored; set **OCR Provider** = *Anthropic Claude* in the form; upload an invoice with known values and note its File docname.
- **Action:**
  ```bash
  bench --site <site> execute \
    erpnext.accounts.ap_closed_loop.extractors.anthropic.smoke_test \
    --kwargs '{"file_name": "<File docname>"}'
  ```
  (Or upload via the Document Capture form and let the cascade run.)
- **Expected:** returns `provider: anthropic` and a `proposal` matching the known invoice values.
- **Pass:** real extraction routed through the setting. **Reset OCR Provider back to Fake afterward** if this is a shared site.

### TC-7 — Regression: existing AP + extractor suites still green
```bash
bench --site <site> run-tests --module erpnext.accounts.ap_closed_loop.extractors.test_extractors
bench --site <site> run-tests --module erpnext.accounts.ap_closed_loop.extractors.test_anthropic
bench --site <site> run-tests --module erpnext.accounts.ap_closed_loop.test_walking_skeleton
bench --site <site> run-tests --module erpnext.accounts.doctype.document_capture.test_document_capture
```
**Expected:** 15, 14 (1 skipped), 4, 66 — all `OK`. **Pass:** all green.

---

## 6. Cleanup / rollback
- If you switched the provider to Anthropic for TC-6, set it back to *Fake (Deterministic)*.
- Remove any test/placeholder key from `AI Provider Settings`.
- `bench drop-site <site> --mariadb-root-password '<pw>'` to fully reset.

---

## 7. Pass / fail summary
```
Test plan: OCR Phase 3 — Settings-Driven Provider Selection
Branch:    russ/migrateToV16
Commit:    <git rev-parse HEAD>
Date:      <YYYY-MM-DD>

  [ ] TC-1  Phase 3 settings suite (8) green, non-destructive
  [ ] TC-2  new OCR fields present on the DocType
  [ ] TC-3  Anthropic without key -> rejected, key-free message
  [ ] TC-4  Anthropic with key -> saves
  [ ] TC-5  default routing is fake
  [ ] TC-6  LIVE end-to-end routing (opt-in)        [ ] skipped (no key)
  [ ] TC-7  regression suites green (15 / 14 / 4 / 66)

Overall:  [ ] PASS  [ ] FAIL
Notes:
```

---

## 8. Critical note for the executor / maintainer
The Phase 3 settings tests manipulate the Anthropic key and the `ocr_provider` Single **inside the per-test transaction with no `frappe.db.commit()`**, so IntegrationTestCase's rollback restores the site's real values afterward. **Do not add `frappe.db.commit()` to these tests** — an earlier version did, which permanently deleted a developer's configured API key and left the live provider toggled. Verify after running TC-1 that `ocr_provider` is unchanged and any real key is still present.
