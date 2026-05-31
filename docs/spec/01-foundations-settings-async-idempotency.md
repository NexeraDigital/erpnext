---
spec: 01-foundations-settings-async-idempotency
title: Foundations — Settings, Idempotency, Async Runner
plan_step: "Cross-cutting: 'Async by default, idempotent everywhere' + the settings backbone for all later steps"
stream: both
status: Draft
depends_on: []
related: [00-overview, 02-intake-stream-tagging, 04-extraction-confidence-line-items, 06-gl-coding-tax-costcenter, 08-validation-gates, 11-approval-sod-workflow, 12-payment-execution, 13-bank-feed-reconciliation]
---

# 01 — Foundations: Settings, Idempotency, Async Runner
> _Revised 2026-05-31: applied native-vs-custom review findings; §7.3 UI testing N/A (backend-only slice)._

## 1. Summary
This spec lays the cross-cutting foundation every later v2 step builds on: it (a) extends the existing `AP Closed Loop Settings` Single into the single settings backbone (new thresholds, SoD config, credit-card/clearing accounts, plus placeholder sections owned by other specs), (b) introduces a real idempotency layer — a new `AP Posting Ledger` DocType plus an `idempotency.py` helper module so a retried job can never double-post an ERPNext document, and (c) generalizes the existing in-controller cascade enqueue into a reusable, step-aware, retry-capable `async_runner.enqueue_step`. It is **stream-agnostic** infrastructure that serves both Stream R (receipts) and Stream I (invoices). It implements the plan's cross-cutting principle "Async by default, idempotent everywhere." Current-state delta: today there is **no idempotency key, no posting ledger, and no `with_idempotency` wrapper** (only per-controller status guards), the async cascade is hardcoded to the `short` queue with no retry/backoff, and the auto-approval threshold is a hardcoded `1000.0` literal — this spec replaces all three with settings-driven, generalized primitives.

## 2. Plan alignment
From `docs/planning/workflow-v2-plan.md`, the cross-cutting engineering principle this spec implements:

> "Every operation that creates an ERPNext document uses an idempotency key so a retried job cannot double-post. AI extraction and bank-feed sync are queue-backed (`frappe.enqueue`) — the UI never blocks."

Control-Summary alignment: this spec does not itself add a row to the per-step control summary; it provides the **mechanism** rows 9–13 depend on. Specifically:
- The idempotency contract (`with_idempotency` + `AP Posting Ledger`) is the enforcement primitive behind every "creates a document" control: Supplier creation (spec 05), Purchase Invoice promote (spec 07), Journal Entry post for Stream R (spec 07), Payment Entry (spec 12), Bank Transaction (spec 13).
- The async runner is the mechanism behind "AI extraction and bank-feed sync are queue-backed": OCR extraction (spec 04) runs on the `long` queue; SimpleFIN bank-feed sync (spec 13) runs queue-backed; matching/posting/payment run on `short`.

**Stream R vs Stream I divergence here:** none at the mechanism level — both streams enqueue steps through the *same* `enqueue_step` using free-text, stream-agnostic step names, and both route their document-creating steps through the *same* `with_idempotency`. The streams diverge only in *which* steps they enqueue (Stream R: extract → code → post Journal Entry → bank-match; Stream I: match-supplier → promote PI → approve → pay), which is owned by specs 02/07/11/12. This spec must keep step names and the queue map free-text so those specs add steps without touching foundation plumbing.

## 3. Current state
What ships today on branch `russ/migrateToV16` (verified against the code, not memory):

**A) Settings Single — `AP Closed Loop Settings` (`issingle:1`).**
- JSON: `erpnext/accounts/doctype/ap_closed_loop_settings/ap_closed_loop_settings.json`. Fields today (field_order at .json:8-25): `promote_defaults_section`, `default_company`/`default_item_code`/`default_expense_account`/`default_cost_center` (Link), `optional_defaults_section`, `default_warehouse`/`default_uom` (Link), `ocr_section`, `ocr_provider` (Select `Fake (Deterministic)`|`Anthropic Claude`, reqd, .json:85-93), `ocr_model`, `ocr_fallback_model`, `ocr_confidence_threshold` (Float, default `"0.70"`, .json:111-118), `ocr_column_break`, `ocr_max_file_mb` (Int, default `25`), `ocr_force_reextract` (Check). Permissions (.json:145-162): System Manager rw, Accounts Manager rw, Accounts User read. `track_changes:1`.
- Controller: `ap_closed_loop_settings.py`. Constants `OCR_PROVIDER_REGISTRY_KEY` and `DEFAULT_OCR_CONFIDENCE_THRESHOLD=0.70` (.py:25-29). `validate()` (.py:55-57) runs `_validate_ocr_provider_has_credentials()` + `_validate_confidence_threshold()` (must be 0..1, .py:79-82). `get_promote_defaults()` (.py:85-108) and `get_ocr_config()` (.py:111-148) BOTH read via `frappe.db.get_singles_dict("AP Closed Loop Settings")` — **deliberately not** `frappe.get_single`, to avoid `set_missing_values` auto-populating empty Link fields from session defaults (the footgun is documented in the `get_promote_defaults` docstring .py:88-96). `get_ocr_config` coerces Singles' text: blank/non-positive threshold → 0.70 (.py:127-133); blank max_mb → 25 (.py:135-139). Whitelisted `get_promote_defaults_for_ui()` at .py:151-158.
  - **Correction to the brief:** the brief's note (B) says `promote_to_purchase_invoice` gathers defaults "via `frappe.get_single`". The shipped code uses `get_singles_dict` in **both** getters (.py:99 and .py:120); the only `frappe.get_single` references are in the *docstrings* warning against it. Treat `get_singles_dict` + manual text coercion as the established, mandatory pattern — all new getters must follow it.

**B) Async cascade (the pattern to generalize) — `erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.py`.**
- `_enqueue_next(self, method_name, reason)` at .py:368-404 is the existing single-queue pattern. It enqueues wrapper `...ap_invoice_capture._run_cascade_step` with `capture=self.name`, `method_name=...`, `queue="short"` (**hardcoded** — no long-vs-short selection, .py:399), `job_id=f"ap-progress-{self.name}-{method_name}"` (.py:400), `deduplicate=True`, `enqueue_after_commit=not in_test`, `now=in_test` where `in_test=bool(frappe.flags.get("in_test"))` (.py:394).
  - **Confirmed discrepancy to fix:** the `_enqueue_next` docstring at .py:372-373 says "a per-capture-per-step `job_name`" but the call correctly passes `job_id=` (the v15/v16 kwarg). The new `async_runner` must use `job_id` and the subsuming refactor must fix this wording.
- Step selection lives in `_determine_next_step()` (.py:321-366): a linear if-ladder over `(status, ocr_status, validation_status, promotion_status, approval_status, payment_readiness)` returning `(method_name, reason)` for steps `run_fake_extraction_for`, `validate_for_purchase_invoice_for`, `request_approval_for`, `issue_mock_payment_for`. Cascade gating in the `_maybe_enqueue` caller (.py:308-319): skips if `frappe.flags.skip_ap_auto_progress`; in tests requires opt-in `frappe.flags.ap_auto_progress_enabled`.
- Dead-letter / surfacing today: `_run_cascade_step(capture, method_name)` at .py:439-487 — worker entry point. On `Exception`: `frappe.log_error(...)` **and** `frappe.db.set_value("AP Invoice Capture", capture, {"action_required":1, "action_required_reason": "Auto-step '{0}' failed: {1}"}, update_modified=True)` then `frappe.db.commit()` (.py:464-482). It deliberately does **not** re-raise (avoids RQ retry loops); `capture.action_required` is the canonical user-visible signal. This is the seed of the spec's dead-letter path — but it has **no** retry/backoff and **no** step-aware queue.

**C) The hard-coded threshold to replace** — `ap_invoice_capture.py:78` `AUTO_APPROVAL_THRESHOLD_DEFAULT=1000.0`. Consumed only by `_resolve_approval_threshold(threshold, source)` at .py:1243-1246: returns `(AUTO_APPROVAL_THRESHOLD_DEFAULT, source or APPROVAL_SOURCE_DEFAULT)` when `threshold is None`, else `(float(threshold), source or "explicit-override")`. `request_approval()` (.py:1249-1318) calls it then auto-approves when `amount <= threshold` (.py:1291) else routes to `MANAGER_APPROVAL_ROLE_DEFAULT="Accounts Manager"` (.py:79, :1308).

**D) Idempotency today = per-controller status guards only.** Each step re-checks its target field and raises (e.g. promotion guard, routing "already recorded" at .py:1278-1283, payment guard). Tests assert these (`test_ap_invoice_capture.py:715` `test_promote_is_idempotent_guard`, `:932` `test_routing_is_idempotent_guard`, `:1114` `test_issue_mock_payment_is_idempotent_guard`). There is **no** idempotency key, **no** `AP Posting Ledger`, **no** `with_idempotency` wrapper anywhere — confirmed by grep across `erpnext/accounts/`. So this spec's `idempotency.py` + `AP Posting Ledger` are **net-new**.

**E) Package dir** — `erpnext/accounts/ap_closed_loop/` currently holds only `__init__.py`, `walking_skeleton.py`, `test_walking_skeleton.py`, `extractors/`. So `idempotency.py` and `async_runner.py` are new files added here. (No `tests/` subpackage yet — this spec creates `erpnext/accounts/ap_closed_loop/tests/`.)

**F) Hook wiring today** — `erpnext/hooks.py`: `after_install="erpnext.setup.install.after_install"` (line 66); `after_migrate=["erpnext.mcp.install.sync_tool_configs"]` (line 69, a **LIST** — appending the new defaults installer is additive); `scheduler_events` present further down.

**G) generate_key precedent** — `erpnext/accounts/doctype/account_closing_balance/account_closing_balance.py:93` defines a module-level `generate_key(entry, accounting_dimensions)` used at :73. It establishes the in-repo convention of a module-level `generate_key()` for dedupe keys. **Note the shape difference:** that one returns `(key_list, key_values)` (a list + a dict), not a single hash string. This spec's `idempotency.generate_key` mirrors the *naming + module-level-function* convention but returns a `sha256` hex digest (a single Data-fittable string), which is the right shape for a UNIQUE-indexed key column. Cite the precedent for consistency; do not copy its tuple return.

**H) Installed framework version.** `bench`'s frappe is **16.18.3** (`apps/frappe/frappe/__init__.py`). CLAUDE.md mandates citing v15 docs; the `enqueue` signature was verified against the `version-15` source and matches the kwargs this spec relies on. Because the runtime is v16, the build phase MUST re-verify `frappe.utils.background_jobs.enqueue` against the installed frappe before finalizing (see Open Decisions D7 and Risks). The v15 docs remain the citation source per CLAUDE.md.

## 4. Upstream grounding
Mandatory grounding evidence. Each citation: URL + what it confirms + the quoted signature/section.

| # | URL | Confirms | Quoted signature / section |
|---|-----|----------|----------------------------|
| 1 | https://github.com/frappe/frappe/blob/version-15/frappe/utils/background_jobs.py | **EXACT `frappe.enqueue` signature** — authoritative for the `async_runner` wrapper. Confirms every kwarg used: `queue` (default `'default'`), `timeout`, `is_async`, `job_name`, `now`, `enqueue_after_commit` (default `False`), `on_success`/`on_failure`, `at_front`, `job_id` (default `None`), `deduplicate` (default `False`), `**kwargs`. Confirms the three queues + timeouts: short=300s, default=300s, long=1500s. Validates queue selection, `enqueue_after_commit=True`, `deduplicate=True`, and `job_id` (NOT `job_name`) as the dedup id. **Also confirms** `enqueue` has no retry/backoff/delay kwarg — but `execute_job` (the worker side) DOES retry up to 5× with `time.sleep(retry+1)` backoff for **deadlock/timeout** errors only. So the spec's "3× exponential backoff" is for **provider/transient** errors (429/5xx) and lives in the worker dispatcher, NOT delegated to `frappe.enqueue`; DB-lock retries are already handled by frappe. | `def enqueue(method, queue='default', timeout=None, event=None, is_async=True, job_name=None, now=False, enqueue_after_commit=False, *, on_success=None, on_failure=None, at_front=False, job_id=None, deduplicate=False, **kwargs) -> Job \| Any` … `short (300s) / default (300s) / long (1500s)` … `execute_job` retries deadlock/timeout up to 5× with `time.sleep(retry + 1)` |
| 2 | https://docs.frappe.io/framework/v15/user/en/python-api/hooks | **`after_migrate` registration + handler signature** (handler takes **no args**) AND **`scheduler_events` cadences**. Grounds the defaults-install path (item 4) and the pointers to scheduler-driven specs (08 anomaly, 13 SimpleFIN). In this fork `after_migrate` is already a LIST (hooks.py:69), so appending is additive. Confirms cadences `all` (every 60s), `hourly/daily/weekly/monthly` (+ `_long` variants), and `cron`. | `after_migrate = "app.migrate.after_migrate"` with `def after_migrate(): ...` (no args). `scheduler_events = {"daily": ["app.scheduled_tasks.manage_recurring_invoices"], "cron": {"15 18 * * *": ["app.scheduled_tasks.delete_all_barcodes_for_users"]}}` |
| 3 | https://docs.frappe.io/framework/v15/user/en/database-migrations | **`patches.txt` convention** — grounds the alternative install path (numbered patch vs `after_migrate`). Patches are dotted module paths in `app/patches.txt`; the file is INI-like with `[pre_model_sync]` (runs BEFORE schema sync) and `[post_model_sync]` (runs AFTER) sections; each module defines `execute()`, run once, sequentially, not re-run if applied. Because `AP Posting Ledger` is a new DocType, a data-defaults patch that reads/writes it must sit under `[post_model_sync]`. Matches the fork's existing `erpnext.patches.v16_0.*` entries (verified at `erpnext/patches.txt`). | "patches.txt supports INI-like file format where two sections specify when a patch should run - before or after doctype schema migration (`[pre_model_sync]` / `[post_model_sync]`); to write a patch you must write an `execute` method … and add a line with the dotted path to the patch module to patches.txt" |
| 4 | https://docs.frappe.io/framework/v15/user/en/basics/doctypes/single-doctype | **Single DocType semantics** (`issingle`, storage in `tabSingles` as doctype/field/value **text** rows, read via the Singles API). Grounds why the existing controller reads Singles as TEXT and coerces types, and why the new fields (`dedupe_window_days`, thresholds, account links, `field_thresholds` JSON) all store in `tabSingles` and need coercion on read. **Note:** the section-path URL returned HTTP 404 on direct WebFetch on 2026-05-30; the parent index `https://docs.frappe.io/framework/v15/user/en/basics/doctypes` lists this as child slug `doctypes/single-doctype` (verified). Single read/coerce behavior is independently confirmed by the shipped fork code (`get_singles_dict` usage at `ap_closed_loop_settings.py:99,120`) and the framework source. No fabricated quote — slug treated as canonical. | (canonical slug; no verified quote — see note. Behavior corroborated by `ap_closed_loop_settings.py:120-147` text-coercion code.) |
| 5 | https://github.com/frappe/frappe/blob/version-15/frappe/utils/background_jobs.py (installed copy: `apps/frappe/frappe/utils/background_jobs.py:275-290`) | **Native transient retry in the worker.** `execute_job` ALREADY retries up to **5×** with `time.sleep(retry + 1)` backoff when the job either raises `frappe.RetryBackgroundJobError` **or** the error is a DB deadlock / lock-timeout (`frappe.db.is_deadlocked(e)` / `frappe.db.is_timedout(e)`). Grounds the build instruction to **raise `frappe.RetryBackgroundJobError`** for immediate-retry-acceptable transient errors (provider 429/5xx) and let frappe own that retry — reserving the custom `_attempt`+re-enqueue loop strictly for *delayed* exponential backoff (D5). Also the basis for the explicit double-retry warning (custom 3× layered on native 5× = up to 15 attempts). | `for retry in range(5): try: … except RetryBackgroundJobError: … except Exception as e: if retry < 4 and (frappe.db.is_deadlocked(e) or frappe.db.is_timedout(e)): frappe.db.rollback(); time.sleep(retry + 1); continue; else: raise` |
| 6 | https://github.com/frappe/frappe/blob/version-15/frappe/exceptions.py (installed copy: `apps/frappe/frappe/exceptions.py:194`) | **`UniqueValidationError` subclasses `ValidationError`.** Grounds the exception-ordering build instruction in §5.3-C.c: the concurrency re-resolve branch (catch `UniqueValidationError` + pymysql `IntegrityError`) MUST be ordered **before** the generic `ValidationError`→dead-letter branch, or a concurrency-loss insert is dead-lettered instead of re-resolved. | `class UniqueValidationError(ValidationError): pass` |

## 5. Design

### 5.1 Data model

#### (A) EXTEND `AP Closed Loop Settings` (`issingle:1`)
Add the following fields. All persist as TEXT in `tabSingles`; every new getter MUST coerce exactly like `get_ocr_config` does (.py:124-147). Defaults are set in JSON (`"default"`) **and** backfilled for existing sites by the install step (§5.3-D). Group under new section breaks; insert into `field_order` after the OCR section.

> **Native type-coercion option:** `frappe.db.get_singles_dict(doctype, *, cast=True)` (`apps/frappe/frappe/database/database.py:782`) will cast each Single value to its DocType-declared fieldtype (Int/Float/Check/etc.) **natively**, so for fields whose only need is "text → typed value" you can read with `cast=True` instead of hand-coercing. **Keep the manual coercion** (the established `get_ocr_config` pattern) **only where the logic is more than a cast** — specifically the non-positive→default fallbacks (blank/`0`/negative threshold → `0.70`, blank `max_mb` → `25`, blank `auto_post_amount_threshold` → `1000.0`, blank `dedupe_window_days` → `90`): `cast=True` yields `0`/`None`, not the business default, so those getters still need the explicit `or <default>` step. Net: prefer `cast=True` for plain typed reads; retain manual coercion for the default-fallback semantics.

New section: **`thresholds_section`** (Section Break, label "Confidence & Approval Thresholds"):

| fieldname | fieldtype | options / default | purpose |
|---|---|---|---|
| `thresholds_section` | Section Break | label "Confidence & Approval Thresholds" | group |
| `per_field_confidence_threshold` | Float | default `0.70` | Per-field confidence floor below which an extracted field is flagged ambiguous. **Reconciles with** existing `ocr_confidence_threshold` — see Open Decision D1. Recommended approach: keep `ocr_confidence_threshold` as the canonical stored field (it is already per-field per its own description), DO NOT add a second scalar; expose `get_confidence_threshold(field=None)` so all later specs read one source. (If D1 resolves to "add the new name", a `[post_model_sync]` patch copies `ocr_confidence_threshold` → `per_field_confidence_threshold` and the getter reads whichever is set.) |
| `field_thresholds` | JSON | options `JSON`; default `{}` | Per-field overrides, e.g. `{"total_amount":0.9,"supplier":0.6}`. Effective threshold = `field_thresholds.get(field) or per_field_confidence_threshold or 0.70`. Read with `json.loads` (Singles store JSON as text). |
| `auto_post_amount_threshold` | Float | default empty/`0` | **Replaces** the hardcoded `AUTO_APPROVAL_THRESHOLD_DEFAULT=1000.0`. Back-compat: when empty/0, `get_auto_post_threshold()` returns `1000.0`. Used by `request_approval` (Stream I). |
| `dedupe_window_days` | Int | default `90` | Cross-capture dedupe horizon for OCR/extraction (consumed by spec 03). |

New section: **`sod_section`** (Section Break, label "Segregation of Duties"):

| fieldname | fieldtype | options / default | purpose |
|---|---|---|---|
| `sod_section` | Section Break | label "Segregation of Duties" | group |
| `enforce_sod` | Check | default `1` | Master switch for the SoD backstop (consumed by spec 11). Stream I only at point of use. |
| `sod_threshold_amount` | Float | default `0` | `0` = SoD applies to all amounts; `>0` = SoD enforced only above this amount. |

New section: **`clearing_accounts_section`** (Section Break, label "Clearing & Suspense Accounts"):

| fieldname | fieldtype | options / default | purpose |
|---|---|---|---|
| `clearing_accounts_section` | Section Break | label "Clearing & Suspense Accounts" | group |
| `credit_card_clearing_account` | Link | options `Account` | Credit-Card-Clearing account for Stream R PI+clearing path (consumed by specs 02/07). **Company-scoped concern** — company is per-capture, so this site-wide link is a default the consuming spec must validate against the capture's company (flag to spec 02). |
| `unmapped_card_spend_account` | Link | options `Account` | Suspense account for card spend with no coding profile match (consumed by specs 02/06). Same company-scope caveat. |

New **placeholder sections owned by other specs** — add as collapsible Section Breaks now so this Single is the settings backbone and each spec fills its block without re-ordering churn. Add only the section break (no fields) unless a thin stub is noted:

| fieldname | fieldtype | options | owner / purpose |
|---|---|---|---|
| `stream_rules_section` | Section Break | `collapsible:1`, label "Stream Tagging Rules" | spec **02** fills provisional-tag rules + 72h SLA config |
| `anomaly_section` | Section Break | `collapsible:1`, label "Anomaly Detection" | spec **08** fills amount-anomaly params |
| `bank_feed_section` | Section Break | `collapsible:1`, label "Bank Feed (SimpleFIN)" | spec **13** fills SimpleFIN config |

Permissions: **unchanged** (System Manager rw / Accounts Manager rw / Accounts User read). All new fields are config; Accounts User read-only is correct.

#### (B) NEW DocType `AP Posting Ledger`
Normal DocType (NOT single; `issingle:0`, `is_submittable:0`), module `Accounts`. The append-only audit row that makes every document-creating step idempotent.

> **Two distinct idempotency layers — do not conflate them.** `AP Posting Ledger` is **DOCUMENT-level** idempotency: its UNIQUE `idempotency_key` index guarantees that *the ERPNext document a step creates* (a Purchase Invoice, Journal Entry, Payment Entry, etc.) is created at most once, regardless of how many times the step's code runs. This is a **separate layer** from `frappe.enqueue`'s **JOB-level** dedup (`deduplicate=True` + `job_id`, §5.3-C), which only prevents *the same queued job from being enqueued twice while one is pending* — it says nothing about document creation and offers no guarantee once a job has run to completion and been retried later. A retried job (new RQ run, same `job_id` long since drained) is exactly the case job-level dedup does **not** cover and document-level idempotency **does**. Reviewers should read the two as complementary, not redundant: job-level dedup trims duplicate *enqueues*; the ledger trims duplicate *posts*.

| fieldname | fieldtype | options / flags | purpose |
|---|---|---|---|
| `idempotency_key` | Data | `reqd:1`, `unique:1` | The sha256 hex (64 chars, fits Data/varchar(140)). `"unique":1` makes Frappe create the UNIQUE index — **this index is the real double-post guard.** |
| `capture` | Link | options `AP Invoice Capture`, `reqd:1`, `in_standard_filter:1` | Which capture this posting belongs to (ops triage). |
| `step` | Data | — | Free-text step name, e.g. `promote_to_purchase_invoice`, `request_approval`, `issue_payment`, `create_journal_entry`, `create_bank_transaction`. Data (not Select) to stay stream-agnostic and avoid coupling; may tighten to Select later. |
| `result_doctype` | Data | — | DocType of the doc the step created (Supplier / Purchase Invoice / Payment Entry / Journal Entry / Bank Transaction). |
| `result_name` | Data | — | Name of the created doc. |
| `posted_at` | Datetime | — | When the row was recorded (`now_datetime()`). |

- **Naming:** `autoname="field:idempotency_key"` so the unique key **is** the docname — gives a cheap `frappe.db.exists("AP Posting Ledger", key)` existence check and lets the primary key double as the guard. (Open Decision D3 if the team prefers a series like `APIPL-.#####` with the unique constraint separate.)
- **Indexes:** UNIQUE on `idempotency_key` (via `"unique":1`); secondary index on `capture` (via `"in_standard_filter":1` Frappe adds a search index; if not, add an explicit index in a patch) for per-capture history listing.
- **Permissions:** System Manager rw; Accounts Manager read (audit); Accounts User read. No create/write for non-admins — rows are written server-side with `ignore_permissions=True`.
- **`track_changes`:** `0` — the row itself *is* the audit record; versioning it is redundant.

#### (C) `generate_key` style precedent
Mirror the module-level-function naming of `account_closing_balance.py:93` `generate_key()`; return a single sha256 hex string (not the tuple that precedent returns) so the value fits the UNIQUE Data column.

### 5.2 Endpoints
This is infrastructure; the only **whitelisted** surface is read-only settings getters for the UI. The core helpers are plain module functions (called server-side, not over HTTP).

Settings getters (add to `ap_closed_loop_settings.py`; all read `get_singles_dict` + coerce text, per the established pattern):

```python
# module-level, ap_closed_loop_settings.py
def get_auto_post_threshold() -> float
    # returns float(auto_post_amount_threshold) if > 0 else AUTO_APPROVAL_THRESHOLD_DEFAULT (1000.0)

def get_dedupe_window_days() -> int
    # returns int(dedupe_window_days) if set else 90

def get_confidence_threshold(field: str | None = None) -> float
    # if field and field in field_thresholds(JSON): return that float
    # elif per_field/ocr_confidence_threshold set: return it
    # else: return DEFAULT_OCR_CONFIDENCE_THRESHOLD (0.70)

def get_field_threshold(field: str) -> float
    # thin alias: get_confidence_threshold(field)

def get_sod_config() -> dict
    # {"enforce": bool(enforce_sod), "threshold": float(sod_threshold_amount or 0)}
```

Idempotency module — `erpnext/accounts/ap_closed_loop/idempotency.py`:

```python
def generate_key(capture_name: str, step_name: str) -> str
    # sha256 hex of NUL-joined [capture_name, step_name] ONLY — NOT settings.modified.
    # The key MUST be stable across settings saves: only a different capture or a
    # different step changes the key. (See §5.3-A for why modified-version is excluded.)

def with_idempotency(key: str, fn: Callable[[], dict], capture: str, step: str) -> dict
    # fn() must return {"doctype": str, "name": str}
    # returns {"doctype", "name", "reused": bool}
```

Async runner — `erpnext/accounts/ap_closed_loop/async_runner.py`:

```python
def enqueue_step(capture: str, step_name: str, **kwargs) -> None
    # selects queue, wraps frappe.enqueue(dispatcher, ...)

def _dispatch_step(capture: str, step_name: str, _attempt: int = 0, **kwargs) -> None
    # worker entry point: classify error -> native RetryBackgroundJobError (immediate
    # transient) | custom _attempt re-enqueue (delayed backoff, D5) | dead-letter (permanent).
    # Concurrency (UniqueValidationError/IntegrityError) re-resolve branch MUST be caught
    # BEFORE the generic ValidationError->dead-letter branch (see §5.3-C.c). NOT whitelisted.
```

**Normalization convention** (matches the existing controller, e.g. `request_approval` at ap_invoice_capture.py:1264-1265): functions that accept a capture as either an `AP Invoice Capture` doc or a `str` name normalize at the top with `if isinstance(capture, str): capture = frappe.get_doc(...)`. The foundation helpers above take `capture` as a **`str` name** (the worker boundary always passes a name, not a doc, so the job payload stays JSON-serializable) — they never accept a doc object. Document this so downstream callers pass `.name`.

### 5.3 Logic

#### (A) `idempotency.generate_key(capture_name, step_name) -> str`
1. Build the key material as a list `[capture_name, step_name]` — **only the capture name and the step name.** Do **NOT** include `AP Closed Loop Settings.modified` (the Single's modified-version) or any other settings field in the material.
2. Join with a NUL byte `"\x00"` (record-separator) — **not** a printable delimiter — so a name containing the separator can't forge a collision.
3. Return `hashlib.sha256(material.encode()).hexdigest()` (64-char hex).
- No persistence, no DB read, no exceptions raised here; pure function. (Dropping the `modified` read also makes this strictly cheaper — no `get_single_value` round-trip.)
- **Why `modified` is excluded (correctness, not optimization):** the key's whole job is "a retried job cannot double-post." If the material includes the Single's `modified` timestamp, then **any** settings save — even an unrelated tweak like editing the OCR model or a clearing account — bumps `modified` and therefore changes the key for **every** capture/step. A job that already posted, retried after such an unrelated settings change, would compute a *new* key, find no matching `AP Posting Ledger` row, re-run `fn()`, and **double-post**. That defeats the core guarantee. The key must depend only on *what* is being posted (`capture` + `step`), never on settings state. Keying on capture+step only makes the ledger row a stable fingerprint of the logical operation for the life of that capture/step.

#### (B) `idempotency.with_idempotency(key, fn, capture, step) -> dict`
1. **Fast path:** if `frappe.db.exists("AP Posting Ledger", {"idempotency_key": key})`, read `frappe.db.get_value("AP Posting Ledger", {"idempotency_key": key}, ["result_doctype","result_name"], as_dict=True)` and return `{"doctype": row.result_doctype, "name": row.result_name, "reused": True}`. **`fn` is not called.** (This is the double-post prevention.)
2. **Create path:** call `result = fn()` (the caller's create logic; must return `{"doctype","name"}`).
3. Insert the ledger row: `frappe.get_doc({"doctype":"AP Posting Ledger", "idempotency_key":key, "capture":capture, "step":step, "result_doctype":result["doctype"], "result_name":result["name"], "posted_at":now_datetime()}).insert(ignore_permissions=True)`.
4. **Concurrency guard:** wrap steps 2–3 in `try/except`. On `frappe.UniqueValidationError` (or the underlying `pymysql.err.IntegrityError`) — meaning a concurrent retry inserted the same key first — **re-resolve** to the existing row (repeat step 1's read) and return it with `reused=True`. The DB UNIQUE index is the real guarantee; the `exists()` check is only a fast path. Do **not** crash.
   - **Important ordering caveat:** if `fn()` (step 2) already created the downstream doc and *then* the ledger insert (step 3) hits the UNIQUE violation, the concurrent winner already created its own downstream doc, so this loser's `fn()` produced a **duplicate** ERPNext doc. Mitigation: callers should make `fn()` itself idempotent where the framework allows (e.g. promote already guards on `promotion_status`), OR the build wraps `fn()`+insert so the doc create and ledger insert share one DB transaction and roll back together on the UNIQUE violation. Flag as Open Decision D6.
5. Return `{**result, "reused": False}`.
- **Contract (binding on all later specs):** EVERY downstream insert of Supplier, Purchase Invoice, Payment Entry, Journal Entry, Bank Transaction routes its create through `with_idempotency(generate_key(capture, step), lambda: <create>, capture, step)`. This is the foundation's exported guarantee; specs 05/07/12/13 wire to it.

#### (C) `async_runner.enqueue_step(capture, step_name, **kwargs)` + `_dispatch_step`
1. **Queue selection** via a `QUEUE_BY_STEP` map (plain dict; free-text keys):
   - OCR/extraction steps (`run_extraction`, `run_fake_extraction`, anything containing "extract"/"ocr") → `"long"` (1500s).
   - matching/posting/payment steps (`validate`, `promote*`, `request_approval`, `issue_payment`, `issue_mock_payment`, `create_journal_entry`, `create_bank_transaction`) → `"short"` (300s).
   - anything else → `"default"`.
   Resolution is by explicit map first, then a substring fallback, then `"default"`.
2. Compute `in_test = bool(frappe.flags.get("in_test"))` — replicate the existing handling at ap_invoice_capture.py:387-403 exactly: `now=in_test`, `enqueue_after_commit=not in_test`. This keeps cascade writes inside the test rollback boundary (the after-commit callback otherwise forces a mid-test commit that `tearDown`'s rollback can't undo — documented footgun at ap_invoice_capture.py:387-393).
3. Call `frappe.enqueue(_dispatch_step_path, capture=capture, step_name=step_name, queue=<resolved>, job_id=f"apic::{capture}::{step_name}", deduplicate=True, enqueue_after_commit=not in_test, now=in_test, **kwargs)`.
4. `_dispatch_step(capture, step_name, _attempt=0, **kwargs)` is the worker entry point:
   a. Resolve the target callable for `step_name` (the same mapping `_run_cascade_step` uses today: `getattr(module, method_name)` — see §5.4 for how the existing if-ladder feeds this).
   b. `try: fn(capture)`.
   c. On exception, classify into THREE buckets (the ordering of the `except` clauses is load-bearing — see the **exception-ordering** note below):
      - **immediate-retry transient** = provider 429/5xx (and any error where an immediate retry is acceptable). For these, **do NOT roll your own retry — `raise frappe.RetryBackgroundJobError`** and let frappe's `execute_job` retry up to 5× with `time.sleep(retry+1)` backoff (citation #5). DB deadlock / lock-timeout is *already* in this native bucket (frappe checks `is_deadlocked`/`is_timedout` itself), so a bare re-raise of those also gets the native retry — you generally never see them in the dispatcher until after frappe's own retries are exhausted.
      - **delayed-backoff transient** = a transient error that needs a *real, growing* delay between attempts (e.g. a provider that returns `Retry-After: 30s`, or a 429 you must space out to respect a rate limit). This — and ONLY this — is what the custom `_attempt`+re-enqueue loop in step (d) is for. `frappe.RetryBackgroundJobError`'s `sleep(retry+1)` is short and blocks the worker, so it is unsuitable for minute-scale backoff; the custom loop schedules a *later* re-enqueue without holding a worker.
      - **permanent** = `frappe.ValidationError` and its AP subclasses (`CapturePromotionError`, etc.), bad data, missing config → dead-letter (step e).
   - **⚠ Do NOT double-retry.** Raising `RetryBackgroundJobError` AND also routing the same error through the custom `_attempt` re-enqueue loop stacks the two: native 5× layered under custom 3× = **up to 15 attempts**, with confusing duplicated `action_required` churn. Each transient error must take **exactly one** path — either `raise RetryBackgroundJobError` (native, immediate) **or** the custom delayed re-enqueue (step d) — never both. The classifier picks one bucket.
   - **Exception ordering (build instruction, MANDATORY):** `UniqueValidationError` **subclasses** `ValidationError` (citation #6, `exceptions.py:194`). Therefore the concurrency re-resolve branch — `except (frappe.UniqueValidationError, pymysql.err.IntegrityError):` → re-resolve to the existing `AP Posting Ledger` row (the §5.3-B concurrency path) — MUST appear **BEFORE** the generic `except frappe.ValidationError:` → dead-letter branch in `_dispatch_step`. If ordered the other way, a concurrency-loss insert is caught by the broad `ValidationError` clause and **dead-lettered** (capture flagged `action_required`) instead of being silently re-resolved to the winning row — a spurious failure on what is actually a successful, deduplicated post.
   d. **Delayed-backoff transient + `_attempt < MAX_RETRIES (3)`:** re-enqueue via `enqueue_step(capture, step_name, _attempt=_attempt+1, ...)` with backoff `delay = base * 2**_attempt`. **Realizing the delay** is an Open Decision (D5): `frappe.enqueue` has no delay arg. Recommended default: a `next_retry_at` Datetime stashed on the capture (or a tiny retry-queue row) plus a `scheduler_events.all`/`cron` sweep that re-enqueues due retries — this avoids blocking a worker on `sleep`. Simpler interim: immediate re-enqueue without true delay (accept tighter retry spacing) for phase-1. (For errors that DON'T need a growing delay, prefer `raise frappe.RetryBackgroundJobError` per (c) — that is strictly less code and is the native path.)
   e. **Permanent OR retries exhausted → dead-letter:** GENERALIZE the existing `_run_cascade_step` behavior (ap_invoice_capture.py:464-482): `frappe.log_error(title=..., message=frappe.get_traceback())` + `frappe.db.set_value("AP Invoice Capture", capture, {"action_required":1, "action_required_reason": <"Auto-step '{step}' failed after {n} attempts: {msg}">}, update_modified=True)` + `frappe.db.commit()`. **Do NOT re-raise** (avoids RQ's own retry loops; `action_required` is the canonical signal). Wrap the surface-update in its own try/except that logs a secondary error if even the surface fails (mirrors .py:483-487).

#### (D) Threshold wiring (replaces the 1000.0 literal)
1. Change `ap_invoice_capture._resolve_approval_threshold` (.py:1243) so that when `threshold is None`, it reads `ap_closed_loop_settings.get_auto_post_threshold()` instead of the bare constant.
2. `get_auto_post_threshold()` returns `auto_post_amount_threshold` when set/`>0`, else `AUTO_APPROVAL_THRESHOLD_DEFAULT` (1000.0).
3. **Keep** `AUTO_APPROVAL_THRESHOLD_DEFAULT=1000.0` as the literal fallback so empty-settings sites are byte-for-byte unchanged in approval routing. The `request_approval()` call-site is unchanged.

#### (E) Subsumption of `_enqueue_next`
1. Replace the **body** of `ap_invoice_capture._enqueue_next(self, method_name, reason)` to delegate: `async_runner.enqueue_step(self.name, method_name, reason=reason)`. Keep the method on the class so `_determine_next_step`'s if-ladder and the `_maybe_enqueue` gating (.py:308-319) are untouched — only routing/queue/retry/dead-letter move into `async_runner`.
2. Fix the stale "job_name" wording in the `_enqueue_next` docstring (.py:372-373) → `job_id`.
3. `_dispatch_step` subsumes `_run_cascade_step`: either (a) keep `_run_cascade_step` as a thin alias that calls `_dispatch_step`, or (b) point the dispatcher path at `_dispatch_step` and delete `_run_cascade_step`. Recommended: (a) for one release to avoid breaking any external job_id references, then remove. (Open Decision D4.)

#### (F) Install / defaults backfill
1. New module `erpnext/accounts/ap_closed_loop/install.py` with `install_ap_defaults()` (no args — matches the `after_migrate` handler signature).
2. It sets each new Single field **only when blank** (never clobbers operator edits): for each `(field, default)` in the new-defaults map, if `frappe.db.get_single_value("AP Closed Loop Settings", field)` is empty, `frappe.db.set_single_value("AP Closed Loop Settings", field, default)`. Safe to re-run (idempotent).
3. **Wiring:** append `"erpnext.accounts.ap_closed_loop.install.install_ap_defaults"` to the existing `after_migrate` LIST in `hooks.py:69` (additive). Because `AP Posting Ledger` is a new DocType and `install_ap_defaults` only touches the Single, ordering vs schema sync is safe either way — but if a future variant reads/writes `AP Posting Ledger`, it must move to a numbered patch under `[post_model_sync]` (so the table exists first). Default install path: `after_migrate`. Alternative: a patch `erpnext.patches.v16_0.ap_closed_loop_settings_defaults` under `[post_model_sync]` (Open Decision D2).

### 5.4 Cascade & stream-awareness
- **Slots into `_determine_next_step`:** unchanged. The if-ladder (.py:321-366) still decides *which* step; `_enqueue_next` now hands the chosen `method_name` to `async_runner.enqueue_step`, which decides *which queue* and *how to retry/dead-letter*. The pure state machine stays pure.
- **Pause vs auto-advance:** unchanged by this spec. Today's pause points (OCR review at `Proposed`, manual promote at `Validated`, manager approval at `Pending Manager`) are encoded by `_determine_next_step` returning `None`/not matching; the foundation does not alter them. Later specs add steps by adding if-ladder branches + map entries — no foundation change.
- **Stream R vs Stream I:** the runner and ledger are stream-agnostic. Step names are free-text so:
  - **Stream R** (spec 02/07) enqueues e.g. `create_journal_entry` (or `create_pi_with_clearing`) → routes through `with_idempotency(step="create_journal_entry")`; **no** `request_approval`/`issue_payment` steps are enqueued (no authorization, no payment execution).
  - **Stream I** (spec 11/12) enqueues `request_approval` → `issue_payment`; both document-creating steps route through `with_idempotency`.
  - Both use the *same* `enqueue_step`; the divergence lives entirely in which steps each stream's `_determine_next_step` branches return.

### 5.5 Cross-cutting
- **Permissions / SoD:** `enforce_sod`/`sod_threshold_amount` are *defined* here (the backbone) but *consumed* by spec 11 (Stream I approval/SoD). Foundation only stores + exposes `get_sod_config()`.
- **Idempotency key usage:** this spec **owns** the primitive; every later document-creating step depends on it (see §5.3-B contract). Cross-linked from [[05-supplier-resolution]], [[07-classification-doctype-branching]], [[12-payment-execution]], [[13-bank-feed-reconciliation]].
- **Async / enqueue:** this spec **owns** `enqueue_step`; OCR (spec 04) and bank-feed sync (spec 13) are the queue-backed consumers the plan names.
- **Observability event emission:** the dead-letter path sets `action_required`/`action_required_reason` (the existing canonical signal). Emitting a structured `AP Review Event` (the richer audit row) is owned by [[10-ap-review-observability]]; foundation should call its emitter *if present* but must not hard-depend on spec 10 (graceful no-op if the doctype/helper isn't installed yet). Flag the seam to spec 10.

## 6. Acceptance criteria
- **AC-01-1** (positive): `generate_key(c, s)` returns the same 64-char hex on repeated calls for the same `(capture, step)` — and the result depends **only** on `(capture, step)` (the function reads no DB / no settings).
- **AC-01-2** (stability across settings saves — the double-post guard): the key is **STABLE** across `AP Closed Loop Settings` saves. Concretely: capture `c` + step `s` saved before an arbitrary settings edit (e.g. change `ocr_model`, which bumps the Single's `modified`) and computed again after that edit yields the **identical** hex. **Only** changing the `step` or the `capture` changes the key. (This is what makes a retried job — even one re-running after an unrelated settings tweak — re-resolve to the *same* `AP Posting Ledger` row instead of re-running `fn()` and double-posting.)
- **AC-01-3** (positive): first `with_idempotency(key, fn, capture, step)` call runs `fn` exactly once, inserts one `AP Posting Ledger` row with the correct `idempotency_key`/`capture`/`step`/`result_doctype`/`result_name`/`posted_at`, and returns `{"reused": False}`.
- **AC-01-4** (negative / double-post guard): a second `with_idempotency` call with the same `key` does **not** call `fn`, creates **no** second ledger row, and returns the same `{doctype, name}` with `{"reused": True}`.
- **AC-01-5** (edge / concurrency): with a ledger row pre-inserted for `key`, calling `with_idempotency(key, fn=<creates a different doc>, ...)` returns the **existing** row (the pre-inserted one wins) and inserts no duplicate ledger row.
- **AC-01-6** (edge / DB guarantee): two direct `insert`s of `AP Posting Ledger` with the same `idempotency_key` raise `frappe.UniqueValidationError` (the UNIQUE index exists).
- **AC-01-7** (positive): `enqueue_step` routes an OCR/extraction step to `queue=="long"`, a posting/matching/payment step to `"short"`, and an unknown step to `"default"`.
- **AC-01-8** (positive): the enqueued `job_id == f"apic::{capture}::{step}"`, `deduplicate is True`, and (non-test path) `enqueue_after_commit is True`.
- **AC-01-9** (edge / retry): a transient-failing step re-enqueues with `_attempt` incrementing up to `MAX_RETRIES (3)`, then stops re-enqueuing.
- **AC-01-10** (negative / dead-letter): after retries are exhausted OR on a permanent `ValidationError`, the dispatcher sets `action_required==1` + a populated `action_required_reason` on the capture, logs an Error Log entry, and does **not** re-raise.
- **AC-01-10a** (native immediate-retry transient): a step raising a provider-429/5xx-class transient error that the classifier marks immediate-retry causes the dispatcher to raise `frappe.RetryBackgroundJobError` (NOT enter the custom `_attempt` loop and NOT dead-letter), so frappe's `execute_job` owns the retry. Assert no `action_required` is set on that single attempt and the custom re-enqueue is not called.
- **AC-01-10b** (no double-retry): an immediate-retry transient error takes the native `RetryBackgroundJobError` path **only** — it does **not** ALSO trigger a custom `_attempt`+1 re-enqueue (guards against the native-5×-under-custom-3× = 15-attempt stacking).
- **AC-01-10c** (exception ordering / concurrency not dead-lettered): when `fn()`'s ledger insert raises `frappe.UniqueValidationError` (concurrency loss), `_dispatch_step` re-resolves to the existing `AP Posting Ledger` row and returns it — it does **NOT** set `action_required` / dead-letter. (Proves the `UniqueValidationError` branch is ordered before the generic `ValidationError` branch, given `UniqueValidationError` subclasses `ValidationError`.)
- **AC-01-11** (positive): `get_auto_post_threshold()` returns `auto_post_amount_threshold` when set; returns `1000.0` when blank.
- **AC-01-12** (edge): `_resolve_approval_threshold(None, ...)` returns the settings value when `auto_post_amount_threshold` is set, and `1000.0` when it is blank (back-compat).
- **AC-01-13** (edge): `get_confidence_threshold(field)` returns the `field_thresholds` JSON override when present, else `per_field/ocr_confidence_threshold`, else `0.70`.
- **AC-01-14** (positive): the new account-link fields (`credit_card_clearing_account`, `unmapped_card_spend_account`) persist and round-trip via `get_singles_dict`.
- **AC-01-15** (negative): `validate()` still rejects an OCR/per-field confidence threshold outside `0..1`.
- **AC-01-16** (positive / install): running `install_ap_defaults()` on a Single with blank new fields backfills the documented defaults; running it again is a no-op and does **not** overwrite an operator-edited value.
- **AC-01-17** (regression / subsumption): the full existing `test_ap_invoice_capture.py` cascade suite passes unchanged with `_enqueue_next` delegating to `async_runner.enqueue_step` (cascade behavior, dead-letter surfacing, and the idempotency-guard tests at :715/:932/:1114 stay green).

## 7. Tests

### 7.1 Automated
Use `frappe.tests.IntegrationTestCase`; roll back DB writes in `tearDown` so suites are reentrant. Run with `bench --site <site> run-tests --module <dotted.path>`.

- **`erpnext.accounts.ap_closed_loop.tests.test_idempotency`** (new file `erpnext/accounts/ap_closed_loop/tests/test_idempotency.py`):
  - `generate_key` determinism (positive — AC-01-1); sensitivity to step/capture ONLY, and **stability across an `AP Closed Loop Settings` save** — assert the key is unchanged after bumping the Single's `modified` via an unrelated field edit (AC-01-2). This is the regression guard against re-introducing a `modified`-in-key double-post bug.
  - `with_idempotency` first call: `fn` runs once, ledger row fields correct, `reused=False` (positive — AC-01-3); use a call-counter or `unittest.mock.Mock` to assert `fn` invocation count.
  - `with_idempotency` second call same key: `fn` NOT called, same `{doctype,name}`, `reused=True` (negative — AC-01-4).
  - concurrency/UNIQUE re-resolve: pre-insert a ledger row, call with a divergent `fn`; existing row wins, no duplicate (edge — AC-01-5); simulate the IntegrityError path.
  - direct double-insert raises `frappe.UniqueValidationError` (edge — AC-01-6).
- **`erpnext.accounts.ap_closed_loop.tests.test_async_runner`** (new file `.../tests/test_async_runner.py`):
  - queue selection long/short/default by monkeypatching `frappe.enqueue` and asserting `queue` kwarg (positive ×3 — AC-01-7).
  - `job_id` format + `deduplicate`/`enqueue_after_commit` flags (positive — AC-01-8).
  - retry (delayed-backoff bucket): transient-failing step re-enqueues with `_attempt+1` up to `MAX_RETRIES`, then stops; assert attempt count (edge — AC-01-9).
  - native immediate-retry: a 429/5xx-class transient causes the dispatcher to **raise `frappe.RetryBackgroundJobError`** and NOT enter the custom re-enqueue / NOT dead-letter; assert the exception type and that `action_required` stays unset (AC-01-10a). Assert the same error does not ALSO custom-re-enqueue — no double-retry (AC-01-10b).
  - dead-letter: after exhaustion / on permanent `ValidationError`, `action_required==1` + reason set, no re-raise (negative — AC-01-10).
  - exception ordering: simulate a `frappe.UniqueValidationError` from the ledger insert inside a dispatched step and assert it is **re-resolved to the existing row, not dead-lettered** (`action_required` stays unset) — proving the concurrency branch precedes the generic `ValidationError` branch (AC-01-10c).
  - QUEUE_BY_STEP unknown-key fallback resolves to `"default"` (registry/adapter unknown-key edge).
- **`erpnext.accounts.doctype.ap_closed_loop_settings.test_ap_closed_loop_settings`** (create file if absent — none exists today):
  - `get_auto_post_threshold` set vs blank→1000.0 (positive+negative — AC-01-11).
  - `_resolve_approval_threshold(None,...)` uses settings vs falls back to 1000.0 (edge — AC-01-12).
  - `get_confidence_threshold(field)` override precedence (edge — AC-01-13).
  - account-link fields round-trip via `get_singles_dict` (positive — AC-01-14).
  - `validate()` still rejects threshold outside 0..1 (negative — AC-01-15).
- **`erpnext.accounts.ap_closed_loop.tests.test_install`** (or fold into `test_ap_closed_loop_settings`):
  - `install_ap_defaults` backfills blanks; re-run is a no-op; never overwrites an operator-edited value (positive + idempotent — AC-01-16).
- **Regression:** run the whole AP suite — `bench ... run-tests --module erpnext.accounts.doctype.ap_invoice_capture.test_ap_invoice_capture` — to prove the `_enqueue_next` subsumption keeps cascade + guard tests green (AC-01-17).

### 7.2 Clean-room test plan
Ship three runbooks under `test/testplans/` (kebab slugs, one per shipped piece):
- **`test/testplans/ap-foundations-settings-backbone.md`** — scope: new + reconciled Single fields, defaults install/backfill, and `auto_post_amount_threshold` → 1000.0 back-compat verified end-to-end.
- **`test/testplans/ap-idempotency-posting-ledger.md`** — scope: `AP Posting Ledger` UNIQUE behavior and `with_idempotency` double-post prevention exercised through a real promote (drive a step twice; assert exactly one downstream doc + one ledger row via `SELECT … FROM tabAP Posting Ledger`).
- **`test/testplans/ap-async-runner.md`** — scope: queue routing (long/short/default), dead-letter surfacing `action_required`, retry/backoff behavior, and the `_enqueue_next` subsumption (cascade unchanged).

Each plan must include exact `bench` setup, the `AP Closed Loop Settings` field values to set, a sample capture to drive a step twice, and DB assertions (DB is the source of truth) since the UNIQUE row is the guarantee.

### 7.3 UI testing (Playwright MCP)
**N/A — this slice is backend-only.** There is no user-facing UI beyond the standard `AP Closed Loop Settings` Single form: the new fields (Thresholds / SoD / Clearing-Accounts sections) are plain config inputs, and the new settings are exercised by the §7.1 getter round-trip tests + the §7.2 clean-room runbooks, not by browser interaction. The idempotency ledger, async runner, and threshold wiring are server-side primitives with no desk surface of their own. No Playwright scenarios are required for this slice.

**Optional smoke (only if a browser is already up for an adjacent slice):** open `/app/ap-closed-loop-settings`, confirm the new **Confidence & Approval Thresholds**, **Segregation of Duties**, and **Clearing & Suspense Accounts** sections render and that **Save** succeeds without error; screenshot to `test/testplans/screenshots/ap-foundations-settings-backbone/settings-sections.png` (committed) — pass that path as the screenshot `filename`. Setup (if run): Playwright MCP per `test/testplans/BROWSER-TESTING-SETUP.md` (`claude mcp list` must list `playwright`; restart Claude Code after registering; `.mcp.json` / `.playwright-mcp/` stay gitignored). No other scenarios.

## 8. Open decisions
- **D1 — Threshold field reconciliation (HIGH).** Should the per-field confidence threshold keep using the existing `ocr_confidence_threshold` field, or add a new `per_field_confidence_threshold` + copy-forward patch? **Options:** (a) keep `ocr_confidence_threshold` as canonical, add only `get_confidence_threshold()` getter — zero migration, no second scalar; (b) add `per_field_confidence_threshold`, patch-copy the old value, getter reads either. **Recommended default: (a)** — the existing field is already documented as per-field; avoids duplication and a migration, and `get_ocr_config`'s 0.70 fallback stays intact. **Owner:** spec 01 author + spec 04 (extraction). **Must lock:** before §5.1-A JSON is written.
- **D2 — Defaults install path (MEDIUM).** `after_migrate` append vs numbered `[post_model_sync]` patch. **Options:** (a) append to `after_migrate` LIST (hooks.py:69) — runs every migrate, naturally re-runnable; (b) one-time `erpnext.patches.v16_0.ap_closed_loop_settings_defaults`. **Recommended default: (a)**, because the installer only touches the Single (no new-table ordering concern) and being re-runnable on every migrate is desirable for a defaults backfill. **Owner:** spec 01 author. **Must lock:** before install module is wired.
- **D3 — `AP Posting Ledger` naming (MEDIUM).** `autoname="field:idempotency_key"` (key IS the name) vs a series `APIPL-.#####` with a separate UNIQUE constraint. **Recommended default: `field:idempotency_key`** — makes `frappe.db.exists(dt, key)` the cheapest possible existence check and the name self-documents. **Owner:** spec 01 author. **Must lock:** before the DocType JSON is created.
- **D4 — `_run_cascade_step` retirement (LOW).** Keep it as a thin alias to `_dispatch_step` for one release, or delete immediately. **Recommended default: keep as alias one release**, then remove, to avoid breaking any in-flight job_ids referencing the old path. **Owner:** spec 01 author. **Must lock:** at build time.
- **D5 — Retry-delay realization (HIGH).** `frappe.enqueue` has no delay arg. How is exponential backoff's *delay* realized? **Options:** (a) `next_retry_at` field + a `scheduler_events` sweep (cron/`all`) that re-enqueues due retries — true delay, no blocked worker; (b) immediate re-enqueue with no real delay (phase-1 simplicity); (c) a tiny dedicated retry-queue DocType. **Recommended default: (b) for phase-1, (a) for phase-2** — ship immediate re-enqueue first (transient errors usually clear fast and frappe already retries DB locks), add the scheduled sweep when provider 429/5xx backoff is needed in earnest. **Owner:** spec 01 author + spec 04/13 (the queue-backed consumers). **Must lock:** before `_dispatch_step` retry branch is built.
- **D6 — `fn()`/ledger atomicity on concurrent UNIQUE loss (HIGH).** If a concurrent winner inserts the key after this caller's `fn()` already created a downstream doc, the loser produced a duplicate doc. **Options:** (a) require each `fn()` to be independently idempotent (rely on the existing per-step status guards, e.g. promote guards on `promotion_status`); (b) run `fn()`+ledger-insert in one DB transaction that rolls back together on the UNIQUE violation. **Recommended default: (a) plus (b) where the step has no natural guard** — belt-and-suspenders; the status guards already cover promote/route/pay. **Owner:** spec 01 author + each consuming spec. **Must lock:** before the first downstream consumer (spec 05/07) wires `with_idempotency`.
- **D7 — Enqueue signature re-verification on v16 (MEDIUM).** Runtime frappe is 16.18.3; the signature was verified against `version-15` source. **Options:** (a) re-inspect `frappe.utils.background_jobs.enqueue` on the installed frappe at build time and adjust kwargs if v16 changed/renamed any; (b) trust the v15 signature. **Recommended default: (a)** — cheap `bench console` / source read; do it before finalizing. **Owner:** spec 01 author. **Must lock:** before the runner is merged. (Citation source remains v15 docs per CLAUDE.md.)
- **D8 — `AP Review Event` coupling (LOW).** Should the dead-letter path emit a structured spec-10 `AP Review Event` in addition to `action_required`? **Recommended default: emit if the spec-10 helper exists, else no-op** — foundation must not hard-depend on spec 10. **Owner:** spec 01 + spec 10. **Must lock:** when spec 10 lands.
- **D9 — Idempotency-key material: include `settings.modified`? (RESOLVED → capture+step only).** An earlier draft folded the Single's `modified`-version into the key material. **Options:** (a) key on `(capture, step)` only; (b) key on `(capture, step, settings.modified)`. **Resolved: (a).** Including `modified` means *any* settings save (even an unrelated edit) changes the key for every capture/step, so a job retried after such a save re-computes a new key, misses its `AP Posting Ledger` row, re-runs `fn()`, and **double-posts** — defeating the "retried job cannot double-post" guarantee (see §5.3-A). The key must depend only on *what* is posted, not on settings state. The cost of (a) is that an operator who *deliberately* wants a step re-run after changing config cannot get it via a key change — but that is a feature (force-rerun is an explicit, audited action via `ocr_force_reextract`-style flags or deleting the ledger row), not a side effect of an unrelated save. **Owner:** spec 01 author. **Status:** locked; reflected in §5.2 / §5.3-A / AC-01-1 / AC-01-2.

## 9. Dependencies & sequencing
- **Depends on:** nothing — this is the root foundation; **sequence it FIRST.** Cross-linked: [[00-overview]].
- **Must land before (unblocks):**
  - [[02-intake-stream-tagging]] — owns `stream_rules_section` on this Single; enqueues stream steps via `enqueue_step`; consumes `credit_card_clearing_account`/`unmapped_card_spend_account`.
  - [[04-extraction-confidence-line-items]] — consumes `get_confidence_threshold`/`field_thresholds`; runs OCR on the `long` queue via `enqueue_step`.
  - [[05-supplier-resolution]] — routes Supplier creation through `with_idempotency`.
  - [[06-gl-coding-tax-costcenter]] — consumes `unmapped_card_spend_account`.
  - [[07-classification-doctype-branching]] — routes PI / Journal Entry creation through `with_idempotency`; enqueues `create_journal_entry` (Stream R) vs PI-branch (Stream I).
  - [[08-validation-gates]] — owns `anomaly_section`.
  - [[11-approval-sod-workflow]] — consumes `get_sod_config` (`enforce_sod`/`sod_threshold_amount`) and `auto_post_amount_threshold`.
  - [[12-payment-execution]] — routes Payment Entry through `with_idempotency`.
  - [[13-bank-feed-reconciliation]] — owns `bank_feed_section`; bank-feed sync queue-backed via `enqueue_step`; routes Bank Transaction through `with_idempotency`.
- **Coordination:** specs 02/08/13 each OWN a settings block on this same `AP Closed Loop Settings` Single — this spec adds their section breaks as placeholders now so `field_order` ownership is reserved and later additions don't collide.
- **Account-link company-awareness:** `credit_card_clearing_account`/`unmapped_card_spend_account` are site-wide here but company is per-capture — flag to the consuming spec (02/06) to validate the chosen account against the capture's company at point of use.
- **Estimated size:** **L** (per IMPLEMENTATION-PLAN units). Three new modules (`idempotency.py`, `async_runner.py`, `install.py`), one new DocType (`AP Posting Ledger`), a Single extension with ~10 fields + 6 sections, a controller refactor (`_enqueue_next` subsumption + threshold wiring), three test modules, and three clean-room test plans.
