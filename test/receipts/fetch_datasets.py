#!/usr/bin/env python
"""Track A — map a PUBLIC real-receipt dataset into the test corpus (local only).

Real scanned/photographed receipts come from research datasets (SROIE, CORD, RVL-CDIP).
They are NOT committed to this repo (research/non-commercial licences + they contain real
imagery), so this script maps a LOCALLY-OBTAINED dataset into our corpus schema and writes
into the gitignored ``test/receipts/external/`` dir, which the harness then reads.

Supported sources (obtain them yourself — see the table below), then run:

    /home/rsmith/frappe-bench/env/bin/python test/receipts/fetch_datasets.py \
        --source cord --hf            # if `datasets` + network are available
    /home/rsmith/frappe-bench/env/bin/python test/receipts/fetch_datasets.py \
        --source local --dir /path/to/receipt_images --genre receipt   # any image folder

| Dataset   | What it is                        | Genre   | How to obtain                                   | Licence note          |
|-----------|-----------------------------------|---------|-------------------------------------------------|-----------------------|
| CORD      | 1k+ Indonesian POS receipts       | receipt | HF hub `naver-clova-ix/cord-v2` (`--hf`)        | research use          |
| SROIE     | ICDAR'19 scanned receipts         | receipt | Kaggle / ICDAR (manual download → `--source local`) | research/competition  |
| RVL-CDIP  | 16-class docs incl. **invoice**   | invoice | HF hub / official site (manual)                 | research use          |

This is the SCAFFOLD: it does not bundle data and degrades gracefully when the dataset
library / network / files are absent (it prints how to obtain them). Labels: receipts →
genre=receipt; invoices → genre=invoice; `paid` is left null (real receipts rarely state
it explicitly) unless overridden. Verify a sample by hand before trusting the numbers.
"""

from __future__ import annotations

import argparse
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
EXT = os.path.join(HERE, "external")


def _write_corpus(entries):
    os.makedirs(os.path.join(EXT, "files"), exist_ok=True)
    # Per-file JSON is the source of truth the harness reads; the combined file is a manifest.
    for e in entries:
        json.dump(e, open(os.path.join(EXT, "files", f"{e['id']}.json"), "w"), indent=2)
    json.dump(
        {"_about": "Track A — external real-receipt dataset mapping (gitignored). Per-file "
                   "JSONs in files/ are authoritative; this is a manifest.", "entries": entries},
        open(os.path.join(EXT, "external_corpus.json"), "w"),
        indent=1,
    )
    print(f"Wrote {len(entries)} entries (per-file JSON + manifest) → {os.path.join(EXT, 'files')}")


def from_local(dir_path, genre, paid, limit):
    """Map a local folder of receipt/invoice images into the corpus (no OCR text yet —
    these entries carry the IMAGE only, so they exercise the full real-OCR pipeline)."""
    exts = (".png", ".jpg", ".jpeg", ".pdf", ".tif", ".tiff")
    files = [f for f in sorted(os.listdir(dir_path)) if f.lower().endswith(exts)][:limit]
    os.makedirs(os.path.join(EXT, "files"), exist_ok=True)
    entries = []
    for i, fn in enumerate(files):
        import shutil

        dst = f"ext_{genre}_{i:04d}{os.path.splitext(fn)[1].lower()}"
        shutil.copy(os.path.join(dir_path, fn), os.path.join(EXT, "files", dst))
        entries.append({
            "id": dst.rsplit(".", 1)[0], "source": "external-local", "difficulty": "real",
            "format": os.path.splitext(fn)[1].lstrip(".").lower(),
            "label": {"genre": genre, "paid": paid, "expected_document_type":
                      "Already Paid" if (genre == "receipt" and paid is not False) else "Unpaid Bill"},
            "image": os.path.join("external", "files", dst),
            "text": "",  # filled by real OCR at test time (full-pipeline mode)
        })
    _write_corpus(entries)


def from_cord_hf(limit):
    try:
        from datasets import load_dataset
    except Exception:
        print("`datasets` not installed. `pip install datasets` (ask first) or use --source local.")
        return
    os.makedirs(os.path.join(EXT, "files"), exist_ok=True)
    ds = load_dataset("naver-clova-ix/cord-v2", split=f"test[:{limit}]")
    entries = []
    for i, row in enumerate(ds):
        dst = f"ext_cord_{i:04d}.png"
        row["image"].convert("RGB").save(os.path.join(EXT, "files", dst))
        # CORD entries are ALL receipts; OCR text is in row['ground_truth'] but we let the
        # real OCR pipeline read the image so this tests OCR + classifier together.
        entries.append({
            "id": f"ext_cord_{i:04d}", "source": "external-cord", "difficulty": "real",
            "format": "png",
            "label": {"genre": "receipt", "paid": None, "expected_document_type": "Already Paid"},
            "image": os.path.join("external", "files", dst), "text": "",
        })
    _write_corpus(entries)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["cord", "local"], required=True)
    ap.add_argument("--hf", action="store_true", help="pull CORD via the HF datasets lib")
    ap.add_argument("--dir", help="local image folder (for --source local)")
    ap.add_argument("--genre", choices=["receipt", "invoice"], default="receipt")
    ap.add_argument("--paid", choices=["true", "false", "null"], default="null")
    ap.add_argument("--limit", type=int, default=30)
    args = ap.parse_args()
    paid = {"true": True, "false": False, "null": None}[args.paid]

    if args.source == "cord":
        from_cord_hf(args.limit)
    else:
        if not args.dir:
            ap.error("--source local needs --dir")
        from_local(args.dir, args.genre, paid, args.limit)


if __name__ == "__main__":
    main()
