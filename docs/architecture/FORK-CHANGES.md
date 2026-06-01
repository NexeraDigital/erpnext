# Fork Changes — AP Closed Loop Receipt Processing

> **Fork:** NexeraDigital/erpnext (this repo, branch `russ/migrateToV16`)
> **Upstream baseline:** `frappe/erpnext` `version-16` at `ff46d20b25` — `chore(release): Bumped to Version 16.20.0` (2026-05-27).
> **Current fork tip:** `51669ff18b` — `feat: rebase AP closed-loop pilot onto upstream/version-16` (2026-05-28).
> **Previous develop-based history** is preserved at tag `pre-v16-migration` and branch `russ/bryanwork`. See [`docs/planning/local-v17-to-v16-migration-plan.md`](../planning/local-v17-to-v16-migration-plan.md) and [`docs/planning/v16-upgrade-business-case.md`](../planning/v16-upgrade-business-case.md) for the migration rationale and procedure.

This fork adds a single, narrowly-scoped vertical slice on top of upstream ERPNext: an **Accounts Payable Closed Loop Receipt Processing** pilot for NexeraDigital. It does **not** modify any existing accounting, stock, or buying logic. The only edit outside the new files is a 2-line refactor in `erpnext/setup/utils.py`.

---

## 1. Files Added / Modified

Brandon's pilot (8 commits, fork base):

```
 AGENTS.md                                                              |   76 ++
 erpnext/accounts/ap_closed_loop/__init__.py                            |    0
 erpnext/accounts/ap_closed_loop/walking_skeleton.py                    |  365 +++++
 erpnext/accounts/ap_closed_loop/test_walking_skeleton.py               |  130 ++
 erpnext/accounts/doctype/ap_invoice_capture/__init__.py                |    0
 erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.json    |  662 +++++++++
 erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.py      | 1424 ++++++++++++++++++++
 erpnext/accounts/doctype/ap_invoice_capture/test_ap_invoice_capture.py | 1272 +++++++++++++++++
 erpnext/setup/utils.py                                                 |    4 +-
```

Phase-2 UI + automation layer (added on top of Brandon's pilot):

```
 erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.js                |  ~400 +++
 erpnext/accounts/doctype/ap_closed_loop_settings/__init__.py                     |    0
 erpnext/accounts/doctype/ap_closed_loop_settings/ap_closed_loop_settings.json    |   90 ++
 erpnext/accounts/doctype/ap_closed_loop_settings/ap_closed_loop_settings.py      |   55 ++
 erpnext/workspace_sidebar/invoicing.json                                         |    +/- (sidebar entry)
 erpnext/tests/utils.py                                                           |    +/- (bootstrap fix)
```

OCR Phase 0 — shared AI provider credentials infrastructure (added on `russ/migrateToV16`):

```
 erpnext/modules.txt                                                              |   +1 (AI module)
 erpnext/ai/__init__.py                                                           |    0
 erpnext/ai/doctype/__init__.py                                                   |    0
 erpnext/ai/doctype/ai_provider_settings/__init__.py                              |    0
 erpnext/ai/doctype/ai_provider_settings/ai_provider_settings.json                |   89 ++ (Single, System-Manager-only)
 erpnext/ai/doctype/ai_provider_settings/ai_provider_settings.py                  |   55 ++ (controller + whitespace-trim validate)
 erpnext/ai/credentials.py                                                        |  110 ++ (AICredentials, get_ai_credentials, AICredentialsNotConfigured)
 erpnext/ai/tests/__init__.py                                                     |    0
 erpnext/ai/tests/test_credentials.py                                             |  130 ++ (6 IntegrationTestCase tests)
 erpnext/workspace_sidebar/erpnext_settings.json                                  |    +/- (sidebar link to AI Provider Settings, after System Settings)
 erpnext/setup/workspace/erpnext_settings/erpnext_settings.json                   |    +/- (shortcut card + content cell for AI Provider Settings)
 test/testplans/ai-provider-settings-phase0.md                                    |  ~280 ++ (external-instance test plan)
 docs/planning/ocr-provider-choice-claude.md                                      |  ~250 ++ (provider-choice justification)
 docs/planning/real-ocr-implementation-plan.md                                    |  ~700 ++ (8-phase implementation plan)
```

OCR Phase 1 — provider adapter seam (no behaviour change):

```
 erpnext/accounts/ap_closed_loop/extractors/__init__.py                           |    0
 erpnext/accounts/ap_closed_loop/extractors/base.py                               |   ~90 (OCRProvider ABC + ExtractionResult + PROPOSAL_KEYS)
 erpnext/accounts/ap_closed_loop/extractors/fake.py                               |   ~75 (FakeExtractor wrapping the existing deterministic proposal)
 erpnext/accounts/ap_closed_loop/extractors/registry.py                           |   ~35 (get_extractor)
 erpnext/accounts/ap_closed_loop/extractors/test_extractors.py                    |  ~150 (15 IntegrationTestCase tests)
 erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.py                |    +/- (run_fake_extraction -> run_extraction, dispatches via registry; alias kept)
 test/testplans/ocr-phase1-adapter.md                                             |  ~200 ++ (external-instance test plan)
```

OCR Phase 2 — Anthropic Claude extractor (real OCR):

```
 pyproject.toml                                                                   |    +1 (anthropic>=0.40.0 dependency)
 erpnext/accounts/ap_closed_loop/extractors/anthropic.py                          |  ~290 (AnthropicExtractor: file read, doc/image block, forced tool use, ExtractionResult mapping, smoke_test)
 erpnext/accounts/ap_closed_loop/extractors/registry.py                           |    +/- (register "anthropic")
 erpnext/accounts/ap_closed_loop/extractors/test_anthropic.py                     |  ~230 (14 mocked unit tests + 1 opt-in live test)
 test/testplans/real-ocr-anthropic.md                                             |  ~250 ++ (external-instance test plan)
```

Note: Phase 2 registers the real provider but does NOT yet flip the live default — the cascade still uses `fake` until Phase 3 wires `AP Closed Loop Settings.ocr_provider`.

OCR Phase 3 — settings-driven provider selection (turns real OCR on in the workflow):

```
 erpnext/accounts/doctype/ap_closed_loop_settings/ap_closed_loop_settings.json   |    +/- (ocr_provider/model/fallback_model/confidence_threshold/max_file_mb/force_reextract fields)
 erpnext/accounts/doctype/ap_closed_loop_settings/ap_closed_loop_settings.py     |    +/- (validate(): require key when Anthropic + range check; get_ocr_config() accessor)
 erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.py               |    +/- (run_extraction reads get_ocr_config(); dispatches provider/model/threshold)
 erpnext/accounts/ap_closed_loop/extractors/registry.py                          |    +/- (get_extractor forwards model/confidence_threshold kwargs)
 erpnext/accounts/ap_closed_loop/extractors/fake.py                              |    +/- (FakeExtractor ignores provider-config kwargs)
 erpnext/accounts/doctype/ap_closed_loop_settings/test_ap_closed_loop_settings.py|  ~180 (8 tests: get_ocr_config, validate, dispatch — transaction-scoped, no commits)
 test/testplans/ocr-phase3-settings.md                                           |  ~180 ++ (external-instance test plan)
```

After Phase 3: an operator sets **AP Closed Loop Settings → OCR Provider = Anthropic Claude** (with a key in **AI Provider Settings**) and the live capture cascade calls Claude. Default remains **Fake (Deterministic)** so an unconfigured site makes no API calls. The `anthropic_api_key` lives only on `AI Provider Settings` (System Manager); AP Managers choose the provider but cannot see the credential.

OCR Phase 4 — low-confidence fallback (Haiku → Sonnet):

```
 erpnext/accounts/ap_closed_loop/extractors/anthropic.py                         |    +/- (one-shot fallback: retry once with ocr_fallback_model when a required field is missing/ambiguous; raw_response records outcome + model)
 erpnext/accounts/doctype/ap_closed_loop_settings/ap_closed_loop_settings.py     |    +/- (get_ocr_config returns fallback_model)
 erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.py               |    +/- (run_extraction forwards fallback_model)
 erpnext/accounts/ap_closed_loop/extractors/test_anthropic.py                    |    +/- (5 mocked fallback tests; 23 total)
 test/testplans/ocr-phase4-fallback.md                                           |  ~150 ++ (external-instance test plan)
```

Phase 4 behaviour: the primary model (default Haiku) handles every invoice; only when it can't confidently read a required field does the extractor retry **once** with `ocr_fallback_model` (e.g. Sonnet). At most one retry — no looping, no Opus escalation. Empty fallback model = disabled (the default). On the synthetic corpus Haiku already scores 100%, so fallback's value is on messy real-world invoices.

OCR Phase 5 — audit logging & cost tracking (via Integration Request):

```
 erpnext/accounts/ap_closed_loop/extractors/pricing.py                           |  ~70 (per-model token rate table + estimate_cost_usd)
 erpnext/accounts/ap_closed_loop/extractors/audit.py                             |  ~120 (write_integration_request + sanitize; never logs the key)
 erpnext/accounts/ap_closed_loop/extractors/anthropic.py                         |    +/- (accumulate per-call usage + total latency_ms into raw_response)
 erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.py               |    +/- (run_extraction logs Completed/Failed Integration Request for the real provider)
 erpnext/accounts/ap_closed_loop/extractors/test_audit.py                        |  ~190 (11 tests: pricing, sanitize, IR write, run_extraction integration)
 test/testplans/ocr-phase5-audit.md                                              |  ~150 ++ (external-instance test plan)
```

Phase 5 behaviour: each real extraction (and failure) is recorded as a Frappe **`Integration Request`** (`integration_request_service="anthropic"`, referenced to the capture) with model(s), per-call + total token usage, estimated USD cost, latency, outcome, and a sanitized error on failure. The fake provider is not logged (no call, no cost). API keys are never persisted in any field. Operators view the trail at `/app/integration-request` filtered by service. Verified live: one extraction → `Completed` row, real tokens/cost/latency, no key leak.

OCR Phase 6 — production hardening (retry + circuit breaker + size guard + non-silent failures):

```
 erpnext/accounts/ap_closed_loop/extractors/circuit.py                            |  ~75 (process-local CircuitBreaker + CircuitOpenError + shared_breaker)
 erpnext/accounts/ap_closed_loop/extractors/anthropic.py                          |    +/- (_call_model: breaker.check + retry-with-backoff on 429/5xx/timeout/conn, honour Retry-After, never retry 400; _classify_exception, _backoff_seconds, _parse_retry_after; injectable sleep/breaker, max_retries ctor arg)
 erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.py               |    +/- (_source_file_size_bytes; run_extraction enforces ocr_max_file_mb pre-flight for real providers + surfaces any failure on the capture via action_required + reason)
 erpnext/accounts/ap_closed_loop/extractors/test_hardening.py                     |  ~310 (16 tests: classify, backoff, breaker, retry loop, size-guard, failure surfacing)
 test/testplans/ocr-phase6-hardening.md                                          |  ~180 ++ (external-instance test plan)
```

Phase 6 behaviour: the real path now tolerates transient provider trouble and never stalls silently. `_call_model` retries 429/5xx/timeout/connection errors with exponential backoff (1/2/4s, honouring a server `Retry-After` on 429) but never retries client errors (400/401/404); after N consecutive transient failures a **process-local circuit breaker** opens for a cooldown so further calls fail fast with no spend, half-opening on the first call past cooldown and resetting on success. Before any API call, `run_extraction` enforces `ocr_max_file_mb` (oversized source → `action_required` + reason + `Failed` Integration Request, no call); the fake provider is exempt. Any extraction failure is surfaced on the capture itself (`action_required=1` + human reason, persisted) **and** logged as a `Failed` Integration Request, then re-raised. Sleep, clock, breaker, and retry count are all injectable, so the 16 tests run deterministically with no network and no real waiting.

OCR proposal — form field visibility:

```
 erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.json             |    +/- (hidden=1 on ocr_provider, ocr_status, ocr_extracted_at, ocr_raw_response)
```

The four diagnostic fields in the "AI / OCR Proposal" section are hidden from the form (`hidden` is a display-only DocField property — `apps/frappe/frappe/core/doctype/docfield/docfield.json`; honoured at `apps/frappe/frappe/public/js/frappe/form/controls/base_control.js:61`). Data is unchanged and still in the DB/API; the per-call audit trail remains fully visible in **Integration Request** (Phase 5). Clerks now see only the proposed values they review (supplier / invoice no / date / total / currency) plus the missing/ambiguous flags.

OCR test corpus + benchmark (supporting the above phases):

```
 test/invoices/{templates.py,generate_invoices.py,README.md}                     |   HTML/CSS invoice generator (Chromium-rendered); organised by purpose into subfolders
 test/invoices/ocr-extraction/                                                   |   20 OCR-accuracy invoices + ground-truth JSON (the benchmark corpus)
 test/invoices/deduplication/{exact-duplicate,near-duplicate,distinct}/          |   spec-03 dedupe fixtures (byte-identical pair / re-scan near-dup / unrelated) + generator
 erpnext/accounts/ap_closed_loop/extractors/benchmark.py                         |  ~160 (run() scores corpus vs ground truth; recursive corpus glob; pure match_field logic)
 erpnext/accounts/ap_closed_loop/extractors/test_benchmark.py                    |  ~90 (9 scoring unit tests)
```

The corpus surfaced two production fixes: image downscaling before send (oversized scans hit Anthropic's 5MB limit) and not inferring an unprinted currency. Benchmark baseline (Haiku 4.5): **20/20 invoices, 100/100 fields.**

MCP server layer (added on `russ/mcp-server`, off `russ/migrateToV16` — see §10):

```
 erpnext/modules.txt                                            |    +1 (MCP module)
 erpnext/hooks.py                                               |    +/- (after_migrate, scheduler, permission_query_conditions)
 erpnext/mcp/__init__.py                                        |   ~25 (vendor sys.path shim)
 erpnext/mcp/endpoint.py                                        |  ~130 (the only HTTP route; L1 + dispatch)
 erpnext/mcp/auth.py                                            |  ~120 (OAuth bearer -> set_user)
 erpnext/mcp/audience.py                                        |   ~50 (RFC 8707 audience binding)
 erpnext/mcp/audit.py                                           |  ~180 (_safe_execute, sanitize, rate limit)
 erpnext/mcp/permissions.py                                     |   ~60 (permitted_names idiom)
 erpnext/mcp/registry.py                                        |   ~90 (per-request registry + scope gate)
 erpnext/mcp/config.py                                          |  ~110 (MCP Settings / Tool Config accessors)
 erpnext/mcp/exceptions.py                                      |   ~50 (typed errors -> HTTP status)
 erpnext/mcp/install.py                                         |   ~45 (after_migrate: seed Tool Config rows)
 erpnext/mcp/tasks.py                                           |   ~25 (daily audit-log prune)
 erpnext/mcp/tools/{base,_scope,ap_invoices,vendors,schema}.py  |  ~430 (5 tools + BaseTool)
 erpnext/mcp/doctype/mcp_settings/*                             |   Single
 erpnext/mcp/doctype/mcp_tool_config/*                          |   one row per tool
 erpnext/mcp/doctype/mcp_audit_log/*                            |   immutable audit
 erpnext/mcp/tests/test_*.py                                    |  ~430 (6 test modules)
 erpnext/mcp/_vendor/frappe_mcp/**                              |   VENDORED frappe/mcp @ 0ea7d0e (MIT)
 docs/changes/ADR-MCP-5-vendor-frappe-mcp-transport.md          |   decision record
```

**Net effect:**
- Two new DocTypes: `AP Invoice Capture` (transaction), `AP Closed Loop Settings` (Single, site-wide defaults).
- One new service module (`ap_closed_loop/`).
- Test modules.
- Form UI with inline state-driven buttons (Upload, Confirm Fields, Re-run Validation, Create Supplier, Promote, Approve/Reject) anchored to the section they act on.
- Auto-progression cascade that advances every step the system can decide on its own; pauses at the three unavoidable human-decision points (OCR review, manual promote — now form-driven, manager decision).
- Two new sidebar entries (Invoice Capture under Payables; AP Closed Loop Settings — to be wired).
- **New top-level `erpnext/mcp/` module** (the AP MCP server): three DocTypes (`MCP Settings`, `MCP Tool Config`, `MCP Audit Log`), a new `MCP` app module, five read-only AP tools, and a vendored MIT transport. See §10.

---

## 2. Commit Timeline

> **Note (2026-05-28):** The fork was rebased onto `upstream/version-16` and now ships as a single squashed commit `51669ff18b feat: rebase AP closed-loop pilot onto upstream/version-16`. The per-feature history below is preserved at tag `pre-v16-migration` and branch `russ/bryanwork` — it describes how the fork was originally built when based on `upstream/develop`. Hashes referenced in the table are reachable via the tag and the old branch, not from the current branch tip.

The fork was built as 8 issue-scoped feature commits + their merges. Each feature is one acceptance-criterion-bounded step in the pilot's vertical slice.

| Commit | Subject | What it landed |
|---|---|---|
| `c95d2d9` | feat: add AP closed loop walking skeleton | `ap_closed_loop/walking_skeleton.py` end-to-end deterministic flow against existing ERPNext PI + PE |
| `78a5a6c` | Merge #2 walking skeleton | merge |
| `10e3a7f` | feat: add AP invoice image intake capture | introduces `AP Invoice Capture` doctype — manual upload, supported-format gating |
| `bce1728` | Merge #3 image intake | merge |
| `4e2fe5a` | feat: add OCR proposal review | deterministic fake OCR + `proposed_*` fields + AP-clerk confirm |
| `af3c7ff` | Merge #4 OCR proposal | merge |
| `1c1c6fa` | feat: add validation promotion | supplier matching + PO/PR classification + promote to Purchase Invoice |
| `e0cfa8e` | Merge #5 validation promotion | merge |
| `2fae4ef` | feat: add approval controls | auto-approval threshold + manager routing + decision |
| `ca37666` | Merge #6 approval controls | merge |
| `04ffeb6` | feat: add mock payment writeback | mock-labeled Payment Entry creation tied to capture |
| `c4ec54e` | Merge #7 mock payment | merge |
| `dbabb28` | feat: add AP invoice capture closure evidence | derives closure from native state, exposes audit payload |
| `69d232d` | Merge #8 closure evidence | merge |
| `ae93cf8` | docs: add AP closed loop agent memory | `AGENTS.md` — Codex/Claude operating notes |
| `f40e4b6` | Merge PR #9 codex/ap-closed-loop | final integration merge into `develop` |

GitHub epic: `NexeraDigital/erpnext#1` (per `AGENTS.md`).

---

## 3. Core Design Principles (encoded in code & tests)

Both `walking_skeleton.py` and `ap_invoice_capture.py` open with the same set of explicit guardrails, and the tests enforce them:

1. **Purchase Invoice is the canonical payable invoice.** The pilot never invents a parallel payable doctype.
2. **Payment Entry is the payment/closure anchor.** Native ERPNext doctype, native lifecycle.
3. **No `Bank Transaction` is created.** Bank reconciliation is *not* implied by closure — they are different signals. Tests assert the Bank Transaction count never increases.
4. **No custom `closed` flag is persisted.** Closure is *derived* from native state: submitted PI + submitted PE + `outstanding_amount == 0` + `status == "Paid"`.
5. **All provider / payment artifacts are visibly labeled MOCK.** `reference_no` carries the `MOCK-PAY-…` prefix; remarks explicitly say "Not bank reconciled. No real banking integration." This prevents the evidence trail from being mistaken for a real banking integration.
6. **Nothing silently progresses.** Unsupported formats, missing mandatory fields, unknown suppliers, ambiguous matches, and unapproved totals all set `action_required = 1` and surface a human-readable `action_required_reason`.

---

## 4. AGENTS.md — Operating Notes (new file)

`AGENTS.md` is a project-memory note for human + AI operators working on this pilot. It pins:

- The canonical project state document in Obsidian (`/Users/brandon/.../00 - Project State.md`).
- Supporting notes (Architecture Decisions, Vertical Slice Plan, Implementation Log, AC Matrix, Open Questions, Claude-Codex Handoff).
- GitHub epic: `https://github.com/NexeraDigital/erpnext/issues/1`.
- Operating model: Codex orchestrates and tracks; Claude is the bounded implementation executor.
- Local commands to open the Obsidian vault and to invoke Claude in read-only or implementation mode.

**This file is documentation only — no runtime effect.**

---

## 5. `erpnext/accounts/ap_closed_loop/walking_skeleton.py`

A pure-Python end-to-end flow that exercises the AP spine *before* any real UI/OCR work. It is intentionally **not** wired into the desk; it's invoked from tests and dev shells.

### 5.1 Dataclasses

| Type | Purpose |
|---|---|
| `SourceCapture` | Stand-in for a real receipt — `capture_id`, `image_uri`, `captured_at`, auto-computed `content_hash` (SHA-256 of the seed string). |
| `FakeExtraction` | Deterministic header-level extraction result — supplier, bill_no, qty, rate, currency. Carries `provider = "deterministic_fake_extractor"` and `is_mock = True`. |
| `ApprovalOutcome` | Records the walking-skeleton approval shortcut. |
| `MockPaymentInstruction` | Mock-only payment request (reference, provider, status, amount, issued_at, `is_mock = True`). |
| `ClosureEvidence` | Audit payload: source, extraction, approval, mock_payment, PI/PE names + native state (status, outstanding_amount, docstatus, paid_amount), GL entry list, **Bank Transaction count**, derived `closed` flag, and `closure_basis` explanation. |

### 5.2 Pipeline functions

```text
SourceCapture
   │
   ▼  fake_extract()           ──► FakeExtraction
   │  (deterministic — same content_hash always yields same bill_no/qty/rate)
   ▼  create_purchase_invoice()──► native Purchase Invoice (inserted + submitted)
   │  (single item row, remarks carry source/content_hash/provider/mock flag)
   ▼  apply_walking_skeleton_approval()
   │  (records APPROVAL_SHORTCUT in PI.remarks via frappe.db.set_value)
   ▼  create_mock_payment_entry()
   │  (get_payment_entry helper, paid_from = "_Test Bank - _TC",
   │   reference_no = "MOCK-PAY-<PI>", remarks state "MOCK PAYMENT … no bank reconciliation")
   ▼  derive_closure_evidence()──► ClosureEvidence
      (re-reads PI/PE state, queries GL Entry & Bank Transaction Payments,
       computes closed = PI.docstatus==1 AND PE.docstatus==1 AND outstanding==0 AND status=="Paid")
```

### 5.3 Constants worth knowing

```python
MOCK_PROVIDER         = "deterministic_fake_extractor"
MOCK_PAYMENT_PROVIDER = "mock_payment_provider"
MOCK_PAYMENT_PREFIX   = "MOCK-PAY"
MOCK_PAYMENT_REMARK   = ("MOCK PAYMENT - AP Closed Loop walking skeleton. "
                        "Not bank reconciled. No real banking integration.")
APPROVAL_SHORTCUT     = "walking_skeleton_auto_approve"
```

### 5.4 Tests (`test_walking_skeleton.py`)

`TestAPClosedLoopWalkingSkeleton(IntegrationTestCase)` with `EXTRA_TEST_RECORD_DEPENDENCIES = ["Item", "Cost Center"]`:

- `test_fake_extraction_is_deterministic` — same `SourceCapture` → same `bill_no`, `qty`, `rate`; provider and `is_mock` correct.
- `test_walking_skeleton_end_to_end` — runs `run_walking_skeleton(supplier="_Test Supplier")` and asserts:
  - PI and PE are both submitted (`docstatus == 1`).
  - `outstanding_amount == 0`, `status == "Paid"`.
  - The mock prefix appears on PE `reference_no`.
  - The Bank Transaction count is unchanged.
  - `evidence.closed is True` and `closure_basis` is the literal explanatory string.

---

## 6. New DocType — `AP Invoice Capture`

This is the *production* shape that succeeds the walking skeleton. The DocType is **not an accounting document**; it is a pre-accounting capture record whose job is to land an invoice image, run a non-authoritative OCR proposal, get AP-clerk confirmation, validate against existing ERPNext records, and then hand off to native Purchase Invoice / Payment Entry.

### 6.1 DocType definition (`ap_invoice_capture.json`)

- Naming: `format:APIC-{YYYY}-{#####}`
- Engine: InnoDB
- Field sections (`Section Break`s) shape the form into sequential clerk steps:
  1. **Source** — `source_filename`, `file_extension`, `intake_channel`, `source_file` (Link → File), `source_file_url`, `received_at`.
  2. **Lifecycle** — `status`, `is_supported_format`, `action_required`, `action_required_reason`.
  3. **Context** — `source_context`, `validation_message`.
  4. **OCR** — `ocr_provider`, `ocr_status`, `ocr_extracted_at`, `proposed_supplier`, `proposed_supplier_invoice_no`, `proposed_invoice_date`, `proposed_total_amount`, `proposed_currency`, `proposed_missing_fields`, `proposed_ambiguous_fields`, `ocr_raw_response`.
  5. **Review** — `final_supplier`, `final_supplier_invoice_no`, `final_invoice_date`, `final_total_amount`, `final_currency`, `reviewed_by`, `reviewed_at`, `review_notes`.
  6. **Validation** — `matched_supplier` (Link → Supplier), `supplier_match_status`, `purchase_order_reference` (Link → PO), `purchase_receipt_reference` (Link → PR), `purchase_reference_status`, `validation_status`, `validation_result`, `validated_by`, `validated_at`, `validation_source`.
  7. **Promotion** — `purchase_invoice` (Link → Purchase Invoice), `promotion_status`.
  8. **Approval** — `approval_status`, `approval_threshold`, `approval_threshold_source`, `routing_reason`, `assigned_approver_role`, `decision_by`, `decision_at`, `decision_notes`, `payment_readiness`.
  9. **Mock Payment** — `payment_entry` (Link → Payment Entry), `payment_lifecycle_status`, `mock_payment_provider`, `mock_payment_reference`, `mock_payment_status`, `mock_payment_amount`, `mock_payment_issued_at`, `mock_payment_response`.

The DocType is intentionally rich — every step's *evidence* is persisted on the record so the audit trail is the document.

### 6.2 Constants & state-machine vocabulary (from `ap_invoice_capture.py`)

```python
SUPPORTED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg"}

# Capture lifecycle
STATUS_PENDING_REVIEW / UNSUPPORTED / REJECTED / PROPOSED / NEEDS_CORRECTION / CONFIRMED

# OCR sub-state
OCR_STATUS_NOT_EXTRACTED / PROPOSED / CONFIRMED / NEEDS_CORRECTION

# Validation
SUPPLIER_MATCH_NOT_VALIDATED / MATCHED / UNKNOWN / AMBIGUOUS
PURCHASE_REF_NOT_VALIDATED / NON_PO / PURCHASE_ORDER / PURCHASE_RECEIPT
VALIDATION_STATUS_NOT_VALIDATED / VALIDATED / BLOCKED

# Promotion
PROMOTION_STATUS_NOT_PROMOTED / PROMOTED

# Approval
APPROVAL_STATUS_NOT_REQUIRED / AUTO_APPROVED / PENDING_MANAGER / MANAGER_APPROVED / REJECTED
PAYMENT_READINESS_NOT_READY / READY / BLOCKED
AUTO_APPROVAL_THRESHOLD_DEFAULT = 1000.0
MANAGER_APPROVAL_ROLE_DEFAULT   = "Accounts Manager"

# Mock payment lifecycle
PAYMENT_LIFECYCLE_NOT_REQUESTED / CONFIRMED / CLOSED / BLOCKED
MOCK_PAYMENT_PROVIDER       = "mock_payment_provider"
MOCK_PAYMENT_PREFIX         = "MOCK-PAY"
MOCK_CLEARING_ACCOUNT_DEFAULT = "_Test Bank - _TC"

INTAKE_MANUAL_UPLOAD = "Manual ERPNext Upload"
FAKE_OCR_PROVIDER    = "fake-deterministic-v1"
```

Mandatory header fields enforced across the pipeline:

```python
MANDATORY_HEADER_FIELDS = (
    ("supplier",            "proposed_supplier",            "final_supplier"),
    ("supplier_invoice_no", "proposed_supplier_invoice_no", "final_supplier_invoice_no"),
    ("invoice_date",        "proposed_invoice_date",        "final_invoice_date"),
    ("total_amount",        "proposed_total_amount",        "final_total_amount"),
    ("currency",            "proposed_currency",            "final_currency"),
)
```

### 6.3 Custom exceptions

All inherit from `frappe.ValidationError` so they surface as 4xx in the desk/API:

- `AmbiguousSourceError` — a capture has no traceable source file/URL.
- `OCRExtractionError` — extraction tried on an unsupported format or pre-extraction.
- `CaptureValidationError` — validation step preconditions not met.
- `CapturePromotionError` — promotion preconditions not met.
- `CaptureApprovalError` — approval routing/decision rules violated.
- `CapturePaymentError` — mock payment issuance rules violated.

### 6.4 End-to-end pipeline

```
File upload (manual ERPNext upload)
   │
   ▼  create_capture_from_uploaded_file(file_name)        @frappe.whitelist
      → create_capture_from_file()
         - hydrates filename + URL from the linked File
         - requires source_file OR source_file_url + filename
         - extension gating ⇒ supported? status=Pending Review; else status=Unsupported, action_required=1
   │
   ▼  run_fake_extraction_for(capture)                    @frappe.whitelist
      → run_fake_extraction()
         - rejects unsupported formats (OCRExtractionError)
         - filename markers `missing_<field>` / `ambiguous_<field>` / bare `ambiguous`
           drive deterministic simulation of partial OCR proposals
         - SHA-256(filename|url|file-name) seeds supplier/currency/invoice_no/amount/date
         - writes proposed_* fields + ocr_raw_response JSON
         - status ⇒ Proposed, ocr_status ⇒ Proposed, action_required=1
   │
   ▼  confirm_extracted_fields_for(capture, corrections=…, notes=…)   @frappe.whitelist
      → confirm_extracted_fields()
         - merges proposed_* → final_*, overridden by corrections{}
         - records reviewed_by + reviewed_at
         - any mandatory final_* still empty ⇒ status=Needs Correction (action_required=1)
         - all present ⇒ status=Confirmed (action_required=0)
   │
   ▼  validate_for_purchase_invoice_for(capture, source=…)            @frappe.whitelist
      → validate_for_purchase_invoice()
         - requires status==Confirmed
         - _match_supplier: exact `name` or unique `supplier_name`
           (Unknown / Ambiguous never auto-creates a Supplier)
         - _classify_purchase_reference: PR > PO > Non-PO/Not Applicable
         - issues = missing finals ∪ supplier match problems
         - validation_status ⇒ Validated | Blocked
         - records validated_by, validated_at, validation_source
   │
   ▼  promote_to_purchase_invoice_for(capture, defaults={…})          @frappe.whitelist
      → promote_to_purchase_invoice()
         - requires validation_status==Validated AND matched_supplier
         - inserts a draft Purchase Invoice with one header-line item
           (rate = final_total_amount, qty default 1)
         - PO/PR refs deliberately stay on the capture (Phase 1 = header-only)
         - capture.purchase_invoice ⇐ pi.name, promotion_status ⇐ Promoted
   │
   ▼  request_approval_for(capture, threshold=…, source=…)            @frappe.whitelist
      → request_approval()
         - requires Validated + Promoted, and no prior approval routing
         - threshold default 1000.0 (overridable); source label tracked
         - amount ≤ threshold ⇒ approval_status=Auto Approved,
           payment_readiness=Ready, decision_by/decision_at recorded
         - amount > threshold ⇒ approval_status=Pending Manager,
           assigned_approver_role default "Accounts Manager",
           payment_readiness=Not Ready, action_required=1
   │
   ▼  record_manager_decision_for(capture, approve=True|False, notes=…)  @frappe.whitelist
      → record_manager_decision()
         - role-gated via frappe.only_for(capture.assigned_approver_role
           or "Accounts Manager") — denies Accounts User who lacks that role
         - requires approval_status==Pending Manager
         - approve ⇒ Manager Approved, payment_readiness=Ready
         - reject  ⇒ Rejected, payment_readiness=Blocked, action_required=1
   │
   ▼  issue_mock_payment_for(capture, paid_from=…)                    @frappe.whitelist
      → issue_mock_payment()
         - role-gated via frappe.only_for("Accounts Manager")
         - requires is_ready_for_payment(capture)
         - submits PI if still draft
         - PE inserted with ignore_permissions=True (the role gate above is
           the authorization boundary; AP-flow approvals shouldn't require
           per-user PE create rights)
         - get_payment_entry("Purchase Invoice", pi.name, bank_account=…)
         - reference_no = MOCK-PAY-<capture-name>
         - remarks = MOCK_PAYMENT_REMARK
         - inserts + submits PE; writes mock_payment_* fields and JSON response
         - payment_lifecycle_status derived from native state
           (Closed when PI.docstatus=1, PE.docstatus=1, outstanding=0, status=Paid)
   │
   ▼  build_closure_evidence_for(capture)                             @frappe.whitelist
      → build_closure_evidence()
         - assembles {capture, ocr, validation, approval, payment, native} payload
         - native.gl_entries: GL Entry rows for both vouchers
         - native.bank_transaction_count: must be 0 (or "no Bank Transaction doctype")
         - top-level closed: derived from native state (no custom flag)
         - closure_basis: literal explanatory string
```

### 6.5 Read-only helpers (clerk dashboards)

```python
get_ap_lifecycle_rows()       → list view: every capture with action_required, statuses, links to PI/PE
get_manager_approval_queue()  → only captures in approval_status == "Pending Manager"
```

Both are exposed via `@frappe.whitelist`-ed `_for` wrappers (`get_ap_lifecycle_rows_for`, `get_manager_approval_queue_for`).

### 6.6 Auto-progression cascade

The controller wires Frappe's standard lifecycle hooks + the background job
queue to auto-advance a capture through every transition that doesn't
require human judgment. Three pause points:

1. **OCR review** (`status == Proposed`) — the clerk must confirm or
   correct the OCR proposal.
2. **Manual promote** (`validation_status == Validated`) — `promote_to_purchase_invoice`
   needs `company` / `item_code` / etc. defaults that have no source on the
   capture; the cascade stops until a clerk supplies them. A future
   `AP Closed Loop Settings` single doctype will close this seam.
3. **Manager approval** (`approval_status == Pending Manager`) — the
   manager must explicitly approve or reject.

Everything else cascades:

```
after_insert (supported file attached)
    │
    ▼  enqueue → run_fake_extraction_for
Proposed  ⏸ human reviews OCR
    │
    ▼  confirm_extracted_fields_for → cascade
Confirmed
    │
    ▼  enqueue → validate_for_purchase_invoice_for
Validated  ⏸ manual promote (defaults required)
    │
    ▼  promote_to_purchase_invoice_for(defaults=…) → cascade
Promoted
    │
    ▼  enqueue → request_approval_for
    ├── Auto Approved
    │      │
    │      ▼  enqueue → issue_mock_payment_for
    │   Closed
    │
    └── Pending Manager  ⏸ human decides
           │
           ▼  record_manager_decision_for(approve=True|False) → cascade
       Manager Approved → enqueue → issue_mock_payment_for → Closed
       Rejected → blocked (no cascade)
```

Mechanisms used:

| Mechanism | Where | Role |
|---|---|---|
| `after_insert(self)` | controller | Entry point for the first hop (intake → OCR). Fires once. |
| `_kick_next_step(self)` | controller | Inspects state, enqueues the next step, or returns silently at a pause point. |
| `_determine_next_step(self)` | controller | Pure state-machine function returning `(method_name, reason)` or `None`. Each branch encodes the same precondition the corresponding pure function would raise on, so the cascade only enqueues steps that will succeed. |
| `_enqueue_next(self, method, reason)` | controller | Wraps `frappe.enqueue` with `enqueue_after_commit=True`, `deduplicate=True`, and a per-capture-per-step `job_id` so repeat triggers in the same transaction coalesce. |
| Whitelisted `*_for` wrappers | module-level | Each wrapper calls `_kick_next_step()` after the underlying pure function succeeds, joining the cascade. |

### 6.6.1 Test integration of the cascade

The cascade is OPT-IN during tests so Brandon's single-step suite remains
deterministic. Two flags control behavior:

```python
frappe.flags.ap_auto_progress_enabled = True   # enable cascade in tests
frappe.flags.skip_ap_auto_progress    = True   # short-circuit cascade anywhere
```

In production (i.e., `frappe.flags.in_test` is unset), the cascade is on by
default and `skip_ap_auto_progress` is the kill switch.

When the cascade does fire under `in_test`, `frappe.enqueue` is called with
`now=True` so the job runs synchronously within the request — tests don't
depend on a real RQ worker.

### 6.6.2 AP Closed Loop Settings (Single DocType)

`promote_to_purchase_invoice` needs four organization-level values that don't exist on the captured invoice image: `company`, `item_code`, `expense_account`, `cost_center` (plus optional `warehouse` and `uom`). These are GL coding decisions, not invoice data. To avoid prompting the clerk for them every time, the fork adds a Single DocType holding site-wide defaults:

```
erpnext/accounts/doctype/ap_closed_loop_settings/
├── __init__.py
├── ap_closed_loop_settings.json   (issingle: 1, 6 fields, standard Accounts permissions)
└── ap_closed_loop_settings.py     (controller + get_promote_defaults() helper)
```

Fields:

| Fieldname | Type | Required | Purpose |
|---|---|---|---|
| `default_company` | Link → Company | (UI requires) | Buyer entity for the generated Purchase Invoice |
| `default_item_code` | Link → Item | (UI requires) | Catch-all line item ("AP General Expenses") |
| `default_expense_account` | Link → Account | (UI requires) | GL expense account the PI line debits |
| `default_cost_center` | Link → Cost Center | (UI requires) | Cost center allocated to the PI line |
| `default_warehouse` | Link → Warehouse | optional | Used when default Item is a stock item |
| `default_uom` | Link → UOM | optional | Falls back to Item's stock UOM if blank |

Permissions mirror the ERPNext Single-doctype convention:
- System Manager: read + write
- Accounts Manager: read + write
- Accounts User: read only

#### Integration with `promote_to_purchase_invoice`

`_coalesce_defaults` is now a two-layer merge:

1. Settings doctype values (via `get_promote_defaults()` — only non-empty fields contribute)
2. Caller-supplied `defaults` dict (overrides settings on a per-field basis)

Tests that pass explicit `_PROMOTION_DEFAULTS` keep working unchanged (caller's dict still wins). UI promotions can pass `defaults=None` or just the per-invoice overrides; settings fill the rest.

The settings-doctype lookup is wrapped in `try/except` so a missing/uninstalled settings DocType doesn't break tests on stale sites.

### 6.7 Whitelisted endpoints

All endpoints are reachable as `/api/method/erpnext.accounts.doctype.ap_invoice_capture.ap_invoice_capture.<fn>`:

```
create_capture_from_uploaded_file(file_name, source_context=None)
run_fake_extraction_for(capture)
confirm_extracted_fields_for(capture, corrections=None, notes=None)
validate_for_purchase_invoice_for(capture, source=None)
promote_to_purchase_invoice_for(capture, defaults=None)
request_approval_for(capture, threshold=None, source=None)
record_manager_decision_for(capture, approve, notes=None)
issue_mock_payment_for(capture, paid_from=None)
build_closure_evidence_for(capture)
get_ap_lifecycle_rows_for()
get_manager_approval_queue_for()
```

The string-vs-dict normalization in each wrapper (parsing JSON `corrections`/`defaults`, coercing `approve` from `"1"|"true"|"yes"|"approve"`) lets the same surface be called from desk client scripts and external clients.

### 6.8 Tests (`test_ap_invoice_capture.py`)

66 tests covering every state transition, every guardrail, and the auto-progression cascade. The test suite uses `EXTRA_TEST_RECORD_DEPENDENCIES = ["Supplier", "Item", "Cost Center"]` and a `_PROMOTION_DEFAULTS` dict that lines up with the ERPNext `_Test …` fixtures. The `TestAPInvoiceCaptureAutoProgress` class is the cascade suite — it sets `frappe.flags.ap_auto_progress_enabled = True` per-test and asserts pause points (Proposed, Validated, Pending Manager) and resume points (after confirm, after promote, after manager approve). Notable patterns:

- PDF intake uses `pypdf.PdfWriter` to produce a real PDF byte stream → uploaded via Frappe's `File` doctype → fed to `create_capture_from_file`.
- Simulated-failure paths use filename markers (`missing_supplier_…pdf`, `ambiguous_invoice_date_…pdf`, bare `ambiguous_…pdf`).
- Closure assertions check the *native* state: `Purchase Invoice.docstatus == 1`, `outstanding_amount == 0`, `status == "Paid"`, `Bank Transaction Payments` count for the PE is 0.
- Negative tests assert each custom exception fires for the intended precondition violation.

---

## 7. Modified Upstream Files

### 7.1 `erpnext/setup/utils.py`

2-line readability refactor inside `_enable_all_roles_for_admin`:

```diff
-    all_roles = set(frappe.db.get_values("Role", pluck="name"))
+    all_roles = set(frappe.get_all("Role", pluck="name"))
     admin_roles = set(
-        frappe.db.get_values("Has Role", {"parent": "Administrator"}, fieldname="role", pluck="role")
+        frappe.get_all("Has Role", filters={"parent": "Administrator"}, pluck="role")
     )
```

Semantically equivalent — `frappe.get_all` is the preferred, higher-level helper and standardizes the call style across the two enumerations. Unrelated to AP Closed Loop functionality; best read as incidental cleanup.

### 7.2 `erpnext/tests/utils.py`

1-line fix to `BootStrapTestData.make_records` so the test bootstrap is idempotent on sites where ERPNext's standard records already exist:

```diff
     for x in records:
         filters = get_filters(x)
         if not frappe.db.exists(doctype, filters):
-            frappe.get_doc(x).insert()
+            frappe.get_doc(x).insert(ignore_if_duplicate=True)
```

`frappe.db.exists(dt, dict)` returns a false negative when the filter dict includes the autoname source field alongside other filters (observed with `Price List` + `{"price_list_name": …, "enabled": 1, …}`). Without this guard, `bench run-tests` raises `DuplicateEntryError` on a previously-used site before any test executes. The `ignore_if_duplicate=True` flag swallows the duplicate insert, matching the function's "create if missing" intent.

---

## 8. What This Fork Deliberately Does NOT Do

- **Does not** create or modify Purchase Invoice, Payment Entry, Bank Transaction, or GL Entry behavior.
- **Does not** auto-create Suppliers — unknown suppliers must be corrected by AP staff.
- **Does not** attach the capture's PO/PR reference to Purchase Invoice line rows — Phase 1 is header-only; the reference remains auditable on the capture.
- **Does not** wire any UI / desk button — every action is invoked via `@frappe.whitelist` RPC. Desk client scripts and a workspace will be Phase 2.
- **Does not** integrate with any real OCR provider — `FAKE_OCR_PROVIDER = "fake-deterministic-v1"` is hash-based and reproducible.
- **Does not** integrate with any real payment provider — `MOCK_PAYMENT_PROVIDER = "mock_payment_provider"` and every Payment Entry it creates carries the `MOCK-PAY-…` prefix and the explicit "Not bank reconciled. No real banking integration." remark.
- **Does not** record a custom `closed` flag — closure is always derived from the native ERPNext PI + PE state.

---

## 9. How to Run the Fork's Tests

From a `bench` that has this app installed against a test site:

```bash
# Walking skeleton (deterministic end-to-end happy path)
bench --site <test-site> run-tests \
    --module erpnext.accounts.ap_closed_loop.test_walking_skeleton

# Full AP Invoice Capture pipeline + all state-machine guardrails
bench --site <test-site> run-tests \
    --module erpnext.accounts.doctype.ap_invoice_capture.test_ap_invoice_capture
```

Both rely on the upstream `before_tests` bootstrap (`erpnext.setup.utils.before_tests`) for `_Test Company`, `_Test Supplier`, `_Test Item`, `_Test Cost Center - _TC`, `_Test Bank - _TC`, `_Test Warehouse - _TC`, and `_Test Account Cost for Goods Sold - _TC`. Each test rolls back in `tearDown`, so the suite is reentrant.

---

## 10. MCP Server (`erpnext/mcp/`)

> **Status (2026-05-28):** built on branch `russ/mcp-server` (off `russ/migrateToV16`). v1 = AP-only, **read-only**. Plan: `docs/planning/mcp-server-plan.md`. Decision record: `docs/changes/ADR-MCP-5-vendor-frappe-mcp-transport.md`.

A secure, audit-logged, permission-respecting **Model Context Protocol** server that lets an LLM client (Claude Desktop, MCP Inspector) query AP data over JSON-RPC. Authenticated with Frappe v16's **native** OAuth 2.x (RFC 9728/8414/7591/PKCE — no shims needed on v16); audience binding (RFC 8707) is the one OAuth check we add ourselves.

### 10.1 Module map

| File | Role |
|---|---|
| `endpoint.py` | The ONLY HTTP route (`/api/method/erpnext.mcp.endpoint.handle_mcp`). L1 (Origin / `MCP-Protocol-Version` / TLS), auth, pre-dispatch scope gate, then delegates JSON-RPC to the vendored transport. |
| `auth.py` | One auth utility: validate v16 OAuth Bearer token (status + expiry), bind audience, `frappe.set_user`. No token passthrough. |
| `audience.py` | RFC 8707 audience binding against `MCP Settings.oauth_resource_uri`. |
| `audit.py` | `safe_execute` funnel: per-(user,tool) rate-limit + concurrency cap, run, then write exactly one `MCP Audit Log` row (args sanitized twice). |
| `permissions.py` | The "permitted names" idiom — `get_list(...).pluck("name")` then constrain `qb` joins. |
| `registry.py` | Per-request `MCP` instance (no module-level singleton); registers only the caller's visible tools; `assert_can_call` 403 gate. |
| `config.py` | Cached accessors for `MCP Settings` (Single) and `MCP Tool Config` rows. |
| `tools/` | `BaseTool` (Pydantic input/output → JSON Schema), `_scope.py` (visibility), and the 5 AP tools. |
| `install.py` / `tasks.py` | `after_migrate` seeds Tool Config rows; daily scheduler prunes the audit log. |
| `_vendor/frappe_mcp/` | Vendored `frappe/mcp` @ `0ea7d0e` (MIT). Transport + JSON-RPC dispatch only. One lazy-import patch (see `_vendor/PROVENANCE.md`). |

### 10.2 New DocTypes (module `MCP`)

- **`MCP Settings`** (Single) — master switch, Origin allowlist, allowed protocol versions, audit retention/size caps, OAuth resource URI. System Manager only.
- **`MCP Tool Config`** (one row per tool) — enable/disable kill switch, required role, required OAuth scope, rate limit, concurrency cap, timeout. Seeded idempotently by `after_migrate`.
- **`MCP Audit Log`** (immutable) — one row per `tools/call`; row-level scoped via `permission_query_conditions` (System Manager + Auditor see all; users see their own).

### 10.3 v1 tools (read-only)

`list_ap_invoices`, `get_ap_invoice`, `list_vendors`, `get_vendor_balance`, `get_doctype_meta` (allowlisted DocTypes only). Each declares a Pydantic input/output model, an OAuth scope, `readOnlyHint` annotations, and ships with permission-regression tests.

### 10.4 hooks.py additions

```python
after_migrate = ["erpnext.mcp.install.sync_tool_configs"]
permission_query_conditions = {"MCP Audit Log": "erpnext.mcp.doctype.mcp_audit_log.mcp_audit_log.get_permission_query_conditions"}
scheduler_events["daily"] += ["erpnext.mcp.tasks.prune_audit_logs"]
```

### 10.5 Running the MCP tests

```bash
# DB-free unit tests (canaries, schema, sanitization, auth, scope) — fast:
bench --site <test-site> run-tests --module erpnext.mcp.tests.test_canaries
bench --site <test-site> run-tests --module erpnext.mcp.tests.test_tools
bench --site <test-site> run-tests --module erpnext.mcp.tests.test_audit
bench --site <test-site> run-tests --module erpnext.mcp.tests.test_auth
bench --site <test-site> run-tests --module erpnext.mcp.tests.test_registry
# Integration (need a site): dispatcher round-trip + permission regression:
bench --site <test-site> run-tests --module erpnext.mcp.tests.test_dispatcher
bench --site <test-site> run-tests --module erpnext.mcp.tests.test_permissions
```

### 10.6 What v1 deliberately does NOT do

- **No write tools** (no create/submit/cancel/delete) — deferred to Phase 3 with elicitation.
- **No `run_python_code`-style tool** — out of scope permanently (attack surface).
- **No `sampling/`, `resources/`, `prompts/`** — server never calls back into the client LLM (enforced by a CI canary).
- **No new Desk navigation** — no UI-SITEMAP change in v1.

---

## 11. Spec 01 — AP Closed Loop Foundations (Settings, Idempotency, Async Runner)

> **Status (2026-05-31):** implemented + tested on `russ/migrateToV16` (working tree). First slice of the v2 workflow build — see `docs/spec/01-foundations-settings-async-idempotency.md`. All 17 acceptance criteria green; **22 new automated tests** pass, and the existing **66-test `AP Invoice Capture` suite passes unchanged** (run under the Fake OCR provider — see the test-plan note below).

Cross-cutting foundation every later v2 step builds on: a single settings backbone, document-level idempotency, and a step-aware async runner. Stream-agnostic; **zero behaviour change on an unconfigured site.**

```
 erpnext/accounts/doctype/ap_posting_ledger/__init__.py                           |    0
 erpnext/accounts/doctype/ap_posting_ledger/ap_posting_ledger.json                |  NEW DocType — idempotency ledger; UNIQUE idempotency_key; autoname field:idempotency_key
 erpnext/accounts/doctype/ap_posting_ledger/ap_posting_ledger.py                  |  controller (auto-typed, no logic)
 erpnext/accounts/ap_closed_loop/idempotency.py                                   |  generate_key (sha256 of capture+step ONLY) + with_idempotency (double-post guard)
 erpnext/accounts/ap_closed_loop/async_runner.py                                  |  enqueue_step (queue selection) + _dispatch_step (RetryBackgroundJobError | delayed re-enqueue | dead-letter) + RetryLaterError
 erpnext/accounts/ap_closed_loop/install.py                                       |  install_ap_defaults (after_migrate; backfills Single defaults, blank-only, idempotent)
 erpnext/accounts/ap_closed_loop/tests/{__init__,test_idempotency,test_async_runner,test_install}.py | 16 new tests
 erpnext/accounts/doctype/ap_closed_loop_settings/ap_closed_loop_settings.json    |  +/- thresholds_section, sod_section, clearing_accounts_section + 3 reserved collapsible sections; 7 new fields
 erpnext/accounts/doctype/ap_closed_loop_settings/ap_closed_loop_settings.py      |  +/- get_auto_post_threshold / get_dedupe_window_days / get_confidence_threshold / get_field_threshold / get_sod_config
 erpnext/accounts/doctype/ap_closed_loop_settings/test_ap_closed_loop_settings.py |  +/- TestFoundationGetters (6 tests)
 erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.py                |  +/- _resolve_approval_threshold reads settings; _enqueue_next delegates to async_runner.enqueue_step; _run_cascade_step is now a back-compat alias to _dispatch_step
 erpnext/hooks.py                                                                 |  +1 after_migrate entry: install_ap_defaults
 test/testplans/ap-foundations-settings-async-idempotency.md                      |  clean-room runbook
```

**Decisions locked (spec §8):** idempotency key = `sha256(capture, step)` ONLY, never `settings.modified` (**D9** — the double-post guarantee); `ocr_confidence_threshold` stays the single canonical confidence scalar (**D1**); `field:idempotency_key` autoname (**D3**); `_run_cascade_step` retained as an alias for one release (**D4**); phase-1 retry uses native `RetryBackgroundJobError` for immediate transients + immediate re-enqueue for delayed backoff (**D5**); defaults install via `after_migrate` (**D2**). `AUTO_APPROVAL_THRESHOLD_DEFAULT=1000.0` retained as the empty-settings fallback.

**Test-environment note (important):** the existing `test_ap_invoice_capture` suite calls `run_fake_extraction_for`, which is now settings-driven (`run_fake_extraction = run_extraction`). It is deterministic **only when `AP Closed Loop Settings.ocr_provider = "Fake (Deterministic)"`** (the default). On a site configured for `Anthropic Claude` the suite invokes the real provider and fails non-deterministically — pin the Fake provider (or set it in the suite's `setUp`) before running. This is a pre-existing isolation gap in that suite, surfaced — not introduced — by this slice.

---

## 12. Spec 02 — Intake & Stream Tagging (Receipt vs Invoice)

> **Status (2026-05-31):** implemented + tested on `russ/migrateToV16` (working tree). Second slice of the v2 build — see `docs/spec/02-intake-stream-tagging.md`. All 15 acceptance criteria green; **20 new automated tests** pass; the spec-01 suites and the 66-test capture suite pass unchanged (capture suite under the Fake OCR provider).

Owns the **stream concept**: tags every `AP Invoice Capture` at intake as Stream R (Receipt) / Stream I (Invoice) / Unclassified, starts the 72h SimpleFIN SLA clock on Stream R, and adds the email / mobile intake adapters + a Phase-3 portal-pull base.

```
 erpnext/accounts/doctype/ap_stream_rule/{__init__,ap_stream_rule}.py + .json    | NEW child DocType — data-driven Receipt/Invoice rule rows (priority/signal/pattern/assign_stream/enabled)
 erpnext/accounts/ap_closed_loop/portal_pull.py                                  | NEW — PortalPullAdapter ABC + register/get_portal_adapter registry (Phase-3 seam; no concrete adapter)
 erpnext/accounts/ap_closed_loop/tests/{test_stream_tagging,test_portal_pull}.py | 19 new tests
 erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.json             | +/- intake_classification_section + stream / stream_provisional_source / stream_revised_from / sla_due_at; intake_channel +3 options
 erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.py               | +/- classify_stream_at_intake (pure); _apply_stream_tag in validate(); create_capture_from_file +sender_domain/body_text; create_capture_from_uploaded_file +intake_channel; create_capture_from_email + handle_inbound_ap_communication
 erpnext/accounts/doctype/ap_closed_loop_settings/ap_closed_loop_settings.json    | +/- fill stream_rules_section: stream_rules (Table) + ap_intake_email_account (Link)
 erpnext/accounts/doctype/ap_closed_loop_settings/ap_closed_loop_settings.py      | +/- get_stream_rules() accessor + 1 test (get_stream_rules)
 erpnext/accounts/ap_closed_loop/install.py                                       | +/- _seed_stream_rules() (4 default rules, blank-only)
 erpnext/hooks.py                                                                 | +1 Communication.after_insert: handle_inbound_ap_communication (no-op unless ap_intake_email_account set)
 test/testplans/{intake-stream-tagging,intake-email-inbound}.md                   | clean-room runbooks
```

**Design notes / decisions (spec §8):** the rule table is a child DocType so non-engineers tune classification with no code change (OD-1); `body` patterns are regex, others substring/glob (OD-2); 4 seed rules ship (OD-3); sender/body reach the classifier as transient, **never-persisted** attrs (OD-4, privacy); email re-fire is guarded per-`source_file` (OD-5); the AP intake Email Account is a Settings Link, **off when empty** (OD-6); unsupported email attachments are skipped (OD-7). Native `Email Account.append_to` was considered and rejected (1:1; this slice needs one-email→many-captures fan-out + per-attachment filtering); native `Assignment Rule` was considered (it can't write a derived field); Phase-2 queue priority will reuse native `ToDo.priority` (OD-8).

**Net effect:** one new child DocType (`AP Stream Rule`), one new module (`portal_pull.py`), `AP Invoice Capture` gains 4 stream fields + 3 intake channels + the email-in adapter, `AP Closed Loop Settings` fills its reserved stream section, and the global `Communication.after_insert` hook is **off by default** (a no-op until an operator sets `ap_intake_email_account`).

## 13. Spec 03 — Pre-Extraction Deduplication (exact + perceptual)

> **Status (2026-05-31):** implemented + tested on `russ/migrateToV16` (working tree). Third slice of the v2 build — see `docs/spec/03-deduplication.md`. All 13 acceptance criteria green this session; **14 new automated tests** pass (13 in the capture suite, 1 in the settings suite); the capture suite is now **79 tests OK** (was 66) and the settings suite **16 OK** (was 15), both under the Fake OCR provider; spec-01 (`async_runner` 6 / `install` 3 / `idempotency` 7) and spec-02 (`stream_tagging` 17 / `portal_pull` 2) suites pass unchanged.

The **firewall against double-booking**: every freshly-intaken capture is checked against the last 90 days for an **exact file-hash** re-upload and a **perceptual near-duplicate** (re-scan) *before* any billable OCR runs. Stream-agnostic — keys only on bytes/pixels + `received_at`, never on `stream`.

```
 erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.json             | +/- dedupe_section + content_hash (Data, search_index, NOT unique) / perceptual_hash (Data, search_index) / duplicate_of (Link self) / duplicate_detected_at (Datetime); status +Duplicate
 erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.py               | + STATUS_DUPLICATE; detect_duplicates_for / run_dedupe_for (whitelisted) / _compute_phash / _phash_distance / _dedupe_checked; Step 0 (pre-OCR dedupe) in _determine_next_step; content_hash copied from File in _hydrate_from_linked_file
 erpnext/accounts/doctype/ap_closed_loop_settings/ap_closed_loop_settings.json    | +/- dedupe_section + dedupe_enabled (Check, 1) / dedupe_phash_max_distance (Int, 6); relocated dedupe_window_days into it
 erpnext/accounts/doctype/ap_closed_loop_settings/ap_closed_loop_settings.py      | + get_dedupe_config() {enabled, window_days, phash_max_distance}
 erpnext/accounts/ap_closed_loop/async_runner.py                                  | +1 QUEUE_BY_STEP: run_dedupe_for -> short
 erpnext/accounts/ap_closed_loop/install.py                                       | +2 backfill defaults: dedupe_enabled=1, dedupe_phash_max_distance=6
 erpnext/accounts/doctype/ap_invoice_capture/test_ap_invoice_capture.py          | +13 tests (TestAPInvoiceCaptureDedup x11, TestAPInvoiceCaptureDedupCascade x2)
 erpnext/accounts/doctype/ap_closed_loop_settings/test_ap_closed_loop_settings.py | +1 test (get_dedupe_config)
 pyproject.toml                                                                   | +imagehash, +pdf2image (NEW pip deps); poppler-utils is a NEW *system* dep (worker host) — degrades gracefully when absent
 test/testplans/pre-extraction-dedup.md                                          | clean-room runbook
```

**Design notes / decisions (spec §8):** the exact key is the **MD5 `content_hash` copied from Frappe's `File`** (never recomputed; per upstream `frappe/core/doctype/file/utils.py:get_content_hash`), so `content_hash` / `perceptual_hash` must be fieldtype **Data** for the `search_index` to emit a real DB index (a `text`/`longtext` column silently drops it). `content_hash` is **NOT unique** — a legitimate duplicate is a *second row* with the same hash, flagged and surfaced rather than rejected at insert. An **exact hit** sets `status=Duplicate` (terminal; the existing `_determine_next_step` status guard stops the cascade — no OCR cost) + `duplicate_of` = the **oldest** matching original (`received_at asc, limit 1`). A **perceptual suspect** (Hamming distance ≤ `dedupe_phash_max_distance`, default 6) only sets `action_required` and stays `Pending Review` so it still gets OCR'd (D1=(b)); a human (and the follow-on body-text fingerprint, D2) confirms. Dedupe runs as a **Step-0 async cascade hop** before OCR (D4); the `duplicate_detected_at` stamp is the single idempotency flag (D5). `_compute_phash` (first-page-only, 150 DPI; D7) **never raises** — when poppler/imagehash is absent it returns `None` and dedupe **degrades to exact-only**, so intake never stalls (AC-03-8). Native `PurchaseInvoice` duplicate control (`check_supplier_invoice_uniqueness`, **off by default**) is **complementary**, not a substitute (different key — parsed `bill_no` vs raw bytes; different timing — post-OCR at PI insert vs pre-OCR at intake; different window — per-fiscal-year vs 90-day); the pilot is **recommended to enable it** as a second promote-time firewall.

**Net effect:** `AP Invoice Capture` gains 4 read-only dedupe audit fields + a `Duplicate` terminal status; `AP Closed Loop Settings` gains a dedupe config section (kill switch + window + pHash distance); a new pre-OCR Step-0 hop runs on every supported-file intake; two NEW pip deps (`imagehash`, `pdf2image`) and one NEW **system** dep (`poppler-utils`, the #1 deploy risk) — all **non-blocking** because the perceptual pass degrades to exact-hash-only when they are absent.
