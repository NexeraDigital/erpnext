# OCR Provider Choice — Anthropic Claude

> **Status:** Recommendation, awaiting build go-ahead.
>
> **Date drafted:** 2026-05-28.
>
> **Audience:** NexeraDigital pilot stakeholders; engineers implementing the real OCR adapter for `Document Capture`.
>
> **Scope:** Justifies the choice of **Anthropic Claude** (Haiku 4.5 default, Sonnet 4.6 / 4.7 fallback) as the OCR / structured-extraction provider that will replace the current `fake_extract` implementation in the AP closed-loop pilot. Does not cover prompt engineering, schema design, retry policy, or settings-DocType changes in detail — those belong in a separate implementation plan.
>
> **Grounding rule (per `CLAUDE.md`):** every factual claim is anchored to either an upstream Anthropic documentation URL, a public independent benchmark with a URL, a file path in this repo, or a commit SHA on `upstream/version-16`.

---

## 0. TL;DR

**Use Anthropic Claude as the OCR provider for Document Capture.** Within the Claude family, use **Claude Haiku 4.5** as the first-pass extractor and **Claude Sonnet 4.6 or 4.7** as the low-confidence fallback. Build it behind an `OCRProvider` adapter interface so a Document AI–class provider (Google Document AI Invoice Parser, AWS Textract, Mindee, etc.) can be added later without touching the state machine.

The two reasons this wins on the merits, not just on vendor alignment:

1. **Claude Sonnet 3.5 outperformed every dedicated invoice-OCR tool tested** in the most rigorous public benchmark I could find — beating Google Document AI, AWS Textract, Microsoft Azure Document Intelligence, Docsumo, and Rossum on key-value-pair extraction across real invoices.
2. **Zero hallucinations** for both Claude tiers on a separate structured-extraction benchmark, vs. 1 for GPT-5 and 3 for Gemini 2.5 Flash. Hallucinated supplier names, invoice numbers, or amounts have direct financial consequences in AP work — this is the failure mode that matters most.

---

## 1. What the OCR step does in this pilot

The `Document Capture` workflow has a deliberate **OCR proposal** step between intake and clerk review. Per `docs/architecture/FORK-CHANGES.md` §6.4, the current implementation:

- Lives in `erpnext/accounts/doctype/document_capture/document_capture.py` (function `run_fake_extraction`, around line 650) and in `erpnext/accounts/ap_closed_loop/walking_skeleton.py` (function `fake_extract`).
- Uses a hash-based deterministic stand-in (`FAKE_OCR_PROVIDER = "fake-deterministic-v1"`) that generates plausible-but-fake values from the filename and content hash.
- Writes structured output to a fixed set of `proposed_*` fields on the capture record: `proposed_supplier`, `proposed_supplier_invoice_no`, `proposed_invoice_date`, `proposed_total_amount`, `proposed_currency`, plus `proposed_missing_fields` and `proposed_ambiguous_fields` for low-confidence cases, plus `ocr_raw_response` (JSON) for the full provider payload.
- Runs asynchronously via the existing cascade (`_enqueue_next` → `frappe.enqueue` with deduplication and per-capture job IDs).
- Pauses for human review (status transitions to `Proposed` and the clerk uses the **Confirm Fields** dialog to merge `proposed_*` into `final_*`).

**The architecture is already shaped for a real provider.** Replacing the fake extractor with a real one does not require changes to the state machine, the cascade, the desk UI, or the review flow. Only the body of `run_fake_extraction` (and `fake_extract`) needs to be swapped, behind a small adapter interface so the choice of provider stays configurable.

---

## 2. Options surveyed

Per the broader research in this session, three realistic tiers exist for an invoice-OCR provider in mid-2026. Self-hosted models (LayoutLMv3, Donut, PaddleOCR, Tesseract + structuring layer) are explicitly out of scope for v1 — they require ML-ops expertise we do not have, and the pilot volume does not justify the investment.

### Tier 1 — Cloud LLMs with native vision
**Examples:** Anthropic Claude (Haiku 4.5, Sonnet 4.6 / 4.7, Opus 4.7), OpenAI GPT-4o / GPT-5, Google Gemini 2.5.

**Profile:**
- Zero training required; handles any invoice layout day-one.
- Structured output via tool-use / JSON-mode maps directly to fixed schemas.
- Per-call cost moderate; latency 5–15 s end-to-end.
- Hallucination is the dominant failure mode and varies significantly between models.

### Tier 2 — Domain-specific Document AI
**Examples:** Google Document AI Invoice Parser, AWS Textract `AnalyzeExpense`, Azure AI Document Intelligence `prebuilt-invoice`.

**Profile:**
- Purpose-built for invoices, with well-calibrated per-field confidence scores.
- Lower per-page cost at scale.
- Less flexible on unusual formats without fine-tuning.
- Ties the deployment to a specific cloud vendor.

### Tier 3 — Specialist invoice APIs
**Examples:** Mindee, Klippa, Rossum, Nanonets.

**Profile:**
- Built specifically for AP automation; line-item extraction is mature.
- Often strongest on European or regional invoice formats.
- Another vendor relationship, opaque pricing tiers.

---

## 3. The benchmark evidence

### 3.1 Invoice-OCR head-to-head (AIMultiple Research, December 2024)

Source: https://aimultiple.com/invoice-ocr — "Invoice OCR Benchmark: Extraction Accuracy of LLMs vs OCRs."

**Methodology (quoted):** 400+ key-value pairs across 20 publicly-available invoice samples, evaluated by binary classification (correct / incorrect) without per-provider fine-tuning.

**Providers tested:** Amazon Textract, Claude Sonnet 3.5, Docsumo, Google Document AI, Microsoft Azure Document Intelligence, Rossum.

**Result (quoted):**

> "Claude Sonnet 3.5 demonstrated the highest overall accuracy and resilience across the full spectrum of document qualities."

That is the striking result of this benchmark: **a general-purpose LLM beat every dedicated invoice-extraction product head-to-head.** Note that this benchmark used Sonnet 3.5; current Claude Sonnet 4.6 / 4.7 and Haiku 4.5 should perform at least as well.

**Reported industry-wide weakness:** most providers extracted total amounts cleanly but struggled with pricing details (per-line rates and quantities). This applies equally across providers and is a reason to keep the fork's human-in-the-loop review step.

### 3.2 Structured-extraction (JSON) head-to-head (DEV Community, 2026)

Source: https://dev.to/shaun_vd_7562913ba77e1e0b/claude-sonnet-46-vs-gpt-41-vs-gemini-25-flash-which-wins-json-extraction-poa

**Caveat:** the test corpus was customer-support emails (30 real tickets), not invoices. The structured-extraction pattern is closely analogous to invoice field extraction, so the relative model performance is informative; absolute numbers are not directly transferable.

**Results table (quoted from the source):**

| Model | Completeness | Hallucinations | Cost / call | Latency |
|---|---|---|---|---|
| **Claude Sonnet 4.6** | 30/30 | **0** | $0.024 | 1.1 s |
| **Claude Haiku 4.5** | 29/30 | **0** | $0.003 | 0.7 s |
| GPT-5 | 30/30 | 1 | $0.045 | 1.8 s |
| Gemini 2.5 Flash | 26/30 | 3 | $0.001 | 0.9 s |

**Two findings that matter most for AP work:**

1. **Zero hallucinations from both Claude tiers; non-zero from GPT-5 and Gemini.** A hallucinated supplier name, invoice number, or amount on an AP capture has direct financial consequences. Even with a human-in-the-loop review step (which the fork enforces), a low-hallucination provider reduces the cognitive load on the reviewer.
2. **Claude Haiku 4.5 = 8× cheaper than Sonnet at 96.7 % completeness with zero hallucinations.** Haiku is the right default for a high-throughput task like invoice extraction.

### 3.3 Anthropic-stated capability anchors

The Anthropic API explicitly supports the integration patterns we need:

- **Native PDF processing** (URL reference or base64) on all current Claude models. Source: https://platform.claude.com/docs/en/build-with-claude/pdf-support
- **Vision for document understanding** with documented best practices around image preparation. Source: https://platform.claude.com/docs/en/build-with-claude/vision
- **Structured output via tool use** with schema validation, eliminating downstream JSON parsing. Source: https://platform.claude.com/docs/en/build-with-claude/structured-outputs

---

## 4. Why Claude wins the cloud-LLM choice

| Decision criterion | Why Claude scores best |
|---|---|
| Extraction accuracy on real invoices | Demonstrated #1 in the AIMultiple benchmark (§3.1), beating dedicated invoice tools. |
| Hallucination rate | 0/30 across both Sonnet 4.6 and Haiku 4.5 in the DEV benchmark (§3.2). The failure mode that costs real money in AP. |
| Cost per extraction at pilot volume | Haiku 4.5 at $0.003/call is below the price of most dedicated invoice APIs and roughly half of GPT-5 hallucination-comparable tier. |
| Latency | Haiku 4.5 at 0.7 s; Sonnet 4.6 at 1.1 s. Well within the human-review-loop budget. |
| Native PDF + vision support | First-party, no preprocessing required (§3.3). |
| Structured output reliability | Tool-use schema becomes the contract; no brittle JSON parsing. (§3.3) |
| Operational alignment with existing relationship | The pilot team already uses Anthropic via Claude Code; same auth pattern, same docs, one fewer vendor relationship. (Not a technical win, but a real operational one.) |
| Adapter portability | Choice is reversible — wrapping the call behind an `OCRProvider` adapter preserves the option to swap providers without changing the state machine. |

---

## 5. Why not the alternatives (briefly)

### Why not GPT-5 / GPT-4o
- One hallucination in 30 tickets vs. Claude's zero (§3.2). For AP, that is the wrong direction.
- Roughly 2× the cost per call vs. Sonnet 4.6 in the DEV benchmark.
- Equivalent feature coverage on PDF and vision; no functional advantage that offsets the hallucination delta.

### Why not Gemini 2.5
- 3 hallucinations in 30 tickets and 4 missing fields (26/30 completeness) in the DEV benchmark (§3.2). Largest hallucination rate among the four models tested.
- Gemini Pro tier may close the gap, but at that point the cost advantage over Sonnet evaporates.

### Why not Google Document AI / AWS Textract / Azure Document Intelligence (Tier 2)
- Beaten by Claude on the AIMultiple invoice benchmark (§3.1).
- Make the pilot dependent on a specific cloud account / billing relationship the customer may not have.
- Better economics at very high volume (1000+/day) but not at pilot volume.
- Still a credible **second** provider to add later through the adapter once volume justifies it.

### Why not Mindee / Rossum / Klippa (Tier 3)
- Strong on European and regional invoice formats; pilot is US-context per current customer profile.
- Adds another vendor relationship, contract, and SLA to manage during a pilot.
- Adapter pattern keeps the door open if a future customer's invoice mix justifies it.

### Why not self-hosted (LayoutLMv3, Donut, Tesseract + LLM post-processing)
- Requires ML-ops expertise the team does not have.
- Operational burden (model serving, GPU capacity, fine-tuning) is wildly disproportionate to pilot volume.
- Only justifies its cost at very high volume or strict on-prem requirements.

---

## 6. Recommended Claude model tiering

A tiered approach materially improves the cost / quality tradeoff, and falls naturally out of the adapter pattern.

| Tier | Model | When to use | Rationale |
|---|---|---|---|
| **Default** | Claude Haiku 4.5 | First-pass extraction on every invoice. | 0 hallucinations, 96.7 % completeness, $0.003 / call in §3.2 benchmark. Right tool for the bulk of the workload. |
| **Fallback** | Claude Sonnet 4.6 or 4.7 | Re-extract when Haiku's response triggers `proposed_ambiguous_fields` OR when any required field is missing OR when downstream supplier-matching fails on the proposed value. | Higher reasoning, still 0 hallucinations, $0.024 / call. Lifts the marginal hard cases without paying Sonnet rates on every invoice. |
| **Reserve** | Claude Opus 4.7 | Truly difficult documents — multi-page, foreign-language, handwritten amendments, photos at extreme angles, low-resolution scans where Sonnet also fails. Manually triggered by an Accounts Manager. | Most expensive; only worth it when correctness is critical and human cost of mis-extraction exceeds model cost. |

This tiering is implemented as a re-extraction policy inside the `AnthropicExtractor` adapter; no DocType or workflow changes required. The clerk-facing UI just sees a slightly slower extraction in the fallback case.

---

## 7. Acknowledged limitations and risks

To keep this document honest, the following are real and should not be ignored when the implementation lands:

- **Benchmark sample sizes are small.** AIMultiple: 20 invoices / 400 key-value pairs. DEV: 30 tickets (not invoices). Real-world performance on the customer's specific supplier mix may differ. The right hedge is to collect a test corpus of 20–50 real invoices with ground truth before declaring the integration done, and to measure F1 per field against it.
- **Model performance drifts.** Anthropic updates Claude regularly. Lock the model version (e.g., explicit `claude-haiku-4-5-20251001` rather than `claude-haiku-4-5-latest`) and re-benchmark on model changes.
- **Pricing changes.** The 8× cost ratio between Haiku and Sonnet is the durable signal; absolute dollar figures will drift. Cost monitoring belongs in the integration from day one.
- **Hallucination ≠ zero.** "0 in 30" is not "0 in production." The human-in-the-loop review step in the fork (`proposed_*` → clerk-confirmed `final_*`) is the actual safety net. **Do not** add an "auto-confirm if confidence > X" shortcut.
- **PII and data residency.** Invoices contain supplier names, addresses, bank details, sometimes tax IDs. Verify Anthropic's data-handling terms against the customer's compliance posture (no-train-on-customer-data is the standard Anthropic API guarantee; check zero-retention options if required).
- **AIMultiple's benchmark observed industry-wide weakness on per-line pricing details** even among the top providers — line-item extraction is harder than header-field extraction. If the pilot ever moves beyond header-level AP (Phase 2+), this is the area to test most carefully.

---

## 8. How this plugs into the existing fork

The change is genuinely small. Suggested file layout (additive to current fork):

```
erpnext/accounts/ap_closed_loop/
├── extractors/
│   ├── __init__.py
│   ├── base.py             # OCRProvider ABC, ExtractionResult dataclass
│   ├── fake.py             # current fake_extract, refactored as FakeExtractor(OCRProvider)
│   └── anthropic.py        # AnthropicExtractor(OCRProvider) — Claude + tool use
└── walking_skeleton.py     # unchanged shape; uses get_extractor() to pick provider
```

In `erpnext/accounts/doctype/document_capture/document_capture.py`:

- `run_fake_extraction()` becomes `run_extraction()`, dispatches to `get_extractor()` for the configured provider.
- `FAKE_OCR_PROVIDER` constant becomes a value read from `AP Closed Loop Settings.ocr_provider`.
- All other fields (`proposed_*`, `ocr_status`, `ocr_raw_response`, `proposed_ambiguous_fields`) keep their current semantics.

In `erpnext/accounts/doctype/ap_closed_loop_settings/`:

- Add `ocr_provider` (Select: `Fake (Deterministic)`, `Anthropic Claude`), `ocr_model` (Select: `claude-haiku-4-5`, `claude-sonnet-4-6`, `claude-sonnet-4-6`), `ocr_confidence_threshold` (Float), `anthropic_api_key` (Password, encrypted).
- Mirror in `docs/architecture/FORK-CHANGES.md` per the project working rule.

Best-practice patterns to bake in (regardless of model choice):

1. **Provider abstraction** — `OCRProvider` ABC with `extract(source: SourceCapture) -> ExtractionResult`. `FakeExtractor` becomes one implementation; future providers slot in alongside.
2. **Content-hash idempotency** — reuse the existing `content_hash` on `SourceCapture` as a cache key so re-extraction of the same file is free and deterministic.
3. **Raw-response retention** — keep storing the full provider payload in `ocr_raw_response`. Essential for audit, debugging, and reprocessing if the provider or model changes.
4. **Field-level confidence drives `action_required`** — when confidence on any required field is below threshold, populate `proposed_ambiguous_fields` and set `action_required = 1`. The fork's existing pause-for-OCR-review step then handles human review.
5. **Async via existing cascade** — `_enqueue_next` → `frappe.enqueue` with `deduplicate=True` and per-capture-per-step `job_id` already does the right thing. Add exponential-backoff retry and a circuit breaker inside the adapter for transient provider failures.
6. **Settings-driven model choice** — see above. Lets the customer change the provider or model without code changes.
7. **Cost + latency logging** — record `(timestamp, provider, model, page_count, latency_ms, cost_usd)` per extraction. Separate log DocType is cleanest.
8. **Test corpus before production** — collect 20–50 real or realistic invoices with ground truth. Measure F1 per field. Use to A/B-test model tiers and detect regressions when models update.
9. **Never skip human review.** Even with a 99 %+ model, 1-in-100 errors change real money. The fork's `proposed_*` vs `final_*` separation enforces this. Do not introduce an auto-confirm shortcut.

---

## 9. Decision (the one-line version)

> Use Anthropic Claude as the OCR provider for Document Capture, defaulting to Haiku 4.5 with Sonnet 4.6 / 4.7 as the low-confidence fallback, behind an `OCRProvider` adapter that preserves the option to add Document AI or specialist providers later.

---

## 10. Sources

### Anthropic (official)
- [Anthropic Claude API — PDF Support](https://platform.claude.com/docs/en/build-with-claude/pdf-support)
- [Anthropic Claude API — Vision](https://platform.claude.com/docs/en/build-with-claude/vision)
- [Anthropic Claude API — Structured Outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
- [Anthropic Claude API — Intro](https://platform.claude.com/docs/en/intro)

### Independent benchmarks
- [Invoice OCR Benchmark: Extraction Accuracy of LLMs vs OCRs — AIMultiple Research](https://aimultiple.com/invoice-ocr) — head-to-head accuracy on 20 invoices / 400+ key-value pairs; Claude Sonnet 3.5 #1 overall against dedicated invoice tools.
- [Claude Sonnet 4.6 vs GPT-4.1 vs Gemini 2.5 Flash: which wins JSON extraction? — DEV Community](https://dev.to/shaun_vd_7562913ba77e1e0b/claude-sonnet-46-vs-gpt-41-vs-gemini-25-flash-which-wins-json-extraction-poa) — structured-extraction benchmark; Claude tiers tied for top with zero hallucinations.

### Third-party (corroborating, not authoritative)
- [Best Invoice OCR Tools in 2026 — Parseur](https://parseur.com/compare-to/best-invoice-ocr-tools)
- [Best OCR Tools for Invoice Processing & AP in 2026 — Klippa](https://www.klippa.com/en/blog/information/best-ocr-ap-invoice-processing/)
- [Claude Vision API: Production Guide — Developers Digest](https://www.developersdigest.tech/blog/claude-vision-api-production-guide)
- [Claude Vision for Document Analysis — Stream](https://getstream.io/blog/anthropic-claude-visual-reasoning/)

### Repo-internal
- `docs/architecture/FORK-CHANGES.md` §6.4 — current Document Capture pipeline, including the OCR proposal step.
- `erpnext/accounts/doctype/document_capture/document_capture.py` — `run_fake_extraction` function, current OCR integration point (lines ~650–720).
- `erpnext/accounts/ap_closed_loop/walking_skeleton.py` — `fake_extract` function, the underlying deterministic stand-in.
- `erpnext/accounts/doctype/ap_closed_loop_settings/` — Single DocType that will hold the OCR provider configuration.

### Related project docs
- `docs/planning/v16-upgrade-business-case.md` — establishes the v16 deployment context this OCR work targets.
- `docs/planning/local-v17-to-v16-migration-plan.md` — confirms the fork is now on v16, where this implementation will land.
- `CLAUDE.md` — grounding rule and working rules cited above.
