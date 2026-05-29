# Real AI / OCR Implementation Plan — Anthropic Claude

> **Status:** Plan (locked decisions in §2; phased build in §8). **No code changes have been made yet** based on this plan.
>
> **Date drafted:** 2026-05-28.
>
> **Scope:** Replace the current `fake_extract` deterministic stand-in in the AP Invoice Capture pipeline with a real Anthropic Claude–based extractor, behind a provider-adapter interface that preserves the option to add Document AI / Mindee–class providers later. Add the settings, security, observability, test coverage, and documentation needed to ship this safely to a customer site.
>
> **Inputs:** `docs/planning/ocr-provider-choice-claude.md` (the choice and why), `docs/architecture/FORK-CHANGES.md` §6.4 (current AP Invoice Capture pipeline), `docs/planning/v16-upgrade-business-case.md` (deployment context), the fork's existing `run_fake_extraction`/`fake_extract` integration points, Anthropic API docs.
>
> **Grounding rule (per `CLAUDE.md`):** every factual claim cites either an upstream Anthropic URL, an upstream Frappe URL, a path in this repo, or a commit on `upstream/version-16`. Where docs are silent, the upstream source file is cited.

---

## 0. TL;DR

Build an `OCRProvider` adapter in `erpnext/accounts/ap_closed_loop/extractors/`. Refactor the current fake extractor to live behind it. Add an `AnthropicExtractor` that sends invoice PDFs/images to Claude using the **Messages API** with **document blocks** ([Anthropic PDF Support](https://platform.claude.com/docs/en/build-with-claude/pdf-support)) and **tool use** to force structured JSON output ([Anthropic Structured Outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)). Default model is **Claude Haiku 4.5**; fall back to **Claude Sonnet 4.6 / 4.7** on low confidence. Wire provider selection, model selection, confidence threshold, and API key into the existing `AP Closed Loop Settings` Single DocType. Persist every extraction as an audit row (capture, provider, model, latency, token usage, cost estimate). Keep the existing human-in-the-loop review step (`proposed_*` → clerk-confirmed `final_*`) unchanged.

**Effort estimate:** ~4–6 days of focused work split across 7 phased slices (§8). Each phase is independently shippable and reversible.

---

## 1. Context

The fork already has the right shape for this work:

- **Function to replace:** `run_fake_extraction()` in `erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.py` (around line 650).
- **Underlying helper:** `fake_extract()` in `erpnext/accounts/ap_closed_loop/walking_skeleton.py` (around line 124).
- **Target fields already exist on the DocType** (see `ap_invoice_capture.json`): `proposed_supplier`, `proposed_supplier_invoice_no`, `proposed_invoice_date`, `proposed_total_amount`, `proposed_currency`, `proposed_missing_fields`, `proposed_ambiguous_fields`, `ocr_provider`, `ocr_status`, `ocr_extracted_at`, `ocr_raw_response`.
- **Async cascade already in place:** `_enqueue_next` → `frappe.enqueue` with `deduplicate=True` and per-capture-per-step `job_id` (see `FORK-CHANGES.md` §6.6).
- **Human-in-the-loop is enforced:** capture goes to `status = Proposed` after extraction; clerk must use the **Confirm Fields** dialog to merge `proposed_*` into `final_*` before the cascade continues.

The choice of Claude (and why Haiku as default with Sonnet as fallback) is justified in detail in `docs/planning/ocr-provider-choice-claude.md`. This plan does not re-litigate it.

---

## 2. Pre-flight decisions (LOCKED)

These need to be agreed before slice 1 starts. Each is recorded with the reason so the rationale doesn't get lost.

| # | Decision | Locked value | Reason |
|---|---|---|---|
| L1 | **Module location** | `erpnext/accounts/ap_closed_loop/extractors/` | Within the AP closed-loop scope; sits next to the existing `walking_skeleton.py`. Per `CLAUDE.md`, fork-scope changes are exempt from the upstream-docs grounding rule for trivial paths but still need `FORK-CHANGES.md` updates. |
| L2 | **Provider abstraction surface** | `OCRProvider` ABC with two methods: `extract(source: SourceCapture, file_bytes: bytes, media_type: str) -> ExtractionResult` and `name() -> str` | Smallest useful surface. Returns a dataclass that already maps 1:1 to the existing `proposed_*` fields, so the calling code converts a dataclass to field writes, nothing more. |
| L3 | **Anthropic SDK** | Official `anthropic` Python SDK (current stable). Pinned in `pyproject.toml` of the fork branch. | Maintained by Anthropic, handles retries and auth properly, matches the docs verbatim. No alternatives considered (the raw HTTP version exists but reinvents auth + retries for no gain). |
| L4 | **Document delivery mode to Claude** | **Base64 inline `document` blocks** for v1. Files API deferred to v2 (only useful when re-querying the same document multiple times — which we don't, since we cache by `content_hash` on our side). | Simplest path; one round trip; no beta header required. Per [PDF Support](https://platform.claude.com/docs/en/build-with-claude/pdf-support#option-2-base64-encoded-pdf-document) the base64 path is GA. |
| L5 | **Structured output strategy** | **Tool use** with `tool_choice = {"type": "tool", "name": "extract_invoice_fields"}` to force the model to call the tool. The tool input schema IS the contract. | Per Anthropic, tool use with forced tool choice is the recommended path for structured extraction. Eliminates JSON-parsing brittleness; schema validation is automatic. |
| L6 | **Default model** | `claude-haiku-4-5-20251001` (pinned by exact version, not `-latest`) | Per benchmarks in `ocr-provider-choice-claude.md` §3.2: 0 hallucinations, 96.7% completeness, 8× cheaper than Sonnet. Pinning by date prevents silent quality drift on model rollover. |
| L7 | **Fallback model** | `claude-sonnet-4-7` (pinned by current published id) | Higher reasoning, still 0 hallucinations in benchmarks. Invoked only when Haiku output triggers `proposed_ambiguous_fields` or fails required-field check. |
| L8 | **Confidence threshold for fallback** | **0.70 per required field** (Default; overridable in `AP Closed Loop Settings`) | Conservative starting point. We can tune after collecting test-corpus data (§7.4). |
| L9 | **API key storage** | Frappe `Password` field on `AP Closed Loop Settings`, retrieved at extraction time via `frappe.utils.password.get_decrypted_password` (Frappe's built-in encryption-at-rest pattern). Never logged. Never exposed in `ocr_raw_response`. | Standard Frappe pattern for secrets. Encrypted in the DB. |
| L10 | **Idempotency cache key** | The existing `SourceCapture.content_hash` (SHA-256 of the file bytes). Cached extraction is the **last successful `ExtractionResult` for that hash**, stored in a new `AP Extraction Cache` Single DocType keyed by hash. TTL: 30 days. | Re-extracting the same file is wasteful and non-deterministic at the LLM layer. Caching on content hash is the right primitive. 30 days is conservative for an audit-driven flow; can be tuned. |
| L11 | **PDF size handling** | Reject (set `action_required=1` with reason) any source larger than 25 MB (under Anthropic's 32 MB request budget, leaving headroom for the prompt and response). For PDFs over 50 pages, downsample images and warn. | Per [PDF Support](https://platform.claude.com/docs/en/build-with-claude/pdf-support#check-pdf-requirements): 32 MB request limit, 600 pages max (100 for 200k-token-context models). Hard fail upstream rather than silently truncate. |
| L12 | **PNG/JPG support** | First-class. Sent via `image` content blocks (not `document`) per [Anthropic Vision](https://platform.claude.com/docs/en/build-with-claude/vision). Same `OCRProvider` interface; the adapter chooses the block type by `media_type`. | The fork's `SUPPORTED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg"}` already commits to these formats. |
| L13 | **Prompt caching** | Not used in v1. Each invoice is different content; the prompt template is short. Caching has no economic payoff here. Revisit if we add multi-pass extraction. | Per [PDF Support — Prompt caching](https://platform.claude.com/docs/en/build-with-claude/pdf-support#use-prompt-caching), caching cuts cost up to 90% on **repeated** content. Not applicable here. |
| L14 | **Test mode behavior** | When `frappe.flags.in_test` is set, `get_extractor()` returns the `FakeExtractor` regardless of settings. Real API calls only happen via an opt-in integration test (env var gated). | Tests stay fast, deterministic, and free. |
| L15 | **Audit log** | New child DocType `AP Extraction Log` (one row per extraction call), parented to the AP Invoice Capture. Stores `provider`, `model`, `started_at`, `latency_ms`, `input_tokens`, `output_tokens`, `cost_usd_estimate`, `outcome` (`success`/`fallback_invoked`/`failed`), `error_message`. Raw response stays in `ocr_raw_response` on the parent (already exists). | Audit + cost monitoring are non-negotiable for production AP. Separate child table keeps the parent form clean and the log queryable. |
| L16 | **Cost estimate source** | Hardcoded per-token rate table in code, keyed by model ID. Updated when Anthropic publishes new pricing. | The API doesn't return cost; only tokens. The estimate is for monitoring, not billing — exact pricing is in Anthropic's billing portal. |

Any disagreement on L1–L16 above re-opens the plan. Do not silently change a locked value in implementation.

---

## 3. Architecture

### 3.1 Module layout

```
erpnext/accounts/ap_closed_loop/
├── extractors/
│   ├── __init__.py
│   ├── base.py             # OCRProvider ABC + ExtractionResult dataclass
│   ├── fake.py             # FakeExtractor(OCRProvider) — wraps existing fake_extract
│   ├── anthropic.py        # AnthropicExtractor(OCRProvider)
│   ├── registry.py         # get_extractor(provider_name: str) -> OCRProvider
│   └── pricing.py          # PER_MODEL_PRICING table for cost estimation
└── walking_skeleton.py     # unchanged shape; fake_extract still exported for tests
```

### 3.2 Provider interface (sketch — exact signatures finalized in slice 1)

```python
# extractors/base.py
@dataclass
class ExtractionResult:
    proposed_supplier: str | None
    proposed_supplier_invoice_no: str | None
    proposed_invoice_date: str | None        # ISO 8601 date
    proposed_total_amount: float | None
    proposed_currency: str | None            # ISO 4217 (3-letter)
    confidence_per_field: dict[str, float]    # 0.0–1.0 per fieldname
    missing_fields: list[str]
    ambiguous_fields: list[str]
    raw_response: dict                        # full provider payload
    provider_name: str
    provider_model: str
    latency_ms: int
    input_tokens: int | None
    output_tokens: int | None

class OCRProvider(ABC):
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def extract(
        self,
        source: SourceCapture,
        file_bytes: bytes,
        media_type: str,           # "application/pdf" | "image/png" | "image/jpeg"
    ) -> ExtractionResult: ...
```

### 3.3 Tool schema for Claude

The single, authoritative tool definition. Lives in `extractors/anthropic.py`.

```python
INVOICE_EXTRACTION_TOOL = {
    "name": "extract_invoice_fields",
    "description": (
        "Extract structured header fields from a supplier invoice document. "
        "Return null for any field you cannot read confidently. Do not guess. "
        "Confidence should reflect how certain you are of each field's value: "
        "1.0 = unambiguous; 0.7 = legible but unverified; 0.4 = partial/ambiguous; "
        "0.0 = absent or unreadable."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "supplier_name":         {"type": ["string", "null"]},
            "supplier_invoice_no":   {"type": ["string", "null"]},
            "invoice_date":          {"type": ["string", "null"], "description": "ISO 8601 date (YYYY-MM-DD)"},
            "total_amount":          {"type": ["number", "null"]},
            "currency":              {"type": ["string", "null"], "description": "ISO 4217 3-letter code (e.g. USD, EUR, INR)"},
            "confidence_per_field": {
                "type": "object",
                "properties": {
                    "supplier_name":       {"type": "number", "minimum": 0, "maximum": 1},
                    "supplier_invoice_no": {"type": "number", "minimum": 0, "maximum": 1},
                    "invoice_date":        {"type": "number", "minimum": 0, "maximum": 1},
                    "total_amount":        {"type": "number", "minimum": 0, "maximum": 1},
                    "currency":            {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["supplier_name", "supplier_invoice_no", "invoice_date", "total_amount", "currency"],
            },
            "ambiguous_fields": {"type": "array", "items": {"type": "string"}},
            "missing_fields":   {"type": "array", "items": {"type": "string"}},
        },
        "required": ["confidence_per_field", "ambiguous_fields", "missing_fields"],
    },
}
```

The system prompt accompanying this tool says: extract the header fields from this invoice, populate the tool input, use null for fields you cannot read confidently. This is the entire prompt — no examples, no chain-of-thought scaffolding. The schema and the document are the contract.

### 3.4 Message structure sent to Claude

Per [PDF Support — Place PDFs before text](https://platform.claude.com/docs/en/build-with-claude/pdf-support#improve-performance), document blocks come first.

```python
messages = [
    {
        "role": "user",
        "content": [
            {
                "type": "document" if media_type == "application/pdf" else "image",
                "source": {"type": "base64", "media_type": media_type, "data": base64_data},
            },
            {
                "type": "text",
                "text": "Extract the invoice header fields using the extract_invoice_fields tool. Use null for any field you cannot read confidently.",
            },
        ],
    }
]

response = client.messages.create(
    model=model_id,
    max_tokens=2048,
    tools=[INVOICE_EXTRACTION_TOOL],
    tool_choice={"type": "tool", "name": "extract_invoice_fields"},
    messages=messages,
)
```

### 3.5 Confidence + fallback logic

```
1. Call Haiku.
2. If response has no tool_use block → log failure, raise OCRExtractionError.
3. Parse tool input into ExtractionResult.
4. For each required field (supplier, invoice_no, date, amount, currency):
     if confidence < threshold AND field not already in missing_fields:
       add field to ambiguous_fields
5. If ambiguous_fields is non-empty AND fallback enabled AND we haven't already escalated:
     call Sonnet with the same prompt + document
     replace ExtractionResult with Sonnet's response
     mark `provider_model = "claude-sonnet-4-7"` in the result
     mark `outcome = "fallback_invoked"` in the audit log
6. Return ExtractionResult (whichever pass produced it).
```

The fallback is at most one re-extraction. We do not cascade to Opus automatically; Opus is operator-triggered only.

### 3.6 Mapping ExtractionResult to the DocType fields

The calling code in `run_extraction` (renamed from `run_fake_extraction`):

```python
def run_extraction(capture: APInvoiceCapture, source: SourceCapture, file_bytes: bytes, media_type: str) -> None:
    settings = frappe.get_single("AP Closed Loop Settings")
    extractor = get_extractor(settings.ocr_provider or "fake")

    result = extractor.extract(source, file_bytes, media_type)

    # Write proposed_* fields
    capture.proposed_supplier            = result.proposed_supplier
    capture.proposed_supplier_invoice_no = result.proposed_supplier_invoice_no
    capture.proposed_invoice_date        = result.proposed_invoice_date
    capture.proposed_total_amount        = result.proposed_total_amount
    capture.proposed_currency            = result.proposed_currency
    capture.proposed_missing_fields      = "\n".join(result.missing_fields)
    capture.proposed_ambiguous_fields    = "\n".join(result.ambiguous_fields)

    # Provenance
    capture.ocr_provider     = result.provider_name
    capture.ocr_status       = OCR_STATUS_PROPOSED
    capture.ocr_extracted_at = now_datetime()
    capture.ocr_raw_response = json.dumps(result.raw_response)

    # Drive existing pause-for-review
    capture.status = STATUS_PROPOSED
    capture.action_required = 1 if (result.missing_fields or result.ambiguous_fields) else 0
    capture.action_required_reason = "Awaiting OCR review" if capture.action_required else ""

    capture.save(ignore_permissions=True)
    frappe.db.commit()

    _write_audit_log(capture, result)
```

This is the **only** code change in `ap_invoice_capture.py` for OCR purposes. The existing state machine, cascade, and clerk-review flow are unchanged.

### 3.7 Idempotency by content hash

Before calling any provider:

```python
cache_hit = frappe.db.get_value(
    "AP Extraction Cache",
    {"content_hash": source.content_hash},
    ["result_json", "provider_name", "provider_model"],
)
if cache_hit and not settings.ocr_force_reextract:
    return ExtractionResult(**json.loads(cache_hit.result_json), ...)
```

The cache is keyed by SHA-256 of the file bytes. Re-uploading the same PDF produces the same hash → free extraction. Forces a re-extract via a Settings toggle for debugging or after a model bump.

### 3.8 Error handling

Provider-side errors that should NOT crash the cascade:

- **HTTP timeouts** → retry once with exponential backoff; if second fail, log and set `action_required=1` with reason "OCR provider timeout — please run manually."
- **HTTP 5xx** → retry once; same fallback as above.
- **HTTP 429 (rate limit)** → respect `Retry-After` header; bump to a delayed enqueue.
- **HTTP 400** (malformed request, oversized PDF, etc.) → do not retry; set `action_required=1` with the specific reason; the operator fixes the source.
- **Tool input fails schema validation** → log full raw response to `ocr_raw_response`; set `action_required=1`; do not corrupt `proposed_*` fields.

Per `CLAUDE.md` working rules, we do NOT silently swallow errors. Every failure leaves an actionable trail on the capture record.

### 3.9 Circuit breaker

If 5 consecutive Anthropic calls fail (any error category) within a 5-minute window, the adapter trips a process-local circuit breaker for 60 seconds and rejects new calls with a clear error. Prevents queue thrashing during a provider outage. Implementation is a simple class-level counter — no external dependency.

---

## 4. Settings DocType changes (`AP Closed Loop Settings`)

Add the following fields to `erpnext/accounts/doctype/ap_closed_loop_settings/ap_closed_loop_settings.json`:

| Fieldname | Type | Required | Default | Notes |
|---|---|---|---|---|
| `ocr_section_break` | Section Break | — | — | Label: "OCR / Extraction" |
| `ocr_provider` | Select | Yes | `Fake (Deterministic)` | Options: `Fake (Deterministic)`, `Anthropic Claude` |
| `ocr_model` | Select | No | `claude-haiku-4-5-20251001` | Options: `claude-haiku-4-5-20251001`, `claude-sonnet-4-6`, `claude-sonnet-4-7`. Only relevant when `ocr_provider = Anthropic Claude`. |
| `ocr_fallback_model` | Select | No | `claude-sonnet-4-7` | Same options as `ocr_model`. Empty disables fallback. |
| `ocr_confidence_threshold` | Float | No | `0.70` | Per-required-field threshold for triggering fallback. |
| `anthropic_api_key` | Password | No | — | Encrypted at rest via Frappe's standard Password field encryption. Required when `ocr_provider = Anthropic Claude`. |
| `ocr_force_reextract` | Check | No | `0` | Bypass the content-hash cache. For debugging only — operators should leave this unchecked in production. |
| `ocr_max_file_mb` | Int | No | `25` | Hard limit per file. Files larger get rejected with a clear `action_required_reason`. |

Permissions mirror the existing pattern: System Manager + Accounts Manager read/write; Accounts User read-only.

Validation hook on the DocType:
- If `ocr_provider = Anthropic Claude`, `anthropic_api_key` must be set. Validate at save.
- `ocr_confidence_threshold` must be in `[0.0, 1.0]`.

---

## 5. Audit log — `AP Extraction Log`

New DocType under `erpnext/accounts/doctype/ap_extraction_log/`. **Not** a child table — separate parent DocType linked to AP Invoice Capture (avoids bloating the capture form, makes the log independently queryable).

| Fieldname | Type | Notes |
|---|---|---|
| `capture` | Link → AP Invoice Capture | Required. Indexed. |
| `provider_name` | Data | e.g. `anthropic` |
| `provider_model` | Data | e.g. `claude-haiku-4-5-20251001` |
| `started_at` | Datetime | UTC |
| `latency_ms` | Int | Wall-clock from request start to response received |
| `input_tokens` | Int | From `response.usage.input_tokens` |
| `output_tokens` | Int | From `response.usage.output_tokens` |
| `cost_usd_estimate` | Currency (USD) | From `pricing.py` table. Always an estimate. |
| `outcome` | Select | `success`, `fallback_invoked`, `cache_hit`, `failed` |
| `error_message` | Small Text | Empty unless `outcome = failed` |
| `cache_hit_for` | Data | If `outcome = cache_hit`, the original extraction log row's name |

Permissions: System Manager + Accounts Manager read/write; Accounts User read.

Indexing: index on `capture` and `started_at`. Allows the AP Invoice Capture form to show its extraction history via a dashboard child.

---

## 6. Security

### 6.1 API key handling

- Stored as Frappe `Password` field → encrypted at rest via Frappe's standard encryption (uses site's `encryption_key`).
- Retrieved at extraction time via `frappe.utils.password.get_decrypted_password("AP Closed Loop Settings", "AP Closed Loop Settings", "anthropic_api_key")`.
- **Never** logged. **Never** included in `ocr_raw_response`, `error_message`, or any audit field.
- The adapter holds the key in memory only for the duration of one API call.

### 6.2 PII in invoices

Invoices contain supplier names, addresses, tax IDs, bank account numbers. Two responses required:

- **Document the data flow.** Anthropic's [Privacy Center](https://privacy.anthropic.com) and [Data Usage Policy](https://www.anthropic.com/legal/commercial-terms) describe the standard handling. For customers with stricter requirements, enable Anthropic's **Zero Data Retention (ZDR)** — per [PDF Support](https://platform.claude.com/docs/en/build-with-claude/pdf-support), PDF processing is ZDR-eligible. ZDR means data sent through the API is not stored after the response returns.
- **Make ZDR a customer-facing setting.** Add to `AP Closed Loop Settings`: `anthropic_zdr_enabled` (Check, default 0). When checked, the adapter requests ZDR-enabled processing (verifies the org has ZDR provisioned). Document in `FORK-CHANGES.md` that enabling this is the customer's responsibility per their Anthropic contract.

### 6.3 What we never store

- The decrypted API key
- The exact prompt content if it ever includes customer data (it doesn't in this design — the prompt is fixed template)
- Anything from `frappe.local.request` that could leak session info

### 6.4 Log redaction

`error_message` on `AP Extraction Log` may contain provider error responses. Sanitize before storing: strip `x-api-key`, any `authorization` header echo, and any field matching `/api[_-]?key/i`. Simple regex pass at write time.

---

## 7. Test strategy

### 7.1 Unit tests (do not call the API)

- `extractors/base.py` — `ExtractionResult` validation (currency is ISO 4217, dates are ISO 8601, confidences are in `[0, 1]`).
- `extractors/fake.py` — existing fake_extract tests, refactored to call through the adapter; ensure semantics are unchanged.
- `extractors/anthropic.py` — schema validation tests (mock the API client; feed it canned responses; verify the adapter correctly maps tool_use blocks → `ExtractionResult` and handles missing/extra fields gracefully).
- `extractors/anthropic.py` — error-handling tests (mock HTTP 429, 500, timeout, malformed response; verify the correct retry/circuit-breaker/`action_required` behavior).
- `extractors/registry.py` — `get_extractor` returns the right class given the settings value; raises clearly for unknown providers.

Run via existing `bench --site erpnext.localhost run-tests --app erpnext --module erpnext.accounts.ap_closed_loop.extractors.test_base` etc.

### 7.2 State-machine tests (unchanged behavior)

The existing `test_ap_invoice_capture.py` suite uses `FakeExtractor` by default (via the L14 flag). These tests should keep passing untouched after the refactor.

### 7.3 Integration test (real Claude call, opt-in)

A new file `test_anthropic_extractor_live.py`:

- Gated behind env var `ENABLE_LIVE_OCR_TESTS=1` (skipped by default — CI never pays for API calls).
- Fixtures: 3 invoice PDFs of varying quality (clean, scanned, low-resolution photo) stored under `erpnext/accounts/ap_closed_loop/extractors/test_fixtures/`.
- For each fixture, asserts the response is non-null on required fields, `provider_name == "anthropic"`, and `latency_ms` is recorded.
- Does NOT assert specific extracted values (model output is non-deterministic) — only that the call succeeds and returns a schema-valid result.

### 7.4 Test corpus + ground-truth benchmark

Separate from the test suite. A directory `docs/planning/ocr-test-corpus/` (gitignored; corpus stored externally) holds 20–50 real or realistic invoices with hand-coded ground truth (`supplier`, `invoice_no`, `date`, `total`, `currency` per file).

A script `erpnext/accounts/ap_closed_loop/extractors/benchmark.py` runs the corpus through any registered extractor and computes F1 per field. Used:

- Once before turning on Anthropic in production, to establish baseline accuracy.
- Whenever Anthropic publishes a new model version, to detect regression.
- When tuning `ocr_confidence_threshold` (find the threshold that minimizes false-confident extractions).

### 7.5 Cost regression sanity test

A small fixture (one-page PDF, ~50 KB) is benchmarked monthly via the live test. Asserts `cost_usd_estimate < $0.01` for Haiku. Catches accidental model promotion to Sonnet/Opus, prompt bloat, or pricing drift.

---

## 8. Phased implementation (vertical slices)

Each slice is independently shippable. Each ends green tests + a verifiable artifact.

### Phase 1 — Adapter infrastructure (no behavior change)

**Goal:** Refactor the existing fake extractor behind the `OCRProvider` interface. The cascade, the form, and the tests all behave identically.

**Files added:**
- `extractors/__init__.py`
- `extractors/base.py` — `OCRProvider` ABC + `ExtractionResult` dataclass
- `extractors/fake.py` — `FakeExtractor(OCRProvider)` wrapping the current `fake_extract`
- `extractors/registry.py` — `get_extractor(name)` → `FakeExtractor` for now (only one provider)

**Files modified:**
- `ap_invoice_capture.py` — `run_fake_extraction` renamed to `run_extraction`, dispatches through `get_extractor("fake")`
- `walking_skeleton.py` — `fake_extract` remains, internally consumed by `FakeExtractor`

**Acceptance criteria:**
- All existing tests in `test_walking_skeleton.py` and `test_ap_invoice_capture.py` pass without modification.
- `bench --site … console` → `from erpnext.accounts.ap_closed_loop.extractors.registry import get_extractor; get_extractor("fake").name()` returns `"fake"`.
- No production data behavior changes; the cascade still calls into the same extraction flow, just one indirection deeper.

**Estimate:** half a day.

### Phase 2 — `AnthropicExtractor` v1 (single model, no fallback, no settings)

**Goal:** A working `AnthropicExtractor` callable from a `bench execute` command. Hardcoded model (`claude-haiku-4-5-20251001`); API key read from env var `ANTHROPIC_API_KEY` for now. No Settings DocType changes yet. No audit log yet.

**Files added:**
- `extractors/anthropic.py` — `AnthropicExtractor(OCRProvider)`
- `extractors/test_anthropic_unit.py` — schema mapping unit tests (mocked client)
- `extractors/test_anthropic_live.py` — opt-in integration test (gated by env var)
- `extractors/test_fixtures/` — 3 sample invoice PDFs

**Files modified:**
- `pyproject.toml` — add `anthropic >= …` dependency
- `extractors/registry.py` — register `"anthropic"`
- `extractors/pricing.py` — initial table for Haiku 4.5 + Sonnet 4.7

**Acceptance criteria:**
- `ANTHROPIC_API_KEY=… bench --site … execute erpnext.accounts.ap_closed_loop.extractors.anthropic.smoke_test` extracts a fixture PDF and prints a valid `ExtractionResult`.
- Unit tests cover: tool_use block parsing, schema validation, null/None handling, missing-tool-use error, malformed response error.
- Live integration test passes against all 3 fixtures.
- Failing API call (mocked) does not corrupt any DocType state.

**Estimate:** 1–1.5 days.

### Phase 3 — Settings DocType integration

**Goal:** Provider + model + API key + threshold are configurable via `AP Closed Loop Settings`. `run_extraction` reads from settings instead of env var.

**Files modified:**
- `ap_closed_loop_settings.json` — add the fields listed in §4
- `ap_closed_loop_settings.py` — `validate()` enforces "API key required when provider is anthropic"; helper `get_anthropic_api_key()` returns the decrypted key
- `ap_invoice_capture.py` — `run_extraction` reads provider/model from settings

**Acceptance criteria:**
- Setting `ocr_provider = "Anthropic Claude"` in the Settings form and triggering an extraction uses Claude.
- Setting `ocr_provider = "Fake (Deterministic)"` reverts to the existing fake flow (no API call).
- Saving with `ocr_provider = "Anthropic Claude"` and no API key fails validation with a clear message.
- API key is encrypted in the DB (verify via `SELECT anthropic_api_key FROM \`tabAP Closed Loop Settings\`` — should not be plaintext).

**Estimate:** half a day.

### Phase 4 — Confidence + fallback logic

**Goal:** Low-confidence Haiku responses trigger one re-extraction with Sonnet. Audit log records `outcome = fallback_invoked`. No infinite loops.

**Files modified:**
- `extractors/anthropic.py` — fallback logic per §3.5
- `extractors/test_anthropic_unit.py` — fallback path tests (mock Haiku low-confidence; verify Sonnet is called once and result is replaced)
- `extractors/test_anthropic_live.py` — add a fixture designed to trigger fallback (e.g., low-resolution scan)

**Acceptance criteria:**
- Haiku response with any required-field confidence < threshold triggers exactly one Sonnet re-extraction.
- A second low-confidence response does NOT trigger a third call.
- Disabling fallback (`ocr_fallback_model` = empty) skips the second call.

**Estimate:** half a day.

### Phase 5 — Audit log + cost tracking

**Goal:** Every extraction call produces an `AP Extraction Log` row. Cost estimate computed from token usage. Cache hits logged distinctly.

**Files added:**
- `erpnext/accounts/doctype/ap_extraction_log/` (full DocType: `__init__.py`, `.json`, `.py`)
- `extractors/pricing.py` — completed pricing table
- `extractors/test_audit_log.py`

**Files modified:**
- `extractors/base.py` — `ExtractionResult` includes the token + latency fields shown in §3.2
- `extractors/anthropic.py` — populates the fields from `response.usage`
- `ap_invoice_capture.py` — `_write_audit_log()` helper in `run_extraction`

**Acceptance criteria:**
- One extraction produces exactly one `AP Extraction Log` row.
- Cache hits write a row with `outcome = cache_hit` and `cache_hit_for` populated; no Claude call made.
- Cost estimate matches manual calculation for a known fixture.

**Estimate:** 1 day.

### Phase 6 — Production hardening

**Goal:** Retry policy, circuit breaker, error redaction, ZDR setting, file-size guard, all per §3.8, §3.9, §6.

**Files modified:**
- `extractors/anthropic.py` — retry + circuit breaker
- `ap_invoice_capture.py` — file-size guard before calling extractor
- `ap_closed_loop_settings.json` — add `anthropic_zdr_enabled`

**Acceptance criteria:**
- Mocked HTTP 429 with `Retry-After: 5` causes a 5-second-delayed re-enqueue.
- 5 mocked consecutive failures in 5 minutes trips the circuit breaker; calls during the cool-down are short-circuited with a clear error; after cool-down, calls resume.
- Submitting a 30 MB PDF sets `action_required = 1` with reason `"Source file exceeds OCR provider's size limit (25 MB)"`. No Claude call is made.
- `error_message` on a failure row contains no `x-api-key` or `authorization` substring.

**Estimate:** 1 day.

### Phase 7 — Documentation + handoff

**Goal:** `FORK-CHANGES.md` and `FORK-CHANGES-PLAIN.md` reflect the new module. A short "OCR Provider Setup" page for operators. Test corpus benchmark results recorded.

**Files modified:**
- `docs/architecture/FORK-CHANGES.md` — add §10 OCR Provider Adapter
- `docs/architecture/FORK-CHANGES-PLAIN.md` — paragraph on "OCR is now real (Claude)"
- `docs/planning/ocr-provider-choice-claude.md` — append benchmark results

**Files added:**
- `docs/runbooks/ocr-provider-setup.md` — operator-facing: how to install the Anthropic SDK, get an API key, fill in settings, verify a test extraction

**Acceptance criteria:**
- Anyone reading `FORK-CHANGES.md` understands the new adapter layout and where extension points live.
- A new operator can follow the runbook end-to-end without asking a developer.

**Estimate:** half a day.

---

## 9. Out of scope (explicit)

- **Line-item extraction.** v1 extracts header fields only (the existing `proposed_*` fields). Line items deferred until Phase 2 of the AP pilot (see `docs/changes/IMPLEMENTATION-PLAN.md`).
- **Multi-page invoice splitting / merging.** Treat each upload as one logical invoice. Multi-page PDFs are sent as one document.
- **OCR for non-invoice document types** (POs, receipts, contracts). The adapter is invoice-specialized for now.
- **Anthropic Batch API.** Useful for backfill scenarios. Not used in v1 (we extract on upload, not in bulk).
- **Anthropic Files API.** Documented in §2 (L4) as deferred — only useful for re-querying the same document, which we already cache locally.
- **Real-time UI updates during extraction.** The clerk sees the cascade message ("Running OCR…") and a refreshed form once extraction completes. No streaming.
- **Fine-tuning a custom model on the customer's invoice corpus.** Out of scope until volume justifies it (see `ocr-provider-choice-claude.md` §7).

---

## 10. Open questions to resolve before slice 1

1. **Customer-specific Anthropic account vs. NexeraDigital-shared account?** Affects who pays the API bill, who handles billing alerts, and how the `anthropic_api_key` field is provisioned (one-time setup vs. per-deployment).
2. **Compliance posture — is ZDR required?** Drives whether `anthropic_zdr_enabled` defaults on or off, and whether we recommend the customer's Anthropic contract include ZDR provisioning.
3. **Test-corpus invoices.** Where do we get 20–50 real-or-realistic invoices? Customer-provided (best, but slow to negotiate), public dataset (worse signal), synthetic (worst). Probably mix.
4. **Cost monitoring threshold.** What dollar-per-day or extractions-per-day triggers an alert? Out of scope to build alerts in v1 but the log structure should support adding them later.

---

## 11. Risks

| Risk | Likelihood | Severity | Mitigation |
|---|---|---|---|
| Model returns confident but wrong values for a key field (e.g., supplier name) | Medium | High (real money) | Human-in-the-loop review step on every capture is preserved; never auto-confirm. Test-corpus benchmark before production. |
| Anthropic API outage during business hours | Low | Medium | Circuit breaker + clear `action_required` reason; clerk falls back to manual entry. No silent failures. |
| Anthropic pricing changes mid-pilot | Medium | Low | Cost estimate in audit log uses a code-local pricing table; we re-verify periodically. The 8× Haiku/Sonnet ratio is durable signal. |
| Customer compliance team rejects Anthropic data handling | Medium | High | ZDR option exists; if rejected, swap to Document AI via the adapter pattern. Have the adapter ready as a Phase 8 if needed. |
| Confidence threshold tuned wrong → too many fallback calls | Medium | Low | Audit log makes this visible immediately; tune the threshold after first 100 real extractions. |
| `content_hash` collisions across different files | Negligible | High | SHA-256; collision probability is astronomically low. Not a practical concern. |
| Frappe encryption key rotation breaks stored API key | Low | Medium | Standard Frappe Password field handles this via re-encryption hooks. Document in the operator runbook. |

---

## 12. Sources

### Anthropic (official)
- [Claude API — PDF Support](https://platform.claude.com/docs/en/build-with-claude/pdf-support)
- [Claude API — Vision](https://platform.claude.com/docs/en/build-with-claude/vision)
- [Claude API — Structured Outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
- [Claude API — Tool Use (overview)](https://platform.claude.com/docs/en/build-with-claude/tool-use)
- [Claude API — Files API](https://platform.claude.com/docs/en/build-with-claude/files)
- [Claude API — Token Counting](https://platform.claude.com/docs/en/build-with-claude/token-counting)
- [Claude API — Models Overview](https://platform.claude.com/docs/en/about-claude/models/overview)
- [Anthropic — Privacy & Data Handling](https://privacy.anthropic.com)
- [Anthropic — Commercial Terms](https://www.anthropic.com/legal/commercial-terms)

### Frappe (official)
- [Frappe v15 — DocTypes](https://docs.frappe.io/framework/v15/user/en/basics/doctypes)
- [Frappe v15 — Background Jobs (`frappe.enqueue`)](https://docs.frappe.io/framework/v15/user/en/api/python-api/background-jobs)
- [Frappe v15 — Whitelisted Methods](https://docs.frappe.io/framework/v15/user/en/python-api/hooks)
- Frappe Password field encryption — source: `frappe/frappe/utils/password.py` (`get_decrypted_password`)

### Repo-internal
- `docs/planning/ocr-provider-choice-claude.md` — the WHY behind choosing Claude
- `docs/architecture/FORK-CHANGES.md` §6.4 — current AP Invoice Capture pipeline
- `docs/architecture/FORK-CHANGES.md` §6.6 — auto-progression cascade mechanics
- `docs/planning/v16-upgrade-business-case.md` — deployment context
- `docs/planning/local-v17-to-v16-migration-plan.md` — confirms the fork is on v16 where this lands
- `CLAUDE.md` — grounding + working rules
- `erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.py` (lines ~650–720) — `run_fake_extraction` integration point
- `erpnext/accounts/ap_closed_loop/walking_skeleton.py` (line ~124) — `fake_extract` underlying function
- `erpnext/accounts/doctype/ap_closed_loop_settings/` — Single DocType extended by §4

### Benchmarks (referenced in choice doc)
- [AIMultiple Research — Invoice OCR Benchmark](https://aimultiple.com/invoice-ocr)
- [DEV Community — JSON Extraction Benchmark](https://dev.to/shaun_vd_7562913ba77e1e0b/claude-sonnet-46-vs-gpt-41-vs-gemini-25-flash-which-wins-json-extraction-poa)
