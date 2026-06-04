# Receipt/invoice test corpus + content-classifier accuracy harness

Labeled corpus and a harness for testing how well the **content classifier** identifies
receipts vs invoices from document content — and for **quantifying what the LLM (Phase 2)
buys over the rule scorer (Phase 1)**.

## Files
| File | What |
|---|---|
| `corpus.json` | **Seed corpus** — hand-authored plain-text entries (`text` + two-axis `label` + `difficulty`). Quick + committed; not visually realistic. |
| `generate_receipts.py` | Renders the seed entries' `text` to plain files. Pure PIL/weasyprint. |
| **`realistic.py`** | **Track B** — generates *layout-rich* receipts/invoices (logo, line-item tables, QR, fonts) with Faker data, then `augment`s them to look scanned/photographed. → `files/` + `realistic_corpus.json`. |
| **`augment.py`** | Scan/photo degradation (rotation, perspective, noise, blur, lighting, JPEG). Used by `realistic.py`; reusable. |
| **`fetch_datasets.py`** | **Track A** — maps a locally-obtained public real-receipt dataset (CORD / SROIE / RVL-CDIP) into the corpus → gitignored `external/`. Does not bundle data. |
| `run_accuracy.py` | Loads the **per-file JSONs** (the source of truth) and prints per-tier + **per-source** accuracy + confusion + misses. Bench console. |
| `files/`, `external/`, `realistic_corpus.json` | Generated/external artifacts — **gitignored** (regenerable). Only the seed `corpus.json` + the scripts are committed. |

## Source of truth: the per-file JSONs
Each receipt is defined by its own `files/<id>.json` (Track A: `external/files/<id>.json`) —
one self-contained labeled entry (`id`, `source`, `difficulty`, `label{genre,paid,
expected_document_type}`, `text`, …) sitting next to its image, mirroring
`test/invoices/ocr-extraction/`. **The harness reads these per-file JSONs**, not the
combined `corpus.json` / `realistic_corpus.json` (those are now just manifests / the seed
authoring input). So **run the generators first** to materialise them, then run the harness.

## Track B — realistic synthetic (committable, no PII)
```bash
/home/rsmith/frappe-bench/env/bin/python test/receipts/realistic.py --n 40
```
Produces thermal POS slips, formal invoices, paid-invoice / unpaid-receipt adversarials —
half degraded to look scanned. Each entry carries both the **rendered image** (real-OCR
mode) and the **`text`** (classifier-only mode).

## Track A — public real datasets (local only, never committed)
Obtain a dataset yourself (licences are research/non-commercial), then map it:
```bash
# any folder of real receipt images:
env/bin/python test/receipts/fetch_datasets.py --source local --dir /path/to/receipts --genre receipt
# CORD via HuggingFace (needs `datasets` installed + network):
env/bin/python test/receipts/fetch_datasets.py --source cord --hf
```
See the dataset table inside `fetch_datasets.py` (sources, how to obtain, licences). These
entries carry the **image only** — they test the full OCR→classifier pipeline; hand-verify
a sample before trusting the numbers.

## Difficulty tiers (the point of the corpus)
- **keyword** — obvious language ("approval code", "amount due", "net 30"). The **rule
  scorer** gets these.
- **semantic** — a receipt/invoice with *no* trigger phrases (just store, items, total, a
  card line). The rule scorer returns **unknown**; the **LLM** should still classify it.
- **adversarial** — paid invoices ("Invoice … PAID"), unpaid receipts, statements, credit
  notes — the cases that expose a naive classifier and test the genre-vs-payment split.

## Two test modes
1. **Classifier-only (cheap, deterministic).** The harness feeds each entry's `text`
   straight to the classifier — no OCR, no image needed. This is what `run_accuracy.py`
   does. Use it for volume + the rule-vs-LLM comparison.
2. **Full pipeline (real).** Generate the files (`generate_receipts.py`), upload them so
   real OCR reads the image, then classify. Costs Anthropic credits (OCR + LLM). Run a
   small subset.

## Run it

Generate first (**required** — this writes the per-file JSONs the harness reads):
```bash
/home/rsmith/frappe-bench/env/bin/python test/receipts/generate_receipts.py   # seed set
/home/rsmith/frappe-bench/env/bin/python test/receipts/realistic.py --n 40     # Track B
# (optional) Track A: fetch_datasets.py --source local --dir /path/to/receipts
```

Rule scorer accuracy (free):
```bash
echo 'import importlib.util, frappe; frappe.flags.ra_provider="rule"; \
  p=frappe.get_app_path("erpnext","..","test","receipts","run_accuracy.py"); \
  s=importlib.util.spec_from_file_location("ra",p); \
  m=importlib.util.module_from_spec(s); s.loader.exec_module(m)' \
  | bench --site erpnext.localhost console
```

LLM accuracy (**REAL Anthropic calls — needs a key in AI Provider Settings, costs
credits**): same as above with `frappe.flags.ra_provider="anthropic"`.

## What "good" looks like
The rule scorer is expected to score ~100% on the **keyword** tier and **0%** genre on the
**semantic** tier (it can't read intent without keywords). The LLM's job is to lift the
**semantic** and **adversarial** tiers. Run both providers and compare the per-tier rows —
that delta is the measured value of Phase 2.

> Baseline measured for the rule scorer on this corpus: keyword 100% / semantic 0% /
> adversarial 17% genre (overall 39% genre, 83% document_type — the marker short-circuit
> carries document_type on the paid cases). Re-run with the LLM to see the lift.

## Extending the corpus
Add entries to `corpus.json` (keep the tiers balanced and label **both** axes). The
adversarial tier is where to invest — paid invoices and unpaid receipts are the cases a
keyword classifier gets wrong.
