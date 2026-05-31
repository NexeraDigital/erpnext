---
spec: 04-extraction-confidence-line-items
title: Extraction — Numeric Per-Field Confidence + Line Items
plan_step: Step 3 — AI Extraction with Per-Field Confidence (and line items)
stream: both
status: Draft
depends_on: [01-foundations-settings-async-idempotency]
related: [00-overview, 02-intake-stream-tagging, 03-deduplication, 06-gl-coding-tax-costcenter, 07-classification-doctype-branching, 08-validation-gates, 09-confidence-routing, 10-ap-review-observability]
---

# 04 — Extraction — Numeric Per-Field Confidence + Line Items
> _Revised 2026-05-31: applied native-vs-custom review findings._

## 1. Summary
This spec EXTENDS the already-shipped real-OCR provider stack (Anthropic Claude via forced tool use, with retry / circuit breaker / file-size guard / Integration-Request audit / Haiku→Sonnet fallback) to (a) persist a **numeric per-field confidence score** for every extracted field and (b) extract and persist **line items**, subtotal, tax, and any visible PO reference. It implements **Step 3** of `docs/planning/workflow-v2-plan.md`. It is stream-agnostic at the *extraction* surface (both Stream R receipts and Stream I invoices get scored line-level extraction) but the line-item write-back on promote diverges by stream (Stream I → Purchase Invoice item rows; Stream R → handled by [[07-classification-doctype-branching]]'s Journal Entry path, out of scope here). **Current-state delta:** the Anthropic model already *returns* `confidence_per_field` but the extractor **discards the numbers** (only deriving missing/ambiguous SETS), and there is **no line-item extraction at all** — this spec stops discarding the scores, adds two new child tables, and makes promote line-aware.

## 2. Plan alignment

> **Step 3 — AI Extraction with Per-Field Confidence.** "A narrow AI layer reads the document and extracts structured fields: vendor name, invoice or receipt number, date, **line items, subtotal, tax, total, and any visible PO or account reference**. The extractor returns a confidence score **per field**, not just per document — extraction systems routinely produce a confident total while hallucinating the vendor, so a single document-level score is not safe to route on. The AI is scoped to extraction only; humans remain in control of validation and decisioning." (`docs/planning/workflow-v2-plan.md` §"Step-by-Step Walkthrough" item 3)

Relevant **Control Summary** rows (`workflow-v2-plan.md` §"Control Summary"):

| Control | Where it lives | Why it matters |
|---|---|---|
| Per-field confidence scoring | Step 3 | Routes safely; catches hallucinations |
| Async background queue (`frappe.enqueue`) | Steps 3, 12 | Keeps UI responsive during AI extraction and bank-feed sync |

Relevant **Key Design Principle**:

> "**Per-field confidence, not document-level.** LLM extractors are poorly calibrated at document level; per-field scores routed against independent thresholds is the published best practice." (`workflow-v2-plan.md` §"Key Design Principles")

**Stream R vs Stream I divergence here:** The extraction pass itself is **stream-agnostic** — both streams produce the same `AP Invoice Capture Confidence` rows and `AP Invoice Capture Item` rows. The divergence is downstream: line-item rows are consumed by `promote_to_purchase_invoice` (Stream I → real PI item rows; this spec). For Stream R receipts, the equivalent posting is a Journal Entry built by [[07-classification-doctype-branching]] — that consumer reads the same `line_items` rows but is out of scope here. The numeric confidence rows feed [[09-confidence-routing]] identically for both streams; the per-line `po_reference` feeds [[08-validation-gates]] three-way match, which is Stream-I-relevant only (receipts have no PO).

## 3. Current state

What is **shipped** (verified against the code on branch `russ/migrateToV16`, erpnext `16.20.0`):

- **Extraction seam (do NOT redesign).** `ExtractionResult` dataclass at `erpnext/accounts/ap_closed_loop/extractors/base.py:41-65` — exact current fields:
  ```python
  @dataclass
  class ExtractionResult:
      proposal: dict
      missing_fields: set[str] = field(default_factory=set)
      ambiguous_fields: set[str] = field(default_factory=set)
      provider_name: str = ""
      raw_response: dict = field(default_factory=dict)
  ```
  `PROPOSAL_KEYS = ("supplier","supplier_invoice_no","invoice_date","total_amount","currency")` at `base.py:32-38`. `OCRProvider` ABC at `base.py:68-89` defines `name()` and `extract(capture, *, simulate_missing=None, simulate_ambiguous=None) -> ExtractionResult`.
- **Registry seam.** `registry.py:21-24` — `_PROVIDERS = {"fake": FakeExtractor, "anthropic": AnthropicExtractor}`; `get_extractor(name="fake", **kwargs)` (`registry.py:27-42`) forwards ctor kwargs and raises `ValueError` on an unknown key.
- **Anthropic provider already asks for per-field confidence but discards the numbers.** `INVOICE_EXTRACTION_TOOL` at `anthropic.py:125-165` has a `confidence_per_field` object property (one number per header field) and `"required": ["confidence_per_field"]`; the tool description encodes the scale (`1.0` unambiguous / `0.7` legible-unverified / `0.4` partial/ambiguous / `0.0` absent). `_TOOL_TO_LOGICAL` at `anthropic.py:168-174` maps tool field names → proposal keys. `_to_extraction_result` at `anthropic.py:417-452` reads `tool_input.get("confidence_per_field")` and uses it ONLY to add fields to the `ambiguous` set when `conf < self._confidence_threshold` (`anthropic.py:431-433`) — **the numeric scores are then thrown away**. Retry/backoff (`anthropic.py:288-321`), process-local circuit breaker, file-size guard, audit Integration Request, and the one-shot fallback (`anthropic.py:264-272`) are all present.
- **Fake provider** at `fake.py:28-83` — deterministic, hash-seeded, honours `simulate_missing` / `simulate_ambiguous`, returns NO confidence and NO lines today. Default extraction yields `missing_fields == set()`, `ambiguous_fields == set()`.
- **Controller.** `run_extraction(capture, *, simulate_missing, simulate_ambiguous, save=True)` at `ap_invoice_capture.py:671-835`: reads `get_ocr_config()` (`:712`), calls `get_extractor(...).extract(...)` (`:742-751`), writes `proposed_*` fields (`:795-807`), writes `proposed_missing_fields` / `proposed_ambiguous_fields` as comma-joined strings (`:802-807`), and writes `ocr_raw_response` JSON (`:813-826`) containing provider / extracted_at / proposal / missing_fields / ambiguous_fields / model / outcome / usage — **no credentials persisted** (the API key is fetched lazily in `anthropic._get_client` at `anthropic.py:218-230` and never stored). Sets `ocr_status=Proposed`, `status=Proposed`, `action_required=1`. Alias `run_fake_extraction = run_extraction` (`:840`).
- **Async already in place.** The auto-progression cascade enqueues each step via `frappe.enqueue(wrapper_path, capture=self.name, method_name=..., queue="short", job_id=f"ap-progress-{self.name}-{method_name}", deduplicate=True, enqueue_after_commit=not in_test, now=in_test)` at `ap_invoice_capture.py:395-404` (wrapper `..._run_cascade_step`). Under `frappe.flags.in_test` the job runs synchronously inside the rollback boundary. **No new enqueue is needed** — the new write-back happens inside the same already-enqueued `run_extraction` job.
- **promote_to_purchase_invoice** at `ap_invoice_capture.py:1148-1235`: builds a **single header-level item row** — `{"item_code": d.get("item_code","_Test Item"), "qty": float(d.get("qty",1) or 1), "rate": float(capture.final_total_amount or 0.0)}` (`:1201-1207`), optionally adds uom/warehouse/expense_account/cost_center, then `pi.append("items", item_row)` (`:1220`). The docstring (`:1161-1164`) explicitly states line-level PO/PR matching is out of scope and PO/PR refs stay on the capture only (`:1217-1219`). Preconditions: `validation_status == Validated`, `matched_supplier` set, not already promoted.
- **Parent doctype fields.** `purchase_order_reference: DF.Link` and `purchase_receipt_reference: DF.Link` already exist (`ap_invoice_capture.py:195-196`); `final_total_amount: DF.Float` (`:160`); `ocr_raw_response: DF.LongText` (`:165`). **The AP Invoice Capture DocType JSON currently has ZERO child tables** (no `fieldtype: Table` rows) — both new child tables and both new parent Table fields are genuinely new.
- **Settings.** `get_ocr_config()` at `ap_closed_loop_settings.py:111-148` returns `{provider, model, fallback_model, confidence_threshold, max_file_mb, force_reextract}`. The **only** confidence field today is `ocr_confidence_threshold` (Float, JSON at `ap_closed_loop_settings.json:115-116`; resolved at `:127-133` with `DEFAULT_OCR_CONFIDENCE_THRESHOLD = 0.70` and a `threshold <= 0 → default` guard). **There is NO `per_field_confidence_threshold` and NO `field_thresholds` field yet** — both must be added.

**Correction to the brief:** none. Every line reference and field shape in the research brief was confirmed against the code. One precision note: the Anthropic `confidence_per_field` block is **not** in the tool's top-level `"required"` array for individual sub-fields — only the `confidence_per_field` object itself is required (`anthropic.py:163`), and its inner properties are optional, so the write-back code must treat any missing inner score as "absent" and fall through to the mapping fallback (§5.3). This is consistent with the brief but worth stating so the build doesn't assume every field always carries a number.

## 4. Upstream grounding

| URL | Confirms | Quoted signature / section |
|---|---|---|
| https://docs.frappe.io/framework/v15/user/en/basics/doctypes/child-doctype | Child-table (istable) mechanics for the two new child DocTypes. A DocType becomes a child by checking **Is Child Table**; the parent references it via a field of fieldtype **Table** with **options** = the child DocType name; child rows persist via `parent`/`parenttype`/`parentfield`/`idx`. | "To make a Child DocType make sure to check **Is Child Table** while creating the doctype." … "To link a Child Doctype to its parent, add another row in Parent Doctype with field type **Table** and options as **Child Table**." … special properties: `parent` (name of the parent), `parenttype` (DocType of the parent), `parentfield` (field in the parent that links this child), `idx` (sequence/row). **(verified — fetched 2026-05-30)** |
| `erpnext/accounts/doctype/purchase_invoice_item/purchase_invoice_item.json` (local, this bench, erpnext 16.20.0) — equivalent to https://github.com/frappe/erpnext/blob/version-16/erpnext/accounts/doctype/purchase_invoice_item/purchase_invoice_item.json | Field shapes to mirror for `AP Invoice Capture Item` AND the exact PI-item fieldnames `promote_to_purchase_invoice` must populate. The local JSON IS the v16 source of truth this fork ships against. | Verified field block read locally: `description: Text Editor`; `qty: Float`; `rate: Currency options=currency`; `amount: Currency options=currency`; `expense_account: Link options=Account`; `cost_center: Link options=Cost Center`; `item_tax_amount: Currency options=Company:company:default_currency`; `purchase_order: Link options=Purchase Order`; `po_detail: Data`; `purchase_receipt: Link options=Purchase Receipt`; `pr_detail: Data`. **(verified — read on bench 16.20.0)** Note: PI's line→PO link is **two** fields — `purchase_order` (Link) + `po_detail` (Data, the PO Item child rowname). The capture-side `po_reference` (Link→Purchase Order) maps to PI Item `purchase_order`; `po_detail` is line granularity OCR does not produce (see §8 / [[08-validation-gates]]). |
| https://github.com/frappe/frappe/blob/version-15/frappe/utils/background_jobs.py | Authoritative `frappe.enqueue` signature — every kwarg the existing cascade already passes (`queue`, `timeout`, `now`, `enqueue_after_commit`, `job_id`, `deduplicate`). The docs.frappe.io background-jobs HTML page 404s on every path variant tried (see §8 risk), so per CLAUDE.md fallback the GitHub source is the standing citation. The async write-back pattern for this spec is exactly what is already shipped at `ap_invoice_capture.py:395-404`. | `def enqueue(method: str | Callable, queue: str = 'default', timeout: int | None = None, event=None, is_async: bool = True, job_name: str | None = None, now: bool = False, enqueue_after_commit: bool = False, *, on_success: Callable | None = None, on_failure: Callable | None = None, at_front: bool = False, job_id: str | None = None, deduplicate=False, **kwargs) -> Job | Any:` **(verified — GitHub source)** |
| https://docs.frappe.io/framework/v15/user/en/python-api/background-jobs | INTENDED canonical docs page for the async write-back pattern. **It 404s** (as do `/python-api/background_jobs`, `/background_jobs`, `/api/jobs`, and the non-versioned `/framework/user/...` variant). Recorded here per the grounding rule; the GitHub source above is the substitute. No quote — page is unavailable. | _(verified=false; canonical URL recorded, no fabricated quote)_ |

## 5. Design

### 5.1 Data model

**Two new child DocTypes** (both `istable = 1`, under `erpnext/accounts/doctype/`, each referenced from `AP Invoice Capture` via a new `fieldtype: Table` parent field). Mirror the fork's existing DocType JSON style (auto-generated `DF` type block inside the controller, `IntegrationTestCase` tests). Child rows persist via `parent`/`parenttype`/`parentfield`/`idx` per the child-doctype citation. No naming series (child tables are not independently named). Permissions are inherited from the parent `AP Invoice Capture` (child tables have no standalone permission table); no separate role grants.

**(A) `AP Invoice Capture Confidence`** (`istable=1`) — persists the numeric per-field confidence the Anthropic tool already returns but currently discards.

| fieldname | fieldtype | options / default | purpose |
|---|---|---|---|
| `field_name` | Data | (in_list_view, reqd) | Logical field key. Header rows: `supplier` / `supplier_invoice_no` / `invoice_date` / `total_amount` / `currency`. Line rows: `line_<i>_<field>` (0-based `i`, e.g. `line_0_amount`). |
| `confidence` | Float | (precision 3; in_list_view) | Numeric score in `0.0`–`1.0`. The dB column holding the model's per-field certainty. |
| `is_above_threshold` | Check | `read_only=1`, `description="Derived: confidence >= the per-field threshold at write time. Not user-entered."` | **Computed at write time** (§5.3 resolution order). Read-only so reviewers see it is derived. |
| `score_source` | Select | options `Model\nDerived-Mapping`; default `Model`; `read_only=1` | Provenance: `Model` = real numeric score from the provider; `Derived-Mapping` = heuristic clear/ambiguous/missing → 0.95/0.5/0.0 stand-in (so [[09-confidence-routing]] does not over-trust a fallback). |

New parent field on `AP Invoice Capture`: `field_confidences` (Table → `AP Invoice Capture Confidence`).

**Division of labor — child table vs `ocr_raw_response` JSON (why both exist).** The `AP Invoice Capture Confidence` child table is the **routing / query index**: [[09-confidence-routing]] filters on the per-row `is_above_threshold` Check, which a relational `WHERE` can index and a Report Builder column can surface. The raw numeric scores ALSO already land in the existing `ocr_raw_response` LongText (`erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.py:165`), which serves as the **audit copy-of-record**. So the split is deliberate: **child table = routing surface (filterable/reportable); `ocr_raw_response` JSON = audit-of-record (immutable provider echo).** This is precisely what justifies the child table on **queryability** grounds — a JSON blob on the parent is not filterable or reportable, so it cannot drive routing even though it already holds the same numbers.

**(B) `AP Invoice Capture Item`** (`istable=1`) — mirrors Purchase Invoice Item's narrow shape (verified field block, §4).

| fieldname | fieldtype | options / default | purpose |
|---|---|---|---|
| `description` | Text Editor | (in_list_view) | Line description / item text (mirrors PI Item `description`). |
| `qty` | Float | default `1` | Quantity (mirrors PI Item `qty`). |
| `rate` | Currency | options `currency` | Unit rate (mirrors PI Item `rate`). |
| `amount` | Currency | options `currency` | Line amount = qty × rate (mirrors PI Item `amount`). |
| `tax_amount` | Currency | options `currency` | Per-line tax. **Narrowed** from PI Item's `item_tax_amount` (which uses `Company:company:default_currency`) to a plain `Currency` because the capture has no company-currency context at extraction time (see §8 decision D5 / risk 4). Company-currency binding deferred to promote. |
| `expense_account` | Link | options `Account` | Per-line expense account (mirrors PI Item `expense_account`); populated by [[06-gl-coding-tax-costcenter]] if known. |
| `cost_center` | Link | options `Cost Center` | Per-line cost center (mirrors PI Item `cost_center`). |
| `po_reference` | Link | options `Purchase Order` | Visible PO ref for this line. Maps to PI Item `purchase_order` on promote; join key for [[08-validation-gates]] three-way match. |
| `pr_reference` | Link | options `Purchase Receipt` | Visible PR ref for this line. Maps to PI Item `purchase_receipt` on promote. |
| `currency` | Data | `read_only=1`, `hidden=1` | Backing field for the `Currency` `options=currency` on `rate`/`amount`/`tax_amount`. Set to `final_currency` at write-back so the child renders/totals in the right symbol. |
| `confidence_summary` | Small Text | `read_only=1` | Human-readable per-line confidence blurb (e.g. `desc 0.95 / amount 0.88 / po 0.40`) for at-a-glance review. The authoritative numbers live in `AP Invoice Capture Confidence` keyed `line_<i>_<field>`. |

New parent field on `AP Invoice Capture`: `line_items` (Table → `AP Invoice Capture Item`).

**New parent header fields on `AP Invoice Capture`** (surface subtotal/tax and ensure the PO ref is populated):

| fieldname | fieldtype | options / default | purpose |
|---|---|---|---|
| `subtotal_amount` | Currency | options `final_currency` | Extracted pre-tax subtotal. Feeds [[06-gl-coding-tax-costcenter]] tax autoselect. |
| `tax_amount` | Currency | options `final_currency` | Extracted total tax. Feeds [[06-gl-coding-tax-costcenter]] tax autoselect. |
| `purchase_order_reference` | Link → Purchase Order | **already exists** (`ap_invoice_capture.py:195`) | This spec **populates** it from the visible header PO ref so [[08-validation-gates]] three-way match unlocks. No schema change — write-back change only. |

**Settings additions to `AP Closed Loop Settings`** (the single canonical settings DocType — do NOT invent a competing one):

| fieldname | fieldtype | options / default | purpose |
|---|---|---|---|
| `per_field_confidence_threshold` | Float | default = `DEFAULT_OCR_CONFIDENCE_THRESHOLD` (0.70); precision 3 | Scalar per-field threshold for `is_above_threshold`. Second tier of the resolution chain (§5.3). |
| `field_thresholds` | Small Text / Code (JSON) | default empty | Optional per-field-name override map, JSON `{"supplier": 0.85, "total_amount": 0.90}`. First tier of the resolution chain. (Decision D3: JSON Code field vs a child table — recommend Code/JSON for v1.) |

`get_ocr_config()` (`ap_closed_loop_settings.py:111-148`) MUST surface both new keys (e.g. `per_field_confidence_threshold`, `field_thresholds` parsed to a dict) **in addition to** the existing keys so existing callers (`run_extraction`, Anthropic ambiguous-flagging) keep working unchanged. **Backward-compat (mandatory):** keep `ocr_confidence_threshold` as the FINAL fallback — the shipped Anthropic ambiguous-flagging (`anthropic.py:432`) reads `confidence_threshold` from `get_ocr_config`; removing or renaming it breaks shipped behaviour.

**Credentials:** `ocr_raw_response` already excludes the API key (`run_extraction:813-826` writes only provider/proposal/missing/ambiguous/model/outcome/usage; the key is fetched lazily and never stored). Line-item / confidence persistence MUST NOT echo credentials — preserve this (asserted as a security test, §7.1).

### 5.2 Endpoints

No new whitelisted endpoint is introduced; this spec extends one existing module-level function and (optionally) the settings config reader. Signatures (full dotted paths) — **unchanged signatures, extended behaviour**:

```python
# erpnext.accounts.doctype.ap_invoice_capture.ap_invoice_capture
def run_extraction(
    capture: "APInvoiceCapture | str",
    *,
    simulate_missing: list[str] | tuple[str, ...] | None = None,
    simulate_ambiguous: list[str] | tuple[str, ...] | None = None,
    save: bool = True,
) -> "APInvoiceCapture":
    ...  # EXTENDED: also rebuilds field_confidences + line_items child rows and
        # sets subtotal_amount/tax_amount/purchase_order_reference (see §5.3)

def promote_to_purchase_invoice(
    capture: "APInvoiceCapture | str",
    actor: str | None = None,
    defaults: dict | None = None,
    save: bool = True,
) -> "Document":
    ...  # EXTENDED: branches on capture.line_items — one PI item per capture
        # line when present; preserves the single-header-line fallback otherwise
```

```python
# erpnext.accounts.doctype.ap_closed_loop_settings.ap_closed_loop_settings
def get_ocr_config() -> dict:
    ...  # EXTENDED return dict gains: "per_field_confidence_threshold": float,
        # "field_thresholds": dict[str, float]  (existing keys unchanged)
```

**String/dict normalization convention** carried across this controller (preserve it): `run_extraction` and `promote_to_purchase_invoice` both accept either an `APInvoiceCapture` doc OR its `name` string, and resolve a string via `frappe.get_doc("AP Invoice Capture", capture)` as the first line (`ap_invoice_capture.py:701-702`, `:1167-1168`). New code paths must keep this `isinstance(capture, str)` resolution and must not assume a doc was passed.

The **dataclass extension** (not an endpoint, but the contract every provider returns) — `ExtractionResult` at `base.py:41-65` gains two fields, both with default factories so existing positional/keyword construction stays valid:

```python
confidence: dict = field(default_factory=dict)  # logical_key -> float in 0..1;
                                                # line rows keyed "line_<i>_<field>"
lines: list[dict] = field(default_factory=list) # each: description/qty/rate/amount/
                                                # tax_amount/expense_account/cost_center/
                                                # po_reference/pr_reference/confidence(dict)
```

### 5.3 Logic

**(1) `ExtractionResult` extension** (`base.py`). Add `confidence: dict` and `lines: list[dict]`, both `field(default_factory=...)`. No other change. Existing tests that construct `ExtractionResult(proposal=..., missing_fields=..., ...)` stay valid because both new fields default.

**(2) Anthropic provider** (`anthropic.py`):
   1. Extend `INVOICE_EXTRACTION_TOOL.input_schema.properties` (`anthropic.py:133-162`): add nullable header props `subtotal` (`["number","null"]`), `tax_total` (`["number","null"]`), `po_reference` (`["string","null"]`); add a `line_items` array property whose items are objects with `description`/`qty`/`rate`/`amount`/`tax_amount`/`expense_account`/`cost_center`/`po_reference` and a per-line `confidence` object (one number per line field). Keep `confidence_per_field` and the forced `tool_choice` (`anthropic.py:305`). Do NOT add the new fields to top-level `"required"` (keep only `confidence_per_field` required, so the model may omit lines for a receipt with no itemization).
   2. In `_to_extraction_result` (`anthropic.py:417-452`): **stop discarding the scores.** Populate `result.confidence` from `tool_input["confidence_per_field"]` keyed by the **logical** name (via `_TOOL_TO_LOGICAL`); populate `result.lines` from `tool_input.get("line_items") or []`, and for each line `i` emit its per-field confidence into `result.confidence["line_<i>_<field>"]`. Set header `subtotal`/`tax_total`/`po_reference` into a known place on `result` (carry them in `result.proposal` under new logical keys `subtotal`/`tax`/`po_reference`, or as attributes the controller reads — recommend `proposal` keys for uniformity). Keep the existing missing/ambiguous derivation untouched (`anthropic.py:425-433`).
   3. **Mapping fallback** (providers that emit NO numeric scores): when `confidence_per_field` (or a per-line `confidence`) is absent for a field, derive it from clarity — present-and-clear ≈ `0.95`, ambiguous ≈ `0.5`, missing/None = `0.0` — and tag those rows `score_source = "Derived-Mapping"`. This is a documented stand-in, NOT a real model confidence (risk 7). Anthropic itself emits real scores → `score_source = "Model"`.
   4. The `_breaker` / retry / file-size / audit / fallback paths are untouched. `result.raw_response` may gain `confidence`/`lines` keys for the audit log but MUST keep excluding credentials.

**(3) Fake provider** (`fake.py:45-83`): keep deterministic. Assign `result.confidence` from its own sets — `field in missing_fields → 0.0`; `field in ambiguous_fields → 0.5`; otherwise `0.95` (one entry per `PROPOSAL_KEYS` logical name). Tag all as `score_source = "Derived-Mapping"`. Leave `lines = []` by default so the existing `TestFakeExtractor` assertions stay byte-for-byte green; optionally emit a single deterministic synthetic line ONLY behind a new `simulate_lines` flag (default off). The default-path `missing_fields == set()` / `ambiguous_fields == set()` invariants are unchanged.

**(4) `run_extraction` write-back** (`ap_invoice_capture.py:671-835`): after the existing `proposed_*` writes (`:795-807`) and BEFORE the existing `capture.save()` (`:833-834`):
   1. **Rebuild `field_confidences`.** Clear the child table, then for each `(field_name, conf)` in `result.confidence`, append a row with `confidence = conf`, `is_above_threshold = _resolve_above(field_name, conf, ocr_config)`, `score_source` from the result. Use `capture.set("field_confidences", rows)` to replace atomically.
   2. **Rebuild `line_items`.** Clear, then for each line dict in `result.lines`, append an `AP Invoice Capture Item` row mapping description/qty/rate/amount/tax_amount/expense_account/cost_center/po_reference/pr_reference, set `currency = capture.final_currency or proposed_currency`, and build `confidence_summary` from that line's per-field confidence. For line `i`, the per-field scores are ALSO appended to `field_confidences` keyed `line_<i>_<field>` (step 1 consumes the line keys too — do steps 1 and 2 so all `result.confidence` keys, header and line, land in `field_confidences`).
   3. **Header surfaces.** Set `capture.subtotal_amount`, `capture.tax_amount` from the result's `subtotal`/`tax`; set `capture.purchase_order_reference` from the result's `po_reference` **only if** it resolves to an existing Purchase Order (guard with `frappe.db.exists("Purchase Order", value)` — a hallucinated PO string must not create a dangling Link; on no-match, leave the field blank and record the raw string in `ocr_raw_response` for review).
   4. `ocr_raw_response` JSON (`:813-826`) MAY gain `confidence` and `lines` keys but MUST keep excluding credentials (it already only serializes proposal/missing/ambiguous/model/outcome/usage).
   5. **`_resolve_above(field_name, conf, cfg)` resolution order** (idempotent, pure): (a) if `field_name` (or its line-stripped base field, e.g. `line_0_amount` → `amount`) has an entry in `cfg["field_thresholds"]`, use it; else (b) use `cfg["per_field_confidence_threshold"]`; else (c) fall back to `cfg["confidence_threshold"]` (the existing `ocr_confidence_threshold`). Return `conf >= threshold`.
   6. **Idempotency.** `run_extraction` is already re-runnable (it overwrites `proposed_*`); the child-table rebuild is a clear-and-replace, so a re-extraction (or `ocr_force_reextract`) yields the same rows for the same input — no duplicate rows accumulate. Per [[01-foundations-settings-async-idempotency]], the cascade job is deduplicated by `job_id` (`ap_invoice_capture.py:395-404`), so a retried enqueue cannot double-run.
   - **Exceptions:** the existing `OCRExtractionError` guards (`:704-707`, file-size `:739`) and the failure write-back (`:764-776`) are untouched. The new write-back adds no new guard on the happy path; a malformed `result.lines` entry (e.g. non-numeric `amount`) is coerced defensively (`float(x or 0)`), never raising mid-write-back — a bad line surfaces later at promote reconciliation (step 6 below), not here.

**(5) `promote_to_purchase_invoice` line-awareness** (`ap_invoice_capture.py:1148-1235`): after the existing preconditions (`:1170-1186`) and `_coalesce_defaults` (`:1188`), branch on `capture.line_items`:
   - **WHEN `capture.line_items` is non-empty (line-aware path):** for each `AP Invoice Capture Item` row, `pi.append("items", {...})` mapping `description`, `qty`, `rate`, `amount`, and (if set) `expense_account`/`cost_center`; map `po_reference → PI Item.purchase_order` and `pr_reference → PI Item.purchase_receipt` (verified PI-item fieldnames, §4). `po_detail`/`pr_detail` (the specific PO/PR child rowname) are **not** set — OCR gives header-PO granularity only (risk 3; [[08-validation-gates]] owns line-level PO matching). Fall back to the default `item_code` (`d.get("item_code","_Test Item")`) when a line carries no item identity, since PI items require an item code in the pilot's setup.
   - **WHEN `capture.line_items` is empty (header-line fallback — UNCHANGED):** preserve the EXACT current single-row build (`item_code` default `"_Test Item"`, `qty=1`, `rate=final_total_amount`) so `test_promote_creates_native_purchase_invoice` (`test_ap_invoice_capture.py:642-669`) stays green (`len(pi.items)==1`, `pi.items[0].item_code=="_Test Item"`, `rate≈250.00`).
   - **Reconciliation:** compute `sum(line.amount)` and compare to `capture.final_total_amount` within `0.01`. **On mismatch (decision D1):** recommended default is to NOT silently mutate — set `capture.action_required = 1` with a human reason and raise `CapturePromotionError` so the clerk reconciles before a payable is created. (Alternative options in §8.)
   - Header `purchase_order_reference` continues to ride on the capture for [[08-validation-gates]]; the per-line mapping above is the new join surface.
   - Idempotency precondition unchanged (`:1181-1186`): already-promoted captures raise `CapturePromotionError`.

### 5.4 Cascade & stream-awareness

- **`_determine_next_step` / cascade:** unchanged shape. Extraction is already a cascade step that enqueues `run_extraction` via `frappe.enqueue` (`ap_invoice_capture.py:395-404`). The new write-back executes INSIDE that same job, committed by the after-commit worker (prod) or synchronously under `in_test`. **No new enqueue, no new pause point.** The post-extraction pause is unchanged: capture lands at `status=Proposed` / `action_required=1` for AP review (the human gate), exactly as today.
- **Stream R vs Stream I:**
  - *Extraction* (this spec's write-back): **stream-agnostic.** Both streams get `field_confidences` + `line_items` rows.
  - *Promotion to PI line rows* (`promote_to_purchase_invoice`): **Stream I only.** Stream R receipts do not promote to a Purchase Invoice — their posting is a Journal Entry built by [[07-classification-doctype-branching]], which reads the same `line_items`. This spec does not build the JE path; it only guarantees the line rows exist for that consumer.
  - *`po_reference` line mapping:* relevant to **Stream I** (3WM via [[08-validation-gates]]). Stream R receipts have no PO, so `po_reference` is normally null there — harmless.
- **Resume-path cross-check:** `promote_to_purchase_invoice` is also reached via the cascade resume helper `promote_to_purchase_invoice_for` (`ap_invoice_capture.py:1687`) and exercised by the auto-approval/payment cascade test (`:1377`). The line-aware branch MUST NOT regress those — when those tests build captures without `line_items`, the fallback path keeps `len(pi.items)==1`.

### 5.5 Cross-cutting

- **Permissions / SoD:** no new role gates here. Child tables inherit `AP Invoice Capture` permissions. Extraction remains a system/`AP Clerk`-triggered action; SoD lives downstream at approval ([[11-approval-sod-workflow]]).
- **Idempotency:** via [[01-foundations-settings-async-idempotency]] — the cascade job is deduplicated by `job_id` (`ap_invoice_capture.py:395-404`); child-row rebuild is clear-and-replace so re-extraction is idempotent. Promotion is guarded against double-create by the existing already-promoted check.
- **Async / enqueue:** unchanged — reuse the shipped `frappe.enqueue(..., enqueue_after_commit=not in_test, now=in_test, deduplicate=True)` pattern (`ap_invoice_capture.py:395-404`), grounded on the `frappe.enqueue` GitHub signature (§4).
- **Observability:** when extraction yields a below-threshold field or a reconciliation mismatch at promote, the resulting `action_required` review is where [[10-ap-review-observability]] emits its `AP Review Event` with a root-cause tag (`extraction_miss` is the natural code for a misread line). This spec does not emit the event itself; it produces the signals (`is_above_threshold=0` rows, the mismatch `action_required`) the observability spec routes on. It also feeds [[09-confidence-routing]] (the numeric rows are the routing input) and [[08-validation-gates]] (per-line `po_reference`).

## 6. Acceptance criteria

- **AC-04-1 (positive, dataclass):** Constructing `ExtractionResult(proposal={...})` with no `confidence`/`lines` args yields `confidence == {}` and `lines == []`; all existing extractor tests pass unchanged.
- **AC-04-2 (positive, Anthropic confidence):** Given a mock `tool_input` carrying `confidence_per_field` with numeric scores, `_to_extraction_result` returns `result.confidence` populated with one float per logical header key, and the missing/ambiguous derivation is unchanged.
- **AC-04-3 (positive, Anthropic lines):** Given a mock `tool_input` with a `line_items` array, `result.lines` has one dict per line and `result.confidence` contains `line_<i>_<field>` keys for each line's per-field score.
- **AC-04-4 (edge, mapping fallback):** Given a mock `tool_input` with NO `confidence_per_field`, every present field gets `0.95`, ambiguous gets `0.5`, absent gets `0.0`, and those entries are tagged `score_source="Derived-Mapping"`.
- **AC-04-5 (positive, fake determinism):** `FakeExtractor.extract` on the default path returns `confidence` with `0.95` for every clear `PROPOSAL_KEYS` field, `lines == []`, and identical output across two calls; `missing_fields`/`ambiguous_fields` stay `set()`.
- **AC-04-6 (positive, write-back rows):** After `run_extraction` on a capture with a multi-field, multi-line result, `capture.field_confidences` has one row per header field plus one per `line_<i>_<field>`, and `capture.line_items` has one row per extracted line.
- **AC-04-7 (edge, is_above_threshold boundary):** With `per_field_confidence_threshold=0.70`, a field at `0.70` → `is_above_threshold=1`; at `0.699` → `0`. A `field_thresholds` entry of `{"supplier":0.90}` overrides the scalar for `supplier` only.
- **AC-04-8 (positive, resolution order):** `_resolve_above` uses `field_thresholds[field]` when present; else `per_field_confidence_threshold`; else `ocr_confidence_threshold`. A line key `line_0_amount` resolves against the `amount` base-field threshold.
- **AC-04-9 (negative/security):** After `run_extraction` with the real provider path, `json.loads(capture.ocr_raw_response)` contains NO `api_key` / credential anywhere, even with `confidence`/`lines` keys added.
- **AC-04-10 (positive, header surfaces):** When the result carries subtotal/tax/po_reference and the PO exists, `capture.subtotal_amount`, `capture.tax_amount`, and `capture.purchase_order_reference` are set; when `po_reference` does not resolve to an existing Purchase Order, `purchase_order_reference` is left blank (no dangling Link) and the raw string is in `ocr_raw_response`.
- **AC-04-11 (positive, promote line-aware):** A capture with N `AP Invoice Capture Item` rows promotes to a PI with N item rows; `po_reference`/`pr_reference` land on PI Item `purchase_order`/`purchase_receipt`; `sum(item.amount)` reconciles to `final_total_amount` within `0.01`.
- **AC-04-12 (negative, reconciliation guard):** A capture whose line amounts sum to a value differing from `final_total_amount` by > `0.01` raises `CapturePromotionError` and sets `action_required=1` (per default decision D1).
- **AC-04-13 (regression, header-line fallback):** A capture with empty `line_items` promotes to a PI with exactly one item row (`item_code=="_Test Item"`, `qty==1`, `rate≈final_total_amount`) — `test_promote_creates_native_purchase_invoice` passes unchanged.
- **AC-04-14 (regression, settings):** `get_ocr_config()` still returns all existing keys (`provider`/`model`/`fallback_model`/`confidence_threshold`/`max_file_mb`/`force_reextract`) plus the two new keys.
- **AC-04-15 (negative, unknown provider):** `get_extractor("nope")` still raises `ValueError` (registry contract unchanged).

## 7. Tests

### 7.1 Automated

Run with `bench --site <site> run-tests --module <dotted.path>`. Use `from frappe.tests import IntegrationTestCase`; roll back DB writes in `tearDown`.

**Existing suites that MUST stay green (the no-break regression proof):**
- `erpnext.accounts.ap_closed_loop.extractors.test_extractors` — esp. `test_extract_returns_extraction_result_with_all_keys` (`test_extractors.py:76-85`, asserts proposal keys present AND missing/ambiguous `== set()`), `test_simulate_missing_strips_and_flags_fields` (`:98-105`), `test_simulate_ambiguous_flags_without_stripping` (`:107-113`), `test_run_extraction_records_raw_response` (`:136`). Default-factory dataclass fields keep these green.
- `erpnext.accounts.ap_closed_loop.extractors.test_anthropic`, `test_hardening`, `test_audit`, `test_integration` — forced-tool parsing, retry/breaker, audit Integration Request still pass after the tool-schema extension.
- `erpnext.accounts.doctype.ap_invoice_capture.test_ap_invoice_capture` — `test_promote_creates_native_purchase_invoice` (`:642-669`), `test_promote_is_idempotent_guard` (`:715`), `test_promote_blocks_when_validation_failed` (`:694`), `test_promote_requires_validation_first` (`:706`), `test_promote_preserves_purchase_reference_classification` (`:673`).
- `erpnext.accounts.doctype.ap_closed_loop_settings.test_ap_closed_loop_settings` — `get_ocr_config` keeps its existing keys after the additions.

**New automated tests (co-located, `IntegrationTestCase`, roll back in `tearDown`):**
- `extractors/test_extractors.py` — FakeExtractor confidence mapping: missing→0.0, ambiguous→0.5, clear→0.95 (positive + each branch); deterministic across two calls; `lines == []` default (AC-04-5).
- `extractors/test_anthropic.py` — `_to_extraction_result` with mock `tool_input` carrying `confidence_per_field` → `result.confidence` populated (AC-04-2); with `line_items` → `result.lines` + `line_<i>_<field>` keys (AC-04-3); mapping-fallback when `confidence_per_field` absent → 0.95/0.5/0.0 + `score_source="Derived-Mapping"` (AC-04-4).
- `ap_invoice_capture/test_ap_invoice_capture.py` — `run_extraction` write-back: `field_confidences` rows with correct `is_above_threshold` at AND below a configured boundary (AC-04-6, AC-04-7); `line_items` rows created; subtotal/tax/`purchase_order_reference` set incl. the non-existent-PO no-dangling-Link case (AC-04-10); `ocr_raw_response` contains NO `api_key` (AC-04-9, security/negative).
- `ap_closed_loop_settings/test_ap_closed_loop_settings.py` — `_resolve_above` resolution order: `field_thresholds` entry wins → falls back to `per_field_confidence_threshold` → falls back to `ocr_confidence_threshold`; line key strips to base field (AC-04-8); `get_ocr_config` returns new keys (AC-04-14).
- `ap_invoice_capture/test_ap_invoice_capture.py` — promote line-aware: N capture lines → N PI items with `purchase_order`/`purchase_receipt` mapped, totals reconcile within 0.01 (AC-04-11); mismatch raises `CapturePromotionError` + sets `action_required` (AC-04-12); header-line fallback unchanged → `len(pi.items)==1` (AC-04-13).
- `extractors/test_extractors.py` — registry: `get_extractor("anthropic")`/`("fake")` resolve; unknown key raises `ValueError` (AC-04-15).

### 7.2 Clean-room test plan

Two runbooks (or one combined) under `test/testplans/`, kebab-case, self-contained for an external instance with zero prior context:
- **`test/testplans/extraction-per-field-confidence.md`** — scope: configure `AP Closed Loop Settings` (`per_field_confidence_threshold`, `field_thresholds`) + `AI Provider Settings`, run real Anthropic extraction on a sample multi-field invoice (provide SHA-256, key obtain-instructions only — never the key), assert `AP Invoice Capture Confidence` child-row counts and `is_above_threshold` values at/around the boundary, and assert `ocr_raw_response` carries no credential.
- **`test/testplans/extraction-line-items-promote.md`** — scope: run extraction on a real multi-line invoice fixture (SHA-256 given), assert `AP Invoice Capture Item` row count, then promote (Stream I) and assert PI item count, per-line `purchase_order` mapping, and totals reconciliation within 0.01 (incl. the mismatch → `action_required` negative case).

## 8. Open decisions

- **D1 — Totals reconciliation behaviour on `sum(lines) != final_total_amount`.** Options: (a) raise `CapturePromotionError` + set `action_required` (surface, don't mutate); (b) append a balancing/rounding PI line silently; (c) scale line amounts to fit. **Recommended default: (a)** — surfacing over silent mutation keeps the ledger honest and matches the "exceptions loop, they don't dead-end" principle. **Owner:** spec-04 + accounting lead. **Must lock:** before promote line-aware path is built.
- **D2 — `field_thresholds` shape.** Options: JSON Code/Small Text field on `AP Closed Loop Settings`; OR a dedicated child table `field_name → threshold`. **Recommended default: JSON Code field** for v1 (fewer DocTypes; thresholds are low-churn config). **Owner:** spec-04. **Must lock:** before the settings field is added.
- **D3 — `score_source` exposure to routing.** Should [[09-confidence-routing]] treat `Derived-Mapping` scores differently (e.g. always route to review)? **Recommended default:** record `score_source` now (this spec) and let spec-09 decide policy; do not auto-trust a derived score as straight-through. **Owner:** spec-09. **Must lock:** when spec-09 routing rules are finalized.
- **D4 — Per-line item identity.** OCR gives a description, not an ERPNext Item. Options: always use the default `item_code` and keep the description as the line text; OR attempt item resolution from description. **Recommended default:** default item + description text for v1 (item resolution is a later enhancement; PI items need an item code in the pilot setup). **Owner:** spec-04 + [[06-gl-coding-tax-costcenter]]. **Must lock:** before promote line-aware path is built.
- **D5 — `tax_amount` currency binding on the child table.** Options: plain `Currency` (no company-currency context at extraction); OR mirror PI Item's `Company:company:default_currency`. **Recommended default:** plain `Currency` bound to the capture's `currency`, defer company-currency conversion to promote. **Owner:** spec-04. **Must lock:** before the child table JSON is written.
- **D6 — Combined vs split clean-room test plan.** One `extraction-confidence-and-line-items.md` vs two files. **Recommended default:** two files (per-field confidence and line-items-promote test distinct user-visible behaviours). **Owner:** spec-04. **Must lock:** at build time.

## 9. Dependencies & sequencing

**Must land first:**
- [[01-foundations-settings-async-idempotency]] — idempotency-key conventions and the async runner pattern this spec reuses (the cascade enqueue already exists at `ap_invoice_capture.py:395-404`; 01 formalizes it). Settings extensions here also live alongside 01's `AP Closed Loop Settings` extensions.

**Builds directly on already-shipped code** (extend, do NOT rebuild): the real-OCR provider stack (`base.py` `ExtractionResult` + `OCRProvider`, `registry.py`, `anthropic.py` forced-tool/retry/breaker/size-guard/audit/fallback, `fake.py` determinism), `AP Closed Loop Settings.get_ocr_config`, and the async cascade enqueue.

**Unblocks / feeds:**
- [[09-confidence-routing]] — the numeric `AP Invoice Capture Confidence` rows + `is_above_threshold` are the routing signal (today only the comma-joined `proposed_ambiguous_fields` string exists). **Hard dependency for 09.**
- [[08-validation-gates]] — per-line `po_reference`/`pr_reference` on `AP Invoice Capture Item`, mapped to PI Item `purchase_order`/`purchase_receipt` on promote, is the three-way-match join key; header `purchase_order_reference` gets populated.
- [[06-gl-coding-tax-costcenter]] — the new header `subtotal_amount`/`tax_amount` feed tax-template selection; per-line `expense_account`/`cost_center` are the slots 06 populates.
- [[07-classification-doctype-branching]] — the Stream R Journal Entry path consumes the same `line_items` rows.

**Estimated size:** **L** (per IMPLEMENTATION-PLAN units). Two new child DocTypes + parent fields + settings fields (M of schema), dataclass + Anthropic tool-schema + fake + `run_extraction` write-back (M of provider/controller logic), promote line-awareness with reconciliation (M, the highest-regression-risk piece), plus the new automated suites and two clean-room plans. Not XL because the provider stack, async, and audit already exist and are untouched.
