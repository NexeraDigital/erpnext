---
spec: 03-deduplication
title: Pre-Extraction Deduplication (exact + perceptual)
plan_step: Step 2 — Pre-Extraction Deduplication
stream: both
status: Done
depends_on: [01-foundations-settings-async-idempotency, 02-intake-stream-tagging]
related: [00-overview, 04-extraction-confidence-line-items, 08-validation-gates, 10-ap-review-observability]
---

# 03 — Pre-Extraction Deduplication (exact + perceptual)
> _Revised 2026-05-31: applied native-vs-custom review findings; added Playwright UI test plan (§7.3)._
> _Revised 2026-06-02: re-visioned automation-first ([[00-overview]] "Guiding principle")._

> **Automation-first stance.** This spec saves both human attention and AI money with **no human in the loop on the common case**: an exact file-hash re-upload is **auto-blocked before a single OCR dollar is spent** — the capture short-circuits to `STATUS_DUPLICATE`, links its original, and never reaches the billable extractor, fully automatically. The design deliberately **escalates, but does not dead-end**: a fuzzy near-duplicate look-alike (a re-scan of the same artifact) is flagged for a human (`action_required` + a "suspected near-duplicate" reason) **yet still proceeds to OCR** (D1 recommended (b)), so the clerk has the extracted fields to confirm or dismiss and the document never falls out of the pipeline. That suspected-near-duplicate flag is the single escalation seam, and it is a soft flag layered on a still-advancing capture — not a stop. The doctrine table lists **no automation gap** for this spec; it is already automation-first, with the follow-on body-text fingerprint (D2) the only mechanism that gates a suspect's eventual auto-close.

## 1. Summary
This spec builds the **firewall against double-booking**: before any OCR call is spent, every freshly-intaken `AP Invoice Capture` is checked against the last 90 days for an **exact file-hash match** (re-uploads of the same bytes) and a **fuzzy near-duplicate match** (re-scans of the same document). It implements **Step 2** of `workflow-v2-plan.md` and is **stream-agnostic** — a re-upload is a duplicate whether the artifact was tagged Stream R (receipt) or Stream I (invoice). Current-state delta: there is **no** `content_hash`, `perceptual_hash`, `duplicate_of`, or `STATUS_DUPLICATE` today, and no dedupe step exists in the cascade — this slots a new pre-OCR hop into the existing `after_insert → _kick_next_step → _determine_next_step` machine so a duplicate never reaches the billable extractor.

## 2. Plan alignment

**Step 2 text** (`docs/planning/workflow-v2-plan.md:28-29`):
> **2. Pre-Extraction Deduplication**
> Before any extraction runs, the document is checked against the last 90 days of intake for duplicates. Two checks run in parallel: an exact file-hash check (catches re-uploads of the same image) and a fuzzy near-duplicate check (catches re-scans of the same receipt). Any hit short-circuits the workflow and surfaces the original record to the operator rather than starting a second extraction. This is the firewall against the most common AP error — paying or booking the same invoice twice.

**Control-Summary row** (`workflow-v2-plan.md:125`):
> | File-hash + fuzzy dedupe | Step 2 | Prevents double-booking |

**Control-Points line** (`workflow-v2-plan.md:148`) lists "Deduplication" as a control point for **both** streams. The two-stream framing (`workflow-v2-plan.md:13, 148`) confirms dedupe is shared infrastructure.

**Stream R vs Stream I behavior here: identical (stream-agnostic).** `detect_duplicates_for` keys purely on file bytes (`content_hash`) and rasterized-page image (`perceptual_hash`) within a `received_at` window. It MUST NOT read or filter on any `stream` field (introduced by [[02-intake-stream-tagging]]) — a re-upload of the same artifact is a duplicate regardless of which stream tagged it. The downstream **consumers** differ (Step 7 validation in [[08-validation-gates]] treats "duplicate check confirmed" as a Stream-I pre-promotion gate; Stream R short-circuits to reconciliation), but detection itself does not branch on stream.

## 3. Current state

**Not implemented today.** Verified against `erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.py` (1759 lines) and its `.json` (running on Frappe **v16.18.3**, branch `version-16`). There are no `content_hash`/`perceptual_hash`/`duplicate_of` fields, no `STATUS_DUPLICATE` value, and no `detect_duplicates_for()`. The plumbing the dedupe step hooks into already exists:

- **Lifecycle constants** — `ap_invoice_capture.py:36-41`: `STATUS_PENDING_REVIEW / UNSUPPORTED / REJECTED / PROPOSED / NEEDS_CORRECTION / CONFIRMED`. The `status` Select options string is `ap_invoice_capture.json:162` (`"Pending Review\nUnsupported\nRejected\nProposed\nNeeds Correction\nConfirmed"`).
- **`validate()`** — `ap_invoice_capture.py:237` calls `_hydrate_from_linked_file` (`:406`, currently `frappe.db.get_value("File", self.source_file, ["file_name", "file_url"], as_dict=True)`) then `_require_source_reference` (`:426`). This is where `content_hash` is populated from the linked File.
- **`after_insert()`** — `ap_invoice_capture.py:281` → `self._kick_next_step()`. Entry point for auto-progression.
- **`_determine_next_step()`** — `ap_invoice_capture.py:321` is the routing table. **Step 1** (`:330-336`) returns `("run_fake_extraction_for", "auto: post-intake OCR")` only when `status == STATUS_PENDING_REVIEW AND ocr_status in (None, "Not Extracted") AND is_supported_format AND source_file`. A capture in `STATUS_DUPLICATE` fails the `:331` status guard, so OCR is **never enqueued** — that is exactly how the firewall short-circuits.
- **`_enqueue_next()`** — `:368` → worker entry `_run_cascade_step` (`:439`): on any exception sets `action_required=1` + `action_required_reason` and logs an Error Log. The SUSPECTED-duplicate "needs human" surface reuses this same `action_required + reason` pattern (also used by the Unsupported path, `:249-259`).
- **OCR billable boundary** — `run_extraction()` (`:671`, alias `run_fake_extraction` `:840`, whitelisted `run_fake_extraction_for` `:937`) reads `get_ocr_config()` at `:712`; for `provider != "fake"` (`:716`) it makes a paid API call + writes an Integration Request. **Dedupe must complete before `:712`** so a duplicate spends no OCR cost.

**Seed-vs-dedupe-hash distinction (must preserve).** `_hash_bytes(seed: str) -> bytes` at `:579` is `hashlib.sha256(seed.encode()).digest()` — it is the deterministic **fake-OCR seed**, consumed only by `_propose_for_seed` (`:583`) via `_seed_for_capture` (`:611`, joins `source_filename | source_file_url | source_file`). It is **NOT** a file-bytes dedupe hash. Do **not** reuse `_hash_bytes` for `content_hash`.

**Settings accessor pattern to mirror.** `erpnext/accounts/doctype/ap_closed_loop_settings/ap_closed_loop_settings.py:111` `get_ocr_config()` reads `frappe.db.get_singles_dict("AP Closed Loop Settings")` and coerces stored-as-text values to int/float with sane defaults (the Singles text-coercion trap is handled at `:124-147` for `confidence_threshold` and `max_file_mb`). `get_dedupe_config()` follows this exactly.

**Corrections to the brief.** The brief's file:line refs all verified except one cosmetic note: `received_at` is the field block at `ap_invoice_capture.json:139-147` (`fieldname` on `:141`), not a single "line 142". No behavioral impact. The brief is otherwise accurate about current state.

### 3.1 Relationship to native PI duplicate control

ERPNext **natively** blocks a duplicate supplier invoice number per supplier within the fiscal year via `PurchaseInvoice.validate_supplier_invoice` (`erpnext/accounts/doctype/purchase_invoice/purchase_invoice.py:1755-1784`). That check is **GATED** by `Accounts Settings.check_supplier_invoice_uniqueness`, which **DEFAULTS TO `0` (off)** — so out of the box it does nothing.

This native control is **COMPLEMENTARY** to — not a substitute for — this spec's image/byte dedupe; neither subsumes the other:

| Axis | Native PI control | This spec (Step 2) |
|---|---|---|
| What it keys on | the **extracted** `bill_no` (supplier invoice number) | file **bytes** (MD5 `content_hash`) + rasterized **pixels** (pHash) |
| When it fires | at **PI insert** (post-OCR, at promote time) | **pre-OCR**, on intake |
| Scope window | per supplier, **per fiscal year** | rolling **90-day** window (`dedupe_window_days`) |
| Default state | **off** (`check_supplier_invoice_uniqueness = 0`) | on (`dedupe_enabled = 1`) |

Because the scope differs (per-fiscal-year vs 90-day window) and the key differs (parsed invoice number vs raw bytes/pixels), a document can slip past one and be caught by the other: a re-typed/re-scanned invoice with the same number but different bytes passes the byte/pixel check yet trips the native number check; conversely a byte-identical re-upload inside the window is caught here pre-OCR before a PI ever exists.

**Recommendation:** the pilot should **ENABLE `check_supplier_invoice_uniqueness`** so the native check acts as a **second, promote-time firewall** behind this spec's pre-OCR pass. Note this dovetails with the spec's own **D2 body-text fingerprint** (which combines `proposed_supplier_invoice_no` + total + date): D2 re-derives at the capture layer essentially what the native control already keys on at the PI layer — so enabling the native flag gives a no-code backstop for the same failure mode D2 targets.

## 4. Upstream grounding

All citations verified against the local bench (Frappe v16.18.3) AND the upstream `version-15` source; the `get_content_hash` implementation is byte-identical between the two, so the v15-doc citations match what actually runs here.

| # | URL | What it confirms | Quoted signature / section |
|---|---|---|---|
| 1 | `https://github.com/frappe/frappe/blob/version-15/frappe/core/doctype/file/file.py` | The `File` DocType **already computes and stores** an exact-bytes hash in its `content_hash` field on save. `generate_content_hash()` reads the bytes and sets it; `validate_duplicate_entry()` (before_insert) filters existing Files on `{"content_hash": self.content_hash}`. ⇒ this spec **READS** `File.content_hash`, never recomputes it. | `def generate_content_hash(self):` … `with open(file_path, "rb") as f:` … `self.content_hash = get_content_hash(f.read())` |
| 2 | `https://raw.githubusercontent.com/frappe/frappe/version-15/frappe/core/doctype/file/utils.py` (verified identical on the local bench at `frappe/core/doctype/file/utils.py:186-189`) | The exact algorithm behind `File.content_hash`: **MD5**, `usedforsecurity=False`, str→bytes. This is the exact-match dedupe key. ⇒ `AP Invoice Capture.content_hash` is a **copy** of this MD5 value — do NOT recompute as SHA-256. | `def get_content_hash(content: bytes \| str) -> str:` … `return hashlib.md5(content, usedforsecurity=False).hexdigest()` |
| 3 | `https://raw.githubusercontent.com/frappe/frappe/version-15/frappe/database/schema.py` | `DocField search_index=1` → a **real DB index** is emitted during `migrate`/`sync`. **Caveat:** the index is created only when the column type is NOT `text`/`longtext`. ⇒ `content_hash` / `perceptual_hash` MUST be fieldtype **Data** (varchar(140)), not Small/Long Text, or the `search_index` is silently dropped. (The docs.frappe.io v15 docfield page does NOT document `search_index`; this source is the authority.) | `elif (not current_def["index"] and self.set_index) and column_type not in ("text", "longtext"): self.table.add_index.append(self)` |
| 4 | `https://docs.frappe.io/framework/v15/user/en/api/database` | `frappe.db.get_all(doctype, filters, …)` skips permission checks (unlike `get_list`); operator filters use list notation. ⇒ the 90-day lookback is `frappe.db.get_all("AP Invoice Capture", filters={"content_hash": h, "received_at": [">=", cutoff], "name": ["!=", self.name], "status": ["!=", STATUS_DUPLICATE]}, …)`. | Greater than: `'date': ['>', '2019-09-08']` ; Between: `'date','between',['2020-04-01','2021-03-31']` |
| 5 | `https://docs.frappe.io/framework/v15/user/en/basics/doctypes/docfield` | **Verification gap (recorded, not fabricated):** this canonical v15 docfield page enumerates `label/fieldname/fieldtype/reqd/options/default/depends_on/…` but does **NOT** document `search_index` or `unique`. The `search_index` grounding therefore rests on `frappe/database/schema.py` (citation #3), not this page. | (Properties "Search Index" / "Unique" are not documented on this page.) |

Supporting framework surfaces used by the design, grounded by the same sources: `frappe.enqueue` cascade semantics (the existing `_enqueue_next`, `ap_invoice_capture.py:368-404`, uses `enqueue_after_commit=True`, `deduplicate=True`, per-step `job_id`) and `frappe.db.get_singles_dict` for the Settings accessor (already in use at `ap_closed_loop_settings.py:99, 120`).

## 5. Design

### 5.1 Data model

**New fields on `AP Invoice Capture`** (`erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.json` + the `# begin: auto-generated types` block at `ap_invoice_capture.py:144-235`). Place them in a new `dedupe_section` Section Break after `context_section` and **before** `ocr_section` (dedupe precedes OCR conceptually and in the form flow).

| fieldname | fieldtype | options / default | purpose |
|---|---|---|---|
| `dedupe_section` | Section Break | label "Deduplication", `hidden: 1` | groups dedupe audit fields (hidden like `lifecycle_section`) |
| `content_hash` | Data | `read_only: 1`, **`search_index: 1`**, **no `unique`** | MD5 exact-bytes hash, **copied** from `File.content_hash` (citation #2). NOT recomputed. Must be Data per citation #3. |
| `perceptual_hash` | Data | `read_only: 1`, **`search_index: 1`** | pHash hex of the rasterized first page (`imagehash.phash` default → 64-bit → 16 hex chars; Data(140) is ample). Computed lazily in `detect_duplicates_for`, not `validate`. |
| `duplicate_of` | Link | `options: "AP Invoice Capture"`, `read_only: 1` | the **oldest** original capture this one duplicates (set on an exact hit; on a *confirmed* perceptual hit only — never auto-set for a mere suspect). Self-referential Link (allowed in Frappe). |
| `duplicate_detected_at` | Datetime | `read_only: 1` | audit timestamp the dedupe verdict was recorded (optional; recommended over a separate status-reason field — see decision D3). |

**Reuse, do NOT add new fields for:** the SUSPECTED-duplicate human-readable reason reuses the existing `action_required` (Check, `ap_invoice_capture.json:177-185`) + `action_required_reason` (Data, `:186-192`) pair, matching the Unsupported/OCR-fail convention (`ap_invoice_capture.py:249-259, 764-767`). No new reason field is introduced.

**Critical fieldtype constraints** (both are hard requirements):
- `content_hash` / `perceptual_hash` **MUST be `Data`** (varchar 140), never Small Text / Long Text — per citation #3 the `search_index` DB index is silently dropped for `text`/`longtext` columns.
- `content_hash` **MUST NOT be `unique`** — a legitimate duplicate is a **second row with the same hash**; a unique constraint would raise at `insert` instead of letting the workflow flag and surface it. `search_index` only.

**New lifecycle value:**

| constant | value | semantics |
|---|---|---|
| `STATUS_DUPLICATE` | `"Duplicate"` | Terminal short-circuit state (like `STATUS_UNSUPPORTED`). Append `\nDuplicate` to `status` options at `ap_invoice_capture.json:162`. **No new branch in `_determine_next_step` is needed** — the `:331` guard already excludes any status `!= "Pending Review"`, so adding the value is sufficient to keep OCR from firing. Add `"Duplicate"` to the `DF.Literal[...]` status union in the auto-generated types block (`ap_invoice_capture.py:182-189`). |
| `STATUS_DUPLICATE_SUSPECT` | `"Duplicate Suspect"` *(only if decision D1 resolves to option (a))* | See **D1**. Recommended default is **(b)** — let suspects proceed to OCR — in which case this constant is **NOT** added and the suspect stays `Pending Review` with `action_required=1`. |

**New Settings fields** on `AP Closed Loop Settings` (`erpnext/accounts/doctype/ap_closed_loop_settings/ap_closed_loop_settings.json` + `.py` types block), in a new `dedupe_section`, mirroring the OCR config block:

| fieldname | fieldtype | default | purpose |
|---|---|---|---|
| `dedupe_section` | Section Break | label "Deduplication" | groups dedupe config |
| `dedupe_enabled` | Check | `1` | kill switch; lets the pilot run without poppler installed (perceptual degrades; exact still runs unless disabled) |
| `dedupe_window_days` | Int | `90` | the plan's 90-day lookback (`workflow-v2-plan.md:29`) |
| `dedupe_phash_max_distance` | Int | `6` | Hamming threshold for a SUSPECTED near-duplicate |

**Permissions:** unchanged from the DocType's existing grants (`ap_invoice_capture.json:640-664`): `Accounts Manager` (full) and `Accounts User` (no delete). All new fields are `read_only`, so role write-grants don't expand. No new role is introduced by this spec. (New v2 roles `AP Clerk` / `Auditor (Read Only)` are owned by [[11-approval-sod-workflow]] and [[14-closure-audit-retention]] respectively; this spec does not gate on them.)

**Naming series:** unchanged — `AP Invoice Capture` keeps `APIC-{YYYY}-{#####}` (`ap_invoice_capture.json:3`). No new naming series.

### 5.2 Endpoints

All new module-level functions live in `erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.py`, matching the existing `run_*` / `validate_*` module-function style (NOT methods on the Document class) so they are unit-testable without a full save.

```python
def detect_duplicates_for(
    capture: "APInvoiceCapture | str",
    save: bool = True,
) -> dict:
    """Run exact + perceptual dedupe against the last `dedupe_window_days`.
    Resolves `capture` (str -> get_doc). Returns a result dict, never raises
    out for a benign 'no duplicate' or 'poppler missing' case.
    Result: {"status": "skipped"|"clean"|"duplicate"|"suspected",
             "kind": "exact"|"perceptual"|None,
             "original": <capture name>|None}.
    """
```

```python
@frappe.whitelist()
def run_dedupe_for(capture: str) -> str:
    """Whitelisted cascade wrapper. Calls detect_duplicates_for(capture)
    then doc._kick_next_step() — same shape as run_fake_extraction_for
    (ap_invoice_capture.py:937). Returns the capture name."""
```

Internal helper (not whitelisted):

```python
def _compute_phash(capture: "APInvoiceCapture") -> str | None:
    """pHash hex of the rasterized first page, or None on ANY failure
    (poppler missing, unreadable file, unsupported type). Never raises."""
```

New accessor in `erpnext/accounts/doctype/ap_closed_loop_settings/ap_closed_loop_settings.py`, mirroring `get_ocr_config` (`:111`):

```python
def get_dedupe_config() -> dict:
    """Return {"enabled": bool, "window_days": int, "phash_max_distance": int}.
    Reads frappe.db.get_singles_dict('AP Closed Loop Settings'); coerces the
    text-stored Int values with the SAME blank/non-positive -> default trap
    used for confidence_threshold/max_file_mb (ap_closed_loop_settings.py:124-147)."""
```

**Normalization conventions** (consistent with the existing controller): `capture` accepts either a `name` string or an `APInvoiceCapture` doc and resolves with `frappe.get_doc` (mirrors `run_extraction`, `ap_invoice_capture.py:701-702`). `get_dedupe_config` coerces Singles-stored text: a stored `"0"` / `""` `window_days` falls back to `90`, mirroring the `confidence_threshold`/`max_file_mb` coercion at `ap_closed_loop_settings.py:124-147`. The whitelisted wrapper takes only the `capture` name string (no dict args), so no JSON-string normalization is needed here.

### 5.3 Logic

**`get_dedupe_config()`** — reads `get_singles_dict`, returns `{"enabled": bool(stored.get("dedupe_enabled", 1)), "window_days": <coerced, default 90>, "phash_max_distance": <coerced, default 6>}`. Coercion: `int(raw) if raw not in (None, "") else default`, then `if value <= 0: value = default`.

**`content_hash` population (in `validate()`):** Extend `_hydrate_from_linked_file` (`ap_invoice_capture.py:406`) to fetch `content_hash` alongside `file_name`/`file_url` in the existing `frappe.db.get_value("File", self.source_file, [...], as_dict=True)` call (add `"content_hash"` to the field list), and set `self.content_hash = file_row.content_hash` when present and currently blank. **Timing guard:** `File.content_hash` is set during `File.save_file`/`generate_content_hash` (before_insert on the File). If the capture is created in the same request before the File's hash is flushed, `content_hash` may be blank at `validate` time — that is acceptable; `detect_duplicates_for` re-reads it from the File at dedupe time (the cascade hop runs after commit). The spec MUST NOT assume `validate()` always sees a populated hash.

**`detect_duplicates_for(capture, save=True)`** — numbered logic:

1. Resolve `capture` (if `str` → `frappe.get_doc("AP Invoice Capture", capture)`).
2. `cfg = get_dedupe_config()`. If not `cfg["enabled"]` → return `{"status": "skipped"}` (kill switch; no mutation).
3. `cutoff = add_to_date(now_datetime(), days=-cfg["window_days"])` using `frappe.utils.add_to_date` (window on `received_at`; `now_datetime`/`today` already imported at `ap_invoice_capture.py:32`).
4. **EXACT pass.** `h = capture.content_hash or frappe.db.get_value("File", capture.source_file, "content_hash")` (re-read from File if the capture field is blank — the timing guard above). If `h`:
   - `hits = frappe.db.get_all("AP Invoice Capture", filters={"content_hash": h, "received_at": [">=", cutoff], "name": ["!=", capture.name], "status": ["!=", STATUS_DUPLICATE]}, fields=["name"], order_by="received_at asc", limit=1)` (filter syntax grounded in citation #4; `order_by … asc` + `limit 1` deterministically surfaces the **oldest** original — the record to keep).
   - On hit: set `capture.status = STATUS_DUPLICATE`; `capture.duplicate_of = hits[0].name`; `capture.duplicate_detected_at = now_datetime()`; `capture.action_required = 1`; `capture.action_required_reason = _("Exact duplicate of {0}").format(hits[0].name)`. **SHORT-CIRCUIT** — skip the perceptual pass, persist (step 6), and return `{"status": "duplicate", "kind": "exact", "original": hits[0].name}`. No OCR is enqueued because `STATUS_DUPLICATE` fails the `_determine_next_step` `:331` guard.
5. **PERCEPTUAL pass** (only if no exact hit AND the source is rasterizable):
   - `capture.perceptual_hash = _compute_phash(capture)`. If `None` (poppler missing / unreadable), skip the rest of the perceptual pass — dedupe **degrades to exact-only**, never blocks intake.
   - Pull candidates: `frappe.db.get_all("AP Invoice Capture", filters={"received_at": [">=", cutoff], "name": ["!=", capture.name], "status": ["!=", STATUS_DUPLICATE], "perceptual_hash": ["is", "set"]}, fields=["name", "perceptual_hash"], order_by="received_at asc")`.
   - Compute Hamming distance in Python (`imagehash` supports `hash_a - hash_b`). Find the candidate with the **smallest** distance `<= cfg["phash_max_distance"]` (default 6). If found → **SUSPECTED** duplicate: set `capture.action_required = 1`; `capture.action_required_reason = _("Suspected near-duplicate of {0} (visual match)").format(candidate)`. **Do NOT** set `STATUS_DUPLICATE` and **do NOT** set `duplicate_of` automatically — a human confirms (mirrors the Unsupported/needs-attention pattern). Return `{"status": "suspected", "kind": "perceptual", "original": candidate}`. Per decision **D1 (recommended (b))**, the capture stays `status == "Pending Review"`, so the cascade still advances to OCR on the next hop; auto-close is gated downstream by the body-text fingerprint (see Cross-cutting / decision D2).
6. If no hit and no suspect → return `{"status": "clean", "kind": None, "original": None}`.
7. If `save`: `capture.save()` (persists `content_hash` if newly read, `perceptual_hash`, `status`/`duplicate_of`/`action_required` as set).

**`_compute_phash(capture)`** — numbered logic:

1. **Late-import** `pdf2image`, `PIL.Image`, `imagehash` inside the function (keeps the module load cycle-free and lets the app load on a host without these deps — same late-import discipline as `run_extraction`, `ap_invoice_capture.py:696`). Wrap the import in `try/except ImportError: return None`.
2. Resolve the on-disk path from the File: prefer `frappe.get_doc("File", capture.source_file).get_full_path()`; fall back to `frappe.utils.get_files_path(file_name, is_private=...)`. If neither resolves → return `None`.
3. Branch on extension (reuse `capture.file_extension`): for `pdf` → `pdf2image.convert_from_path(path, first_page=1, last_page=1, dpi=150)[0]`; for `png`/`jpg`/`jpeg` → `PIL.Image.open(path)`.
4. `return str(imagehash.phash(image))`.
5. **Any** exception (poppler binary absent, `PDFInfoNotInstalledError`, unreadable bytes) → `frappe.log_error(...)` (engineer signal only) and `return None`. **Never raise** out of `_compute_phash` — a failed pHash degrades to exact-only dedupe, it does not block intake.

**Idempotency / retry.** The exact-pass filters `name != self.name` and `status != STATUS_DUPLICATE` so a capture cannot match itself or an already-flagged dupe; `order_by received_at asc, limit 1` deterministically returns the **oldest** original (so a third upload points `duplicate_of` at the original, not the middle dupe). Re-running `detect_duplicates_for` on an already-`Duplicate` capture is a no-op for the *verdict* (it would re-confirm the same `duplicate_of`); the cascade guard (5.4) prevents re-running it once a hash/verdict exists. Idempotency keys per [[01-foundations-settings-async-idempotency]] are NOT required here because dedupe creates no posting document (no Supplier/PI/PE/JE) — it only mutates the capture in place; the cascade's own `deduplicate=True` + per-step `job_id` (`ap_invoice_capture.py:400`) coalesces repeat triggers.

**What gets persisted:** `content_hash` (MD5, copied from File), `perceptual_hash` (hex or None), `duplicate_of` (on exact hit / confirmed perceptual only), `status = STATUS_DUPLICATE` (exact hit only), `duplicate_detected_at`, `action_required` + `action_required_reason`. No external write, no posting document.

### 5.4 Cascade & stream-awareness

**Placement = before OCR.** Add a **Step 0** to `_determine_next_step` (`ap_invoice_capture.py:321`), *before* the existing Step-1 OCR branch at `:330`:

```
Step 0 (pre-extraction dedupe):
  if status == STATUS_PENDING_REVIEW
     and is_supported_format and source_file
     and not _dedupe_checked(self):       # idempotency guard
        return ("run_dedupe_for", "auto: pre-extraction dedupe")
```

`_dedupe_checked(self)` returns `True` when the capture has already been through dedupe — inferred from `content_hash`/`perceptual_hash` being set OR `status == STATUS_DUPLICATE` OR `duplicate_detected_at` being set (whichever the build chooses; recommend `duplicate_detected_at is not None` as the single unambiguous flag, since exact-clean captures may legitimately have a `content_hash` but no perceptual run). This keeps Step 0 from looping: after dedupe runs, the guard is satisfied and the next `_kick_next_step` hop falls through to Step 1 (OCR) — unless dedupe set `STATUS_DUPLICATE`, in which case the `:331` status guard stops the cascade entirely (terminal).

`run_dedupe_for` (the whitelisted wrapper) calls `detect_duplicates_for(capture)` then `doc._kick_next_step()` (same shape as `run_fake_extraction_for`, `:937`). Routing dedupe through the cascade rail (`_enqueue_next` → `_run_cascade_step`, `:368/439`) gives it the error surface for free: a pHash crash that somehow escapes `_compute_phash` (it shouldn't) still lands as `action_required + reason` instead of a silent stall.

**Why Step 0, not synchronous in `after_insert`** (decision D4, recommended): the alternative — calling `detect_duplicates_for` synchronously inside `after_insert` before `_kick_next_step` — runs heavy rasterization in the request thread and blocks the user's save. Step 0 keeps dedupe on the same async rail as OCR.

**Stream R vs Stream I divergence: none in detection.** `detect_duplicates_for` does not read or filter on any `stream` field (introduced by [[02-intake-stream-tagging]]) and MUST NOT — the dedupe query keys on `content_hash` / `perceptual_hash` / `received_at` only. This makes the function safe to ship **independent of** the stream-tagging spec (it must not assume a `stream` field exists). Divergence is downstream: the `STATUS_DUPLICATE` / `duplicate_of` produced here is consumed by [[08-validation-gates]] as the Stream-I "duplicate check confirmed" pre-promotion gate (`workflow-v2-plan.md:55`); Stream R's lighter reconciliation path reads the same fields but does not block on approval.

**Pause vs auto-advance:**
- **Exact hit** → `STATUS_DUPLICATE` → cascade **stops** (terminal pause; human reviews the surfaced original). No OCR.
- **Perceptual suspect** (recommended D1=(b)) → `action_required=1` but `status` stays `Pending Review` → cascade **continues** to OCR; the suspect gets extracted, then the body-text fingerprint (D2, follow-on) gates any auto-close.
- **Clean** → cascade **advances** to Step 1 OCR exactly as today.

### 5.5 Cross-cutting

- **Permissions / SoD:** none added; all new fields `read_only`. No new role gate. SoD is owned by [[11-approval-sod-workflow]].
- **Idempotency:** see 5.3 — no [[01-foundations-settings-async-idempotency]] posting-idempotency key needed (no posting doc created); the cascade's `deduplicate=True` job dedup + the Step-0 `_dedupe_checked` guard provide retry-safety.
- **Async / enqueue:** dedupe runs as a cascade hop via the existing `frappe.enqueue` machinery (`enqueue_after_commit=True`, `now=in_test`; `ap_invoice_capture.py:368-404`). The perceptual pass (rasterization) is the heaviest step in the AP cascade — keeping it on the `short` queue worker (not the request thread) is the reason for the Step-0 design.
- **Observability ([[10-ap-review-observability]]):** when a perceptual **suspect** is later confirmed-or-dismissed by a clerk, or an exact `STATUS_DUPLICATE` is reviewed, emit an `AP Review Event` with root-cause vocabulary. The relevant root-cause tag for an over-flagged recurring-template suspect is best expressed via the dedupe surface; this spec does **not** define the event schema (that is [[10-ap-review-observability]]) but names the emission point: the human action on a `STATUS_DUPLICATE` / suspect capture.
- **Follow-on guard (body-text fingerprint):** the perceptual-suspect false-positive mitigation (D2) depends on OCR output (`proposed_supplier_invoice_no` + `proposed_total_amount` + `proposed_invoice_date`, `ap_invoice_capture.py:251-281` proposed fields) produced by [[04-extraction-confidence-line-items]] — it is a **follow-on spec**, named here so the suspect path is explicitly NOT wired to auto-close.

## 6. Acceptance criteria

- **AC-03-1 (positive, exact):** Given two captures with the same `content_hash` and the second's `received_at` within `dedupe_window_days`, after dedupe the second has `status == "Duplicate"`, `duplicate_of == <first.name>`, `action_required == 1`, and `action_required_reason` contains "Exact duplicate". OCR did **not** run: `ocr_status` stays "Not Extracted" and no Integration Request row exists for the second capture.
- **AC-03-2 (negative, window):** Same `content_hash` but the first capture's `received_at` is older than `dedupe_window_days` → the second is **not** flagged; `status` stays "Pending Review"; OCR proceeds.
- **AC-03-3 (negative, distinct):** Different `content_hash` and pHash distance > threshold → no exact hit, no suspect; `status` stays "Pending Review"; cascade advances to OCR.
- **AC-03-4 (edge, self):** With only one capture, the `name != self.name` filter means it never flags itself; `status` stays "Pending Review".
- **AC-03-5 (edge, already-flagged chain):** A third upload of the same bytes, with the middle capture already `status == "Duplicate"`, has its `duplicate_of` set to the **oldest** original (excluded by `status != "Duplicate"`, ordered `received_at asc`), not the middle dupe.
- **AC-03-6 (positive, perceptual):** Two captures with pHashes at Hamming distance `<= dedupe_phash_max_distance` → the second has `action_required == 1` with a "suspected near-duplicate" reason, `status` is **NOT** "Duplicate", and `duplicate_of` is **NOT** set.
- **AC-03-7 (negative, perceptual):** pHash distance `> dedupe_phash_max_distance` (e.g. 10) → no flag.
- **AC-03-8 (edge, poppler missing / unreadable):** `_compute_phash` raises internally → `detect_duplicates_for` swallows it, `perceptual_hash` stays `None`, exact-only dedupe still runs, and intake is **not** blocked (no exception escapes).
- **AC-03-9 (kill switch):** `get_dedupe_config()["enabled"]` is `False` → `detect_duplicates_for` returns `{"status": "skipped"}` with no field mutation.
- **AC-03-10 (edge, window boundary):** `received_at` exactly at `cutoff` (`>=` comparison) is a hit; one second older is a miss.
- **AC-03-11 (config defaults):** With `AP Closed Loop Settings` unset, `get_dedupe_config()` returns `{"enabled": True, "window_days": 90, "phash_max_distance": 6}`. A stored `"0"` / `""` `window_days` coerces back to `90`; an explicit `"30"` yields `30`.
- **AC-03-12 (cascade integration, with `frappe.flags.ap_auto_progress_enabled = True`):** Inserting a duplicate file drives intake → dedupe → `STATUS_DUPLICATE` and **stops**; `run_extraction` is never reached (no OCR cost). Inserting a unique file: intake → dedupe (clean) → OCR proceeds to `Proposed` as today.
- **AC-03-13 (fieldtype guard):** After `bench migrate`, `content_hash` and `perceptual_hash` exist as `varchar(140)` columns with a DB index, and `content_hash` has **no** unique constraint (verified via `DESCRIBE`/`SHOW INDEX`).

## 7. Tests

### 7.1 Automated

Conventions confirmed from the existing suites: `from frappe.tests import IntegrationTestCase`; **never** `frappe.db.commit()` (rollback happens in `tearDown`); cascade is opt-in via `frappe.flags.ap_auto_progress_enabled` and hard-disabled with `frappe.flags.skip_ap_auto_progress` (`ap_invoice_capture.py:300-313`); mock the late-imported `get_dedupe_config` the same way the OCR-config tests patch `get_ocr_config` (patch path `erpnext.accounts.doctype.ap_closed_loop_settings.ap_closed_loop_settings.get_dedupe_config`). **Monkeypatch `_compute_phash` in ALL perceptual tests** so the fuzzy-distance logic is under test, not the rasterizer/poppler.

- **Module:** `erpnext/accounts/doctype/ap_invoice_capture/test_ap_invoice_capture.py` — new class `TestAPInvoiceCaptureDedup(IntegrationTestCase)`.
  - `detect_duplicates_for` — **positive exact** (AC-03-1: status Duplicate + duplicate_of + action_required, assert OCR did not run); **negative window** (AC-03-2); **negative distinct** (AC-03-3, falls through to perceptual); **edge self** (AC-03-4); **edge already-flagged chain** → oldest surfaced (AC-03-5); **positive perceptual** via monkeypatched `_compute_phash` returning two near hashes (AC-03-6, assert NOT Duplicate, duplicate_of unset); **negative perceptual** distance 10 (AC-03-7); **edge poppler-missing** via `_compute_phash` raising → swallowed, exact-only still works (AC-03-8); **kill switch** (AC-03-9); **window boundary** at exact cutoff (AC-03-10).
  - **Cascade integration** with `frappe.flags.ap_auto_progress_enabled = True`: duplicate-file insert → `STATUS_DUPLICATE`, assert `run_extraction` never reached (patch/spy on `run_extraction`); unique-file insert → reaches `Proposed` (AC-03-12).
  - **ONE skip-if-not-installed test** exercising the **real** `_compute_phash` against a tiny fixture PDF/PNG to prove dep wiring — `@unittest.skipUnless(<import succeeded>, "imagehash/pdf2image not installed")`. This is the only test that touches poppler.
- **Module:** `erpnext/accounts/doctype/ap_closed_loop_settings/test_ap_closed_loop_settings.py` — extend with `get_dedupe_config` cases (mirror the existing `TestGetOcrConfig`): defaults when unset (enabled True / 90 / 6); Singles text-coercion (`"0"`/`""` window → 90; explicit `"30"` → 30) (AC-03-11).

Coverage bar per CLAUDE.md: `detect_duplicates_for` and `get_dedupe_config` each get positive + negative + edge; `_compute_phash` gets the swallow-on-failure edge (mocked) + the one real-dep wiring test.

### 7.2 Clean-room test plan

**`test/testplans/specs/03-deduplication.md`** — scope: an external zero-context Claude on a fresh bench installs the perceptual deps (`pip install imagehash pdf2image` — **Pillow is already present via Frappe, do NOT pip-install it as if missing**) **plus** the `poppler-utils` system binary — `apt-get install poppler-utils`, verified with `pdftoppm -v`; the poppler binary is flagged as the **#1 install/system-dep risk** for the pilot/UAT box (`which pdftoppm` returns nothing on a stock dev bench), uploads the same PDF twice (→ lands in **Duplicate** with `duplicate_of` surfaced and no OCR Integration Request), uploads a re-saved/re-scanned near-identical variant (→ `action_required` "suspected near-duplicate" banner, status **NOT** Duplicate), uploads a clearly different invoice (→ normal flow), and lowers `dedupe_window_days` so an old original no longer matches. DB-is-truth verification via `bench --site … mariadb` on `status` / `duplicate_of` / `content_hash` / `perceptual_hash`; provide SHA-256s for the fixtures; cleanup of all captures + Files created through the UI. **Known risk to flag in the plan:** pHash false positives on identical-template recurring invoices (monthly Amazon/utility) — only an exact `content_hash` match auto-closes pre-OCR; perceptual hits are suspects gated by the follow-on body-text fingerprint (D2).

### 7.3 UI testing (Playwright MCP)
Browser-driven verification of the desk UI this slice adds, executed by driving a real browser through the **Playwright MCP** server. These are the UI steps of the §7.2 clean-room runbook.
- **Prereq:** Playwright MCP set up per `test/testplans/BROWSER-TESTING-SETUP.md` (`claude mcp list` must list `playwright`; restart Claude Code after registering). `.mcp.json` and `.playwright-mcp/` stay gitignored.
- **Evidence:** save screenshots to `test/testplans/screenshots/03-deduplication/<name>.png` (committed) — always pass that path as the screenshot `filename`.
- **Source of truth stays the DB:** screenshots are UI evidence, but after every UI action that writes data, verify the actual write via `bench --site <site> mariadb` / `bench … execute` (consistent with §7.2), then delete data created through the UI.

**Scenarios** (each `route → action → expected UI → DB assertion`):
- `/app/ap-invoice-capture/new` (or the list-view **Upload** action) → upload a supported file, then upload the **same bytes** again → the second capture surfaces the duplicate state (`status == "Duplicate"`, `action_required_reason` naming the original "Exact duplicate of …", and the `duplicate_of` link visible on the form) and **no** re-extraction runs; screenshot the duplicate warning → DB-assert `duplicate_of` is set and `status == "Duplicate"` (and no Integration Request row exists for the second capture).
- Upload a **near-duplicate** (the same invoice re-rendered / re-scanned to different bytes) → a "suspected near-duplicate" `action_required` flag is shown and the capture is **NOT** auto-closed; screenshot → DB-assert `action_required == 1` and `status != "Duplicate"` (`duplicate_of` left unset).

**Not browser-testable in this slice** (covered by §7.1): the 90-day lookback query (`detect_duplicates_for` window filtering) and the pHash compute (`_compute_phash` rasterization) are pure server-side logic verified by the §7.1 automated suites. Note the **poppler** dependency — if `pdftoppm` is absent, the perceptual path degrades to exact-only, so the near-duplicate scenario only fires when poppler is installed on the bench/worker host.

## 8. Open decisions

- **D1 — Suspect-path / OCR interaction.** The plan says a perceptual SUSPECT "does not auto-close (human confirms)" but is silent on whether it still gets OCR'd. **Options:** (a) add a non-advancing `STATUS_DUPLICATE_SUSPECT` that fails the `_determine_next_step` `:331` guard, so the suspect skips OCR and is fully manual; (b) leave the suspect at `status == "Pending Review"` so it still gets OCR'd, then gate any auto-close on the body-text fingerprint (D2). **Recommended default: (b)** — it preserves extraction for the suspect (the clerk needs the extracted fields to confirm/dismiss) and resolves the recurring-template false-positive risk in one mechanism. **Owner:** pilot lead (Russ). **Must lock:** before the dedupe build starts (it determines whether `STATUS_DUPLICATE_SUSPECT` is added).
- **D2 — Body-text fingerprint as the auto-close gate (follow-on guard).** To avoid over-flagging identical-template recurring invoices, no perceptual suspect ever auto-closes pre-OCR; after OCR, combine pHash with a body-text fingerprint (`proposed_supplier_invoice_no` + `proposed_total_amount` + `proposed_invoice_date`) before any AUTO action. **Options:** spec it as a follow-on (depends on [[04-extraction-confidence-line-items]]) vs fold a minimal version into this spec. **Recommended default:** follow-on spec, named here so the suspect path is explicitly not wired to auto-close. **Owner:** pilot lead. **Must lock:** when [[04-extraction-confidence-line-items]] lands (the proposed fields it needs).
- **D3 — Audit-field shape for the verdict.** Reuse `action_required_reason` for the human reason (no new reason field) and add only `duplicate_detected_at` as the audit timestamp, vs add a dedicated `dedupe_reason` / `duplicate_check_status` field. **Recommended default:** reuse `action_required_reason` + add `duplicate_detected_at` (matches the Unsupported/OCR-fail convention; avoids field sprawl). **Owner:** spec author. **Must lock:** at DocType-JSON authoring time.
- **D4 — Cascade seam (Step 0 vs synchronous `after_insert`).** **Options:** (A) Step 0 in `_determine_next_step` → dedupe runs as an async cascade hop (gets the `_run_cascade_step` error surface; rasterization off the request thread); (B) call `detect_duplicates_for` synchronously in `after_insert` before `_kick_next_step` (simpler, but blocks the save on rasterization). **Recommended default: (A) Step 0.** **Owner:** spec author. **Must lock:** at build start.
- **D5 — `_dedupe_checked` idempotency signal.** Which field proves "already deduped" for the Step-0 guard: `duplicate_detected_at is not None` (set on every dedupe run, including clean), vs inferring from `content_hash`/`perceptual_hash` being set, vs `status == "Duplicate"`. **Recommended default:** `duplicate_detected_at is not None` (set it on every `detect_duplicates_for` run, clean or not), so the Step-0 guard is a single unambiguous check. **Owner:** spec author. **Must lock:** at build start (drives whether `detect_duplicates_for` always stamps `duplicate_detected_at`).
- **D6 — pHash distance default.** `dedupe_phash_max_distance` default `6` (imagehash 64-bit pHash). **Options:** keep 6, or tune per the real invoice corpus during pilot. **Recommended default:** ship at 6, expose as a Settings Int so the pilot can tune without a code change. **Owner:** pilot lead, tuned against pilot data. **Must lock:** value can change post-pilot; the field+default lock at build.
- **D7 — Rasterization DPI / first-page-only.** `_compute_phash` rasterizes only the first page at `dpi=150`. **Options:** first-page-only (cheap, robust for header-bearing invoices) vs multi-page hashing. **Recommended default:** first-page-only at 150 DPI (the firewall targets re-scans of the same document; first page is sufficient and bounds cost). **Owner:** spec author. **Must lock:** at build (affects `_compute_phash`).

## 9. Dependencies & sequencing

**Must land first:**
- [[01-foundations-settings-async-idempotency]] — extends `AP Closed Loop Settings` and establishes the async-runner conventions this spec's `get_dedupe_config` and cascade hop reuse. (Soft dependency: the Settings DocType already exists; this spec adds three fields + one accessor in the same pattern. Dedupe does **not** need the [[01-foundations-settings-async-idempotency]] posting-idempotency ledger.)
- [[02-intake-stream-tagging]] — listed as a dependency for **sequencing only** (intake adapters land the artifacts dedupe checks). **Detection is decoupled:** `detect_duplicates_for` must NOT read a `stream` field and ships even if stream-tagging is delayed.
- Frappe `File.content_hash` (MD5, computed by core on save) — runtime dependency, not a build-order one (already present).

**Net-new system/package dependencies (call out as pilot risk):**

- **`imagehash`, `pdf2image`** — the ONLY net-new **Python** pip deps; add them to `erpnext/pyproject.toml`.
- **`Pillow` — NOT new; do NOT list it as a new dependency.** Pillow is **already a Frappe dependency** (`apps/frappe/pyproject.toml:18`, `Pillow~=12.2.0`) and is therefore already installed in every bench venv. `imagehash` imports it transitively too. Do not add `Pillow` to `erpnext/pyproject.toml` and do not list it in the test-plan `pip install` line as if it were missing.
- **`poppler-utils` system binary (`pdftoppm`/`pdfinfo`) — the #1 install risk.** This is a NEW **system** dependency and is **NOT currently installed on the dev bench** (`which pdftoppm` returns nothing). `pdf2image` shells out to poppler — pip alone is insufficient; the binary must be on **every** bench/worker host (`apt-get install poppler-utils` on Debian/Ubuntu/WSL). Rank it the **single biggest deployment risk** for this spec. It is **non-blocking**, however: the perceptual pass degrades to exact-hash-only (`_compute_phash` → `None`) when poppler is absent (AC-03-8), so intake never stalls — the graceful degradation is what keeps the missing binary from being a hard blocker.

**This unblocks:**
- [[08-validation-gates]] — consumes `STATUS_DUPLICATE` / `duplicate_of` as the Step-7 "duplicate check confirmed" pre-promotion gate (`workflow-v2-plan.md:55`).
- The **body-text-fingerprint anti-false-positive guard** (D2) — a follow-on that depends on this spec **plus** the OCR proposed fields from [[04-extraction-confidence-line-items]].

**Estimated size: M** (per IMPLEMENTATION-PLAN units). Three JSON fields + one lifecycle value + one Settings accessor + two module functions + one helper + one cascade Step-0 branch + the two test modules and the clean-room plan. The perceptual dep wiring + graceful-degradation paths and the suspect/OCR decision (D1) push it above S, but there is no new DocType and no posting logic.
