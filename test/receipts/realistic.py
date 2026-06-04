#!/usr/bin/env python
"""Track B — realistic synthetic receipt/invoice generator (committable, no PII).

Renders genuinely layout-rich documents with PIL — logo, columns / line-item tables,
QR code, multiple fonts, totals/tax blocks — driven by Faker data, then optionally
degrades them with `augment.scan_augment` to look scanned/photographed. Emits, per
document: the rendered file (png/jpg), the plain `text` (for the cheap classifier-only
harness mode), and a labeled corpus entry. A subset is also written as clean PDF.

Run with the bench python (no frappe needed):
    /home/rsmith/frappe-bench/env/bin/python test/receipts/realistic.py --n 40

Output: files in test/receipts/files/  +  test/receipts/realistic_corpus.json
(same schema as corpus.json, with "source":"synthetic-realistic" + "augmented").
"""

from __future__ import annotations

import argparse
import json
import os
import random

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "files")


# ---- assets ---------------------------------------------------------------
def _font(name, size):
    try:
        return ImageFont.truetype(name, size)
    except Exception:
        return ImageFont.load_default()


F_REG = lambda s: _font("DejaVuSans.ttf", s)        # noqa: E731
F_BOLD = lambda s: _font("DejaVuSans-Bold.ttf", s)  # noqa: E731
F_MONO = lambda s: _font("DejaVuSansMono.ttf", s)   # noqa: E731


def _qr(data, box=3):
    import qrcode

    qr = qrcode.QRCode(box_size=box, border=1)
    qr.add_data(data)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").convert("RGB")


def _logo(draw, x, y, initials, color, size=46):
    draw.rounded_rectangle([x, y, x + size, y + size], radius=8, fill=color)
    f = F_BOLD(int(size * 0.5))
    w = draw.textlength(initials, font=f)
    draw.text((x + (size - w) / 2, y + size * 0.22), initials, fill="white", font=f)


# ---- data model -----------------------------------------------------------
def _model(fake, rng, genre, paid, keyworded):
    cur = rng.choice(["USD", "EUR", "GBP"])
    sym = {"USD": "$", "EUR": "€", "GBP": "£"}[cur]
    vendor = fake.company()
    items = []
    for _ in range(rng.randint(2, 5)):
        items.append((fake.bs().title()[:26], round(rng.uniform(2, 480), 2)))
    subtotal = round(sum(p for _, p in items), 2)
    tax = round(subtotal * rng.choice([0.0, 0.05, 0.08, 0.2]), 2)
    total = round(subtotal + tax, 2)
    return {
        "genre": genre, "paid": paid, "keyworded": keyworded,
        "vendor": vendor, "initials": "".join(w[0] for w in vendor.split()[:2]).upper() or "AP",
        "addr": fake.street_address(), "city": f"{fake.city()}, {fake.postcode()}",
        "cur": cur, "sym": sym, "items": items, "subtotal": subtotal, "tax": tax, "total": total,
        "date": fake.date_between("-1y", "today").isoformat(),
        "ref": fake.bothify("??-####-#####").upper(),
        "card4": fake.numerify("####"), "approval": fake.numerify("#####"),
        "color": tuple(rng.randint(40, 180) for _ in range(3)),
    }


# ---- renderers (return (PIL image, plain text)) ---------------------------
def render_thermal(m, rng):
    """Narrow monospace thermal POS slip (receipt)."""
    W = 384
    rows = []
    rows.append(("c", F_BOLD(20), m["vendor"][:24]))
    rows.append(("c", F_MONO(12), m["addr"][:34]))
    rows.append(("c", F_MONO(12), m["city"][:34]))
    rows.append(("sep", None, None))
    if m["keyworded"]:
        rows.append(("l", F_MONO(12), f"SALES RECEIPT  #{m['ref']}"))
    rows.append(("l", F_MONO(12), m["date"]))
    rows.append(("sep", None, None))
    for name, price in m["items"]:
        rows.append(("kv", F_MONO(13), (name[:22], f"{m['sym']}{price:.2f}")))
    rows.append(("sep", None, None))
    rows.append(("kv", F_MONO(13), ("Subtotal", f"{m['sym']}{m['subtotal']:.2f}")))
    rows.append(("kv", F_MONO(13), ("Tax", f"{m['sym']}{m['tax']:.2f}")))
    rows.append(("kv", F_BOLD(15), ("TOTAL", f"{m['sym']}{m['total']:.2f}")))
    rows.append(("sep", None, None))
    if m["paid"]:
        rows.append(("l", F_MONO(12), f"VISA ****{m['card4']}"))
        if m["keyworded"]:
            rows.append(("l", F_MONO(12), f"Approval Code {m['approval']}"))
            rows.append(("l", F_MONO(12), "Change Due 0.00"))
    else:
        rows.append(("l", F_MONO(12), f"Balance Due {m['sym']}{m['total']:.2f}"))
        if m["keyworded"]:
            rows.append(("l", F_MONO(12), "PLEASE PAY AT COUNTER"))
    rows.append(("qr", None, m["ref"]))
    if m["keyworded"] and m["paid"]:
        rows.append(("c", F_MONO(12), "Thank you for your purchase"))

    H = 40
    for kind, f, _v in rows:
        H += 70 if kind == "qr" else (10 if kind == "sep" else 24)
    img = Image.new("RGB", (W, H + 30), "white")
    d = ImageDraw.Draw(img)
    y = 20
    for kind, f, v in rows:
        if kind == "sep":
            d.line([(16, y + 4), (W - 16, y + 4)], fill=(150, 150, 150)); y += 10
        elif kind == "c":
            w = d.textlength(v, font=f); d.text(((W - w) / 2, y), v, fill="black", font=f); y += 24
        elif kind == "l":
            d.text((16, y), v, fill="black", font=f); y += 24
        elif kind == "kv":
            k, val = v; d.text((16, y), k, fill="black", font=f)
            w = d.textlength(val, font=f); d.text((W - 16 - w, y), val, fill="black", font=f); y += 24
        elif kind == "qr":
            q = _qr(v).resize((60, 60)); img.paste(q, (int((W - 60) / 2), y)); y += 70
    return img, _text_receipt(m)


def render_invoice(m, rng, paid_stamp=False):
    """Formal A4-style invoice with logo + line-item table (invoice genre)."""
    W, H = 760, 560
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    _logo(d, 40, 36, m["initials"], m["color"])
    d.text((100, 40), m["vendor"][:34], fill="black", font=F_BOLD(22))
    d.text((100, 70), m["addr"][:40], fill=(80, 80, 80), font=F_REG(12))
    title = "INVOICE" if m["keyworded"] else "STATEMENT OF CHARGES"
    d.text((W - 220, 40), title, fill=m["color"], font=F_BOLD(30))
    d.text((W - 220, 80), f"No {m['ref']}", fill="black", font=F_MONO(12))
    d.text((W - 220, 98), m["date"], fill="black", font=F_MONO(12))
    d.text((40, 120), "Bill To: Acme Holdings, 1 Market St" if m["keyworded"] else "For: Acme Holdings",
           fill="black", font=F_REG(13))
    # table
    ty = 165
    d.rectangle([40, ty, W - 40, ty + 26], fill=(238, 238, 238))
    d.text((50, ty + 5), "Description", fill="black", font=F_BOLD(13))
    d.text((W - 150, ty + 5), "Amount", fill="black", font=F_BOLD(13))
    ty += 34
    for name, price in m["items"]:
        d.text((50, ty), name[:48], fill="black", font=F_REG(13))
        val = f"{m['sym']}{price:.2f}"; w = d.textlength(val, font=F_REG(13))
        d.text((W - 50 - w, ty), val, fill="black", font=F_REG(13)); ty += 26
    ty += 8
    d.line([(W - 300, ty), (W - 40, ty)], fill=(180, 180, 180)); ty += 8
    for k, val in (("Subtotal", m["subtotal"]), ("Tax", m["tax"]), ("Total", m["total"])):
        f = F_BOLD(15) if k == "Total" else F_REG(13)
        d.text((W - 300, ty), k, fill="black", font=f)
        s = f"{m['sym']}{val:.2f}"; w = d.textlength(s, font=f)
        d.text((W - 50 - w, ty), s, fill="black", font=f); ty += 24
    ty += 10
    if paid_stamp:
        d.text((40, ty), "PAID IN FULL — thank you", fill=(20, 130, 40), font=F_BOLD(16))
    elif m["keyworded"]:
        d.text((40, ty), f"Amount Due {m['sym']}{m['total']:.2f}  ·  Payment Terms: Net 30  ·  Please remit",
               fill="black", font=F_REG(13))
    else:
        d.text((40, ty), f"Due {m['date']}  ·  Bank transfer to acct {m['card4']}", fill="black", font=F_REG(13))
    img.paste(_qr(m["ref"]).resize((64, 64)), (40, H - 84))
    return img, _text_invoice(m, paid_stamp)


# ---- text serialization (what OCR roughly yields → classifier-only mode) --
def _text_receipt(m):
    lines = [m["vendor"], m["addr"], m["city"]]
    if m["keyworded"]:
        lines.append(f"SALES RECEIPT #{m['ref']}")
    lines.append(m["date"])
    lines += [f"{n} {m['sym']}{p:.2f}" for n, p in m["items"]]
    lines += [f"Subtotal {m['sym']}{m['subtotal']:.2f}", f"Tax {m['sym']}{m['tax']:.2f}", f"TOTAL {m['sym']}{m['total']:.2f}"]
    if m["paid"]:
        lines.append(f"VISA ****{m['card4']}")
        if m["keyworded"]:
            lines += [f"Approval Code {m['approval']}", "Change Due 0.00", "Thank you for your purchase"]
    else:
        lines.append(f"Balance Due {m['sym']}{m['total']:.2f}")
        if m["keyworded"]:
            lines.append("PLEASE PAY AT COUNTER")
    return "\n".join(lines)


def _text_invoice(m, paid_stamp):
    lines = [m["vendor"], m["addr"]]
    lines.append(f"INVOICE No {m['ref']}" if m["keyworded"] else f"Statement of charges {m['ref']}")
    lines.append(m["date"])
    lines.append("Bill To: Acme Holdings" if m["keyworded"] else "For: Acme Holdings")
    lines += [f"{n} {m['sym']}{p:.2f}" for n, p in m["items"]]
    lines += [f"Subtotal {m['sym']}{m['subtotal']:.2f}", f"Tax {m['sym']}{m['tax']:.2f}", f"Total {m['sym']}{m['total']:.2f}"]
    if paid_stamp:
        lines.append("PAID IN FULL — thank you")
    elif m["keyworded"]:
        lines.append(f"Amount Due {m['sym']}{m['total']:.2f}  Payment Terms Net 30  Please remit")
    else:
        lines.append(f"Due {m['date']}  Bank transfer to acct {m['card4']}")
    return "\n".join(lines)


# ---- orchestration --------------------------------------------------------
def _expected_dt(genre, paid):
    if paid:
        return "Already Paid"
    return "Unpaid Bill"


def generate(n=40, seed=7, augment_ratio=0.5):
    import sys

    sys.path.insert(0, HERE)
    from augment import scan_augment  # sibling module
    from faker import Faker

    fake = Faker()
    Faker.seed(seed)
    rng = random.Random(seed)
    os.makedirs(OUT, exist_ok=True)
    entries = []

    # plan: spread across genre × paid × difficulty × layout
    plans = []
    for i in range(n):
        keyworded = rng.random() < 0.5  # semantic vs keyword
        roll = rng.random()
        if roll < 0.4:
            plans.append(("receipt", True, keyworded, "thermal"))
        elif roll < 0.7:
            plans.append(("invoice", False, keyworded, "invoice"))
        elif roll < 0.8:
            plans.append(("invoice", True, keyworded, "paid_invoice"))   # adversarial
        elif roll < 0.9:
            plans.append(("receipt", False, keyworded, "unpaid_receipt"))  # adversarial
        else:
            plans.append(("receipt", True, keyworded, "thermal"))

    for i, (genre, paid, keyworded, layout) in enumerate(plans):
        m = _model(fake, rng, genre, paid, keyworded)
        if layout in ("thermal", "unpaid_receipt"):
            img, text = render_thermal(m, rng)
        elif layout == "paid_invoice":
            img, text = render_invoice(m, rng, paid_stamp=True)
        else:
            img, text = render_invoice(m, rng)

        augmented = rng.random() < augment_ratio
        if augmented:
            img = scan_augment(img, seed=seed + i, intensity=rng.choice(["light", "medium", "heavy"]))
        fmt = "jpg" if augmented else "png"
        eid = f"real_{i:03d}_{layout}"
        img.save(os.path.join(OUT, f"{eid}.{fmt}"), quality=85)

        difficulty = "adversarial" if layout in ("paid_invoice", "unpaid_receipt") else (
            "keyword" if keyworded else "semantic")
        entry = {
            "id": eid, "source": "synthetic-realistic", "difficulty": difficulty,
            "file": f"{eid}.{fmt}", "format": fmt, "augmented": augmented, "layout": layout,
            "vendor": m["vendor"], "currency": m["cur"],
            "label": {"genre": genre, "paid": paid, "expected_document_type": _expected_dt(genre, paid)},
            "text": text,
        }
        entries.append(entry)
        # Paired per-file ground-truth JSON (mirrors generate_receipts.py / the invoice
        # corpus convention, so every receipt image has its own definition next to it).
        json.dump(entry, open(os.path.join(OUT, f"{eid}.json"), "w"), indent=2)

    json.dump({"_about": "Track B synthetic-realistic corpus — see README.md", "entries": entries},
              open(os.path.join(HERE, "realistic_corpus.json"), "w"), indent=1)
    by = {}
    for e in entries:
        by[e["difficulty"]] = by.get(e["difficulty"], 0) + 1
    print(f"Generated {len(entries)} realistic docs in {OUT} ({by}); "
          f"corpus → realistic_corpus.json")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--augment-ratio", type=float, default=0.5)
    args = ap.parse_args()
    generate(n=args.n, seed=args.seed, augment_ratio=args.augment_ratio)
