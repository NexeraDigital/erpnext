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
 test/testplans/ocr/phase0-ai-provider-settings.md                                    |  ~280 ++ (external-instance test plan)
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
 test/testplans/ocr/phase1-adapter.md                                             |  ~200 ++ (external-instance test plan)
```

OCR Phase 2 — Anthropic Claude extractor (real OCR):

```
 pyproject.toml                                                                   |    +1 (anthropic>=0.40.0 dependency)
 erpnext/accounts/ap_closed_loop/extractors/anthropic.py                          |  ~290 (AnthropicExtractor: file read, doc/image block, forced tool use, ExtractionResult mapping, smoke_test)
 erpnext/accounts/ap_closed_loop/extractors/registry.py                           |    +/- (register "anthropic")
 erpnext/accounts/ap_closed_loop/extractors/test_anthropic.py                     |  ~230 (14 mocked unit tests + 1 opt-in live test)
 test/testplans/ocr/phase2-real-ocr-anthropic.md                                             |  ~250 ++ (external-instance test plan)
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
 test/testplans/ocr/phase3-settings.md                                           |  ~180 ++ (external-instance test plan)
```

After Phase 3: an operator sets **AP Closed Loop Settings → OCR Provider = Anthropic Claude** (with a key in **AI Provider Settings**) and the live capture cascade calls Claude. Default remains **Fake (Deterministic)** so an unconfigured site makes no API calls. The `anthropic_api_key` lives only on `AI Provider Settings` (System Manager); AP Managers choose the provider but cannot see the credential.

OCR Phase 4 — low-confidence fallback (Haiku → Sonnet):

```
 erpnext/accounts/ap_closed_loop/extractors/anthropic.py                         |    +/- (one-shot fallback: retry once with ocr_fallback_model when a required field is missing/ambiguous; raw_response records outcome + model)
 erpnext/accounts/doctype/ap_closed_loop_settings/ap_closed_loop_settings.py     |    +/- (get_ocr_config returns fallback_model)
 erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.py               |    +/- (run_extraction forwards fallback_model)
 erpnext/accounts/ap_closed_loop/extractors/test_anthropic.py                    |    +/- (5 mocked fallback tests; 23 total)
 test/testplans/ocr/phase4-fallback.md                                           |  ~150 ++ (external-instance test plan)
```

Phase 4 behaviour: the primary model (default Haiku) handles every invoice; only when it can't confidently read a required field does the extractor retry **once** with `ocr_fallback_model` (e.g. Sonnet). At most one retry — no looping, no Opus escalation. Empty fallback model = disabled (the default). On the synthetic corpus Haiku already scores 100%, so fallback's value is on messy real-world invoices.

OCR Phase 5 — audit logging & cost tracking (via Integration Request):

```
 erpnext/accounts/ap_closed_loop/extractors/pricing.py                           |  ~70 (per-model token rate table + estimate_cost_usd)
 erpnext/accounts/ap_closed_loop/extractors/audit.py                             |  ~120 (write_integration_request + sanitize; never logs the key)
 erpnext/accounts/ap_closed_loop/extractors/anthropic.py                         |    +/- (accumulate per-call usage + total latency_ms into raw_response)
 erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.py               |    +/- (run_extraction logs Completed/Failed Integration Request for the real provider)
 erpnext/accounts/ap_closed_loop/extractors/test_audit.py                        |  ~190 (11 tests: pricing, sanitize, IR write, run_extraction integration)
 test/testplans/ocr/phase5-audit.md                                              |  ~150 ++ (external-instance test plan)
```

Phase 5 behaviour: each real extraction (and failure) is recorded as a Frappe **`Integration Request`** (`integration_request_service="anthropic"`, referenced to the capture) with model(s), per-call + total token usage, estimated USD cost, latency, outcome, and a sanitized error on failure. The fake provider is not logged (no call, no cost). API keys are never persisted in any field. Operators view the trail at `/app/integration-request` filtered by service. Verified live: one extraction → `Completed` row, real tokens/cost/latency, no key leak.

OCR Phase 6 — production hardening (retry + circuit breaker + size guard + non-silent failures):

```
 erpnext/accounts/ap_closed_loop/extractors/circuit.py                            |  ~75 (process-local CircuitBreaker + CircuitOpenError + shared_breaker)
 erpnext/accounts/ap_closed_loop/extractors/anthropic.py                          |    +/- (_call_model: breaker.check + retry-with-backoff on 429/5xx/timeout/conn, honour Retry-After, never retry 400; _classify_exception, _backoff_seconds, _parse_retry_after; injectable sleep/breaker, max_retries ctor arg)
 erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.py               |    +/- (_source_file_size_bytes; run_extraction enforces ocr_max_file_mb pre-flight for real providers + surfaces any failure on the capture via action_required + reason)
 erpnext/accounts/ap_closed_loop/extractors/test_hardening.py                     |  ~310 (16 tests: classify, backoff, breaker, retry loop, size-guard, failure surfacing)
 test/testplans/ocr/phase6-hardening.md                                          |  ~180 ++ (external-instance test plan)
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
 test/testplans/specs/01-foundations-settings-async-idempotency.md                      |  clean-room runbook
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
 test/testplans/specs/03-deduplication.md                                          | clean-room runbook
```

**Design notes / decisions (spec §8):** the exact key is the **MD5 `content_hash` copied from Frappe's `File`** (never recomputed; per upstream `frappe/core/doctype/file/utils.py:get_content_hash`), so `content_hash` / `perceptual_hash` must be fieldtype **Data** for the `search_index` to emit a real DB index (a `text`/`longtext` column silently drops it). `content_hash` is **NOT unique** — a legitimate duplicate is a *second row* with the same hash, flagged and surfaced rather than rejected at insert. An **exact hit** sets `status=Duplicate` (terminal; the existing `_determine_next_step` status guard stops the cascade — no OCR cost) + `duplicate_of` = the **oldest** matching original (`received_at asc, limit 1`). A **perceptual suspect** (Hamming distance ≤ `dedupe_phash_max_distance`, default 6) only sets `action_required` and stays `Pending Review` so it still gets OCR'd (D1=(b)); a human (and the follow-on body-text fingerprint, D2) confirms. Dedupe runs as a **Step-0 async cascade hop** before OCR (D4); the `duplicate_detected_at` stamp is the single idempotency flag (D5). `_compute_phash` (first-page-only, 150 DPI; D7) **never raises** — when poppler/imagehash is absent it returns `None` and dedupe **degrades to exact-only**, so intake never stalls (AC-03-8). Native `PurchaseInvoice` duplicate control (`check_supplier_invoice_uniqueness`, **off by default**) is **complementary**, not a substitute (different key — parsed `bill_no` vs raw bytes; different timing — post-OCR at PI insert vs pre-OCR at intake; different window — per-fiscal-year vs 90-day); the pilot is **recommended to enable it** as a second promote-time firewall.

**Net effect:** `AP Invoice Capture` gains 4 read-only dedupe audit fields + a `Duplicate` terminal status; `AP Closed Loop Settings` gains a dedupe config section (kill switch + window + pHash distance); a new pre-OCR Step-0 hop runs on every supported-file intake; two NEW pip deps (`imagehash`, `pdf2image`) and one NEW **system** dep (`poppler-utils`, the #1 deploy risk) — all **non-blocking** because the perceptual pass degrades to exact-hash-only when they are absent.

## 14. Spec 04 — Extraction: Numeric Per-Field Confidence + Line Items

> **Status (2026-05-31):** implemented + tested on `russ/migrateToV16` (working tree). Fourth slice of the v2 build — see `docs/spec/04-extraction-confidence-line-items.md`. All 15 acceptance criteria green this session; **15 new automated tests** pass; capture suite now **88 OK** (was 81 — includes 2 added for the tax-aware reconciliation fix below), extractors **19 OK** (was 15), anthropic **26 OK** (was 23), settings **17 OK** (was 16); hardening/audit/integration (16/11/5) and spec-01/02/03 suites pass unchanged. A real-Anthropic e2e on `invoice_01.pdf` confirmed header + per-field confidence + 2 line items extracted correctly, and surfaced the tax-reconciliation bug now fixed.

Stops **discarding** the per-field confidence the Anthropic tool already returns, and adds **line-item extraction**. Two new child tables persist the numeric scores (the routing/query index for spec 09) and the extracted lines (the join surface for spec 08 and the Stream-R JE path); promote becomes **line-aware** with a totals-reconciliation guard.

```
 erpnext/accounts/doctype/ap_invoice_capture_confidence/{__init__,ap_invoice_capture_confidence}.py + .json | NEW child DocType (istable) — field_name / confidence (Float) / is_above_threshold (Check, derived) / score_source (Model|Derived-Mapping)
 erpnext/accounts/doctype/ap_invoice_capture_item/{__init__,ap_invoice_capture_item}.py + .json             | NEW child DocType (istable) — mirrors Purchase Invoice Item (description/qty/rate/amount/tax_amount/expense_account/cost_center/po_reference/pr_reference/currency/confidence_summary)
 erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.json                                       | +/- extraction_detail_section + subtotal_amount/tax_amount (Currency, options=proposed_currency so they display in the extracted currency like the line items, not the pre-review-empty final_currency) + line_items (Table) + field_confidences (Table)
 erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.py                                         | +/- run_extraction write-back (_write_extraction_detail / _resolve_above / _base_field / _existing_link); promote_to_purchase_invoice line-aware branch + reconciliation guard; ocr_raw_response gains confidence/lines (no creds)
 erpnext/accounts/ap_closed_loop/extractors/base.py                                                        | +/- ExtractionResult gains confidence / lines / score_sources (default factories)
 erpnext/accounts/ap_closed_loop/extractors/anthropic.py                                                   | +/- tool schema (subtotal/tax_total/po_reference + line_items array); _to_extraction_result keeps numeric scores + emits lines + line_<i>_<field> keys + mapping fallback
 erpnext/accounts/ap_closed_loop/extractors/fake.py                                                        | +/- derives confidence (missing 0.0 / ambiguous 0.5 / clear 0.95), all Derived-Mapping; lines stay []
 erpnext/accounts/doctype/ap_closed_loop_settings/ap_closed_loop_settings.py                               | +/- get_ocr_config surfaces field_thresholds (parsed dict)
 test_*.py across extractors / settings / ap_invoice_capture                                               | +13 tests (AC-04-1..15)
 test/testplans/{extraction-per-field-confidence,extraction-line-items-promote}.md                        | clean-room runbooks
```

**Design notes / decisions (spec §8):** the per-field threshold reuses spec-01's `field_thresholds` + the canonical `ocr_confidence_threshold` — **no second scalar** was added (honoring locked gating decision #4); `_resolve_above` resolves `field_thresholds[base] → confidence_threshold`, with `line_<i>_<field>` keys stripped to their base field (D2). Child table vs `ocr_raw_response` JSON is a deliberate split: **child table = filterable/reportable routing surface; JSON = immutable audit-of-record** (the same numbers land in both). `score_source` distinguishes a real `Model` number from a `Derived-Mapping` stand-in so spec-09 routing never over-trusts a fallback (D3). Promote reconciliation **surfaces** a line/total mismatch (>0.01) as `CapturePromotionError` + `action_required` rather than silently mutating the ledger (D1). The check is **tax-aware** — a real-Anthropic e2e on a 19%-VAT invoice showed lines sum to the *pre-tax subtotal* while `final_total_amount` is *tax-inclusive*, so it accepts either `sum(lines) == total` (tax-inclusive lines) **or** `sum(lines) + tax_amount == total` (pre-tax lines + separate tax); a genuine misread reconciles under neither and still raises. line item identity uses the default `item_code` + the extracted description (D4); the child `tax_amount` is plain `Currency` bound to the capture currency, deferring company-currency conversion to promote (D5). All Link writes (`po_reference`/`pr_reference`/`expense_account`/`cost_center` + the header PO) are guarded with `frappe.db.exists` so a hallucinated OCR string never creates a dangling Link. The cascade shape is **unchanged** — the write-back runs inside the already-enqueued `run_extraction` job; the header-line promote fallback is byte-for-byte preserved for captures with no lines.

**Net effect:** `AP Invoice Capture` gains two child grids (line items + per-field confidence) and surfaced subtotal/tax; the Anthropic extractor stops throwing away the scores it already computes and now reads line items; promote maps one capture line → one PI item (Stream I) with a reconciliation guard; `get_ocr_config` gains `field_thresholds`. No new DocTypes beyond the two child tables, no new posting logic, no cascade-shape change.

## 15. AI Chat Panel — context-aware desk assistant (read-only v1)

> **Status (2026-06-01):** backend committed in `96dea75d5e` (`feat(ai-chat): backend for context-aware desk AI chat panel (read-only v1)`); the **front-end UI + `hooks.py` mount** land in this slice on `russ/migrateToV16`. Plan: `docs/planning/ai-chat-panel-plan.md`; completion plan: `docs/planning/ai-chat-panel-completion-plan.md`. v1 = **read-only**, consumes the existing §10 MCP tool catalogue **in-process** as the signed-in desk user.

A global, slide-over **chat panel** on every desk page. The user types a question ("summarize this invoice", "what's this vendor's balance?"); a **server-side Claude tool loop** answers it by calling the §10 MCP read tools **as the signed-in user** (no OAuth token minted — the desk session is the credential), streaming the reply back over Socket.IO. The panel is **context-aware**: it tells the backend which record the user is viewing, and the backend **re-validates + re-fetches** that record under the user's own permissions before grounding the model on it.

### 15.1 Backend (committed `96dea75d5e` — `erpnext/ai/chat/`)

```
 erpnext/modules.txt is unchanged (chat lives under the existing AI module)
 erpnext/ai/chat/__init__.py                                                     |    0
 erpnext/ai/chat/boot.py                                                         |   ~40 (extend_bootinfo: frappe.boot.ai_chat_enabled; true for non-Guest when MCP is enabled; never decrypts the key)
 erpnext/ai/chat/api.py                                                          |  ~155 (whitelisted: start_turn / get_conversation / list_conversations / clear_conversation; per-user rate limit; owner-scoped)
 erpnext/ai/chat/agent.py                                                        |  ~420 (run_turn: enqueued Claude tool loop; in-process MCP dispatch via audit.safe_execute; realtime streaming; prompt-injection-hardened system prompt; key fetched per-turn, never logged)
 erpnext/ai/chat/context.py                                                      |  ~135 (resolve_context: has_permission(throw=True) forged-context guard + server re-fetch + apply_fieldlevel_read_permissions; client field values discarded)
 erpnext/ai/chat/tests/test_chat.py                                              |  10 IntegrationTestCase tests (owner-scoping, rate limit, forged-context PermissionError, mocked tool loop, missing-key error)
 erpnext/ai/doctype/ai_chat_conversation/*                                       |  NEW DocType — owner-scoped thread (title, context_doctype/name, last_active); if_owner read/write
 erpnext/ai/doctype/ai_chat_message/*                                            |  NEW DocType — owner-scoped turn (role User|Assistant, content, model, tools_invoked, input/output_tokens, latency_ms, error, context_doctype/name)
 erpnext/hooks.py                                                                |  +1 extend_bootinfo: erpnext.ai.chat.boot.boot_session
```

**Turn flow (`agent.run_turn`, enqueued by `api.start_turn`):** the turn runs in a **background job as the enqueuing desk user** (`frappe.enqueue(..., user=user)`), never on the web worker — no held-open request. Each Claude tool call is dispatched through **`erpnext.mcp.audit.safe_execute`**, so the MCP rate-limit, concurrency cap, per-tool `MCP Tool Config` role/enable gate, Frappe RBAC inside each tool, and the immutable `MCP Audit Log` row **all apply identically to an external MCP client** — but as the desk user. The loop is bounded (`_MAX_TOOL_ITERATIONS = 6`, `_MAX_OUTPUT_TOKENS = 1500`). The answer streams to the user's room as `frappe.publish_realtime("ai_chat:<conversation>", …)` events — the **Raven-validated pattern; no SSE, no held-open worker**.

**Security invariants (do not weaken):**
- **Read-only.** Only the five §10 read tools are reachable; the system prompt states the model cannot modify/create/send/delete anything.
- **Runs as the user.** Every tool executes under `frappe.session.user`'s permissions — never Administrator/service account. The `test_chat` suite proves a forged context for a record the user can't read raises `PermissionError`.
- **Context is a hint, never authority.** Browser-supplied `{doctype, name, view}` is re-validated (`has_permission(..., "read", doc=name, throw=True)`) and **re-fetched server-side** (`apply_fieldlevel_read_permissions` strips permlevel-masked fields); the browser's own field values are discarded.
- **Key stays server-side.** The Anthropic key is fetched per-turn via `get_ai_credentials`, held only for the API call, never logged/published/stored; `_sanitize` scrubs any `sk-…` substring from user-visible errors.
- **Prompt-injection hardened.** The system prompt instructs the model to treat all tool results and document text as untrusted DATA, never instructions.

### 15.2 Front-end (this slice — `erpnext/public/js/ai_chat/` + scss)

```
 erpnext/public/js/ai_chat/ai_chat.bundle.js                                     |   esbuild entry; singleton init on `app_ready`, gated on frappe.boot.ai_chat_enabled
 erpnext/public/js/ai_chat/controller.js                                         |   wires Launcher + Panel; one instance mounted on document.body (survives SPA nav)
 erpnext/public/js/ai_chat/launcher.js                                           |   floating action button (bottom-right) + Ctrl/Cmd-J toggle
 erpnext/public/js/ai_chat/panel.js                                              |   slide-over: header (context chip pin/clear, history, new, close), message log, composer; states (empty/loading/error); Esc closes; HTML-escaped bubbles (no markdown render in v1 — XSS-safe)
 erpnext/public/js/ai_chat/context.js                                            |   ContextTracker — frappe.router.on("change") → get_route() → {doctype,name,view}; pin/clear; Form identity only (no field values)
 erpnext/public/js/ai_chat/stream.js                                             |   TurnStream — frappe.realtime.on("ai_chat:<conv>"); dispatches status/delta/done/error; off on done/error (no handler leak)
 erpnext/public/js/ai_chat/api.js                                               |   thin frappe.call wrappers over erpnext.ai.chat.api.*
 erpnext/public/scss/ai_chat.bundle.scss                                         |   launcher FAB + slide-over (384px / full-width <768px); Frappe CSS vars; reduced-motion
 erpnext/hooks.py                                                                |  +/- app_include_js / app_include_css string → list (adds ai_chat.bundle.{js,css})
```

**Mount mechanism (grounded, local `version-16` source):** `app_include_js`/`app_include_css` accept a **list** of bundles, each concatenated into `desk.html` (frappe `www/desk.py`; frappe's own `hooks.py` uses lists; the v15 hooks doc confirms *"support a list of paths too"*). esbuild globs `public/**/*.bundle.{js,scss}` → `dist/js|css/ai_chat.<hash>.{js,css}`, so `"ai_chat.bundle.js"` resolves after `bench build --app erpnext`. The bundle mounts a **single controller on `document.body`** on the `app_ready` event (fired by `frappe.Application.startup()` after nav/sidebar), gated on `frappe.boot.ai_chat_enabled` — so the launcher is **absent for Guest and on MCP-disabled sites**, and the conversation state survives SPA navigation.

**Realtime contract consumed (from `agent.py`):** channel `ai_chat:<conversation>`, payloads `{type:"status",text}` · `{type:"delta",text}` · `{type:"done",message,content,tools}` · `{type:"error",text}`. On `done`, the panel reconciles against the persisted thread via `get_conversation` (covers a missed socket event). Client JS is browser/test-plan verified — this repo has **no `bench`-runnable JS unit harness** (the logic-bearing server side is covered by `test_chat`); see the CLAUDE.md automated-tests rule (client-only, no server logic → browser/test-plan verified).

### 15.3 What v1 deliberately does NOT do
- **No write/action tools** — read-only; T-009 chat-specific tool gate stays deferred.
- **No markdown rendering** — bubbles are HTML-escaped (literal `**bold**` shows); rich render is a later polish (Slice F).
- **No dedicated chat queue** — turns ride the shared `short` queue (deferred).
- **No new sidebar/workspace entry** — the launcher is the only new always-present desk element (besides the navbar); see `UI-SITEMAP.md`.

### 15.4 Running the chat tests
```bash
bench --site <test-site> run-tests --module erpnext.ai.chat.tests.test_chat       # 10 tests
# Blast-radius (extend_bootinfo runs on every desk boot):
bench --site <test-site> run-tests --module erpnext.mcp.tests.test_permissions
```

## 16. Spec 05 — Supplier Resolution (3-tier) + Gated Creation

> **Status (2026-06-01):** implemented + tested on `russ/migrateToV16` (working tree). Fifth slice of the v2 build — see `docs/spec/05-supplier-resolution.md`. All 23 acceptance criteria green this session; **36 new automated tests** pass (alias 8, SMCR 6, capture +19 → **107 OK**, settings +3 → **20 OK**); spec-01/02/03/04 + extractor suites pass unchanged. The Fake OCR provider was pinned for the capture-suite run (spec-01 test-env note), then the site's `Anthropic Claude` provider restored.

Replaces today's single-tier `_match_supplier` with a **three-tier supplier resolver** — deterministic alias table → fuzzy match → **gated** create-new-supplier request — preserving the **never-auto-create** guarantee in every branch, and makes validation **stream-aware**: on **Stream I (Invoice)** an unresolved supplier *blocks* (no payable against an unknown vendor); on **Stream R (Receipt / card spend)** it is a *soft* flag (validation passes, the raw vendor string is preserved verbatim for the downstream Unmapped-Card-Spend JE owned by spec 07).

```
 erpnext/accounts/doctype/ap_supplier_alias/{__init__,ap_supplier_alias}.py + .json + test_ap_supplier_alias.py | NEW master DocType (Tier 1) — canonical_supplier/alias_pattern/match_type(exact|glob|regex)/is_active/priority/source_capture; AM-curated, AU read; 8 tests
 erpnext/accounts/doctype/supplier_master_change_request/{__init__,supplier_master_change_request}.py + .json + test_*.py | NEW submittable DocType (Tier 3) — the gated vehicle for supplier-master mutations; controller approve/reject with role gate + requester≠approver SoD + idempotent Supplier insert + capture re-validation; 6 tests
 erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.json                 | +/- supplier_match_tier (Select None|Alias|Fuzzy|Exact) + supplier_match_confidence (Float) + supplier_change_request (Link) + proposed_supplier_confidence (Float); supplier_match_status Literal gains "Alias"
 erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.py                   | +/- _resolve_supplier (3-tier) + _resolve_alias + _resolve_fuzzy; _match_supplier kept as back-compat shim; queue_supplier_create_request + _maybe_queue_supplier_create (Tier-3); validate_for_purchase_invoice rewritten with stream-aware branching; resolve_supplier_for whitelisted wrapper; _write_extraction_detail derives proposed_supplier_confidence
 erpnext/accounts/doctype/ap_closed_loop_settings/ap_closed_loop_settings.json + .py | +/- supplier_resolution_section: supplier_fuzzy_threshold(90)/supplier_fuzzy_min_length(4)/enable_gated_supplier_creation(0)/supplier_autocreate_confidence_threshold(0.85)/supplier_change_approver_role(Accounts Manager); get_supplier_resolution_settings() helper; validate() rejects a group/non-existent unmapped_card_spend_account (AC-05-23)
 test/testplans/specs/05-supplier-resolution-3tier.md                                         | clean-room runbook
```

**Resolver tiers (`_resolve_supplier`, spec §5.3):** **Tier 1** queries active `AP Supplier Alias` rows — precedence `exact > glob > regex`, then `priority` asc, then `name` asc; a bad `regex` is caught + logged + skipped (never raises into validation); aliases to a disabled Supplier are ignored; one distinct canonical supplier → `Alias` (confidence 100), >1 distinct → `Ambiguous`. **Tier 2a** preserves the legacy exact behaviour (PK / unique `supplier_name`, tier `Exact`, confidence 100). **Tier 2b** runs `rapidfuzz.fuzz.token_set_ratio` over active Suppliers with the `supplier_fuzzy_threshold` cutoff (inclusive `>=`); a candidate shorter than `supplier_fuzzy_min_length` (default 4) is skipped (Unknown); one hit → `Matched`/`Fuzzy`, >1 → `Ambiguous`, zero → `Unknown` carrying the best score seen. **Tier 3** (in the caller) queues a Draft `Supplier Master Change Request` iff the gate is on **AND** `proposed_supplier_confidence >= supplier_autocreate_confidence_threshold` **AND** no open request exists for the capture — **never** creating a Supplier inline.

**Approval (`approve_supplier_master_change_request`):** doubly gated — `frappe.only_for(approver_role)` (default `Accounts Manager`) **and** a requester≠approver SoD backstop in the controller. For `change_type=Create` it creates the Supplier from an allow-listed `proposed_payload` (keys verified against `supplier.json`: `supplier_name`/`supplier_group`/`supplier_type` + optional `country`/`default_currency`/`tax_id`), idempotently (the `created_supplier` short-circuit + the spec-01 `AP Posting Ledger` `with_idempotency` guard when a capture is linked), sets `created_supplier`, moves the request to `Posted`, auto-seeds an `exact` alias from the vendor string (OD-05-3), and re-runs `validate_for_purchase_invoice` so a blocked Stream-I capture flips `BLOCKED → VALIDATED`. The non-`Create` variants are dispatched here but their bodies (Update Bank Details → a **`Bank Account`** row, not the Supplier master; Payment Terms; Disable) are **owned by specs 08/11**.

**Out of scope (deferred):** the native `Workflow` record (states/transitions/Allowed Roles) for the request DocType and the `Treasury Approver` / `Auditor (Read Only)` roles are owned by [[11-approval-sod-workflow]] — until then the lifecycle is controller-driven via the `workflow_state` Select. No cascade-shape change: the richer resolver runs inside the existing post-confirm validation hop.

### 16.1 Running the spec-05 tests
```bash
# Pin Fake OCR first (the capture suite calls run_fake_extraction; spec-01 note):
#   AP Closed Loop Settings -> OCR Provider = Fake (Deterministic)
bench --site <test-site> run-tests --module erpnext.accounts.doctype.ap_supplier_alias.test_ap_supplier_alias                       # 8
bench --site <test-site> run-tests --module erpnext.accounts.doctype.supplier_master_change_request.test_supplier_master_change_request  # 6
bench --site <test-site> run-tests --module erpnext.accounts.doctype.ap_invoice_capture.test_ap_invoice_capture                     # 107
bench --site <test-site> run-tests --module erpnext.accounts.doctype.ap_closed_loop_settings.test_ap_closed_loop_settings           # 20
```

## 17. Spec 06 — GL Coding, Cost Center & Tax Assignment

> **Status (2026-06-01):** implemented + tested on `russ/migrateToV16` (working tree). Sixth slice of the v2 build — see `docs/spec/06-gl-coding-tax-costcenter.md`. All 14 acceptance criteria green this session; **18 new automated tests** (profile suite 5; capture suite +13 → **120 OK**); spec-01..05 + extractor suites pass unchanged.

Adds the **auto-coding layer** for routine vendors: a per-supplier `AP Supplier Coding Profile` (default expense account / cost center / purchase-tax template / payment terms / accounting dimensions) layered **on top of** native Party Account + `Supplier.payment_terms`/`tax_category`, plus a re-runnable `apply_coding_profile_for(capture)` that merges three default layers, infers a cost center (routing conflicts to a new **Coding-Review** queue rather than guessing), validates tax, and stages the coding for promote. `is_fully_coded(capture)` is the new gate later specs consult before anything auto-posts — *"without coding, nothing auto-posts."*

```
 erpnext/accounts/doctype/ap_supplier_coding_profile/{__init__,ap_supplier_coding_profile}.py + .json + test_*.py | NEW master DocType (autoname field:supplier, unique) — default expense/cost-center/tax-template/payment-terms + dimensions table; 5 tests
 erpnext/accounts/doctype/ap_supplier_coding_dimension/{__init__,ap_supplier_coding_dimension}.py + .json       | NEW child DocType (istable) — (dimension, value) via Dynamic Link off the Accounting Dimension's document_type
 erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.json                | +/- coding_section + coding_status(Pending|Coded|Ambiguous|Flagged)/coding_review_reason/applied_expense_account/applied_cost_center/applied_tax_template/applied_payment_terms_template/coding_source/card_last4/receipt_location
 erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.py                  | +/- apply_coding_profile_for + is_fully_coded + _resolve_supplier_coding + _infer_cost_center (+ _location/_card_cost_center stubs) + _validate_coding_tax + _apply_dimensions_to_row + _apply_coding_to_draft_pi; promote consumes capture.applied_* + sets pi.taxes_and_charges/payment_terms_template; submitted-PI guard; cascade Step-2b hop (gated on _coding_configured); apply_coding_profile_for_ui + get_coding_review_queue_for whitelisted
 erpnext/accounts/doctype/ap_closed_loop_settings/ap_closed_loop_settings.json + .py | +/- coding_section + default_purchase_tax_template; get_coding_settings() accessor (unmapped_card_spend_account + purchase_tax_template)
 test/testplans/specs/06-gl-coding-tax-costcenter.md                                 | clean-room runbook
```

**Three-layer merge (`apply_coding_profile_for`, §5.3):** Layer 0 = `AP Closed Loop Settings` (`get_promote_defaults` + `get_coding_settings`), Layer 1 = the supplier's coding profile, Layer 2 = caller `defaults` (highest). Effective expense resolves caller > profile > settings; on **Stream R** with no supplier/profile it falls to `unmapped_card_spend_account` (soft-flag). **Cost-center inference** collects location/card/profile signals — one (or agreeing) → written; **conflicting → `Ambiguous`, nothing written, routed to review** (never guesses). Tax: the resolved template is staged on the capture and written to the PI header `taxes_and_charges` at promote; the extracted `tax_amount` is validated against `subtotal × Σ(template rates)` within ±0.01, mismatch → `Flagged`. A **submitted-PI guard** refuses to re-code a `docstatus==1` invoice.

**Cascade:** a new Step-2b coding hop runs between validation and the manual-promote seam, but **only when coding is configured** for the capture (a profile exists, or the Stream-R catch-all is set) — so unconfigured sites (and the existing auto-progress suite) flow straight to promote unchanged (graceful degrade). `Ambiguous`/`Flagged` coding parks the capture in the Coding-Review queue.

**Reconciliations / decisions:** reused spec-04's `tax_amount`/`subtotal_amount` (no duplicate `extracted_tax_amount`); `unmapped_card_spend_account` already existed (spec 01/05); `receipt_location` is `Data` (the `Location` doctype is absent on this bench, decision D4); a separate `get_coding_settings()` accessor was added rather than overloading `get_promote_defaults`. Open decisions adopted per the spec's recommendations (D1 single-company, D2 profile-only-shipped, D3 ±0.01, D5 Dynamic Link, D7 new pause point, D8 separate doctype). **Deferred:** real location→CC / card→CC maps (D2 — stubs degrade to the profile signal); HRMS Department→CC signal (HRMS not installed).

### 17.1 Running the spec-06 tests
```bash
# Pin Fake OCR first (the capture suite calls run_fake_extraction; spec-01 note).
bench --site <test-site> run-tests --module erpnext.accounts.doctype.ap_supplier_coding_profile.test_ap_supplier_coding_profile   # 5
bench --site <test-site> run-tests --module erpnext.accounts.doctype.ap_invoice_capture.test_ap_invoice_capture                    # 120
```

## 18. Spec 07 — Document-Type Classification & Doctype Branching (stream-aware)

> **Status (2026-06-01):** implemented + tested on `russ/migrateToV16` (working tree). Seventh slice of the v2 build — see `docs/spec/07-classification-doctype-branching.md`. All 14 acceptance criteria green this session; **14 new automated tests** (capture suite 120 → **134 OK**); spec-01..06 suites pass unchanged. Built on the **provisionally-locked Stream-R posting model = Option C (PI `is_paid=1`)** (gating decision #1 / D-07-1; reversible, see TODO T-010).

Adds the Step-6 fork that classifies a confirmed capture and routes it to the right posting doctype — **Unpaid Bill → Purchase Invoice** (existing path), **Already Paid → Purchase Invoice with `is_paid=1`** (NEW Stream-R path: one submitted PI books the invoice legs *and* the payment legs, netting the supplier to zero while keeping it visible in spend-by-supplier/AP), **Employee Reimbursement → Manual Review** (hrms absent), **Other / stream conflict → Manual Review**. Routing everything to one doctype double-counts liabilities; this branch is the heart of correct AP automation.

```
 erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.json | +/- classification_section + document_type/classified_stream/stream_tag_agreement/classification_override/card_charge_marker/detected_last4/expense_claim(Data)/classified_at/by/source; status +Manual Review
 erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.py   | +/- classify_document_type (+_for) + _detect_card_marker/_provisional_stream/_finalize_classification; promote_already_paid (+_for) + _build_already_paid_voucher (Option-C swap seam); promote_to_purchase_invoice gains _already_paid param + the document_type guard + is_paid fields; cascade Step-1b classify hop + Already-Paid posting hop + Step-3 approval guard (Already-Paid skips approval/payment)
 erpnext/accounts/doctype/ap_closed_loop_settings/ap_closed_loop_settings.json + .py | +/- employee_supplier_group + get_already_paid_config() (reuses credit_card_clearing_account as the paid-from account)
 test/testplans/specs/07-classification-doctype-branching.md | clean-room runbook
```

**Classifier (`classify_document_type`, §5.3):** clerk `classification_override` always wins; else a paid/card marker (`****1234` / `PAID`) → Already Paid; a matched supplier in the configured `employee_supplier_group` → Employee Reimbursement; an unmatched supplier when an employee group IS configured → Manual Review; otherwise → Unpaid Bill. It then **confirms/revises** the intake stream tag — a disagreement forces Manual Review and records `stream_tag_agreement='Disagree'` (the spec-10 tuning signal). **Already-paid posting** is isolated to `_build_already_paid_voucher()` (Option C builds the `is_paid` PI; swap to a Journal Entry or PI+Clearing is a one-function change). Already-Paid PIs **skip approval/payment** (the money already moved; closure is reconciliation-only per specs 13/14).

**Reconciliations / decisions:** derived the provisional stream from spec-02's existing `stream` field (no duplicate field); reused `purchase_invoice` (Option C makes the Stream-R voucher a PI — no `journal_entry` field, and closure-evidence needs no third voucher type); reused spec-01's `credit_card_clearing_account` as the paid-from account; `expense_claim` is a `Data` placeholder (hrms / Expense Claim absent — D-07-3). **Deferred:** the `AP Review Event` emission on disagreement (spec 10 owns that doctype — the signal is persisted on the capture instead); the Employee → Expense Claim path (Manual Review until hrms is installed); the Option-A JE builder (specified behind the seam, not built since C is locked).

### 18.1 Running the spec-07 tests
```bash
# Pin Fake OCR first.
bench --site <test-site> run-tests --module erpnext.accounts.doctype.ap_invoice_capture.test_ap_invoice_capture   # 134
```

## 19. Spec 08 — Validation Gates: Three-Way Match, Amount Anomaly, Vendor Bank-Change

> **Status (2026-06-01):** implemented + tested on `russ/migrateToV16` (working tree). Eighth slice of the v2 build — see `docs/spec/08-validation-gates.md`. All 21 acceptance criteria green this session; **22 new automated tests** (capture suite 134 → **156 OK**, skipped=1; the extra test is an AC-08-16 re-check — promotion re-runs bank detection so a change *after* a clean validation is still caught); spec-01..07 suites pass unchanged (the gates add no false blocks to the existing happy paths). Adopted the spec's recommended defaults for every open decision (PO-cumulative 3WM, dedicated `AP Supplier Anomaly Baseline` cache, conservative bank-change lift deferring the full Treasury-Approver rule to spec 11 — TODO T-012).

Adds three **stream-aware** validation gates that run inside `validate_for_purchase_invoice` and one promotion-time re-check. On **Stream I** (or unset/Unclassified — the stricter D7 fallback) a failing gate **blocks** the capture into the review queue (`validation_status='Blocked'`, `action_required=1`); on **Stream R** (already-paid card spend) every gate is **recorded but never blocks**.

- **Three-way match** — the invoiced qty/amount vs the referenced Purchase Order's cumulative `received_qty` + ordered amount (D1 cumulative, not per-delivery), within `qty_tolerance_pct` / `amount_tolerance_pct`. PO-level match is the pilot scope (OCR resolves a PO reference at header/line granularity but produces no `po_detail` row mapping). Statuses: `Not Checked` / `Not Applicable` (receipt / no-PO) / `Matched` / `Exception` / `Matched (Override)`. An AP `override_three_way_match` (dedicated override-by/at/notes fields, D6) flips an Exception to `Matched (Override)` and re-validates.
- **Amount anomaly** — the capture total vs the supplier's rolling submitted-PI history: `> anomaly_multiple × mean` OR `> anomaly_sigma × stddev`. Below `anomaly_min_sample` prior PIs → `Insufficient History` (never blocks). Backed by a derived `AP Supplier Anomaly Baseline` cache (one row/supplier, refreshed by a daily scheduler, recomputed inline when stale).
- **Vendor bank-change** — a watched bank field (`Bank Account.iban`/`bank_account_no`/`branch_code`, `Bank.swift_number`/`bank_name`, `Supplier.default_bank_account`) changed **after** the supplier's last submitted Payment Entry, read from Frappe's native `Version` audit. Detection blocks **promotion** (`CapturePromotionError`) until a Posted Update-Bank-Details `Supplier Master Change Request` decided by someone other than the requester lifts it. No prior PE → soft-skip (no false block).

```
 erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.json | +/- validation_gates_section + three_way_match_status/result/checked_at/override_by/override_at/override_notes + anomaly_status/result/checked_at + vendor_bank_change_detected/result/checked_at
 erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.py   | +/- _is_stream_i/_resolve_gate_config + three_way_match_for + detect_amount_anomaly_for + _anomaly_baseline + detect_vendor_bank_change_for + has_approved_bank_change + override_three_way_match + refresh_anomaly_baselines/_upsert_anomaly_baseline; gate-run + Stream-I issue wiring inside validate_for_purchase_invoice; bank-change block inside promote_to_purchase_invoice; gates block added to build_closure_evidence; 4 whitelisted wrappers (three_way_match_for_capture/detect_amount_anomaly_for_capture/detect_vendor_bank_change_for_capture/override_three_way_match_for)
 erpnext/accounts/doctype/ap_closed_loop_settings/ap_closed_loop_settings.json + .py | +/- three_way_match_section (qty/amount tolerance, respect_over_billing_allowance, require_po_for_invoices) + anomaly_section fields (lookback_months/multiple/sigma/min_sample) + get_validation_gate_config()
 erpnext/accounts/doctype/ap_supplier_coding_profile/*.json + .py | +/- per-supplier gate overrides (qty/amount tolerance, anomaly multiple/sigma/min_sample)
 erpnext/accounts/doctype/ap_supplier_anomaly_baseline/* | NEW derived cache doctype (supplier-keyed mean/stddev/sample_count/window/computed_at)
 erpnext/hooks.py | +/- scheduler_events.daily += refresh_anomaly_baselines
 docs/architecture/AP-CAPTURE-SEQUENCE.md + .png | refreshed to current cascade (also caught up specs 06/07): Step 1b classify, Step 2 gates, Step 2a already-paid, Step 2b coding, promote-time bank re-check
 test/testplans/specs/08-validation-gates.md | clean-room runbook
```

**Decisions adopted** (= spec recommendations): D1 PO-cumulative 3WM; D2 `respect_over_billing_allowance` off by default (AP tolerance independent/stricter); D3 dedicated `AP Supplier Anomaly Baseline` cache; D4 daily-refresh + lazy-recompute (no per-PI `on_submit` hook); D5 pre-promotion custom 3WM only; D6 dedicated 3WM-override fields; D7 absent stream ⇒ Stream I (stricter); D8 soft-skip when no prior PE; D10 conservative `has_approved_bank_change` (Posted + decided-by-≠-requester) with the full **non-AP / Treasury-Approver role rule deferred to [[11-approval-sod-workflow]]** (TODO T-012). **Pilot simplification (honest):** 3WM is PO-level (sum of PO-item `received_qty`/ordered amount), not per-line PO-item matching — OCR doesn't emit a `po_detail` mapping; per-line 3WM lands when classification produces it.

### 19.1 Running the spec-08 tests
```bash
# Pin Fake OCR first (run_fake_extraction is explicit, but the site provider should be Fake for the suite).
bench --site <test-site> run-tests --module erpnext.accounts.doctype.ap_invoice_capture.test_ap_invoice_capture   # 156
```

## 20. Spec 09 — Confidence-Based Routing (Auto-Advance vs Needs-Review Queue)

> **Status (2026-06-01):** implemented + tested on `russ/migrateToV16` (working tree). Ninth slice of the v2 build — see `docs/spec/09-confidence-routing.md`. All 14 acceptance criteria green this session; **15 new automated tests** (capture suite 156 → **171 OK**, skipped=1); spec-01..08 suites pass unchanged (existing approval tests extract via the fake provider, so their confidence rows stay above threshold — the new gate adds no false reroutes).

Replaces the amount-only auto-approve decision in `request_approval` with a **three-axis combined-signal evaluator**: (1) amount vs the canonical `auto_post_amount_threshold`, (2) every `MANDATORY_HEADER_FIELDS` per-field confidence above threshold (spec 04's `is_above_threshold`), (3) zero open validation flags (spec 08). A clean+confident capture auto-advances exactly as before (Auto Approved at/under threshold, Pending Manager over it); **any** low-confidence field or open flag parks it at the new **`Needs Review`** approval state with the *specific* failing field/flag named in `routing_reason`, and emits a guarded `AP Review Event` (spec-10 telemetry seam). A sanctioned `reroute_after_review` re-routes once the clerk clears the flags.

```
 erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.json | +/- approval_status Select += "Needs Review"
 erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.py   | +/- APPROVAL_STATUS_NEEDS_REVIEW + ROUTING_AXIS_* consts; RoutingDecision namedtuple + _evaluate_routing_signals + _residual_gate_flag + _emit_review_event (guarded seam); request_approval gains the not-clean → Needs Review branch (names failing axis/field/flag); reroute_after_review (+ _for wrapper)
 erpnext/accounts/doctype/ap_closed_loop_settings/ap_closed_loop_settings.py | +/- get_routing_config() (composes auto_post_amount_threshold + spec-04 confidence threshold/field_thresholds)
 docs/architecture/AP-CAPTURE-SEQUENCE.md + .png | Step 3 now shows the confidence/flag → Needs Review branch + the reroute hop
 test/testplans/specs/09-confidence-routing.md | clean-room runbook
```

**Reconciliations (the spec predates specs 05–08; trust the code):**
- **Stream-R "no approval" is owned by spec 07, not this spec.** An Already-Paid (Stream R) capture posts via `promote_already_paid` (PI `is_paid`, **not** a Journal Entry) and the cascade *skips* Step-3 approval — so it never reaches `request_approval`. This spec therefore does **NOT** add JE auto-posting; the evaluator is **stream-agnostic** (it only ever sees Stream-I / unclassified captures that promoted to a standard PI). The spec's "Stream R → auto-post JE, no approval" matrix row is satisfied upstream.
- **The `auto_post_amount_threshold` settings field + `get_auto_post_threshold()` already existed** (spec 01/04) — the spec's "hard-coded 1000" current-state was already fixed. AC-09-10 was already met; this spec keeps it and adds `get_routing_config()`.
- **`AP Review Event` (spec 10) is not built** — emission is a `frappe.db.exists`-guarded seam (forward-compatible; the concrete field contract is reconciled when spec 10 lands). The "event row exists" sub-assertions of AC-09-4/5 defer to spec 10; this slice tests the routing behaviour + the graceful-absent path (AC-09-14).

**Decisions adopted** (= spec recommendations): D-1(b) `Auto Approved` + posted artifact (no `Auto Posted` enum), D-2 dedicated `get_routing_config()`, D-3(a) leave `payment_readiness=Not Ready` (moot — Stream R skips here), D-4(a) distinct `reroute_after_review` entrypoint, D-6(a) header fields only gate routing, D-7(a) no Stream-R amount ceiling, D-8(a) read `is_above_threshold` (no re-derive). **Pilot carve-out (honest):** the confidence axis fails closed on a *populated* table with a missing/low mandatory row, but an **empty** confidence table degrades to pass (graceful, matching specs 06/08) so non-extracted captures route on amount/flags as before. **Deferral:** D-9 (spec 11's native Workflow transition must read this same `auto_post_amount_threshold`, not a duplicate literal) → TODO T-013.

### 20.1 Running the spec-09 tests
```bash
bench --site <test-site> run-tests --module erpnext.accounts.doctype.ap_invoice_capture.test_ap_invoice_capture   # 171
```

## 21. Spec 10 — AP Review (Exception Handling) — instrumented feedback gate

> **Status (2026-06-01):** implemented + tested on `russ/migrateToV16` (working tree). Tenth slice of the v2 build — see `docs/spec/10-ap-review-observability.md`. All 17 acceptance criteria green this session; **18 new automated tests** across two modules (capture suite 171 → **185 OK**; new `test_ap_review_event` **4 OK**); spec-01..09 suites pass unchanged. Closes the Gate phase (08–10).

Turns Step 9 from a silent exception handler into an instrumented **feedback gate**: a clerk reject/reopen transition pair the capture lacked, plus the **`AP Review Event`** telemetry sink that every review action emits into, plus a weekly root-cause report + auto-rate chart.

```
 erpnext/accounts/doctype/ap_review_event/* | NEW append-only log DocType (capture, action_taken, root_cause_tag [fixed 8-value vocab], fields_changed JSON, time_to_resolve_seconds, exception_reason_code, note, clerk, created; autoname APRE-{YYYY}-{#####}; clerk-read-only)
 erpnext/accounts/doctype/ap_capture_rejection_log/* | NEW child table (action Rejected/Reopened, reason, from_status, to_status, actor, timestamp)
 erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.json | +/- rejection_section + rejection_log Table; status "Rejected" already existed (no enum migration)
 erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.py | +/- emit_review_event (shared primitive) + _safe_emit_review_event; reject_capture / reopen_capture (+ _for wrappers + get_rejection_log_for); validate() Rejected short-circuit; _determine_next_step Rejected→None guard; instrumentation on confirm_extracted_fields (field_corrected/coding_completed) + record_manager_decision reject (rejected, Stream I only); spec-09 _emit_review_event reconciled onto the canonical primitive
 erpnext/accounts/report/ap_top_step_9_root_causes/* | NEW Query Report (GROUP BY root_cause_tag, % of total, distinct captures; date filters)
 erpnext/accounts/dashboard_chart/ap_review_root_causes/* | NEW Group-By chart over AP Review Event by root_cause_tag
 docs/architecture/AP-CAPTURE-SEQUENCE.md | notes: reject/reopen clerk action + AP Review Event sink now built
 test/testplans/ap-review-event-gate.md + ap-capture-reject-reopen.md | clean-room runbooks
```

**`emit_review_event` is the shared instrumentation primitive** other specs import — it stabilizes here. The spec-09 route-to-review seam (a placeholder that wrote non-existent fields) is **reconciled onto it**: a confidence/flag park now records one real `AP Review Event` (`classified_other` + the mapped root cause `confidence_threshold_too_tight` / `policy_violation`).

**Reconciliations / decisions adopted** (= spec recommendations): D-1(a) `validate()` early `if status == Rejected: return` (the highest-risk integration point — `Rejected` now survives a re-save, AC-10-4); D-2(a) keep the 5-value `action_taken` enum (reopen logs as `classified_other` + note); D-3(a) `action_required = 0` on Rejected (terminal-quiet, drops off the queue); D-4 Dashboard Chart field names **verified against the running v16 site** before writing JSON; D-5(a) `fields_changed` as Small Text JSON string; D-6(a) `emit_review_event` inserts with `ignore_permissions=True` (append-only-by-controller); D-7(a) field_corrected vs coding_completed by comparing pre/post `final_*`; D-8(a) `time_to_resolve_seconds` from `creation` (v1); D-9(a)/D-10(a) report-on-demand Query Report (no scheduler). **Honest deferrals:** the `Auditor (Read Only)` role and an accurate `review_queue_entered_at` timestamp are fast-follows → TODO T-014. **Reconciliation with spec 11:** this is the **capture-level** reject (pre-PI, controller transition); spec 11 owns the **PI-level** native-Workflow reject — distinct doctypes at distinct stages, neither double-emits an event for one action.

### 21.1 Running the spec-10 tests
```bash
bench --site <test-site> run-tests --module erpnext.accounts.doctype.ap_invoice_capture.test_ap_invoice_capture   # 185
bench --site <test-site> run-tests --module erpnext.accounts.doctype.ap_review_event.test_ap_review_event          # 4
```

## 22. T-015 — Confidence-gated auto-confirm (the #1 automation lever)

> **Status (2026-06-02):** implemented + tested on `russ/migrateToV16`. First **automation-first** slice off the 2026-06-02 re-vision — builds the planned auto-confirm ACs in specs 04 §5.6 + 09 §5.6. **10 new tests** (capture suite 185 → **195 OK**, skipped=1); zero regressions (default OFF).

The whole pipeline already auto-advances the common case **except** the OCR-confirm pause: every capture stopped at `Proposed` for a human to confirm the OCR proposal **regardless of confidence**, so 100% of documents touched a human at least once. This closes that gap: when opted in, a clean+confident extraction auto-confirms and flows on — only the doubtful ones pause.

```
 erpnext/accounts/doctype/ap_closed_loop_settings/* | +/- auto_confirm_enabled Check (default OFF) + is_auto_confirm_enabled()
 erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.py | +/- _confidence_fields_ok (shared confidence axis, extracted from _evaluate_routing_signals — one copy of the gate) + _evaluate_confirm_signals (ConfirmDecision; fields_ok + residual-gate flags_ok, no amount axis); _determine_next_step Step 1a auto-confirm hop; auto_confirm_extracted_fields_for wrapper (re-checks the gate, suppresses the AP Review Event); confirm_extracted_fields gains emit_event param
 docs/architecture/AP-CAPTURE-SEQUENCE.md + .png | new Step 1a auto-confirm branch at the OCR-review pause
```

**The gate (OCR-confirm seam).** Reuses the approval evaluator's confidence axis (`_confidence_fields_ok` — all mandatory `field_confidences` rows `is_above_threshold`, fail-closed on a missing row) but **no amount axis** (no posting/authorization decision at confirm time) and a confirm-appropriate flags check (the spec-08 residual-gate guard — validation hasn't run yet at `Proposed`). On pass → auto-calls the existing `confirm_extracted_fields` with no corrections and no human; on any fail (low/missing confidence, open flag, or setting OFF) → falls back to the shipped `Proposed` human pause. **Auto-confirm emits no AP Review Event** — it is the opposite of an escalation, so it must not pollute the spec-10 root-cause report that measures *avoidable* human work.

**Default OFF.** `auto_confirm_enabled` ships `0`; the cascade is byte-for-byte unchanged until a site opts in (the pilot turns it on). The slice ticks AC-04-16..19 and AC-09-15..17 (previously "planned").

### 22.1 Running the T-015 tests
```bash
bench --site <test-site> run-tests --module erpnext.accounts.doctype.ap_invoice_capture.test_ap_invoice_capture   # 195
```

## 23. T-016 — Coding bootstrap from history (self-coding routine vendors)

> **Status (2026-06-02):** implemented + tested. Second automation-first slice (builds spec 06 §5.3.1 planned ACs). **4 new tests** (capture suite 195 → **199 OK**, skipped=1); zero regressions.

Shipped auto-coding (spec 06) only fired when a human pre-built an `AP Supplier Coding Profile` — a new-but-routine vendor was hand-coded every time. This adds **Layer 1.5**: a vendor with no profile self-codes from its **own prior posted Purchase Invoices** when their coding is consistent, so the profile bootstraps itself; a split history escalates to Coding Review; thin history falls through.

```
 erpnext/accounts/doctype/ap_closed_loop_settings/* | +/- enable_coding_history_bootstrap (default ON) + consensus/min_samples/lookback + get_coding_history_config()
 erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.py | +/- _derive_coding_from_history (per-field consensus over the supplier's docstatus=1 PIs → derived + ambiguous); apply_coding_profile_for gains Layer-1.5 merge (below profile+caller, above Settings) + split-history → Coding Review escalation; _coding_configured fires the coding hop for a history-codable supplier with no profile
```

**The gate.** For each codable field independently (`expense_account` / `cost_center` / `taxes_and_charges`) over the supplier's last `lookback` posted PIs: a value is derived only when it covers `>= consensus` (default 0.8) of the non-empty observations AND there are `>= min_samples` (default 3). A confidently-derived field is merged **below** the profile and the caller `defaults` (they always win) but **above** Settings — history only fills what no human pinned. A **split** field (no consensus), that neither a profile nor the caller pinned and nothing else resolved, routes to **Coding Review** naming the competing values (escalate only the doubtful). **Thin** history derives nothing (no auto-post on shaky evidence).

**Default ON** (decision D9 b) with conservative thresholds — but inert for any vendor without qualifying history, so existing sites/tests are unchanged. Self-seeding a profile from a confident derivation (D9 c) is the natural follow-on, deferred.

### 23.1 Running the T-016 tests
```bash
bench --site <test-site> run-tests --module erpnext.accounts.doctype.ap_invoice_capture.test_ap_invoice_capture   # 199
```

## 24. T-017 — Classification trusts confident content over a disagreeing intake tag

> **Status (2026-06-02):** implemented + tested. Third automation-first slice (builds spec 07 §5.3 planned ACs). **3 new tests** (capture suite 199 → **202 OK**); zero regressions.

Shipped classification sent **every** intake-vs-content stream disagreement to Manual Review — over-escalation, since the structured content read is usually the stronger signal. Now, when opted in, a **confident** content read that disagrees with the weak intake tag is **trusted**: the correction is recorded as telemetry and the cascade continues with no human. Only genuinely ambiguous content still escalates.

```
 erpnext/accounts/doctype/ap_closed_loop_settings/* | +/- enable_classification_trust_content (default OFF) + is_classification_trust_content_enabled()
 erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.py | +/- _content_classification_confident (decisive marker OR _confidence_fields_ok); classify_document_type disagreement branch now trusts confident content (records a stream_mistag AP Review Event, no halt) instead of unconditional Manual Review
```

**The gate.** In the classifier's disagreement branch: when `enable_classification_trust_content` is ON AND the content is confident (`card_charge_marker` is itself decisive, else the spec-04 mandatory-field confidence passes), keep the content's `document_type`/`classified_stream`, set `stream_tag_agreement='Disagree'`, emit one `AP Review Event` (`classified_other` / `stream_mistag`), and **do not halt** (`reason` stays None → status remains Confirmed, cascade continues). Otherwise → Manual Review exactly as shipped. **Default OFF** — the disagreement→Manual-Review behaviour (AC-07-5) is unchanged until a site opts in. Disagreement is a *tuning signal* (the `stream_mistag` rate feeds the spec-10 report), not an exception.

### 24.1 Running the T-017 tests
```bash
bench --site <test-site> run-tests --module erpnext.accounts.doctype.ap_invoice_capture.test_ap_invoice_capture   # 202
```

## 25. T-018 — Gated supplier auto-create defaults ON for high-confidence names

> **Status (2026-06-02):** implemented + tested. Fourth (final) automation-first slice — builds spec 05 AC-05-24..26 (OD-05-9 b). **3 new tests** (capture suite 202 → **205 OK**); zero regressions. **Completes the automation-first backlog.**

The Tier-3 gated-create capability already existed but shipped `enable_gated_supplier_creation` **OFF** — a confident-but-unknown vendor dead-stopped at a human who had to notice *and* file the create request. This flips the default **ON, scoped to high OCR confidence**: a confident unknown auto-files the Draft `Supplier Master Change Request`; the human's only remaining step is approval (SoD fully intact — Draft-only, a different user approves, the Stream-I capture stays Blocked until posted). A low-confidence name still does **not** auto-file (escalation preserved).

```
 erpnext/accounts/doctype/ap_closed_loop_settings/* | enable_gated_supplier_creation default 0 → 1 (JSON + getter unset-default True). The high-confidence scope guard already lives in _maybe_queue_supplier_create.
```

One-line default flip — no new desk surface (the auto-filed-request behaviour is identical to the already-screenshotted AC-05-16 gated path under `screenshots/05-supplier-resolution-3tier/`, only reached by default now), so screenshots are **N/A**. The **approval policy** (who approves new vendors) remains a customer decision — **TODO T-011**.

### 25.1 Running the T-018 tests
```bash
bench --site <test-site> run-tests --module erpnext.accounts.doctype.ap_invoice_capture.test_ap_invoice_capture   # 205
```

## 26. Spec 11 — Approval & Segregation of Duties (automation-first pilot)

> **Status (2026-06-02):** implemented + tested (pilot scope). 11th spec — see `docs/spec/11-approval-sod-workflow.md`. **6 new tests** + a strengthened AC-08-18 (capture suite 205 → **211 OK**); zero regressions.

Closes the real control gap: **the person who prepared an invoice may not also approve it.** The shipped engine only checked a *role* (`frappe.only_for`) — it could not stop a manager from approving an invoice they themselves entered. The pilot keeps the engine (in-policy invoices still auto-approve, spec 09) and adds the identity control; the company-wide native `Workflow` on Purchase Invoice is a **deferred, opt-in upgrade** (§5.6 / D-2/D-8 — it would govern every PI company-wide).

```
 erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.py | +/- record_manager_decision app-code SoD guard (above-threshold approve by reviewed_by/validated_by raises; self-reject allowed; Administrator break-glass exempt); resolve_approver_role (pilot default; matrix deferred); has_approved_bank_change now requires a non-requester Treasury Approver (T-012)
 erpnext/accounts/ap_closed_loop/install.py | +/- _seed_ap_roles — AP Clerk / Treasury Approver / Auditor (Read Only), idempotent, on after_migrate
 test/testplans/specs/11-approval-sod-workflow.md | clean-room runbook
```

**SoD guard (the control).** Above threshold (`approval_status == Pending Manager`), `record_manager_decision(approve=True)` raises `CaptureApprovalError` when the approver is the recorded preparer. Administrator is the audited break-glass exception (D-7 a; also the all-Administrator test harness). **Bank-change (T-012):** the bank-change promotion block (spec 08) is now lifted only by a Posted Update-Bank-Details request **decided by a non-requester holding the Treasury Approver role** — an AP clerk can no longer lift it. **Deferred:** native Workflow + `AP Approval Matrix` + Expense Claim (hrms absent). The SoD *failure path* is unit-tested rather than screenshotted (the desk session is Administrator, which is exempt by design); the roles are desk-visible.

### 26.1 Running the spec-11 tests
```bash
bench --site <test-site> run-tests --module erpnext.accounts.doctype.ap_invoice_capture.test_ap_invoice_capture   # 211
```

## 27. Spec 12 — Payment Execution (auto-pay opt-in per vendor)

> **Status (2026-06-02):** implemented + tested (pilot scope). 12th spec. **2 new tests** + 2 updated auto-progress tests (capture suite 211 → **213 OK**); zero regressions.

Payment moves real money, so the safe default is **human-triggered**. The automation lever is the per-supplier **`auto_pay_eligible`** flag: a *trusted* vendor flows approved → paid hands-free; every other vendor pauses for a human "Pay" click. The pilot grows the trusted set over time.

```
 erpnext/accounts/ap_closed_loop/install.py | +/- _seed_supplier_custom_fields — Supplier.auto_pay_eligible Check (default OFF), on after_migrate
 erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.py | +/- _determine_next_step Step 4 now gates on _auto_pay_eligible() — only a per-supplier auto_pay_eligible vendor auto-issues the (mock) Payment Entry; everyone else pauses at payment_readiness=Ready
```

Previously the cascade auto-paid **every** approved+ready capture (gated only by test flags). Now an approved, non-eligible capture stops at `Ready` until a human calls `issue_mock_payment` — and `issue_mock_payment` itself is unchanged (still `frappe.only_for(Accounts Manager)` + the `payment_entry` idempotency guard). Stream-R already-paid captures never reach Step 4 (they skip approval/payment at spec 07). **Deferred (phase 2):** the real external rail seam `issue_real_payment_for(capture, rail)` — real money warrants extra care; the mock/dev path flows freely.

### 27.1 Running the spec-12 tests
```bash
bench --site <test-site> run-tests --module erpnext.accounts.doctype.ap_invoice_capture.test_ap_invoice_capture   # 213
```

## 28. Spec 13 — Bank-Feed Match & dual-signal closure (the external close signal)

> **Status (2026-06-02):** implemented + tested (pilot scope; live feed deferred to cutover). 13th spec. **4 new tests** + 2 updated closure tests (capture suite 213 → **217 OK**); zero regressions.

"Closure comes from outside." A document isn't truly closed until the **bank feed confirms the money moved**. This reuses ERPNext's **native** Bank Reconciliation (no matching rebuilt), reads the result, and splits closure into `settled` (internal) + `bank_cleared` (external).

```
 erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.json | +/- bank_reconciliation_section + bank_cleared (Check) + bank_transaction (Link → Bank Transaction); payment_lifecycle_status += "Bank Cleared"
 erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.py | +/- _matched_bank_transaction (reads native Bank Transaction Payments) + reconcile_bank_for (stamps bank_cleared + the BT + lifecycle); build_closure_evidence now derives settled + bank_cleared and closed = settled AND bank_cleared; "no Bank Transaction" guardrail retired
```

**Dual-signal closure.** `closed = settled AND bank_cleared`. `settled` = submitted PI (Paid, outstanding 0) + submitted PE; `bank_cleared` = the native bank feed matched a `Bank Transaction` to the disbursing voucher. The Phase-1 guardrail ("Bank Transaction count must remain 0") is **retired** — a Bank Transaction now *enables* closure. **Deferred to cutover:** the live feed connection (native **Plaid** default, decision #8); dev uses fixture Bank Transactions. Verified with a real `Bank Transaction` matched to the PE (`TestAPBankReconciliation`).

### 28.1 Running the spec-13 tests
```bash
bench --site <test-site> run-tests --module erpnext.accounts.doctype.ap_invoice_capture.test_ap_invoice_capture   # 217
```
