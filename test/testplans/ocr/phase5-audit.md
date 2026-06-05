# Test Plan — OCR Phase 5: Audit Logging & Cost Tracking

> **Audience:** Cloud-hosted Claude instance on a clean ERPNext bench, no prior context. Runbook.
> **Rule:** per `CLAUDE.md` "Test plans".

---

## 1. Feature under test

**Phase 5** records every real OCR extraction (and failure) as a Frappe
**`Integration Request`** — the standard outbound-API audit DocType used by
payment gateways. Operators get a queryable trail of model calls with token
usage, estimated cost, latency, outcome, and (on failure) a sanitized error.

- `AnthropicExtractor` now accumulates per-call telemetry (`calls`:
  model + input/output tokens for the primary AND any fallback call) plus total
  `latency_ms` into `raw_response`.
- `extractors/pricing.py` estimates cost from token usage via a per-model rate
  table (`estimate_cost_usd`).
- `extractors/audit.py` `write_integration_request(...)` creates the row:
  `integration_request_service="anthropic"`, `reference_doctype/docname` = the
  capture, `output` = JSON {model, outcome, calls, total tokens, cost_usd_estimate,
  latency_ms, missing/ambiguous}, `error` = sanitized text on failure.
- `run_extraction` logs a `Completed` row on success and a `Failed` row on
  exception — **only for the real (anthropic) provider**; the fake provider
  makes no call and is not logged. Audit failures never break extraction.
- **No API key is ever stored** in any field; `sanitize()` scrubs key-like text.

**Not in Phase 5:** retry/backoff, circuit breaker, file-size guard (Phase 6).

Context: `docs/planning/real-ocr-implementation-plan.md` §5, §8 Phase 5.

---

## 2. Branch / commit
- **Branch:** `russ/migrateToV16` (`origin` = `https://github.com/NexeraDigital/erpnext.git`)
- **Locate:** `git log --oneline -- erpnext/accounts/ap_closed_loop/extractors/audit.py`
- **Frappe:** `version-16`, min `v16.18.3`.

---

## 3. Environment setup
Same as Phase 2/3/4 (fresh bench, fork app, site + erpnext, `install-app payments`,
register `AI` Module Def, `bench migrate`, `anthropic` SDK installed). A real key
in `AI Provider Settings` is needed only for the live test (TC-4).

---

## 4. Test data prerequisites
None for mocked tests. For the live test, a corpus invoice File.

---

## 5. Numbered test cases

### TC-1 — Audit + pricing unit suite (no API)
```bash
bench --site <site> run-tests \
  --module erpnext.accounts.ap_closed_loop.extractors.test_audit
```
**Expected:** `OK`, 11 tests — pricing (known/unknown/prefix/multi-call), sanitize
(redacts keys + auth headers), Integration Request write (service/reference/cost/
latency present; failed row stores sanitized error; no key anywhere), and the
run_extraction integration (anthropic → one Completed row; fake → none).
**Pass:** green.

### TC-2 — Cost math is correct
```bash
bench --site <site> console <<'PY'
from erpnext.accounts.ap_closed_loop.extractors.pricing import estimate_cost_usd
# Haiku $1/Mtok in, $5/Mtok out
print(estimate_cost_usd([{"model":"claude-haiku-4-5-20251001","input_tokens":1_000_000,"output_tokens":1_000_000}]))
PY
```
**Expected:** `(6.0, True)`. **Pass:** matches.

### TC-3 — Fake provider writes no audit row
```bash
bench --site <site> console <<'PY'
import frappe
frappe.db.set_single_value("AP Closed Loop Settings","ocr_provider","Fake (Deterministic)")
before = frappe.db.count("Integration Request", {"integration_request_service":"anthropic"})
# (run a fake extraction via the form or a capture, then:)
after = frappe.db.count("Integration Request", {"integration_request_service":"anthropic"})
print("delta:", after-before)
PY
```
**Expected:** delta 0 (fake provider is never audited). **Pass:** 0.

### TC-4 — LIVE: a real extraction writes a Completed row with real cost (opt-in)
- **Precondition:** real key configured; `ocr_provider = Anthropic Claude`.
- **Action:** upload a corpus invoice via the Document Capture form (or run
  `run_extraction` on a saved capture), then:
  ```bash
  bench --site <site> console <<'PY'
  import frappe, json
  name = frappe.db.get_value("Integration Request",
      {"integration_request_service":"anthropic"}, "name", order_by="creation desc")
  ir = frappe.get_doc("Integration Request", name)
  out = json.loads(ir.output)
  print("status:", ir.status, "model:", out["model"], "cost:", out["cost_usd_estimate"],
        "tokens:", out["total_input_tokens"], out["total_output_tokens"], "latency:", out["latency_ms"])
  print("key_leak:", "sk-ant" in (ir.data or "")+(ir.output or "")+(ir.error or ""))
  PY
  ```
- **Expected:** `status: Completed`, a real model id, non-zero cost/tokens/latency,
  `key_leak: False`.
- **Pass:** row present with real telemetry, no key leak.

### TC-5 — Regression: all OCR suites green
```bash
for m in extractors.test_anthropic extractors.test_extractors extractors.test_benchmark \
         extractors.test_integration extractors.test_audit ap_closed_loop.test_walking_skeleton; do
  bench --site <site> run-tests --module erpnext.accounts.$m
done
bench --site <site> run-tests --module erpnext.accounts.doctype.ap_closed_loop_settings.test_ap_closed_loop_settings
bench --site <site> run-tests --module erpnext.accounts.doctype.document_capture.test_document_capture
```
**Expected:** 23 / 15 / 9 / 5 / 11 / 4 / 8 / 66 — all `OK`.

---

## 6. Cleanup / rollback
- Delete any Integration Request rows created during testing.
- Reset `ocr_provider` to Fake; remove any test key; delete uploaded Files.

---

## 7. Pass / fail summary
```
Test plan: OCR Phase 5 — Audit Logging & Cost Tracking
Branch:    russ/migrateToV16
Commit:    <git rev-parse HEAD>

  [ ] TC-1  audit + pricing unit suite (11) green
  [ ] TC-2  cost math correct
  [ ] TC-3  fake provider writes no audit row
  [ ] TC-4  LIVE real extraction -> Completed row, real cost, no key leak   [ ] skipped (no key)
  [ ] TC-5  regression suites green

Overall:  [ ] PASS  [ ] FAIL
Notes:
```

## 8. Where to view the audit trail
Operators see calls in the standard list:
`/app/integration-request/view/list?integration_request_service=anthropic`
filterable by status, date, and reference (Document Capture). No custom report.
