# Test Plan — AP Closed Loop Foundations (Settings, Idempotency, Async Runner)

> Clean-room runbook for **spec 01** (`docs/spec/01-foundations-settings-async-idempotency.md`).
> Consolidates the three pieces the spec names (settings backbone · idempotency / posting ledger · async runner) into one self-contained runbook. Executable by a fresh instance with no prior context.

## 1. Feature under test

The cross-cutting foundation for the AP Closed-Loop Workflow v2. Three user-/operator-visible behaviours:

1. **Settings backbone** — the existing **AP Closed Loop Settings** Single gains a *Confidence & Approval Thresholds* section (`auto_post_amount_threshold`, `dedupe_window_days`, per-field `field_thresholds`), a *Segregation of Duties* section (`enforce_sod`, `sod_threshold_amount`), a *Clearing & Suspense Accounts* section (`credit_card_clearing_account`, `unmapped_card_spend_account`), and three reserved collapsible sections. The auto-approval limit that was a hard-coded `1000.0` is now read from `auto_post_amount_threshold` (blank → 1000.0, so nothing changes until set).
2. **Idempotency / posting ledger** — a new **AP Posting Ledger** DocType + `idempotency.with_idempotency()` guarantee a document-creating step posts at most once even if its background job runs twice (a UNIQUE `idempotency_key` index is the guard).
3. **Async runner** — `async_runner.enqueue_step()` routes cascade steps to the right RQ queue (OCR → `long`, posting → `short`), retries transient failures, and dead-letters permanent ones onto the capture's `action_required` (no behaviour change visible to users; the existing cascade still works).

No new screens; nothing changes on a site that hasn't set the new options.

## 2. Branch / commit

- **Branch:** `russ/migrateToV16`
- **Commit:** working tree (this slice may be uncommitted at execution time — apply the spec-01 changes if not present). Verify `erpnext/accounts/doctype/ap_posting_ledger/` and `erpnext/accounts/ap_closed_loop/idempotency.py` exist.

## 3. Environment setup

```bash
# From a bench with this erpnext fork installed against a test site:
bench --site <test-site> migrate          # creates AP Posting Ledger + the new Single fields,
                                           # and runs after_migrate → install_ap_defaults
```

- **Apps/versions:** frappe v16, this erpnext fork. No third-party API keys required (the foundation makes no external calls).
- **CRITICAL precondition for the regression suite (Test Case 5):** set the OCR provider to the deterministic fake, otherwise the capture suite invokes the real provider and fails non-deterministically:
  ```bash
  bench --site <test-site> execute frappe.db.set_single_value \
    --kwargs "{'doctype':'AP Closed Loop Settings','fieldname':'ocr_provider','value':'Fake (Deterministic)'}"
  ```
  Record the prior value first and restore it afterward if the site was configured for a real provider.

## 4. Test data prerequisites

None beyond the standard ERPNext test bootstrap (`_Test Company`, `_Test Supplier`, etc., installed by `before_tests`). The automated suites create and roll back their own data. For the manual checks (Test Case 6) you need a System Manager / Accounts Manager login.

## 5. Numbered test cases

### TC-1 — Idempotency module (automated)
- **Action:** `bench --site <test-site> run-tests --module erpnext.accounts.ap_closed_loop.tests.test_idempotency`
- **Expected:** `Ran 7 tests ... OK`. Covers: deterministic key; **key stable across a settings save**; run-once + ledger row written; second call reuses (no re-run, no duplicate row); pre-inserted row wins; UNIQUE violation re-resolves; duplicate insert raises.
- **Pass/fail:** PASS iff all 7 green.

### TC-2 — Async runner (automated)
- **Action:** `bench --site <test-site> run-tests --module erpnext.accounts.ap_closed_loop.tests.test_async_runner`
- **Expected:** `Ran 6 tests ... OK`. Covers: queue routing (long/short/default incl. unknown→default); enqueue kwargs (`job_id`, `deduplicate`, `enqueue_after_commit` prod vs `now` test); delayed-backoff re-enqueue up to MAX_RETRIES then dead-letter; permanent error → `action_required`, no re-raise; immediate transient → raises `RetryBackgroundJobError`, not dead-lettered, no double-retry; concurrency `UniqueValidationError` not dead-lettered.
- **Pass/fail:** PASS iff all 6 green.

### TC-3 — Defaults installer (automated)
- **Action:** `bench --site <test-site> run-tests --module erpnext.accounts.ap_closed_loop.tests.test_install`
- **Expected:** `Ran 3 tests ... OK` — backfills blank fields, never overwrites an operator value, idempotent re-run.
- **Pass/fail:** PASS iff all 3 green.

### TC-4 — Settings getters + threshold wiring (automated)
- **Action:** `bench --site <test-site> run-tests --module erpnext.accounts.doctype.ap_closed_loop_settings.test_ap_closed_loop_settings`
- **Expected:** `Ran 14 tests ... OK` (6 foundation getters + the 8 pre-existing OCR-config/validation tests). Covers `get_auto_post_threshold` (set vs blank→1000), `_resolve_approval_threshold` reads settings, `get_confidence_threshold` precedence, account-link round-trip, SoD config, dedupe window, and out-of-range threshold rejection.
- **Pass/fail:** PASS iff all 14 green.

### TC-5 — Regression: existing capture suite still green (automated)
- **Precondition:** OCR provider = `Fake (Deterministic)` (see §3).
- **Action:** `bench --site <test-site> run-tests --module erpnext.accounts.doctype.ap_invoice_capture.test_ap_invoice_capture`
- **Expected:** `Ran 66 tests ... OK` in ~10 s — proving `_enqueue_next` delegating to `async_runner` and `_run_cascade_step` as an alias did not change cascade behaviour.
- **Pass/fail:** PASS iff 66/66 green. (If it fails with `'Needs Correction' != 'Confirmed'`, the OCR provider is not Fake — fix the precondition.)

### TC-6 — Settings page renders the new sections (manual / desk)
- **Precondition:** logged in as System Manager.
- **Action:** open `/app/ap-closed-loop-settings`.
- **Expected:** three new visible sections — **Confidence & Approval Thresholds**, **Segregation of Duties**, **Clearing & Suspense Accounts** — plus three collapsed reserved sections (*Stream Tagging Rules*, *Anomaly Detection*, *Bank Feed (SimpleFIN)*). Enter `Auto-Post Amount Threshold = 2500`, **Save** → saves without error.
- **DB check (source of truth):**
  ```bash
  bench --site <test-site> execute frappe.db.get_single_value \
    --kwargs "{'doctype':'AP Closed Loop Settings','fieldname':'auto_post_amount_threshold'}"   # → 2500.0
  ```
- **Pass/fail:** PASS iff the sections render, Save succeeds, and the DB shows 2500.0. Reset to blank afterward.

### TC-7 — Idempotency ledger end-to-end (manual / console)
- **Action:** in `bench --site <test-site> console`:
  ```python
  import frappe
  from erpnext.accounts.ap_closed_loop import idempotency
  cap = frappe.get_doc({"doctype":"AP Invoice Capture",
                        "source_file_url":"http://x/tc7.pdf","source_filename":"tc7.pdf"}).insert(ignore_permissions=True)
  key = idempotency.generate_key(cap.name, "demo")
  fn  = lambda: {"doctype":"Purchase Invoice","name":"PINV-TC7"}
  r1  = idempotency.with_idempotency(key, fn, cap.name, "demo")   # {'reused': False}
  r2  = idempotency.with_idempotency(key, fn, cap.name, "demo")   # {'reused': True}
  print(r1["reused"], r2["reused"],
        frappe.db.count("AP Posting Ledger", {"idempotency_key": key}))   # → False True 1
  frappe.db.rollback()
  ```
- **Expected:** `False True 1` — the second call did not re-run and there is exactly **one** ledger row.
- **Pass/fail:** PASS iff output is `False True 1`.

## 6. Cleanup / rollback

- Automated suites roll back per test (`tearDown`). No residue.
- TC-6: clear `auto_post_amount_threshold` back to blank.
- TC-7: `frappe.db.rollback()` (shown) discards the demo capture + ledger row.
- §3: restore the original `ocr_provider` if you changed it for TC-5.

## 7. Pass/fail summary template

| Case | What | Result |
|---|---|---|
| TC-1 | `test_idempotency` (7) | [ ] |
| TC-2 | `test_async_runner` (6) | [ ] |
| TC-3 | `test_install` (3) | [ ] |
| TC-4 | `test_ap_closed_loop_settings` (14) | [ ] |
| TC-5 | `test_ap_invoice_capture` regression (66, Fake provider) | [ ] |
| TC-6 | Settings page renders new sections + saves | [ ] |
| TC-7 | Idempotency ledger: `False True 1` | [ ] |

**Overall:** [ ] PASS  [ ] FAIL — notes: ______
