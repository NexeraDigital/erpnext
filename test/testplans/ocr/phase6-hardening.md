# Test Plan — OCR Phase 6: Production Hardening

> **Audience:** Cloud-hosted Claude instance on a clean ERPNext bench, no prior context. Runbook.
> **Rule:** per `CLAUDE.md` "Test plans".

---

## 1. Feature under test

**Phase 6** makes the real (Anthropic) OCR path resilient and never-silent:

- **Retry with backoff** — `AnthropicExtractor._call_model` retries transient
  failures (HTTP 429, 5xx, timeouts, connection errors) with exponential backoff
  (1s, 2s, 4s…), honouring a server-sent `Retry-After` on 429. Client errors
  (400 bad request, 401 auth, 404) are **not** retried. Default `max_retries=1`
  (two attempts total); sleep is injectable for deterministic tests.
- **Circuit breaker** (`extractors/circuit.py`) — process-local. After N
  consecutive transient failures (default 5) the breaker **opens** for a cooldown
  (default 60s); calls during cooldown fail fast with `CircuitOpenError` and make
  **no API call**. The first call after cooldown is allowed (half-open); a success
  resets it. Clock is injectable.
- **File-size guard** — `run_extraction` enforces `AP Closed Loop Settings →
  ocr_max_file_mb` **before** any API call. An oversized source is rejected with
  `action_required=1` + a human reason, a `Failed` Integration Request, and no
  spend. The fake provider is exempt (it reads no file).
- **Graceful failure surfacing** — when extraction raises, the capture itself is
  marked `action_required=1` with a human-readable reason (mutated in place and
  persisted when `save=True`) AND a `Failed` Integration Request is written, then
  the error re-raises so the cascade/job records it. No silent stalls.

**Not in Phase 6:** operator runbook / docs (Phase 7).

Context: `docs/planning/real-ocr-implementation-plan.md` §6, §8 Phase 6.

---

## 2. Branch / commit
- **Branch:** `russ/migrateToV16`
- **Locate:** `git log --oneline -- erpnext/accounts/ap_closed_loop/extractors/circuit.py`
- **Frappe:** `version-16`, min `v16.18.3`.

---

## 3. Environment setup
Same as Phase 2–5 (fresh bench, fork app, site + erpnext, `install-app payments`,
register `AI` Module Def, `bench migrate`, `anthropic` SDK installed). `httpx` is
already a Frappe dependency (used by the tests to build real SDK exceptions). No
real API key is needed — all Phase 6 tests mock the network client.

---

## 4. Test data prerequisites
None. Tests build their own captures and mock the Anthropic client and the
file-size lookup; no uploaded files or API keys required.

---

## 5. Numbered test cases

### TC-1 — Phase 6 hardening unit/integration suite (no API)
```bash
bench --site <site> run-tests \
  --module erpnext.accounts.ap_closed_loop.extractors.test_hardening
```
**Expected:** `OK`, 16 tests across:
- `TestClassifyException` (4): 429 retryable w/ Retry-After parsed; 5xx retryable;
  timeout retryable; 400 fatal.
- `TestBackoff` (2): exponential 1/2/4; Retry-After acts as a floor.
- `TestCircuitBreaker` (3): opens at threshold; half-open after cooldown; success resets.
- `TestCallModelRetry` (4): retries once then succeeds (sleeps the Retry-After
  value); exhausts retries on persistent 5xx (2 calls); 400 not retried (1 call,
  no sleep, breaker not tripped); open breaker fails fast (no API call).
- `TestRunExtractionHardening` (3): oversize file rejected before any extractor is
  built (Failed IR + action_required); extraction failure surfaces on the capture
  (action_required + Failed IR) and re-raises; fake provider skips the size guard.

**Pass:** green, 16 tests.

### TC-2 — Retry math is correct
```bash
bench --site <site> console <<'PY'
from erpnext.accounts.ap_closed_loop.extractors.anthropic import _backoff_seconds
print(_backoff_seconds(1, None), _backoff_seconds(2, None), _backoff_seconds(3, None))  # 1.0 2.0 4.0
print(_backoff_seconds(1, 10))   # 10.0 (Retry-After floor)
print(_backoff_seconds(3, 1))    # 4.0 (exponential wins)
PY
```
**Expected:** `1.0 2.0 4.0`, then `10.0`, then `4.0`. **Pass:** matches.

### TC-3 — Exception classification
```bash
bench --site <site> console <<'PY'
import httpx, anthropic
from erpnext.accounts.ap_closed_loop.extractors.anthropic import _classify_exception
req = httpx.Request("POST","https://api.anthropic.com/v1/messages")
rl = anthropic.RateLimitError("x", response=httpx.Response(429, headers={"retry-after":"5"}, request=req), body=None)
br = anthropic.BadRequestError("x", response=httpx.Response(400, request=req), body=None)
print(_classify_exception(rl))   # (True, 5.0)
print(_classify_exception(br))   # (False, None)
PY
```
**Expected:** `(True, 5.0)` then `(False, None)`. **Pass:** matches.

### TC-4 — Circuit breaker opens and fails fast
```bash
bench --site <site> console <<'PY'
from erpnext.accounts.ap_closed_loop.extractors.circuit import CircuitBreaker, CircuitOpenError
t = [1000.0]
cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=30, clock=lambda: t[0])
cb.record_failure(); cb.record_failure()      # opens
try:
    cb.check(); print("NOT OPEN (FAIL)")
except CircuitOpenError as e:
    print("open:", str(e)[:40])
t[0] += 31; cb.check(); print("half-open ok, is_open:", cb.is_open)
PY
```
**Expected:** prints `open: ...` then `half-open ok, is_open: False`. **Pass:** matches.

### TC-5 — Oversize file rejected with NO API call (mocked)
Covered by `TestRunExtractionHardening.test_oversize_file_rejected_before_api_call`
in TC-1 — asserts `get_extractor` is never called, `action_required=1`, reason
contains "over the 5 MB", and exactly one `Failed` Integration Request is written.
**Pass:** that test green within TC-1.

### TC-6 — Regression: all OCR + capture suites green
```bash
for m in extractors.test_hardening extractors.test_anthropic extractors.test_extractors \
         extractors.test_benchmark extractors.test_integration extractors.test_audit; do
  bench --site <site> run-tests --module erpnext.accounts.ap_closed_loop.$m
done
bench --site <site> run-tests --module erpnext.accounts.doctype.ap_closed_loop_settings.test_ap_closed_loop_settings
bench --site <site> run-tests --module erpnext.accounts.doctype.ap_invoice_capture.test_ap_invoice_capture
```
**Expected:** 16 / 23 (1 skip) / 15 / 9 / 5 (2 skip) / 11, then 8, then 66 — all `OK`.

### TC-7 — LIVE (opt-in): real retry behaviour is observable
Phase 6 has no dedicated live test (forcing a real 429 is not reliably
reproducible). The Phase 5 live test (TC-4 there) still exercises the real path
end-to-end; on a transient 429/5xx the new retry simply makes it more robust.
**Pass:** N/A unless the operator can induce a rate limit; otherwise mark skipped.

---

## 6. Cleanup / rollback
- Delete any Integration Request rows created during testing (`Failed` rows from
  TC-1/TC-5).
- Reset `AP Closed Loop Settings`: `ocr_provider = Fake (Deterministic)`,
  `ocr_max_file_mb` to its default. No keys are set by these tests.
- The circuit breaker is process-local in-memory state — it resets on worker
  restart; nothing to clean in the DB.

---

## 7. Pass / fail summary
```
Test plan: OCR Phase 6 — Production Hardening
Branch:    russ/migrateToV16
Commit:    <git rev-parse HEAD>

  [ ] TC-1  hardening suite (16) green
  [ ] TC-2  backoff math correct
  [ ] TC-3  exception classification correct
  [ ] TC-4  circuit breaker opens + half-opens
  [ ] TC-5  oversize file rejected, no API call
  [ ] TC-6  regression suites green
  [ ] TC-7  LIVE retry observable                                   [ ] skipped (cannot induce 429)

Overall:  [ ] PASS  [ ] FAIL
Notes:
```

## 8. Operational notes
- **Tuning:** retry count is `AnthropicExtractor(max_retries=...)` (default 1);
  breaker threshold/cooldown are `CircuitBreaker(failure_threshold=, cooldown_seconds=)`
  defaults (5 / 60s). These are code defaults, not yet settings fields.
- **Where failures show up:** the capture's `action_required` banner (clerk-facing)
  and the standard Integration Request list
  (`/app/integration-request/view/list?integration_request_service=anthropic`,
  status `Failed`).
