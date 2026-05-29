"""HTML/CSS invoice templates for the test corpus.

Four visually distinct vendor styles, each rendering a logo, bill-to block, a
line-item table, a subtotal/tax/total breakdown, and a footer. Rendered to
PDF/PNG via headless Chromium by generate_invoices.py.

Each template function takes a ``spec`` dict and returns a full HTML string.
The spec's monetary/line-item values are authoritative — the ground truth in
generate_invoices.py is derived from the same spec, so renders and labels stay
in sync.
"""

from __future__ import annotations

from datetime import date

CURRENCY_SYMBOL = {
	"USD": "$", "EUR": "€", "GBP": "£", "INR": "₹",
	"CAD": "C$", "JPY": "¥", "AUD": "A$",
}


def fmt_date(iso: str, style: str) -> str:
	y, m, d = (int(x) for x in iso.split("-"))
	dt = date(y, m, d)
	return {
		"iso": iso,
		"us": f"{m:02d}/{d:02d}/{y}",
		"eu": f"{d:02d}.{m:02d}.{y}",
		"long": dt.strftime("%d %B %Y"),
	}.get(style, iso)


def money(amount: float, currency: str, *, symbol=True) -> str:
	sym = CURRENCY_SYMBOL.get(currency, "")
	body = f"{int(round(amount)):,}" if currency == "JPY" else f"{amount:,.2f}"
	return f"{sym}{body}" if symbol else body


def _logo_svg(initials: str, color: str) -> str:
	return (
		f'<svg width="64" height="64" viewBox="0 0 64 64">'
		f'<rect rx="12" width="64" height="64" fill="{color}"/>'
		f'<text x="32" y="42" font-size="28" font-family="Arial" font-weight="700" '
		f'fill="#fff" text-anchor="middle">{initials}</text></svg>'
	)


def _line_rows(spec, *, money_symbol=True):
	rows = []
	for it in spec["line_items"]:
		desc, qty, unit = it
		line_total = qty * unit
		rows.append(
			(desc, qty, money(unit, spec["currency"], symbol=money_symbol),
			 money(line_total, spec["currency"], symbol=money_symbol))
		)
	return rows


# --- Template 1: modern SaaS (accent header, zebra table, totals box) -------
def tmpl_modern(spec) -> str:
	accent = spec.get("accent", "#2b6cb0")
	d = fmt_date(spec["invoice_date"], spec["date_style"]) if spec.get("invoice_date") else ""
	# When show_currency is False, drop the currency marker EVERYWHERE (line
	# items, subtotal, tax, total) so the invoice genuinely states no currency.
	sym = spec.get("show_currency", True)
	rows = "".join(
		f'<tr class="{"z" if i%2 else ""}"><td>{desc}</td><td class="r">{qty}</td>'
		f'<td class="r">{unit}</td><td class="r">{tot}</td></tr>'
		for i, (desc, qty, unit, tot) in enumerate(_line_rows(spec, money_symbol=sym))
	)
	cur = spec["currency"]
	inv_no_row = (
		f'<div><span>Invoice #</span><b>{spec["invoice_no"]}</b></div>'
		if spec.get("invoice_no") else ""
	)
	date_row = f'<div><span>Date</span><b>{d}</b></div>' if d else ""
	currency_total = money(spec["total"], cur, symbol=sym)
	return f"""<!doctype html><html><head><meta charset="utf-8"><style>
* {{ box-sizing:border-box; }} body {{ font-family:'DejaVu Sans',Arial,sans-serif; color:#1a202c; margin:0; padding:48px; font-size:14px; }}
.head {{ display:flex; justify-content:space-between; align-items:center; }}
.brand {{ display:flex; gap:16px; align-items:center; }}
.brand .nm {{ font-size:22px; font-weight:700; }} .brand .sub {{ color:#718096; font-size:12px; }}
.title {{ text-align:right; }} .title h1 {{ margin:0; font-size:34px; color:{accent}; letter-spacing:2px; }}
.meta {{ text-align:right; margin-top:8px; }} .meta div {{ margin:2px 0; }} .meta span {{ color:#718096; margin-right:8px; }}
.parties {{ display:flex; gap:48px; margin:36px 0 8px; }}
.parties h4 {{ margin:0 0 4px; color:{accent}; font-size:12px; text-transform:uppercase; letter-spacing:1px; }}
table {{ width:100%; border-collapse:collapse; margin-top:16px; }}
th {{ background:{accent}; color:#fff; padding:10px; text-align:left; font-size:12px; }}
td {{ padding:10px; border-bottom:1px solid #e2e8f0; }} td.r,th.r {{ text-align:right; }}
tr.z td {{ background:#f7fafc; }}
.totals {{ width:280px; margin-left:auto; margin-top:16px; }}
.totals div {{ display:flex; justify-content:space-between; padding:6px 10px; }}
.totals .g {{ background:{accent}; color:#fff; font-weight:700; font-size:16px; border-radius:6px; }}
.foot {{ margin-top:40px; color:#718096; font-size:12px; border-top:1px solid #e2e8f0; padding-top:12px; }}
</style></head><body>
<div class="head">
  <div class="brand">{_logo_svg(spec["initials"], accent)}
    <div><div class="nm">{spec["supplier"]}</div><div class="sub">{spec.get("vendor_tag","")}</div></div></div>
  <div class="title"><h1>INVOICE</h1><div class="meta">{inv_no_row}{date_row}</div></div>
</div>
<div class="parties">
  <div><h4>Bill To</h4>{spec.get("bill_to","NexeraDigital Pilot Co.<br>123 Finance Way")}</div>
  <div><h4>Pay To</h4>{spec["supplier"]}<br>{spec.get("vendor_addr","Suite 200")}</div>
</div>
<table><tr><th>Description</th><th class="r">Qty</th><th class="r">Unit</th><th class="r">Amount</th></tr>{rows}</table>
<div class="totals">
  <div><span>Subtotal</span><span>{money(spec["subtotal"], cur, symbol=sym)}</span></div>
  <div><span>Tax ({spec["tax_rate"]}%)</span><span>{money(spec["tax_amount"], cur, symbol=sym)}</span></div>
  <div class="g"><span>Total Due</span><span>{currency_total}</span></div>
</div>
<div class="foot">Payment due within 30 days. {spec.get("terms","Bank transfer preferred.")}</div>
</body></html>"""


# --- Template 2: classic corporate (serif, ruled, centered) -----------------
def tmpl_classic(spec) -> str:
	d = fmt_date(spec["invoice_date"], spec["date_style"]) if spec.get("invoice_date") else ""
	rows = "".join(
		f'<tr><td>{desc}</td><td class="r">{qty}</td><td class="r">{unit}</td><td class="r">{tot}</td></tr>'
		for (desc, qty, unit, tot) in _line_rows(spec)
	)
	cur = spec["currency"]
	meta = []
	if spec.get("invoice_no"):
		meta.append(f"Invoice No. {spec['invoice_no']}")
	if d:
		meta.append(f"Date: {d}")
	return f"""<!doctype html><html><head><meta charset="utf-8"><style>
body {{ font-family:'DejaVu Serif',Georgia,serif; color:#111; margin:0; padding:56px; font-size:14px; }}
.center {{ text-align:center; }} h1 {{ margin:0; letter-spacing:6px; font-size:26px; }}
.co {{ font-size:20px; font-weight:700; margin-top:8px; }} .addr {{ color:#444; font-size:12px; }}
hr {{ border:none; border-top:2px solid #111; margin:18px 0; }}
.meta {{ display:flex; justify-content:space-between; margin:10px 0 18px; font-size:13px; }}
table {{ width:100%; border-collapse:collapse; }}
th {{ border-bottom:2px solid #111; padding:8px; text-align:left; }}
td {{ padding:8px; border-bottom:1px solid #bbb; }} .r {{ text-align:right; }}
.tot {{ margin-top:14px; width:300px; margin-left:auto; }}
.tot div {{ display:flex; justify-content:space-between; padding:4px 0; }}
.tot .grand {{ border-top:2px solid #111; font-weight:700; font-size:16px; padding-top:8px; }}
.foot {{ margin-top:36px; font-size:12px; color:#444; font-style:italic; }}
</style></head><body>
<div class="center"><h1>I N V O I C E</h1>
  <div class="co">{spec["supplier"]}</div>
  <div class="addr">{spec.get("vendor_addr","Registered Office, Commerce St.")}</div></div>
<hr>
<div class="meta"><div>Bill To: {spec.get("bill_to_name","NexeraDigital Pilot Co.")}</div><div>{' &nbsp; '.join(meta)}</div></div>
<table><tr><th>Particulars</th><th class="r">Qty</th><th class="r">Rate</th><th class="r">Amount</th></tr>{rows}</table>
<div class="tot">
  <div><span>Subtotal</span><span>{money(spec["subtotal"], cur)}</span></div>
  <div><span>Tax ({spec["tax_rate"]}%)</span><span>{money(spec["tax_amount"], cur)}</span></div>
  <div class="grand"><span>Total {cur}</span><span>{money(spec["total"], cur, symbol=False)}</span></div>
</div>
<div class="foot">Remit to account on file. Thank you for your business.</div>
</body></html>"""


# --- Template 3: European VAT (VAT no, IBAN, tax-by-rate) --------------------
def tmpl_euvat(spec) -> str:
	accent = spec.get("accent", "#2f855a")
	d = fmt_date(spec["invoice_date"], "eu") if spec.get("invoice_date") else ""
	rows = "".join(
		f'<tr><td>{desc}</td><td class="r">{qty}</td><td class="r">{unit}</td>'
		f'<td class="r">{spec["tax_rate"]}%</td><td class="r">{tot}</td></tr>'
		for (desc, qty, unit, tot) in _line_rows(spec)
	)
	cur = spec["currency"]
	return f"""<!doctype html><html><head><meta charset="utf-8"><style>
body {{ font-family:'DejaVu Sans',Arial,sans-serif; color:#1a202c; margin:0; padding:44px; font-size:13px; }}
.top {{ display:flex; justify-content:space-between; border-bottom:3px solid {accent}; padding-bottom:14px; }}
.co {{ font-size:20px; font-weight:700; color:{accent}; }} .small {{ color:#555; font-size:11px; line-height:1.5; }}
.rt {{ text-align:right; }} .rt .lbl {{ color:{accent}; font-weight:700; font-size:22px; }}
.box {{ background:#f0fff4; border:1px solid {accent}; border-radius:6px; padding:10px 14px; margin:18px 0; font-size:12px; }}
table {{ width:100%; border-collapse:collapse; margin-top:8px; }}
th {{ background:#edf2f7; padding:9px; text-align:left; border-bottom:2px solid {accent}; }}
td {{ padding:9px; border-bottom:1px solid #e2e8f0; }} .r {{ text-align:right; }}
.tot {{ width:300px; margin-left:auto; margin-top:14px; }}
.tot div {{ display:flex; justify-content:space-between; padding:5px 8px; }}
.tot .g {{ background:{accent}; color:#fff; font-weight:700; border-radius:6px; font-size:15px; }}
.foot {{ margin-top:30px; font-size:11px; color:#555; }}
</style></head><body>
<div class="top">
  <div><div class="co">{spec["supplier"]}</div>
    <div class="small">{spec.get("vendor_addr","Hauptstrasse 12, 10115")}<br>
    VAT No: {spec.get("vat_no","DE123456789")}<br>IBAN: {spec.get("iban","DE89 3704 0044 0532 0130 00")}</div></div>
  <div class="rt"><div class="lbl">RECHNUNG / INVOICE</div>
    <div class="small">No. {spec.get("invoice_no","")}<br>{('Datum: '+d) if d else ''}</div></div>
</div>
<div class="box"><b>Bill To:</b> {spec.get("bill_to_name","NexeraDigital Pilot Co.")} &nbsp;|&nbsp; Reverse charge may apply.</div>
<table><tr><th>Leistung / Item</th><th class="r">Menge</th><th class="r">Einzelpreis</th><th class="r">MwSt</th><th class="r">Betrag</th></tr>{rows}</table>
<div class="tot">
  <div><span>Zwischensumme</span><span>{money(spec["subtotal"], cur)}</span></div>
  <div><span>MwSt {spec["tax_rate"]}%</span><span>{money(spec["tax_amount"], cur)}</span></div>
  <div class="g"><span>Gesamtbetrag</span><span>{money(spec["total"], cur)}</span></div>
</div>
<div class="foot">Zahlbar innerhalb 14 Tagen. Payable within 14 days to the IBAN above.</div>
</body></html>"""


# --- Template 4: minimal contractor (whitespace, single accent line) --------
def tmpl_minimal(spec) -> str:
	accent = spec.get("accent", "#dd6b20")
	d = fmt_date(spec["invoice_date"], spec["date_style"]) if spec.get("invoice_date") else ""
	rows = "".join(
		f'<tr><td>{desc}</td><td class="r">{tot}</td></tr>'
		for (desc, qty, unit, tot) in _line_rows(spec)
	)
	cur = spec["currency"]
	total_str = money(spec["total"], cur) if spec.get("show_currency", True) else money(spec["total"], cur, symbol=False)
	return f"""<!doctype html><html><head><meta charset="utf-8"><style>
body {{ font-family:'DejaVu Sans',Helvetica,Arial,sans-serif; color:#222; margin:0; padding:72px; font-size:15px; font-weight:300; }}
.nm {{ font-size:30px; font-weight:700; }} .line {{ height:4px; width:80px; background:{accent}; margin:14px 0 36px; }}
.row {{ display:flex; justify-content:space-between; color:#666; font-size:13px; margin-bottom:40px; }}
table {{ width:100%; border-collapse:collapse; }}
td {{ padding:12px 0; border-bottom:1px solid #eee; }} .r {{ text-align:right; }}
.total {{ margin-top:30px; text-align:right; }} .total .lbl {{ color:#999; font-size:13px; }}
.total .amt {{ font-size:30px; font-weight:700; color:{accent}; }}
.sig {{ margin-top:60px; font-family:'DejaVu Serif',cursive; font-style:italic; font-size:20px; color:#444; }}
</style></head><body>
<div class="nm">{spec["supplier"]}</div><div class="line"></div>
<div class="row">
  <div>{('Invoice '+spec['invoice_no']) if spec.get('invoice_no') else 'Invoice'}<br>{('Issued '+d) if d else ''}</div>
  <div>For: {spec.get("bill_to_name","NexeraDigital Pilot Co.")}</div>
</div>
<table>{rows}</table>
<div class="total"><div class="lbl">Total Due ({cur})</div><div class="amt">{total_str}</div></div>
<div class="sig">— {spec.get("signer", spec["supplier"].split()[0])}</div>
</body></html>"""


TEMPLATES = {
	"modern": tmpl_modern,
	"classic": tmpl_classic,
	"euvat": tmpl_euvat,
	"minimal": tmpl_minimal,
}
