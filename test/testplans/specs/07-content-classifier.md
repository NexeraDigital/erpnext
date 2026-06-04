# Test plan — Spec 07 enhancement: content-based receipt/invoice classifier

## 1. Feature under test
Step-6 classification now decides receipt-vs-invoice from the **document content**, not just
the filename/keyword markers. Two phases behind one verdict contract:
- **Phase 1** — `_score_document_content`: deterministic rule scorer over the OCR text/fields
  (genre receipt/invoice/other + paid state + confidence).
- **Phase 2** — `_classify_text_anthropic`: an LLM reads the text (forced tool call), same contract.
- **Dispatcher** — `classify_document_content`: rule by default; LLM when enabled + provider=Anthropic;
  degrades to the rule scorer on any LLM failure.

`enable_content_classifier` (default **OFF**) gates whether the verdict *decides* the document
type; `content_classifier_provider` (Rule|Anthropic) selects the engine. `classification_confidence`
+ `classification_rationale` are recorded either way. FORK-CHANGES §34.

## 2. Branch / commit
`russ/migrateToV16`; the commit adding `classify_document_content` + the two settings + the two capture fields.

## 3. Environment setup
`bench --site <site> migrate` (adds the settings flags + the two capture fields). For the LLM path,
an Anthropic key in **AI Provider Settings** (the LLM tests mock the SDK — no key needed for them).
Force `ocr_provider=""` (fake) before running so the fixtures don't trigger real OCR.

## 4. Test data prerequisites
None for the unit tests (text is injected via `source_context` / passed directly). For the accuracy
harness: the labeled corpus under `test/receipts/` (regenerate with `generate_receipts.py` +
`realistic.py`).

## 5. Numbered test cases
### A. Automated (mocked — no API cost)
- **A-1.** `TestAPContentClassifier` (8) → scorer reads invoice/receipt/ambiguous/card-boost;
  confidence+rationale recorded with flag OFF; flag ON recognises a receipt from content; invoice
  stays Unpaid Bill; clerk override wins. Expect `Ran 8 … OK`.
- **A-2.** `TestAPContentClassifierLLM` (6) → tool-response mapping (+ "other"→unknown, confidence
  clamp); dispatcher rule-by-default / uses-LLM-when-enabled / **rule-fallback on LLM error**;
  end-to-end LLM source stamp. Expect `Ran 6 … OK`.
- **A-3.** Full module green at default settings (`enable_content_classifier` OFF → shipped behaviour
  unchanged).

### B. Accuracy harness (measures quality on the labeled corpus)
- **B-1.** Rule provider → per-tier/per-source scorecard (baseline: keyword 100% / semantic ~50% /
  overall ~62% genre).
- **B-2.** Anthropic provider (**real API calls**) → expect the *semantic* tier to lift toward 100%
  and overall genre toward ~88%. See `test/receipts/README.md` for the invocation.

### C. Manual UI
- **C-1.** Enable the classifier + provider=Anthropic; create a capture from a receipt; classify →
  `Document Type`, `Classification Confidence`, `Classification Rationale` populated; source =
  `content-classifier-llm-v1`.
- **C-2.** With provider=Anthropic but the key removed → classification still completes (rule
  fallback), source = `content-classifier-v1` / rule.

## 6. Cleanup / rollback
Automated suites roll back. Restore `ocr_provider` after forcing fake. The corpus `files/` are
regenerable.

## 7. Pass/fail summary template
| # | Case | Result |
|---|---|---|
| A-1 | `TestAPContentClassifier` — `Ran 8 … OK` | [ ] |
| A-2 | `TestAPContentClassifierLLM` — `Ran 6 … OK` | [ ] |
| B-1 | Rule scorecard prints; keyword tier 100% | [ ] |
| B-2 | LLM scorecard; semantic tier ≫ rule | [ ] |
| C-1 | Desk: confidence + rationale shown, LLM source | [ ] |
| C-2 | Key removed → graceful rule fallback | [ ] |
