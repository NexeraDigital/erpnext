#!/usr/bin/env python3
"""Generate a realistic test corpus of 20 invoices + ground-truth definitions.

Invoices are rendered from rich HTML/CSS templates (templates.py) via headless
Chromium — real logos, colored headers, line-item tables, tax breakdowns,
footers — then optionally degraded with Pillow to emulate scans/photos/faxes.
Each invoice gets a matching <name>.json ground truth.

These are SYNTHETIC: no real vendors, no PII. Safe to commit.

Run:
    <bench>/env/bin/python apps/erpnext/test/invoices/generate_invoices.py

Deterministic: fixed values + fixed noise seed, so the committed *.json ground
truth stays valid across regenerations.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile

import numpy as np
from PIL import Image, ImageFilter, ImageOps

import templates as T

HERE = os.path.dirname(os.path.abspath(__file__))
# OCR-accuracy corpus lives in its own subfolder (test/invoices is organised by
# what each set tests: ocr-extraction/ here, deduplication/ alongside).
OUT = os.path.join(HERE, "ocr-extraction")
CHROME = os.path.expanduser(
	"~/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome"
)
SEED = 20260529
rng = np.random.default_rng(SEED)

# A4-ish portrait canvas.
PAGE_W, PAGE_H = 1000, 1400


def render_html_to_png(html: str, out_png: str) -> None:
	with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as fh:
		fh.write(html)
		html_path = fh.name
	try:
		subprocess.run(
			[
				CHROME, "--headless", "--disable-gpu", "--no-sandbox",
				"--hide-scrollbars", "--force-device-scale-factor=2",
				f"--window-size={PAGE_W},{PAGE_H}",
				f"--screenshot={out_png}", f"file://{html_path}",
			],
			check=True, capture_output=True,
		)
	finally:
		os.unlink(html_path)


def render_html_to_pdf(html: str, out_pdf: str) -> None:
	with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as fh:
		fh.write(html)
		html_path = fh.name
	try:
		subprocess.run(
			[
				CHROME, "--headless", "--disable-gpu", "--no-sandbox",
				"--no-pdf-header-footer", f"--print-to-pdf={out_pdf}",
				f"file://{html_path}",
			],
			check=True, capture_output=True,
		)
	finally:
		os.unlink(html_path)


def degrade(img: Image.Image, quality: str) -> Image.Image:
	if quality == "clean":
		return img
	if quality == "scanned":
		small = img.resize((int(img.width * 0.85), int(img.height * 0.85)))
		arr = np.asarray(small.convert("RGB")).astype(np.int16)
		arr = np.clip(arr + rng.normal(0, 10, arr.shape), 0, 255).astype(np.uint8)
		return Image.fromarray(arr).filter(ImageFilter.GaussianBlur(0.6))
	if quality == "photo":
		rotated = img.convert("RGB").rotate(-3, expand=True, fillcolor=(255, 255, 255))
		arr = np.asarray(rotated).astype(np.int16)
		arr[..., 2] = np.clip(arr[..., 2] - 10, 0, 255)  # warm tint
		arr = np.clip(arr + rng.normal(0, 7, arr.shape), 0, 255).astype(np.uint8)
		return Image.fromarray(arr)
	if quality == "faxed":
		g = ImageOps.grayscale(img).resize((int(img.width * 0.7), int(img.height * 0.7)))
		return g.point(lambda p: 255 if p > 140 else 0, mode="1").convert("RGB")
	if quality == "degraded":
		tiny = img.resize((int(img.width * 0.5), int(img.height * 0.5)))
		back = tiny.resize((img.width, img.height))
		arr = np.asarray(back.convert("RGB")).astype(np.int16)
		arr = np.clip(arr + rng.normal(0, 18, arr.shape), 0, 255).astype(np.uint8)
		return Image.fromarray(arr)
	return img


def compute_totals(spec) -> None:
	"""Derive subtotal/tax/total from line_items + tax_rate; mutate spec."""
	subtotal = sum(qty * unit for _, qty, unit in spec["line_items"])
	tax = round(subtotal * spec["tax_rate"] / 100.0, 2)
	if spec["currency"] == "JPY":
		subtotal = round(subtotal)
		tax = round(subtotal * spec["tax_rate"] / 100.0)
	spec["subtotal"] = round(subtotal, 2)
	spec["tax_amount"] = tax
	spec["total"] = round(subtotal + tax, 2)


# --- 20 specs across 4 templates, currencies, date styles, qualities --------
SPECS = [
	# modern
	dict(n=1, template="modern", quality="clean", fmt="pdf", accent="#2b6cb0",
		 supplier="Northwind Traders Ltd.", initials="NT", invoice_no="NW-2026-00417",
		 invoice_date="2026-03-18", date_style="iso", currency="EUR", tax_rate=19,
		 line_items=[("Cloud hosting — Mar", 1, 899.00), ("Support retainer", 1, 172.27)]),
	dict(n=2, template="modern", quality="scanned", fmt="png", accent="#6b46c1",
		 supplier="Cyberdyne Systems", initials="CS", invoice_no="CYB-2026-0808",
		 invoice_date="2026-03-11", date_style="us", currency="USD", tax_rate=8.5,
		 line_items=[("Sensor array", 2, 1500.00), ("Calibration", 1, 420.00)]),
	dict(n=3, template="modern", quality="photo", fmt="jpg", accent="#dd6b20",
		 supplier="Stark Components", initials="SC", invoice_no="STK-2026-77",
		 invoice_date="2026-04-18", date_style="long", currency="GBP", tax_rate=20,
		 line_items=[("Arc reactor parts", 1, 5000.00), ("Machining", 3, 200.00)]),
	dict(n=4, template="modern", quality="degraded", fmt="jpg", accent="#319795",
		 supplier="Massive Dynamic", initials="MD", invoice_no="MD-2026-7",
		 invoice_date="2026-04-09", date_style="iso", currency="CAD", tax_rate=13,
		 line_items=[("R&D consulting", 10, 250.00)]),
	dict(n=5, template="modern", quality="clean", fmt="png", accent="#2b6cb0",
		 supplier="Hooli Cloud KK", initials="HC", invoice_no="HOOLI-2026-5",
		 invoice_date="2026-02-14", date_style="iso", currency="JPY", tax_rate=10,
		 line_items=[("Compute credits", 1, 88000), ("Egress", 1, 1090)]),

	# classic
	dict(n=6, template="classic", quality="clean", fmt="pdf",
		 supplier="Globex Logistics GmbH", initials="GL", invoice_no="GLX/2026/0091",
		 invoice_date="2026-01-31", date_style="eu", currency="EUR", tax_rate=19,
		 line_items=[("Freight EU-wide", 1, 12500.00), ("Customs handling", 1, 940.34)]),
	dict(n=7, template="classic", quality="scanned", fmt="png",
		 supplier="Wayne Industries", initials="WI", invoice_no="WI-99201",
		 invoice_date="2026-01-12", date_style="long", currency="USD", tax_rate=0,
		 line_items=[("Structural steel", 50, 2400.00)]),
	dict(n=8, template="classic", quality="faxed", fmt="png",
		 supplier="Tyrell Corporation", initials="TC", invoice_no="TYR-880",
		 invoice_date="2026-03-22", date_style="us", currency="USD", tax_rate=8.25,
		 line_items=[("Replicant maintenance", 4, 9000.00), ("Memory implants", 2, 3750.00)]),
	dict(n=9, template="classic", quality="clean", fmt="pdf",
		 supplier="Initech Services Pvt Ltd", initials="IS", invoice_no="INI-2026-3310",
		 invoice_date="2026-03-05", date_style="iso", currency="INR", tax_rate=18,
		 line_items=[("TPS report automation", 1, 65000.00), ("On-site visit", 2, 6000.00)]),
	dict(n=10, template="classic", quality="photo", fmt="jpg",
		 supplier="Soylent Foods Co.", initials="SF", invoice_no="SF-2026-118",
		 invoice_date="2026-03-29", date_style="iso", currency="CAD", tax_rate=5,
		 line_items=[("Bulk nutrient base", 100, 21.50)]),

	# euvat
	dict(n=11, template="euvat", quality="clean", fmt="pdf", accent="#2f855a",
		 supplier="Vandelay Industries", initials="VI", invoice_no="VAN-26-0012",
		 invoice_date="2026-01-07", date_style="eu", currency="EUR", tax_rate=19,
		 vat_no="NL004495445B01", iban="NL91 ABNA 0417 1643 00",
		 line_items=[("Latex import (container)", 1, 41000.00), ("Inspection", 1, 1500.00)]),
	dict(n=12, template="euvat", quality="scanned", fmt="png", accent="#2c5282",
		 supplier="Pied Piper B.V.", initials="PP", invoice_no="PP-2026-44",
		 invoice_date="2026-04-25", date_style="eu", currency="EUR", tax_rate=21,
		 vat_no="NL822010690B01", iban="NL39 RABO 0300 0652 64",
		 line_items=[("Middle-out compression license", 1, 1899.95)]),
	dict(n=13, template="euvat", quality="clean", fmt="pdf", accent="#702459",
		 supplier="Gekko & Co AG", initials="GC", invoice_no="GEK-2026-301",
		 invoice_date="2026-02-28", date_style="eu", currency="GBP", tax_rate=20,
		 vat_no="GB654321987", iban="GB29 NWBK 6016 1331 9268 19",
		 line_items=[("Advisory — M&A", 25, 480.00), ("Due diligence", 1, 7500.00)]),
	dict(n=14, template="euvat", quality="degraded", fmt="jpg", accent="#2f855a",
		 supplier="Aperture Science Ltd", initials="AS", invoice_no="APS-2026-1129",
		 invoice_date="2026-01-25", date_style="eu", currency="EUR", tax_rate=19,
		 vat_no="DE811569869", iban="DE75 5121 0800 1245 1261 99",
		 line_items=[("Portal gun servicing", 2, 9000.00), ("Companion cube (ea)", 6, 1600.00)]),

	# minimal
	dict(n=15, template="minimal", quality="clean", fmt="pdf", accent="#dd6b20",
		 supplier="Acme Office Supplies", initials="AO", invoice_no="AC-5582",
		 invoice_date="2026-04-02", date_style="long", currency="GBP", tax_rate=20, signer="A. Coyote",
		 line_items=[("Anvils (pack of 3)", 1, 260.99), ("Rocket skates", 1, 52.00)]),
	dict(n=16, template="minimal", quality="scanned", fmt="png", accent="#3182ce",
		 supplier="Umbrella Holdings", initials="UH", invoice_no="UMB-0420",
		 invoice_date="2026-02-22", date_style="us", currency="USD", tax_rate=0, signer="A. Wesker",
		 line_items=[("Biohazard disposal", 1, 4999.00)]),
	dict(n=17, template="minimal", quality="photo", fmt="jpg", accent="#805ad5",
		 supplier="Nakatomi Trading", initials="NT", invoice_no="NAK-2026-31",
		 invoice_date="2026-02-03", date_style="iso", currency="AUD", tax_rate=10, signer="H. Gruber",
		 line_items=[("Bearer bonds handling", 1, 7500.00), ("Security audit", 1, 625.00)]),

	# 18-20: intentionally incomplete fields (varied templates/quality)
	dict(n=18, template="modern", quality="clean", fmt="pdf", accent="#2b6cb0",
		 supplier="Oscorp Industries", initials="OS", invoice_no="OSC-2026-55",
		 invoice_date="2026-03-14", date_style="iso", currency="USD", tax_rate=8,
		 show_currency=False,  # totals print without a currency marker
		 missing=["currency"],
		 line_items=[("Genome sequencing", 1, 3000.00), ("Lab time", 4, 100.00)]),
	dict(n=19, template="classic", quality="scanned", fmt="png",
		 supplier="Wonka Industries", initials="WW", invoice_no=None,  # no invoice number
		 invoice_date="2026-04-11", date_style="us", currency="USD", tax_rate=7,
		 missing=["supplier_invoice_no"],
		 line_items=[("Everlasting gobstoppers", 500, 1.10), ("Golden tickets", 5, 50.00)]),
	dict(n=20, template="minimal", quality="photo", fmt="jpg", accent="#dd6b20",
		 supplier="Wernham Hogg", initials="WH", invoice_no="WH-2026-9",
		 invoice_date=None, date_style="iso", currency="GBP", tax_rate=20, signer="D. Brent",  # no date
		 missing=["invoice_date"],
		 line_items=[("Paper (reams)", 80, 6.50), ("Delivery", 1, 40.25)]),
]


def main():
	os.makedirs(OUT, exist_ok=True)
	written = []
	for spec in SPECS:
		compute_totals(spec)
		html = T.TEMPLATES[spec["template"]](spec)

		base = f"invoice_{spec['n']:02d}"
		fmt = spec["fmt"]
		out_path = os.path.join(OUT, f"{base}.{fmt}")

		if fmt == "pdf" and spec["quality"] == "clean":
			# Born-digital crisp PDF straight from Chromium.
			render_html_to_pdf(html, out_path)
		else:
			# Raster path: render PNG, degrade, save in the target format.
			tmp_png = os.path.join(OUT, f".{base}.raw.png")
			render_html_to_png(html, tmp_png)
			img = Image.open(tmp_png)
			img = degrade(img, spec["quality"])
			if fmt == "pdf":
				img.convert("RGB").save(out_path, format="PDF", resolution=150.0)
			elif fmt == "jpg":
				img.convert("RGB").save(out_path, format="JPEG", quality=40)
			else:
				img.save(out_path, format="PNG")
			os.remove(tmp_png)

		missing = spec.get("missing", [])
		expected = {
			"supplier": spec["supplier"],
			"supplier_invoice_no": spec.get("invoice_no"),
			"invoice_date": spec.get("invoice_date"),
			"total_amount": spec["total"],
			"currency": None if "currency" in missing else spec["currency"],
		}
		definition = {
			"file": f"{base}.{fmt}",
			"format": fmt,
			"template": spec["template"],
			"quality": spec["quality"],
			"date_style": spec["date_style"],
			"expected": expected,
			"expected_missing": missing,
			"line_item_count": len(spec["line_items"]),
			"notes": f'{spec["template"]}; {spec["quality"]}; {fmt}; date={spec["date_style"]}'
			+ ("; missing=" + ",".join(missing) if missing else ""),
		}
		with open(os.path.join(OUT, f"{base}.json"), "w") as fh:
			json.dump(definition, fh, indent=2, ensure_ascii=False)
		written.append(f"{base}.{fmt}")

	print(f"Generated {len(written)} invoices + definitions in {OUT}")
	for name in written:
		print("  ", name)


if __name__ == "__main__":
	main()
