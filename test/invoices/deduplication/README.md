# Deduplication Test Fixtures (spec 03)

Invoices built to exercise the **pre-extraction deduplication** firewall in
`erpnext.accounts.doctype.ap_invoice_capture` (`detect_duplicates_for` /
`_compute_phash`). See `docs/spec/03-deduplication.md` and the clean-room
runbook `test/testplans/pre-extraction-dedup.md`.

These are **not** OCR-accuracy fixtures (that corpus is `../ocr-extraction/`) and
they carry **no** `*.json` ground truth — what matters is the *bytes/pixels*, not
the extracted fields.

## Scenarios — one subfolder each

Within a folder the numeric prefix is the **upload order**: upload `01` first
(it becomes the original already in the system), then upload `02`.

| Folder | Files (upload order) | What the dedupe step should do on `02` | AC / runbook |
|---|---|---|---|
| `exact-duplicate/` | `01_acme_original.pdf` → `02_acme_reupload.pdf` (**byte-identical** copy) | **Exact hit** — `02` lands in status **`Duplicate`**, `duplicate_of` → `01`, `action_required` "Exact duplicate of …", **no OCR runs**. | AC-03-1 / TC-2 |
| `near-duplicate/` | `01_globex_original.pdf` → `02_globex_rescan.png` (same invoice, **re-scanned**: different bytes + format, near-identical pixels) | **Perceptual suspect** — `02` gets `action_required` "Suspected near-duplicate of …", but status is **NOT** `Duplicate` and `duplicate_of` stays empty (a human confirms; it still gets OCR'd). | AC-03-6 / TC-4 |
| `distinct/` | `01_initech_invoice.pdf` → `02_umbrella_invoice.pdf` (two **different** invoices) | **Clean** — `02` is not flagged and flows to OCR as normal. | AC-03-3 / TC-3 |

Each scenario uses a **different base vendor** (Acme / Globex / Initech+Umbrella)
so uploading every fixture against one site never produces an *accidental*
cross-scenario match — each folder is a self-contained test. Clean up the
captures + uploaded Files between scenarios (the runbook §6 covers this).

## Verified properties (at generation time)

- **Exact pair** is byte-identical (`cmp` clean) → same MD5 `content_hash`.
- **Near pair** differs in bytes; its perceptual-hash (imagehash-compatible
  64-bit pHash) Hamming distance to a clean raster of the same invoice is **0**
  — well inside the default `dedupe_phash_max_distance = 6`, so it trips the
  suspect path.
- **Distinct pair** pHash distance is **18** — above the threshold, so no
  perceptual flag.

> **`near-duplicate/` needs `poppler` on the worker host.** The perceptual pass
> rasterizes the PDF first page via `pdf2image`/poppler. With poppler absent,
> dedupe **degrades to exact-only** and the near-duplicate scenario won't fire
> (the `.png` half still hashes, but the `.pdf` original produces no
> `perceptual_hash`). The exact-duplicate and distinct scenarios work without
> poppler. See `docs/spec/03-deduplication.md` §9.

## Regenerating

```bash
<bench>/env/bin/python apps/erpnext/test/invoices/deduplication/generate_dedup_invoices.py
```

Deterministic; reuses the HTML/CSS templates + Chromium render + Pillow degrade
helpers from `../generate_invoices.py` (same Chromium binary — see `../README.md`).
