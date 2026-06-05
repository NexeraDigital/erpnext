# Invoice Test Fixtures

Synthetic invoices for testing the Document Capture pipeline. **Organised into
subfolders by what each set tests** — add new fixtures to the matching purpose
folder (or a new one), not to this root.

Invoices are rendered from rich **HTML/CSS templates** (`templates.py`) via
**headless Chromium** — real logos, colored headers, bill-to/pay-to blocks,
line-item tables, subtotal/tax/total breakdowns, VAT numbers/IBANs, footers —
then optionally degraded with Pillow to emulate scans, photos, faxes, and
low-quality copies.

**Synthetic** — no real vendors, no PII. Safe to commit. Do not add real
customer invoices here.

## Layout

```
templates.py             # 4 HTML/CSS invoice templates + helpers (shared)
generate_invoices.py     # builds the OCR corpus (deterministic) -> ocr-extraction/

ocr-extraction/          # 20 invoices + ground-truth JSON — OCR EXTRACTOR ACCURACY
  invoice_01.pdf  invoice_01.json
  invoice_02.png  invoice_02.json
  ...

deduplication/           # spec-03 PRE-EXTRACTION DEDUPE fixtures (see its README)
  generate_dedup_invoices.py
  exact-duplicate/   01_*.pdf  02_*.pdf   (byte-identical re-upload)
  near-duplicate/    01_*.pdf  02_*.png   (same invoice re-scanned)
  distinct/          01_*.pdf  02_*.pdf   (two different invoices)
```

The rest of this README documents the **`ocr-extraction/`** corpus. The
deduplication fixtures have their own `deduplication/README.md`.

## Templates (vendor styles)

| key | look |
|---|---|
| `modern` | SaaS style: accent-colour header band, SVG logo, zebra line-item table, totals box |
| `classic` | Corporate serif: centred title, ruled lines, "Particulars / Rate / Amount" table |
| `euvat` | European: VAT no + IBAN, MwSt tax-per-line column, bilingual DE/EN labels, DD.MM.YYYY |
| `minimal` | Contractor: whitespace, single accent rule, simple list, cursive sign-off |

## Quality profiles

`clean` (born-digital crisp), `scanned` (downscale + gaussian noise + blur),
`photo` (rotation + warm tint + noise), `faxed` (1-bit threshold, low-res),
`degraded` (heavy downscale + strong noise). Clean PDFs are printed straight
from Chromium (vector text); everything else is rastered then degraded.

## Definition file schema

```json
{
  "file": "invoice_01.pdf",
  "format": "pdf",                 // pdf | png | jpg
  "template": "modern",
  "quality": "clean",              // clean | scanned | photo | faxed | degraded
  "date_style": "iso",             // how the date is PRINTED (iso|us|eu|long)
  "expected": {
    "supplier": "Northwind Traders Ltd.",
    "supplier_invoice_no": "NW-2026-00417",
    "invoice_date": "2026-03-18",  // ground truth is ALWAYS ISO 8601, even when
                                    // printed as 03/18/2026 or "18 March 2026"
    "total_amount": 1274.81,        // the GRAND total (subtotal + tax), numeric
    "currency": "EUR"              // null when the invoice omits it
  },
  "expected_missing": [],          // logical fields the OCR should report absent
  "line_item_count": 2,
  "notes": "modern; clean; pdf; date=iso"
}
```

`total_amount` is the computed grand total (line items + tax), so it tests that
the extractor picks the *total due*, not a line amount or subtotal.

## Coverage

- **Formats:** 7 PDF, 7 PNG, 6 JPG
- **Templates:** all 4 used across the set
- **Quality:** clean / scanned / photo / faxed / degraded
- **Currency:** USD, EUR, GBP, INR, CAD, JPY, AUD
- **Date printed as:** ISO, US (MM/DD/YYYY), EU (DD.MM.YYYY), long ("18 March 2026")
- **Incomplete invoices:** #18 omits currency, #19 omits invoice number, #20 omits
  date — each flagged in `expected_missing` with `expected.<field>` = null

## Using it in a test / benchmark

```python
import glob, json, os
CORPUS = os.path.join(os.path.dirname(__file__), "ocr-extraction")
for p in sorted(glob.glob(os.path.join(CORPUS, "invoice_*.json"))):
    d = json.load(open(p))
    # upload d["file"] as a File, build an Document Capture, run the
    # AnthropicExtractor, then compare result.proposal to d["expected"]:
    #   supplier        -> fuzzy text match (minor punctuation ok)
    #   supplier_invoice_no -> exact
    #   invoice_date    -> exact ISO after the extractor normalises
    #   total_amount    -> numeric equality
    #   currency        -> exact 3-letter code, OR in result.missing_fields
    #                       when d["expected_missing"] lists it
```

## Regenerating

```bash
<bench>/env/bin/python apps/erpnext/test/invoices/generate_invoices.py
```

Requirements: a Chromium binary (the Playwright one at
`~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome` — see
`test/testplans/BROWSER-TESTING-SETUP.md`), Pillow, numpy. Deterministic (fixed
values + fixed noise seed) so regenerating keeps the committed `*.json` valid.
If you edit a spec in `generate_invoices.py`, re-run so the image and its
definition stay in sync.

## Benchmark harness

A permanent scorer lives in the app package (the runner is code; this folder is
data):

```bash
bench --site <site> execute \
  erpnext.accounts.ap_closed_loop.extractors.benchmark.run
# subset / different provider:
bench --site <site> execute \
  erpnext.accounts.ap_closed_loop.extractors.benchmark.run \
  --kwargs '{"provider": "anthropic", "files": ["invoice_01", "invoice_18"]}'
```

It runs each invoice through the provider, scores every field against the
ground truth (numeric for total, fuzzy for supplier, exact otherwise; missing
fields pass when reported absent), and prints per-field accuracy + a
perfect-invoice count. **Run it whenever the Anthropic model version changes**
to catch accuracy regressions. The pure scoring logic is unit-tested in
`extractors/test_benchmark.py` (no API calls).

Baseline (Claude Haiku 4.5, this corpus): **20/20 invoices, 100/100 fields.**

## Cost note

Running the corpus through the **Anthropic** provider is one real API call per
invoice (~20 calls, a few cents on Haiku). The `fake` provider needs no calls
but ignores image content, so it can't validate accuracy.
