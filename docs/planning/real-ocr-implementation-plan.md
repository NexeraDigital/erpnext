# Real AI / OCR Implementation Plan — Anthropic Claude

> **Status:** Plan (locked decisions in §2; phased build in §8). **No code changes have been made yet** based on this plan.
>
> **Date drafted:** 2026-05-28.
>
> **Scope:** Replace the current `fake_extract` deterministic stand-in in the Document Capture pipeline with a real Anthropic Claude–based extractor, behind a provider-adapter interface that preserves the option to add Document AI / Mindee–class providers later. Add the settings, security, observability, test coverage, and documentation needed to ship this safely to a customer site.
>
> **Inputs:** `docs/planning/ocr-provider-choice-claude.md` (the choice and why), `docs/architecture/FORK-CHANGES.md` §6.4 (current Document Capture pipeline), `docs/planning/v16-upgrade-business-case.md` (deployment context), the fork's existing `run_fake_extraction`/`fake_extract` integration points, Anthropic API docs.
>
> **Grounding rule (per `CLAUDE.md`):** every factual claim cites either an upstream Anthropic URL, an upstream Frappe URL, a path in this repo, or a commit on `upstream/version-16`. Where docs are silent, the upstream source file is cited.

---

## 0. TL;DR

Build an `OCRProvider` adapter in `erpnext/accounts/ap_closed_loop/extractors/`. Refactor the current fake extractor to live behind it. Add an `AnthropicExtractor` that sends invoice PDFs/images to Claude using the **Messages API** with **document blocks** ([Anthropic PDF Support](https://platform.claude.com/docs/en/build-with-claude/pdf-support)) and **tool use** to force structured JSON output ([Anthropic Structured Outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)). Default model is **Claude Haiku 4.5**; fall back to **Claude Sonnet 4.6 / 4.7** on low confidence. AI credentials (Anthropic key, default model, ZDR flag) live in a **new shared `AI Provider Settings` Single DocType** under a new top-level `erpnext/ai/` module — System Manager–only — so future AI features (supplier matching, account prediction, etc.) reuse the same setup. AP-feature-specific tuning (provider choice, confidence threshold, fallback model) stays on `AP Closed Loop Settings`. Persist every extraction as an `Integration Request` row (Frappe's canonical outbound-API audit DocType — see §5). Keep the existing human-in-the-loop review step (`proposed_*` → clerk-confirmed `final_*`) unchanged.

**Effort estimate:** ~4.5–6.5 days of focused work split across 8 phased slices (§8). Each phase is independently shippable and reversible.

---

## 1. Context

The fork already has the right shape for this work:

- **Function to replace:** `run_fake_extraction()` in `erpnext/accounts/doctype/document_capture/document_capture.py` (around line 650).
- **Underlying helper:** `fake_extract()` in `erpnext/accounts/ap_closed_loop/walking_skeleton.py` (around line 124).
- **Target fields already exist on the DocType** (see `document_capture.json`): `proposed_supplier`, `proposed_supplier_invoice_no`, `proposed_invoice_date`, `proposed_total_amount`, `proposed_currency`, `proposed_missing_fields`, `proposed_ambiguous_fields`, `ocr_provider`, `ocr_status`, `ocr_extracted_at`, `ocr_raw_response`.
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
| L7 | **Fallback model** | `claude-sonnet-4-6` (pinned by current published id) | Higher reasoning, still 0 hallucinations in benchmarks. Invoked only when Haiku output triggers `proposed_ambiguous_fields` or fails required-field check. |
| L8 | **Confidence threshold for fallback** | **0.70 per required field** (Default; overridable in `AP Closed Loop Settings`) | Conservative starting point. We can tune after collecting test-corpus data (§7.4). |
| L9 | **API key storage** | **New shared `AI Provider Settings` Single DocType** (System Manager–only read/write) holds `anthropic_api_key` and `openai_api_key` as Frappe `Password` fields, plus default model preferences and org-level AI flags (e.g. `anthropic_zdr_enabled`). The AP feature reads `AP Closed Loop Settings.ocr_provider` to choose a provider, then calls a small server-side helper `get_ai_credentials("anthropic")` to fetch the decrypted key via `frappe.utils.password.get_decrypted_password`. Key is held in process memory only for the duration of one API call. Never logged; never exposed in `ocr_raw_response`. | Designed so a second AI feature (supplier matching, account / cost-center prediction, anomaly detection, summarization, etc.) reuses the same credentials and the same provider configuration without duplication. Cleanly separates infrastructure credentials (locked to System Manager) from feature settings (AP Manager–readable). Per-feature cost attribution is preserved via distinct `integration_request_service` values in audit logs (see §5). |
| L10 | **Idempotency by content hash** | **No new caching DocType.** Reuse the `content_hash` field that Frappe's `File` DocType already populates on every uploaded file (`File.generate_content_hash()` at `apps/frappe/frappe/core/doctype/file/file.py:516`, using `get_content_hash()` from `apps/frappe/frappe/core/doctype/file/utils.py:186`). The cascade already prevents re-extraction at the capture level (won't re-run when `ocr_status != "Not Extracted"`). If cross-capture dedup is ever needed, query existing Document Capture records via the linked `tabFile.content_hash`. | The fork's `SourceCapture.content_hash` and Frappe's `File.content_hash` are the same SHA-256 by construction. Storing it twice and adding TTL logic would be reinventing what Frappe ships. |
| L11 | **PDF size handling** | Reject (set `action_required=1` with reason) any source larger than 25 MB (under Anthropic's 32 MB request budget, leaving headroom for the prompt and response). For PDFs over 50 pages, downsample images and warn. | Per [PDF Support](https://platform.claude.com/docs/en/build-with-claude/pdf-support#check-pdf-requirements): 32 MB request limit, 600 pages max (100 for 200k-token-context models). Hard fail upstream rather than silently truncate. |
| L12 | **PNG/JPG support** | First-class. Sent via `image` content blocks (not `document`) per [Anthropic Vision](https://platform.claude.com/docs/en/build-with-claude/vision). Same `OCRProvider` interface; the adapter chooses the block type by `media_type`. | The fork's `SUPPORTED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg"}` already commits to these formats. |
| L13 | **Prompt caching** | Not used in v1. Each invoice is different content; the prompt template is short. Caching has no economic payoff here. Revisit if we add multi-pass extraction. | Per [PDF Support — Prompt caching](https://platform.claude.com/docs/en/build-with-claude/pdf-support#use-prompt-caching), caching cuts cost up to 90% on **repeated** content. Not applicable here. |
| L14 | **Test mode behavior** | When `frappe.flags.in_test` is set, `get_extractor()` returns the `FakeExtractor` regardless of settings. Real API calls only happen via an opt-in integration test (env var gated). | Tests stay fast, deterministic, and free. |
| L15 | **Audit log** | **Reuse Frappe's `Integration Request` DocType** (`apps/frappe/frappe/integrations/doctype/integration_request/`) — the canonical pattern Frappe ships for outbound API call audit, already used by every payment gateway integration. Per call, write one row with `integration_request_service = "anthropic"`, `reference_doctype = "Document Capture"`, `reference_docname = capture.name`, `status = success/failed/queued`, `data` = sanitized request summary, `output` = JSON of `{latency_ms, input_tokens, output_tokens, cost_usd_estimate, model, outcome}` next to the raw response, `error` = sanitized error text on failure. Raw response also continues to be written to `ocr_raw_response` on the capture (already exists). | Building a new `AP Extraction Log` DocType would duplicate fields that already exist (`status`, `data`, `output`, `error`, `reference_doctype`, `reference_docname`, `url`, `request_headers`, `response_headers`) and split the audit story across two places. Operators expect outbound integration calls to appear in the standard Integration Request list view; we should not deviate. |
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
     mark `provider_model = "claude-sonnet-4-6"` in the result
     mark `outcome = "fallback_invoked"` in the audit log
6. Return ExtractionResult (whichever pass produced it).
```

The fallback is at most one re-extraction. We do not cascade to Opus automatically; Opus is operator-triggered only.

### 3.6 Mapping ExtractionResult to the DocType fields

The calling code in `run_extraction` (renamed from `run_fake_extraction`) normalizes the model's outputs through Frappe's own helpers before writing — never trust the raw string for date or currency:

```python
def run_extraction(capture: APInvoiceCapture, source: SourceCapture, file_bytes: bytes, media_type: str) -> None:
    settings = frappe.get_single("AP Closed Loop Settings")
    extractor = get_extractor(settings.ocr_provider or "fake")

    result = extractor.extract(source, file_bytes, media_type)

    # Normalize and validate against Frappe's own sources of truth
    normalized_date, date_ok = _normalize_date(result.proposed_invoice_date)        # frappe.utils.getdate
    normalized_currency, currency_ok = _normalize_currency(result.proposed_currency)  # frappe.db.exists("Currency", ...)

    extra_ambiguous = []
    if result.proposed_invoice_date and not date_ok:
        extra_ambiguous.append("invoice_date")
    if result.proposed_currency and not currency_ok:
        extra_ambiguous.append("currency")

    # Write proposed_* fields
    capture.proposed_supplier            = result.proposed_supplier
    capture.proposed_supplier_invoice_no = result.proposed_supplier_invoice_no
    capture.proposed_invoice_date        = normalized_date          # ISO date string or None
    capture.proposed_total_amount        = result.proposed_total_amount
    capture.proposed_currency            = normalized_currency      # validated 3-letter code or None
    capture.proposed_missing_fields      = "\n".join(result.missing_fields)
    capture.proposed_ambiguous_fields    = "\n".join(result.ambiguous_fields + extra_ambiguous)

    # Provenance
    capture.ocr_provider     = result.provider_name
    capture.ocr_status       = OCR_STATUS_PROPOSED
    capture.ocr_extracted_at = now_datetime()
    capture.ocr_raw_response = json.dumps(result.raw_response)

    # Drive existing pause-for-review
    capture.status = STATUS_PROPOSED
    needs_review = bool(result.missing_fields or result.ambiguous_fields or extra_ambiguous)
    capture.action_required = 1 if needs_review else 0
    capture.action_required_reason = "Awaiting OCR review" if needs_review else ""

    capture.save(ignore_permissions=True)
    frappe.db.commit()

    _write_integration_request(capture, result)  # see §5
```

`_normalize_date` and `_normalize_currency` defer to Frappe's existing helpers rather than re-implementing format checking:

```python
def _normalize_date(raw):
    if not raw:
        return None, True
    try:
        return frappe.utils.getdate(raw).isoformat(), True   # accepts ISO 8601, MM/DD/YYYY, "May 28, 2026", etc.
    except Exception:
        return None, False

def _normalize_currency(raw):
    if not raw:
        return None, True
    code = raw.strip().upper()
    return (code, True) if frappe.db.exists("Currency", code) else (None, False)
```

This is the **only** code change in `document_capture.py` for OCR purposes. The existing state machine, cascade, and clerk-review flow are unchanged.

### 3.7 Idempotency by content hash

Frappe already populates `tabFile.content_hash` for every uploaded file (`File.generate_content_hash()` in `apps/frappe/frappe/core/doctype/file/file.py:516`, using `get_content_hash()` from the same module's `utils.py:186`). The fork's `SourceCapture.content_hash` is the same SHA-256 by construction.

At capture level, the existing cascade already prevents re-extraction: the next-step logic only enqueues OCR when `ocr_status == "Not Extracted"`. Re-running on the same capture is therefore a no-op without any caching layer.

The only remaining case is **cross-capture dedup** — the same file uploaded as two different captures. At pilot volume this is rare; do not build a separate cache table for it. If it does become a real problem later, the lookup is a one-shot SQL join via the linked File:

```python
prior = frappe.db.sql("""
    SELECT cap.name, cap.ocr_raw_response,
           cap.proposed_supplier, cap.proposed_supplier_invoice_no,
           cap.proposed_invoice_date, cap.proposed_total_amount, cap.proposed_currency
    FROM `tabDocument Capture` cap
    INNER JOIN `tabFile` f ON f.name = cap.source_file
    WHERE f.content_hash = %s
      AND cap.ocr_status IN ('Proposed', 'Confirmed')
      AND cap.name != %s
    LIMIT 1
""", (source.content_hash, capture.name), as_dict=True)
```

If a prior is found, copy its `proposed_*` and `ocr_raw_response` onto the new capture and skip the Claude call. The Settings toggle `ocr_force_reextract` (per §4) bypasses any dedup path for debugging or after a model bump.

### 3.8 Error handling

Two distinct retry layers exist; understanding the boundary is important:

- **Queue-level retry (Frappe, free)** — `frappe.utils.background_jobs.execute_job` already retries up to 5 times on Redis / connection-level failures with `time.sleep(retry + 1)` backoff (`apps/frappe/frappe/utils/background_jobs.py:278-290`). Applies when the worker can't reach Redis, the job times out at the queue layer, etc. We get this for free because the cascade enqueues OCR via `frappe.enqueue`.
- **Call-level retry (adapter, new)** — Frappe's queue-level retry does NOT catch application exceptions raised inside our handler (HTTP 429, 5xx, network timeout when talking to Anthropic). Those need to be caught and retried inside `AnthropicExtractor`.

Adapter-level error handling, designed to surface every failure on the capture record (no silent swallowing — per `CLAUDE.md`):

- **HTTP timeouts** → retry once with exponential backoff; if second fail, set `action_required=1` with reason "OCR provider timeout — please run manually."
- **HTTP 5xx** → retry once; same fallback as above.
- **HTTP 429 (rate limit)** → respect `Retry-After` header; raise a typed exception that the cascade catches and re-enqueues with the requested delay (do not block the worker for arbitrary seconds).
- **HTTP 400** (malformed request, oversized PDF, etc.) → do not retry; set `action_required=1` with the specific reason; the operator fixes the source.
- **Tool input fails schema validation** → write the full raw response to `ocr_raw_response`; set `action_required=1`; do not corrupt `proposed_*` fields.

Every failure path writes an `Integration Request` row with `status = "Failed"` and a sanitized `error` (see §5 and §6.4).

### 3.9 Circuit breaker

If 5 consecutive Anthropic calls fail (any error category) within a 5-minute window, the adapter trips a process-local circuit breaker for 60 seconds and rejects new calls with a clear error. Prevents queue thrashing during a provider outage. Implementation is a simple class-level counter — no external dependency.

---

## 4. Settings DocType changes

Two DocTypes are touched: one new (shared infrastructure), one existing (AP-feature-specific). The split keeps credentials out of feature-team visibility and makes future AI features cheap to add.

### 4.1 NEW: `AI Provider Settings` (Single, shared)

Path: `erpnext/ai/doctype/ai_provider_settings/ai_provider_settings.json` (introduces a new top-level `erpnext/ai/` module — added to `erpnext/modules.txt`).

| Fieldname | Type | Required | Default | Notes |
|---|---|---|---|---|
| `anthropic_section` | Section Break | — | — | Label: "Anthropic" |
| `anthropic_api_key` | Password | No | — | Encrypted via Frappe Password field encryption. Required for any feature that selects `Anthropic Claude`. |
| `anthropic_default_model` | Data | No | `claude-haiku-4-5-20251001` | Used as a fallback if a feature does not override its own model. Pinned by exact id, not `-latest`. |
| `anthropic_zdr_enabled` | Check | No | `0` | Customer signals their Anthropic contract supports Zero Data Retention (per [PDF Support](https://platform.claude.com/docs/en/build-with-claude/pdf-support)). When checked, the adapter requests ZDR-eligible processing. |
| `openai_section` | Section Break | — | — | Label: "OpenAI" — present from day one but unused until a feature selects it. |
| `openai_api_key` | Password | No | — | Reserved for future features. Empty in v1. |
| `openai_default_model` | Data | No | — | Reserved for future features. |

**Permissions:** System Manager only, read + write. Other roles (including Accounts Manager) cannot read this DocType — credentials are not feature-team visibility.

**Helper:** `erpnext/ai/credentials.py` exposes `get_ai_credentials(provider: str) -> AICredentials` (small dataclass with `api_key`, `default_model`, `zdr_enabled`). Raises `AICredentialsNotConfigured` with a clear message if the requested provider has no key set.

Validation hook on save: trim whitespace from API keys; do not validate the key by calling the provider (that's a separate "test connection" button if we want one later).

### 4.2 EXISTING: `AP Closed Loop Settings` (extended)

Add the following fields to `erpnext/accounts/doctype/ap_closed_loop_settings/ap_closed_loop_settings.json`:

| Fieldname | Type | Required | Default | Notes |
|---|---|---|---|---|
| `ocr_section_break` | Section Break | — | — | Label: "OCR / Extraction" |
| `ocr_provider` | Select | Yes | `Fake (Deterministic)` | Options: `Fake (Deterministic)`, `Anthropic Claude`. When set to `Anthropic Claude`, the `anthropic_api_key` field in `AI Provider Settings` must be populated (validated on save — see below). |
| `ocr_model` | Select | No | `claude-haiku-4-5-20251001` | Options: `claude-haiku-4-5-20251001`, `claude-sonnet-4-6`, `claude-sonnet-4-6`. Empty falls back to `AI Provider Settings.anthropic_default_model`. Only relevant when `ocr_provider = Anthropic Claude`. |
| `ocr_fallback_model` | Select | No | `claude-sonnet-4-6` | Same options as `ocr_model`. Empty disables fallback. |
| `ocr_confidence_threshold` | Float | No | `0.70` | Per-required-field threshold for triggering fallback. |
| `ocr_force_reextract` | Check | No | `0` | Bypass the cross-capture dedup lookup (see §3.7). Debug only. |
| `ocr_max_file_mb` | Int | No | `25` | Hard limit per file. Files larger get rejected with a clear `action_required_reason`. |

Note: **`anthropic_api_key` is NOT on this DocType.** It lives only in `AI Provider Settings` per §4.1.

Permissions on `AP Closed Loop Settings` are unchanged from the existing pattern: System Manager + Accounts Manager read/write; Accounts User read-only. AP Managers can configure how AP uses AI; they cannot see the underlying credential.

Validation hook on save:
- If `ocr_provider = Anthropic Claude`, look up `AI Provider Settings` and confirm `anthropic_api_key` is non-empty. If empty, raise a clear `ValidationError` instructing the operator to populate it under `AI Provider Settings` first. (Do NOT echo the key in the error message.)
- `ocr_confidence_threshold` must be in `[0.0, 1.0]`.

---

## 5. Audit log — reuse Frappe `Integration Request`

**No new DocType.** Use `frappe.integrations.doctype.integration_request.Integration Request` — the canonical Frappe DocType for outbound API call audit, already used by every payment gateway integration (Stripe, Razorpay, etc.). Operators expect outbound calls to show up in the standard Integration Request list at `/app/integration-request`; we should not deviate from that.

### 5.1 Field mapping

| Concept we need | Integration Request field | Value |
|---|---|---|
| Service name | `integration_request_service` | `"anthropic"` |
| Link to source capture | `reference_doctype` + `reference_docname` | `"Document Capture"` + `capture.name` (Dynamic Link, indexed) |
| Outcome | `status` | `"Queued"` → `"Completed"` / `"Failed"` (Integration Request's existing vocabulary) |
| Endpoint URL | `url` | `"https://api.anthropic.com/v1/messages"` |
| Request payload summary | `data` | Sanitized JSON: `{model, media_type, page_count, content_hash, file_size_bytes}` — never the file bytes, never the API key |
| Response payload | `output` | JSON: `{latency_ms, input_tokens, output_tokens, cost_usd_estimate, model_used, outcome: "success"\|"fallback_invoked"\|"cache_hit", raw_response_excerpt}` |
| Error message | `error` | Sanitized error text on failure (see §6.4) |
| Request headers | `request_headers` | Sanitized headers (no `x-api-key`) |
| Response headers | `response_headers` | Full Anthropic response headers (request-id, rate-limit info) |

Raw response also continues to be written to `ocr_raw_response` on the capture itself (the field already exists). That gives operators one click from the capture form to the latest raw response, while Integration Request gives the full per-call history.

### 5.2 Cost estimate

Anthropic returns `usage.input_tokens` and `usage.output_tokens` on every response. The cost estimate is computed via a small local pricing table in `extractors/pricing.py`, keyed by model id, and written into the `output` JSON of the Integration Request row. The Integration Request DocType doesn't have a native currency field for cost, which is fine — we keep cost in the structured `output` JSON where the rest of the per-call telemetry already lives.

### 5.3 Cache-hit rows

When the cross-capture dedup path in §3.7 fires, write a row with `status = "Completed"`, `output.outcome = "cache_hit"`, and `output.source_capture = <original_capture_name>`. No Anthropic call made.

### 5.4 Querying the log

Standard Frappe report-builder queries work out of the box:

```
/app/integration-request/view/list?integration_request_service=anthropic&reference_doctype=Document Capture
```

Operators can filter by status, group by date, drill into individual calls — all using the built-in Integration Request list view. No custom report module needed.

---

## 6. Security

### 6.1 API key handling

- Stored on the **shared `AI Provider Settings` Single DocType** (System Manager–only read/write — see §4.1), as a Frappe `Password` field → encrypted at rest via Frappe's standard encryption using the site's `encryption_key`.
- Retrieved at extraction time via the helper `get_ai_credentials("anthropic")` in `erpnext/ai/credentials.py`, which internally calls `frappe.utils.password.get_decrypted_password("AI Provider Settings", "AI Provider Settings", "anthropic_api_key")`.
- AP Managers configuring `AP Closed Loop Settings` cannot read the key — they can only choose which provider this *feature* uses; the credential is invisible to their role.
- **Never** logged. **Never** included in `ocr_raw_response`, `error`/`data`/`request_headers` on Integration Request, or any other field.
- The adapter holds the key in process memory only for the duration of one API call.

### 6.2 PII in invoices

Invoices contain supplier names, addresses, tax IDs, bank account numbers. Two responses required:

- **Document the data flow.** Anthropic's [Privacy Center](https://privacy.anthropic.com) and [Data Usage Policy](https://www.anthropic.com/legal/commercial-terms) describe the standard handling. For customers with stricter requirements, enable Anthropic's **Zero Data Retention (ZDR)** — per [PDF Support](https://platform.claude.com/docs/en/build-with-claude/pdf-support), PDF processing is ZDR-eligible. ZDR means data sent through the API is not stored after the response returns.
- **Make ZDR a customer-facing setting.** Add to `AP Closed Loop Settings`: `anthropic_zdr_enabled` (Check, default 0). When checked, the adapter requests ZDR-enabled processing (verifies the org has ZDR provisioned). Document in `FORK-CHANGES.md` that enabling this is the customer's responsibility per their Anthropic contract.

### 6.3 What we never store

- The decrypted API key
- The exact prompt content if it ever includes customer data (it doesn't in this design — the prompt is fixed template)
- Anything from `frappe.local.request` that could leak session info

### 6.4 Log redaction

The `error`, `data`, `request_headers`, and `response_headers` fields on an `Integration Request` row may contain provider error responses or echoed headers. Sanitize before storing: strip `x-api-key`, any `authorization` header echo, and any field matching `/api[_-]?key/i`. Simple regex pass at write time inside `extractors/audit.py`'s `write_integration_request` helper. Same sanitization applies to anything we write to `ocr_raw_response` on the capture.

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

The existing `test_document_capture.py` suite uses `FakeExtractor` by default (via the L14 flag). These tests should keep passing untouched after the refactor.

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

### Phase 0 — `AI Provider Settings` DocType + credentials helper

**Goal:** Stand up the shared infrastructure for AI credentials so subsequent phases (and future AI features) read from one place. No behavior change visible to users.

**Files added:**
- `erpnext/ai/__init__.py`
- `erpnext/ai/doctype/ai_provider_settings/` (full DocType: `__init__.py`, `.json`, `.py`) — per §4.1
- `erpnext/ai/credentials.py` — `get_ai_credentials(provider: str) -> AICredentials` helper; `AICredentialsNotConfigured` exception
- `erpnext/ai/tests/test_credentials.py` — verifies the helper retrieves a stored key, raises clearly when unset, and never echoes the key in any exception message

**Files modified:**
- `erpnext/modules.txt` — register the new `AI` module

**Acceptance criteria:**
- Navigating to `/app/ai-provider-settings` as System Manager renders the form; navigating as Accounts Manager returns 403 (permissions correct).
- `get_ai_credentials("anthropic")` returns a non-empty key after one is stored and saved.
- `get_ai_credentials("anthropic")` raises `AICredentialsNotConfigured` with a helpful message (no key echoed) when the field is empty.
- `bench --site … console` → `from erpnext.ai.credentials import get_ai_credentials; get_ai_credentials("anthropic")` works as expected after manual setup.

**Estimate:** half a day.

### Phase 1 — Adapter infrastructure (no behavior change)

**Goal:** Refactor the existing fake extractor behind the `OCRProvider` interface. The cascade, the form, and the tests all behave identically.

**Files added:**
- `extractors/__init__.py`
- `extractors/base.py` — `OCRProvider` ABC + `ExtractionResult` dataclass
- `extractors/fake.py` — `FakeExtractor(OCRProvider)` wrapping the current `fake_extract`
- `extractors/registry.py` — `get_extractor(name)` → `FakeExtractor` for now (only one provider)

**Files modified:**
- `document_capture.py` — `run_fake_extraction` renamed to `run_extraction`, dispatches through `get_extractor("fake")`
- `walking_skeleton.py` — `fake_extract` remains, internally consumed by `FakeExtractor`

**Acceptance criteria:**
- All existing tests in `test_walking_skeleton.py` and `test_document_capture.py` pass without modification.
- `bench --site … console` → `from erpnext.accounts.ap_closed_loop.extractors.registry import get_extractor; get_extractor("fake").name()` returns `"fake"`.
- No production data behavior changes; the cascade still calls into the same extraction flow, just one indirection deeper.

**Estimate:** half a day.

### Phase 2 — `AnthropicExtractor` v1 (single model, no fallback)

**Goal:** A working `AnthropicExtractor` callable from a `bench execute` command. Hardcoded model (`claude-haiku-4-5-20251001`); API key read via `get_ai_credentials("anthropic")` from `AI Provider Settings` (built in Phase 0). No fallback yet. No audit log yet.

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
- With an `anthropic_api_key` populated in `AI Provider Settings`, `bench --site … execute erpnext.accounts.ap_closed_loop.extractors.anthropic.smoke_test` extracts a fixture PDF and prints a valid `ExtractionResult`.
- With the key empty, the same command raises `AICredentialsNotConfigured` with a clear message and does not call Anthropic.
- Unit tests cover: tool_use block parsing, schema validation, null/None handling, missing-tool-use error, malformed response error.
- Live integration test passes against all 3 fixtures.
- Failing API call (mocked) does not corrupt any DocType state.

**Estimate:** 1–1.5 days.

### Phase 3 — `AP Closed Loop Settings` feature integration

**Goal:** Provider, model, fallback model, threshold, and per-file guards are configurable via `AP Closed Loop Settings`. `run_extraction` reads provider + model from `AP Closed Loop Settings` and fetches the key via the Phase 0 helper.

**Files modified:**
- `ap_closed_loop_settings.json` — add the fields listed in §4.2 (no `anthropic_api_key` here — that's in `AI Provider Settings`)
- `ap_closed_loop_settings.py` — `validate()` enforces "if `ocr_provider = Anthropic Claude`, `AI Provider Settings.anthropic_api_key` must be non-empty" via the helper. Validation message points the operator to the right form; does NOT echo the key.
- `document_capture.py` — `run_extraction` reads `ocr_provider`, `ocr_model`, `ocr_fallback_model`, `ocr_confidence_threshold` from `AP Closed Loop Settings`; reads the credential via `get_ai_credentials("anthropic")`.

**Acceptance criteria:**
- Setting `ocr_provider = "Anthropic Claude"` in `AP Closed Loop Settings` and triggering an extraction uses Claude (key sourced from `AI Provider Settings`).
- Setting `ocr_provider = "Fake (Deterministic)"` reverts to the existing fake flow (no API call).
- Saving `AP Closed Loop Settings` with `ocr_provider = "Anthropic Claude"` while `AI Provider Settings.anthropic_api_key` is empty fails validation with a message that names `AI Provider Settings` as the place to fix it. The validation message does not contain the key.
- An Accounts Manager can save `AP Closed Loop Settings` but cannot open `AI Provider Settings` (permission boundary holds).
- API key is encrypted in the DB on `AI Provider Settings` — verify the stored value in `tabPassword` is not plaintext.

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

### Phase 5 — Audit log + cost tracking (via Integration Request)

**Goal:** Every extraction call produces an `Integration Request` row keyed by the capture. Cost estimate computed from `usage.input_tokens` / `usage.output_tokens` and stored in the row's `output` JSON. Cross-capture cache hits logged distinctly.

**Files added:**
- `extractors/pricing.py` — completed pricing table (Haiku 4.5, Sonnet 4.7, Opus 4.7)
- `extractors/audit.py` — `write_integration_request(capture, result, http_meta)` helper that creates the Integration Request row with sanitized payloads
- `extractors/test_audit.py` — verifies row creation, field mapping, sanitization (no API key in any field), cost estimate accuracy

**Files modified:**
- `extractors/base.py` — `ExtractionResult` includes `latency_ms`, `input_tokens`, `output_tokens` (as noted in §3.2)
- `extractors/anthropic.py` — populates those fields from `response.usage`; calls `write_integration_request` after each call (success or failure)
- `document_capture.py` — `run_extraction` calls `write_integration_request` once per call, including the cache-hit path from §3.7

**Acceptance criteria:**
- One Anthropic call produces exactly one Integration Request row with `integration_request_service = "anthropic"`, `reference_doctype = "Document Capture"`, `reference_docname = capture.name`.
- Cross-capture cache hits produce a row with `status = "Completed"`, `output.outcome = "cache_hit"`, `output.source_capture` populated; no Anthropic call is made.
- Cost estimate matches a manual hand-calculation for a known fixture (within rounding).
- `request_headers` and `error` contain no `x-api-key` or `authorization` substring (sanitization test).
- The standard list view at `/app/integration-request` filtered by `integration_request_service=anthropic` shows the capture's calls without any custom view code.

**Estimate:** half a day (lighter than the original plan — no new DocType to design, schema-migrate, or document).

### Phase 6 — Production hardening

**Goal:** Retry policy, circuit breaker, error redaction, ZDR signaling, file-size guard, all per §3.8, §3.9, §6.

**Files modified:**
- `extractors/anthropic.py` — retry + circuit breaker; reads `anthropic_zdr_enabled` from `AI Provider Settings` via the credentials helper and passes the appropriate header to the SDK when set
- `document_capture.py` — file-size guard before calling extractor (uses `ocr_max_file_mb` from `AP Closed Loop Settings`)
- (No new field on `AP Closed Loop Settings` — `anthropic_zdr_enabled` was already added on `AI Provider Settings` in Phase 0 since it's an org-level flag, not an AP-feature flag.)

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
| Frappe encryption key rotation breaks stored API key on `AI Provider Settings` | Low | Medium | Standard Frappe Password field handles this via re-encryption hooks. Document in the operator runbook (Phase 7) that key rotation requires re-entering the Anthropic key in `AI Provider Settings`. |
| AP Manager mistakenly believes they need an Anthropic key (because earlier docs put it on the AP DocType) | Low (post-rollout) | Low | Phase 7 docs explicitly explain the split: provider choice lives on `AP Closed Loop Settings`; credentials live on `AI Provider Settings`. Validation error message in Phase 3 names `AI Provider Settings` as the place to fix it. |

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
- Frappe `Integration Request` DocType — source: `apps/frappe/frappe/integrations/doctype/integration_request/` (canonical outbound-API audit pattern, reused in §5 instead of building a new DocType)
- Frappe `File.content_hash` — source: `apps/frappe/frappe/core/doctype/file/file.py:516` (`generate_content_hash`) and `apps/frappe/frappe/core/doctype/file/utils.py:186` (`get_content_hash`) — reused in §3.7 instead of building a separate cache
- Frappe queue-level retry — source: `apps/frappe/frappe/utils/background_jobs.py:278-290` (`execute_job` retry on Redis/connection failures) — cited in §3.8
- Frappe `Currency` DocType — source: `apps/frappe/frappe/geo/doctype/currency/` — used in §3.6 for ISO 4217 validation via `frappe.db.exists("Currency", code)`
- `frappe.utils.getdate()` — robust multi-format date parser, used in §3.6 to normalize Claude's date output
- Frappe Password field encryption — source: `apps/frappe/frappe/utils/password.py` (`get_decrypted_password`)

### Repo-internal
- `docs/planning/ocr-provider-choice-claude.md` — the WHY behind choosing Claude
- `docs/architecture/FORK-CHANGES.md` §6.4 — current Document Capture pipeline
- `docs/architecture/FORK-CHANGES.md` §6.6 — auto-progression cascade mechanics
- `docs/planning/v16-upgrade-business-case.md` — deployment context
- `docs/planning/local-v17-to-v16-migration-plan.md` — confirms the fork is on v16 where this lands
- `CLAUDE.md` — grounding + working rules
- `erpnext/accounts/doctype/document_capture/document_capture.py` (lines ~650–720) — `run_fake_extraction` integration point
- `erpnext/accounts/ap_closed_loop/walking_skeleton.py` (line ~124) — `fake_extract` underlying function
- `erpnext/accounts/doctype/ap_closed_loop_settings/` — Single DocType extended by §4

### Benchmarks (referenced in choice doc)
- [AIMultiple Research — Invoice OCR Benchmark](https://aimultiple.com/invoice-ocr)
- [DEV Community — JSON Extraction Benchmark](https://dev.to/shaun_vd_7562913ba77e1e0b/claude-sonnet-46-vs-gpt-41-vs-gemini-25-flash-which-wins-json-extraction-poa)
