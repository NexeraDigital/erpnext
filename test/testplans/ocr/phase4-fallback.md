# Test Plan — OCR Phase 4: Low-Confidence Fallback (Haiku → Sonnet)

> **Audience:** Cloud-hosted Claude instance on a clean ERPNext bench, no prior context. Runbook.
> **Rule:** per `CLAUDE.md` "Test plans".

---

## 1. Feature under test

**Phase 4** adds a one-shot model fallback to `AnthropicExtractor`. After the
primary (default Haiku) extraction, if any required field is **missing or
ambiguous** (below the confidence threshold) AND a fallback model is configured,
the extractor **retries the same invoice once** with the stronger fallback model
(e.g. Sonnet) and uses that result. At most one retry — it never loops or
escalates further.

- Wired to `AP Closed Loop Settings.ocr_fallback_model` (added/​reserved in Phase
  3). Empty = fallback disabled.
- `get_ocr_config()` now returns `fallback_model`; `run_extraction` forwards it;
  `AnthropicExtractor(fallback_model=...)` consumes it.
- The result's `raw_response` records `outcome` = `"primary"` or
  `"fallback_invoked"` and `model` = the model that produced the final result.

**Not in Phase 4:** no audit-log persistence yet (Phase 5), no retry/backoff or
circuit breaker (Phase 6). Default remains Haiku with no fallback unless an
operator sets `ocr_fallback_model`.

Context: `docs/planning/real-ocr-implementation-plan.md` §3.5, §8 Phase 4.

---

## 2. Branch / commit
- **Branch:** `russ/migrateToV16` (`origin` = `https://github.com/NexeraDigital/erpnext.git`)
- **Locate:** `git log --oneline -- erpnext/accounts/ap_closed_loop/extractors/anthropic.py`
- **Frappe:** `version-16`, min `v16.18.3`.

---

## 3. Environment setup
Same as the Phase 2/3 plans (fresh bench, fork app, site with erpnext, install
`payments`, register the `AI` Module Def, `bench migrate`). The `anthropic` SDK
must be installed (`bench setup requirements`). A real Anthropic key in
`AI Provider Settings` is needed only for the live test (TC-4).

---

## 4. Test data prerequisites
None for the mocked tests. For the live test, one invoice File on the site (any
from `test/invoices/`).

---

## 5. Numbered test cases

### TC-1 — Fallback unit suite passes (mocked, no API)
```bash
bench --site <site> run-tests \
  --module erpnext.accounts.ap_closed_loop.extractors.test_anthropic
```
**Expected:** `OK (skipped=1)`, 23 tests, including the `TestAnthropicFallback`
cases:
- low-confidence primary → exactly **one** retry with the fallback model; result
  replaced; `outcome="fallback_invoked"`.
- high-confidence primary → **no** retry; `outcome="primary"`.
- no `fallback_model` → no retry even when low-confidence.
- `fallback_model == primary model` → no retry.
- both passes low-confidence → exactly 2 calls (no loop); field still flagged.

**Pass:** suite green; the live test (1) skips without a key.

### TC-2 — Settings expose the fallback model
```bash
bench --site <site> console <<'PY'
from erpnext.accounts.doctype.ap_closed_loop_settings.ap_closed_loop_settings import get_ocr_config
import frappe
frappe.db.set_single_value("AP Closed Loop Settings", "ocr_fallback_model", "claude-sonnet-4-6")
print("FALLBACK:", get_ocr_config()["fallback_model"])
frappe.db.set_single_value("AP Closed Loop Settings", "ocr_fallback_model", "")  # reset
PY
```
**Expected:** `FALLBACK: claude-sonnet-4-6`. **Pass:** value flows through.

### TC-3 — Default config has no fallback (no surprise Sonnet calls)
```bash
bench --site <site> console <<'PY'
from erpnext.accounts.doctype.ap_closed_loop_settings.ap_closed_loop_settings import get_ocr_config
print("FALLBACK:", get_ocr_config()["fallback_model"])
PY
```
**Expected:** `FALLBACK: None` on a site where the operator hasn't set one.
**Pass:** None.

### TC-4 — LIVE: fallback resolves a low-confidence read (opt-in)
- **Precondition:** real key configured; set `ocr_provider = Anthropic Claude`,
  `ocr_model = claude-haiku-4-5-20251001`, `ocr_fallback_model = claude-sonnet-4-6`.
  Pick a degraded/faxed corpus invoice (e.g. `invoice_08`).
- **Action:** run the benchmark on that one file:
  ```bash
  bench --site <site> execute \
    erpnext.accounts.ap_closed_loop.extractors.benchmark.run \
    --kwargs '{"provider": "anthropic", "model": "claude-haiku-4-5-20251001", "files": ["invoice_08"]}'
  ```
  (Note: the benchmark runner constructs the provider directly; to exercise the
  *settings-driven* fallback path end-to-end, instead upload the file via the AP
  Invoice Capture form and let the cascade run with the settings above, then
  inspect `ocr_raw_response.outcome` on the capture.)
- **Expected:** extraction succeeds; on a genuinely hard field, the capture's
  `ocr_raw_response.outcome` is `fallback_invoked` and `model` is the Sonnet id.
  On an easy invoice it stays `primary` — both are acceptable.
- **Pass:** no error; outcome/model recorded correctly.

### TC-5 — Regression: extractor + AP suites still green
```bash
bench --site <site> run-tests --module erpnext.accounts.ap_closed_loop.extractors.test_extractors
bench --site <site> run-tests --module erpnext.accounts.ap_closed_loop.extractors.test_benchmark
bench --site <site> run-tests --module erpnext.accounts.doctype.ap_closed_loop_settings.test_ap_closed_loop_settings
bench --site <site> run-tests --module erpnext.accounts.doctype.document_capture.test_document_capture
```
**Expected:** 15, 9, 8, 66 — all `OK`.

---

## 6. Cleanup / rollback
- Reset `ocr_fallback_model` to empty and `ocr_provider` to *Fake (Deterministic)*.
- Remove any test key; delete uploaded File fixtures.

---

## 7. Pass / fail summary
```
Test plan: OCR Phase 4 — Low-Confidence Fallback
Branch:    russ/migrateToV16
Commit:    <git rev-parse HEAD>

  [ ] TC-1  fallback unit suite (23) green
  [ ] TC-2  ocr_fallback_model flows through get_ocr_config
  [ ] TC-3  default config has no fallback
  [ ] TC-4  LIVE fallback path records outcome/model    [ ] skipped (no key)
  [ ] TC-5  regression suites green (15 / 9 / 8 / 66)

Overall:  [ ] PASS  [ ] FAIL
Notes:
```

## 8. Note
On the current synthetic corpus Haiku scores 100%, so the fallback rarely fires
there — its value is on genuinely messy real-world invoices. TC-1 (mocked)
deterministically exercises the fallback logic regardless.
