#!/usr/bin/env python3
"""Generate the pre-extraction **deduplication** test fixtures (spec 03).

These are NOT for OCR accuracy (that's ../ocr-extraction/). They exercise the
dedupe firewall in `erpnext.accounts.doctype.document_capture` —
`detect_duplicates_for` / `_compute_phash` — so each fixture is built to trip a
specific branch. Files are grouped into one subfolder per scenario; within a
folder the numeric prefix is the **upload order** (upload 01, then 02).

| folder            | 01 → 02                                   | expected dedupe verdict on 02            | AC / test case |
|-------------------|-------------------------------------------|------------------------------------------|----------------|
| exact-duplicate/  | a PDF, then a **byte-identical copy**     | exact hit → status **Duplicate**, no OCR | AC-03-1, TC-2  |
| near-duplicate/   | a clean PDF, then a **re-scan** (same     | perceptual **suspect** (action_required, | AC-03-6, TC-4  |
|                   | invoice, different bytes/format)          | NOT Duplicate) — needs poppler installed |                |
| distinct/         | one invoice, then a **different** invoice | clean → normal flow, no flag             | AC-03-3, TC-3  |

Reuses the HTML/CSS templates + Chromium render + Pillow degrade helpers from
../generate_invoices.py, so the look matches the OCR corpus. Deterministic.

Run:
    <bench>/env/bin/python apps/erpnext/test/invoices/deduplication/generate_dedup_invoices.py

Requires the same Chromium binary as the OCR generator (see ../README.md).
"""

from __future__ import annotations

import os
import shutil
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(HERE)
sys.path.insert(0, PARENT)

import templates as T  # noqa: E402
from generate_invoices import (  # noqa: E402
	compute_totals,
	degrade,
	render_html_to_pdf,
	render_html_to_png,
)

# Distinct base invoice per scenario, so uploading every fixture against one
# site never produces an *accidental* cross-scenario match — each folder is a
# self-contained test.
ACME = dict(
	template="modern", accent="#2b6cb0",
	supplier="Acme Office Supplies", initials="AO", invoice_no="ACME-2026-0142",
	invoice_date="2026-05-04", date_style="iso", currency="USD", tax_rate=8.5,
	line_items=[("Ergonomic chairs", 4, 320.00), ("Standing desk", 2, 540.00)],
)
GLOBEX = dict(
	template="classic",
	supplier="Globex Logistics", initials="GL", invoice_no="GLX-2026-7781",
	invoice_date="2026-05-09", date_style="eu", currency="EUR", tax_rate=19,
	line_items=[("Pallet freight", 6, 410.00), ("Fuel surcharge", 1, 230.00)],
)
INITECH = dict(
	template="modern", accent="#319795",
	supplier="Initech Services", initials="IS", invoice_no="INI-2026-5520",
	invoice_date="2026-05-12", date_style="us", currency="USD", tax_rate=0,
	line_items=[("TPS report automation", 1, 4200.00)],
)
UMBRELLA = dict(
	template="euvat", accent="#702459",
	supplier="Umbrella Holdings AG", initials="UH", invoice_no="UMB-2026-0303",
	invoice_date="2026-05-15", date_style="eu", currency="GBP", tax_rate=20,
	vat_no="GB761234509", iban="GB29 NWBK 6016 1331 9268 19",
	line_items=[("Compliance retainer", 3, 1500.00), ("Audit support", 1, 2750.00)],
)


def render_pdf(spec: dict, out_pdf: str) -> None:
	compute_totals(spec)
	render_html_to_pdf(T.TEMPLATES[spec["template"]](spec), out_pdf)


def render_scanned_png(spec: dict, out_png: str) -> None:
	"""Render the same invoice, then apply the mild 'scanned' degrade — different
	bytes/format from the clean PDF, but visually near-identical so its pHash sits
	within the suspect threshold."""
	compute_totals(spec)
	tmp = os.path.join(HERE, ".dedup.raw.png")
	render_html_to_png(T.TEMPLATES[spec["template"]](spec), tmp)
	degrade(Image.open(tmp), "scanned").convert("RGB").save(out_png, format="PNG")
	os.remove(tmp)


def main() -> None:
	written = []

	# --- exact-duplicate: render once, then copy the bytes verbatim ----------
	d = os.path.join(HERE, "exact-duplicate")
	os.makedirs(d, exist_ok=True)
	orig = os.path.join(d, "01_acme_original.pdf")
	render_pdf(dict(ACME), orig)
	shutil.copyfile(orig, os.path.join(d, "02_acme_reupload.pdf"))  # identical bytes
	written += ["exact-duplicate/01_acme_original.pdf", "exact-duplicate/02_acme_reupload.pdf"]

	# --- near-duplicate: clean PDF, then a re-scan of the same invoice -------
	d = os.path.join(HERE, "near-duplicate")
	os.makedirs(d, exist_ok=True)
	render_pdf(dict(GLOBEX), os.path.join(d, "01_globex_original.pdf"))
	render_scanned_png(dict(GLOBEX), os.path.join(d, "02_globex_rescan.png"))
	written += ["near-duplicate/01_globex_original.pdf", "near-duplicate/02_globex_rescan.png"]

	# --- distinct: two genuinely different invoices --------------------------
	d = os.path.join(HERE, "distinct")
	os.makedirs(d, exist_ok=True)
	render_pdf(dict(INITECH), os.path.join(d, "01_initech_invoice.pdf"))
	render_pdf(dict(UMBRELLA), os.path.join(d, "02_umbrella_invoice.pdf"))
	written += ["distinct/01_initech_invoice.pdf", "distinct/02_umbrella_invoice.pdf"]

	print(f"Generated {len(written)} dedupe fixtures in {HERE}")
	for name in written:
		print("  ", name)


if __name__ == "__main__":
	main()
