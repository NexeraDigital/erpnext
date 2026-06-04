#!/usr/bin/env python
"""Generate the labeled receipt/invoice test corpus from corpus.json.

Renders each entry's `text` into an actual file (PNG/JPG via Pillow, PDF via
weasyprint) under ``test/receipts/files/`` and writes a paired ground-truth JSON
mirroring the ``test/invoices/ocr-extraction/`` convention (file/format/vendor/
currency/label/text). The rendered files are what you upload for the REAL-OCR test
mode; the `text` field alone drives the classifier-only mode (see README.md).

Run with the bench python (no frappe needed):
    /home/rsmith/frappe-bench/env/bin/python test/receipts/generate_receipts.py

Pure PIL + weasyprint — does not import frappe. Idempotent: re-running overwrites.
"""

from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(HERE, "corpus.json")
OUT = os.path.join(HERE, "files")


def _render_png(text: str, path: str, fmt: str) -> None:
    from PIL import Image, ImageDraw, ImageFont

    lines = text.split("\n")
    pad, line_h, width = 24, 26, 560
    height = pad * 2 + line_h * (len(lines) + 1)
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSansMono.ttf", 16)
    except Exception:
        font = ImageFont.load_default()
    y = pad
    for ln in lines:
        draw.text((pad, y), ln, fill="black", font=font)
        y += line_h
    if fmt in ("jpg", "jpeg"):
        img.save(path, "JPEG", quality=85)
    else:
        img.save(path, "PNG")


def _render_pdf(text: str, path: str) -> None:
    from weasyprint import HTML

    body = "<br/>".join(_escape(ln) for ln in text.split("\n"))
    html = (
        "<html><body style='font-family:monospace;font-size:13px;"
        "white-space:pre-wrap;padding:24px'>" + body + "</body></html>"
    )
    HTML(string=html).write_pdf(path)


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main() -> None:
    corpus = json.load(open(CORPUS))
    os.makedirs(OUT, exist_ok=True)
    made = 0
    for e in corpus["entries"]:
        eid, fmt, text = e["id"], e["format"], e["text"]
        fname = f"{eid}.{fmt}"
        fpath = os.path.join(OUT, fname)
        if fmt == "pdf":
            _render_pdf(text, fpath)
        else:
            _render_png(text, fpath, fmt)
        gt = {
            "id": eid,
            "source": "seed",
            "difficulty": e["difficulty"],
            "file": fname,
            "format": fmt,
            "vendor": e.get("vendor"),
            "currency": e.get("currency"),
            "label": e["label"],
            "text": text,
        }
        json.dump(gt, open(os.path.join(OUT, f"{eid}.json"), "w"), indent=2)
        made += 1
    print(f"Generated {made} files + ground-truth JSON in {OUT}")


if __name__ == "__main__":
    main()
