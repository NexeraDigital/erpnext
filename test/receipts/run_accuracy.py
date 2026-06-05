"""Accuracy harness for the content classifier — rule scorer (Phase 1) vs LLM (Phase 2).

Runs every labeled corpus entry (corpus.json) through the chosen classifier provider,
compares the predicted genre / paid / document_type to the ground-truth label, and
prints per-difficulty-tier accuracy + a genre confusion matrix + the misses. This is
the "how good is it actually" measurement the per-feature unit tests don't give you.

Runs inside a frappe context (it imports the classifier). Load it as a MODULE via
importlib (a bare ``exec(open().read())`` breaks module-global scoping). Bench console:

    # Rule scorer (free, deterministic):
    echo 'import importlib.util, frappe; frappe.flags.ra_provider="rule"; \
      p=frappe.get_app_path("erpnext","..","test","receipts","run_accuracy.py"); \
      s=importlib.util.spec_from_file_location("ra",p); \
      m=importlib.util.module_from_spec(s); s.loader.exec_module(m)' \
      | bench --site erpnext.localhost console

    # LLM (REAL Anthropic calls — needs a key in AI Provider Settings, costs credits):
    #   ...same, with frappe.flags.ra_provider="anthropic"

The harness exercises the content classifier in ISOLATION (it calls the scorer/LLM
directly), then derives the document_type the full Step-6 cascade would reach, INCLUDING
the card/PAID marker short-circuit (_detect_card_marker), so the document_type column
reflects real routing. Override / employee-group branches are out of scope here.
"""

import json
import os

import frappe

from erpnext.accounts.doctype.document_capture.document_capture import (
    _classify_text_anthropic,
    _detect_card_marker,
    _score_document_content,
)

import glob

_DIR = os.path.join(frappe.get_app_path("erpnext"), "..", "test", "receipts")
# SOURCE OF TRUTH: the per-file JSONs the generators emit — one self-contained labeled
# entry per receipt, alongside its image. Seed + Track-B realistic land in files/;
# Track-A external datasets land in external/files/. The combined corpus.json /
# realistic_corpus.json are just manifests now and are NOT read here. Run the generators
# first (generate_receipts.py, realistic.py, fetch_datasets.py) to materialise them.
_ENTRY_GLOBS = [
    os.path.join(_DIR, "files", "*.json"),
    os.path.join(_DIR, "external", "files", "*.json"),
]


def _load_entries():
    entries = []
    for pattern in _ENTRY_GLOBS:
        for path in sorted(glob.glob(pattern)):
            e = json.load(open(path))
            if "label" not in e:  # skip stray non-entry json
                continue
            e.setdefault("id", os.path.splitext(os.path.basename(path))[0])
            e.setdefault("source", "seed")
            e.setdefault("difficulty", "real")
            e.setdefault("text", "")
            entries.append(e)
    if not entries:
        print("No per-file entries found in files/ — run the generators first "
              "(generate_receipts.py / realistic.py / fetch_datasets.py).")
    return entries


_GENRE_FROM_KIND = {"Receipt": "receipt", "Invoice": "invoice",
                    "Statement": "other", "CreditNote": "other", "Other": "other"}
_PAID_FROM_STATE = {"Paid": True, "Unpaid": False, "Unknown": None}


def _baml_verdict(entry):
    """Read the entry's IMAGE with the BAML cheap-vision provider (real call)."""
    import base64
    import os as _os

    from baml_py import Image, Pdf

    from erpnext.accounts.ap_closed_loop.baml_client.sync_client import b

    fname = entry.get("file") or _os.path.basename(entry.get("image", ""))
    path = _os.path.join(_DIR, "files", fname)
    if not _os.path.exists(path) and entry.get("image"):
        path = _os.path.join(_DIR, entry["image"])
    data = base64.standard_b64encode(open(path, "rb").read()).decode()
    ext = fname.rsplit(".", 1)[-1].lower()
    media = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
             "pdf": "application/pdf"}.get(ext, "image/png")
    r = b.ReadReceiptPdf(Pdf.from_base64(data)) if media == "application/pdf" \
        else b.ReadReceipt(Image.from_base64(media, data))
    kind = getattr(r.kind, "value", str(r.kind))
    pay = getattr(r.payment_state, "value", str(r.payment_state))
    return {"genre": _GENRE_FROM_KIND.get(kind, "unknown"),
            "paid": _PAID_FROM_STATE.get(pay), "confidence": float(r.confidence or 0),
            "signals": [], "provider": "baml"}


def _verdict(entry, provider):
    text = entry.get("text", "")
    if provider == "baml":
        try:
            return _baml_verdict(entry)
        except Exception as exc:
            print(f"  [warn] baml failed for {entry.get('id')} ({exc}); counting as unknown")
            return {"genre": "unknown", "paid": None, "confidence": 0.0, "signals": [], "provider": "error"}
    if provider == "anthropic":
        try:
            return _classify_text_anthropic(text)
        except Exception as exc:  # per-entry resilience — never abort a paid run
            print(f"  [warn] anthropic call failed ({exc}); counting as unknown")
            return {"genre": "unknown", "paid": None, "confidence": 0.0, "signals": [], "provider": "error"}
    return _score_document_content(text, has_card_marker=bool(_detect_card_marker(text)[0]))


def _predicted_document_type(text, verdict):
    # Mirror classify_document_type's content branch + the marker short-circuit.
    if _detect_card_marker(text)[0]:
        return "Already Paid"
    if verdict["genre"] == "receipt" and verdict["paid"] is not False:
        return "Already Paid"
    return "Unpaid Bill"


def run(provider="rule"):
    corpus = _load_entries()
    # BAML / anthropic need the key in env; fetch it from AI Provider Settings.
    if provider in ("baml", "anthropic"):
        from frappe.utils.password import get_decrypted_password

        key = get_decrypted_password("AI Provider Settings", "AI Provider Settings",
                                     "anthropic_api_key", raise_exception=False)
        if key:
            os.environ["ANTHROPIC_API_KEY"] = key
    tiers = {}
    sources = {}
    confusion = {}  # (true_genre, pred_genre) -> count
    misses = []

    for e in corpus:
        text, label = e["text"], e["label"]
        v = _verdict(e, provider)
        pred_genre = v["genre"]
        pred_paid = v["paid"]
        pred_dt = _predicted_document_type(text, v)

        genre_ok = pred_genre == label["genre"]
        paid_ok = pred_paid == label["paid"]
        dt_ok = pred_dt == label["expected_document_type"]

        for bucket, key in ((tiers, e["difficulty"]), (sources, e.get("source", "seed"))):
            b = bucket.setdefault(key, {"n": 0, "genre": 0, "paid": 0, "dt": 0})
            b["n"] += 1
            b["genre"] += genre_ok
            b["paid"] += paid_ok
            b["dt"] += dt_ok
        confusion[(label["genre"], pred_genre)] = confusion.get((label["genre"], pred_genre), 0) + 1
        if not (genre_ok and paid_ok and dt_ok):
            misses.append(
                f"  {e['id']:30} true(genre={label['genre']},paid={label['paid']},dt={label['expected_document_type']}) "
                f"got(genre={pred_genre},paid={pred_paid},dt={pred_dt}) conf={v['confidence']}"
            )

    print(f"\n===== Content classifier accuracy — provider={provider} =====")
    print(f"{'tier':14}{'n':>4}{'genre':>9}{'paid':>9}{'doc_type':>10}")
    tot = {"n": 0, "genre": 0, "paid": 0, "dt": 0}
    for name in ("keyword", "semantic", "adversarial"):
        t = tiers.get(name)
        if not t:
            continue
        for k in tot:
            tot[k] += t[k]
        print(f"{name:14}{t['n']:>4}{t['genre']/t['n']:>8.0%}{t['paid']/t['n']:>9.0%}{t['dt']/t['n']:>10.0%}")
    n = tot["n"] or 1
    print(f"{'OVERALL':14}{tot['n']:>4}{tot['genre']/n:>8.0%}{tot['paid']/n:>9.0%}{tot['dt']/n:>10.0%}")

    print(f"\n{'by source':14}{'n':>4}{'genre':>9}{'paid':>9}{'doc_type':>10}")
    for name in sorted(sources):
        s = sources[name]
        print(f"{name:14}{s['n']:>4}{s['genre']/s['n']:>8.0%}{s['paid']/s['n']:>9.0%}{s['dt']/s['n']:>10.0%}")

    print("\nGenre confusion (true → predicted):")
    for (tg, pg), c in sorted(confusion.items()):
        flag = "" if tg == pg else "   <-- miss"
        print(f"  {tg:8} -> {pg:8} : {c}{flag}")

    if misses:
        print(f"\nMisses ({len(misses)}):")
        print("\n".join(misses))
    print()
    return tot


# Auto-run when exec'd in a connected console (provider from frappe.flags.ra_provider).
run(provider=(getattr(frappe.flags, "ra_provider", None) or "rule"))
