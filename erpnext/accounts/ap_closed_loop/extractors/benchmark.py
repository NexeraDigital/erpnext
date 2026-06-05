# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""OCR accuracy benchmark against the invoice test corpus.

Runs every invoice in ``test/invoices/`` through an OCR provider and scores the
extraction field-by-field against the committed ground truth, reporting per-field
accuracy and a perfect-invoice count.

This is a manual / on-demand evaluation tool, NOT a unit test — it makes one real
API call per invoice when run against the ``anthropic`` provider (~20 calls, a
few cents on Haiku). The pure scoring logic (``match_field``) is unit-tested in
``test_benchmark.py`` without any API calls.

Usage:
    bench --site <site> execute \\
        erpnext.accounts.ap_closed_loop.extractors.benchmark.run
    # against a specific provider / subset:
    bench --site <site> execute \\
        erpnext.accounts.ap_closed_loop.extractors.benchmark.run \\
        --kwargs '{"provider": "anthropic", "files": ["invoice_01", "invoice_18"]}'

Run it whenever the model version changes to catch accuracy regressions.
"""

from __future__ import annotations

import glob
import json
import os
import re
import traceback

import frappe

FIELDS = ("supplier", "supplier_invoice_no", "invoice_date", "total_amount", "currency")


# --- pure scoring logic (unit-tested, no API) -------------------------------

def _normalize_text(s) -> str:
	return re.sub(r"[^a-z0-9]", "", str(s).lower()) if s is not None else ""


def match_field(field, expected, got, expected_missing, missing_fields) -> bool:
	"""Return True if the extracted value for ``field`` is acceptable.

	Rules:
	  * expected_missing fields pass when the model returned nothing OR flagged
	    the field missing,
	  * total_amount compares numerically (epsilon 0.01),
	  * supplier is fuzzy (normalized equality or containment),
	  * other fields are exact after strip.
	"""
	expected_missing = expected_missing or []
	missing_fields = missing_fields or set()
	if field in expected_missing:
		return (got in (None, "")) or (field in missing_fields)
	if expected is None:
		return got in (None, "")
	if field == "total_amount":
		try:
			return abs(float(expected) - float(got)) < 0.01
		except (TypeError, ValueError):
			return False
	if field == "supplier":
		e, g = _normalize_text(expected), _normalize_text(got)
		return bool(e) and (e == g or e in g or g in e)
	return str(expected).strip() == str(got).strip()


def score(definition: dict, proposal: dict, missing_fields) -> dict:
	"""Score one extraction against a corpus definition. Pure."""
	exp = definition["expected"]
	exp_missing = definition.get("expected_missing", [])
	marks = {
		f: match_field(f, exp.get(f), proposal.get(f), exp_missing, missing_fields)
		for f in FIELDS
	}
	return {"marks": marks, "n_ok": sum(marks.values())}


# --- corpus location + runner (live) ----------------------------------------

def _corpus_dir() -> str:
	return os.path.abspath(
		os.path.join(frappe.get_app_path("erpnext"), "..", "test", "invoices")
	)


def _extract_one(definition: dict, base_dir: str, provider: str, model, threshold):
	"""Upload the corpus file, run the provider, return (proposal, missing).

	``base_dir`` is the directory holding this definition's JSON (the corpus is
	organised into per-purpose subfolders, e.g. ``ocr-extraction/``), so the image
	is resolved next to its definition, not at the corpus root."""
	from erpnext.accounts.ap_closed_loop.extractors.registry import get_extractor

	fname = definition["file"]
	content = open(os.path.join(base_dir, fname), "rb").read()
	existing = frappe.db.get_value("File", {"file_name": fname}, "name")
	if existing:
		frappe.delete_doc("File", existing, force=True, ignore_permissions=True)
	fdoc = frappe.get_doc(
		{"doctype": "File", "file_name": fname, "is_private": 1, "content": content}
	).insert(ignore_permissions=True)
	frappe.db.commit()
	try:
		cap = frappe.new_doc("Document Capture")
		cap.source_filename = fname
		cap.file_extension = definition["format"]
		cap.intake_channel = "Manual ERPNext Upload"
		cap.is_supported_format = 1
		cap.source_file = fdoc.name
		cap.received_at = frappe.utils.now_datetime()
		kwargs = {}
		if model:
			kwargs["model"] = model
		if threshold is not None:
			kwargs["confidence_threshold"] = threshold
		result = get_extractor(provider, **kwargs).extract(cap)
		return result.proposal, result.missing_fields
	finally:
		frappe.delete_doc("File", fdoc.name, force=True, ignore_permissions=True)
		frappe.db.commit()


def run(provider: str = "anthropic", model: str | None = None,
        threshold: float | None = None, files=None, verbose: bool = True) -> dict:
	"""Benchmark the corpus. Returns a summary dict; prints a report if verbose.

	provider  — registry key ("anthropic" | "fake"). Defaults to anthropic
	            (the only one that actually reads image content).
	files     — optional list of basenames (e.g. ["invoice_01"]) to limit the run.
	"""
	corpus = _corpus_dir()
	# Recurse: the corpus is organised into per-purpose subfolders (ocr-extraction/).
	defs = sorted(glob.glob(os.path.join(corpus, "**", "invoice_*.json"), recursive=True))
	if files:
		want = {f if f.endswith(".json") else f + ".json" for f in files}
		defs = [d for d in defs if os.path.basename(d) in want]

	pf_ok = {f: 0 for f in FIELDS}
	pf_total = {f: 0 for f in FIELDS}
	perfect = 0
	errors = 0
	rows = []

	for dp in defs:
		definition = json.load(open(dp))
		try:
			proposal, missing = _extract_one(definition, os.path.dirname(dp), provider, model, threshold)
			s = score(definition, proposal, missing)
			for f in FIELDS:
				pf_total[f] += 1
				pf_ok[f] += s["marks"][f]
			perfect += s["n_ok"] == len(FIELDS)
			rows.append((definition, s, proposal, None))
		except Exception as e:  # noqa: BLE001 - one bad invoice shouldn't abort the run
			errors += 1
			rows.append((definition, None, None, str(e)[:100]))
			if verbose:
				traceback.print_exc()

	total = sum(pf_total.values())
	ok = sum(pf_ok.values())
	summary = {
		"provider": provider,
		"model": model,
		"invoices": len(defs),
		"perfect": perfect,
		"errors": errors,
		"field_accuracy": (ok, total),
		"per_field": {f: (pf_ok[f], pf_total[f]) for f in FIELDS},
	}

	if verbose:
		_print_report(rows, summary)
	return summary


def _print_report(rows, summary) -> None:
	print("=== OCR BENCHMARK ===")
	print(f"provider={summary['provider']} model={summary['model'] or '(default)'}")
	for definition, s, proposal, err in rows:
		fname = definition["file"]
		tag = f"[{definition['quality']:8}/{definition['format']}]"
		if err:
			print(f"  {fname:16} {tag} ERROR: {err}")
			continue
		fl = lambda f: "." if s["marks"][f] else "X"
		print(f"  {fname:16} {tag} {s['n_ok']}/5  "
		      f"sup{fl('supplier')} no{fl('supplier_invoice_no')} "
		      f"dt{fl('invoice_date')} tot{fl('total_amount')} cur{fl('currency')}")
		for f in FIELDS:
			if not s["marks"][f]:
				exp = definition["expected"].get(f)
				print(f"        {f}: expected={exp!r} got={proposal.get(f)!r}")
	print("--- per field ---")
	for f in FIELDS:
		o, t = summary["per_field"][f]
		print(f"  {f:22} {o}/{t} ({100*o//t if t else 0}%)")
	o, t = summary["field_accuracy"]
	print(f"perfect: {summary['perfect']}/{summary['invoices']}   "
	      f"fields: {o}/{t} ({100*o//t if t else 0}%)   errors: {summary['errors']}")
