---
spec: 02-intake-stream-tagging
title: Intake & Stream Tagging (Receipt vs Invoice)
plan_step: "Step 1 — Receipt/Invoice Intake with provisional stream tag (the 'two streams from intake' fork)"
stream: both
status: Done
depends_on: [01-foundations-settings-async-idempotency]
related: [00-overview, 03-deduplication, 04-extraction-confidence-line-items, 07-classification-doctype-branching, 10-ap-review-observability, 13-bank-feed-reconciliation]
---

# 02 — Intake & Stream Tagging (Receipt vs Invoice)
> _Revised 2026-05-31: applied native-vs-custom review findings; added Playwright UI test plan (§7.3)._

## 1. Summary

This spec **owns the stream concept**: it tags every `AP Invoice Capture` at intake with a provisional **Stream R (Receipt, already-paid)** or **Stream I (Invoice, unpaid payable)** label using the cheapest available signals (attachment filename, sender domain, intake channel/label, card-receipt body patterns), starts the **72-hour SimpleFIN match clock** on Stream R, and adds the missing **intake adapters** beyond manual upload (email-in, mobile, and a Phase-3 portal-pull base). It implements **plan Step 1** ("Receipt / Invoice Intake (with stream tag)"). Current-state delta: today there is exactly one intake channel (`Manual ERPNext Upload`) and **no `stream` field, no classifier, no `sla_due_at`, no email/mobile/portal adapter** — captures land undifferentiated and immediately cascade to OCR.

## 2. Plan alignment

**Plan Step 1 (verbatim, `docs/planning/workflow-v2-plan.md:23-26`):**

> **1. Receipt / Invoice Intake (with stream tag)** — The process begins when an invoice or receipt arrives — emailed PDF, scanned paper document, phone-camera photo, or vendor portal pull. The document is logged into ERPNext immediately and attached to a new AP record so the artifact is timestamped and retrievable from the moment it enters the organization. … At intake the document is tagged with a **provisional stream** — Stream R (Receipt, already-paid) or Stream I (Invoice, unpaid payable) — using the cheapest signals available: sender domain heuristics, attachment filename (`receipt_*.pdf` vs `invoice_*.pdf`), folder/label routing from the email channel, and the presence of card-receipt patterns in the body (e.g., "PAID", last-4 digits, authorization codes). The provisional tag drives queue priority and the downstream SLA clock: Stream R items start a **72-hour SimpleFIN match countdown** immediately. Step 6 can revise the stream tag if extraction reveals the heuristic was wrong; the revision is logged for tuning.

**Two-streams framing (`workflow-v2-plan.md:9-17`):** "The workflow forks at step 1, not step 6 … the two streams have different SLAs, different control sets, and different downstream doctypes." This spec is the **fork point**.

**Control-Summary rows this spec implements (`workflow-v2-plan.md:124, 148`):**

| Control | Where | Why it matters |
|---|---|---|
| Stream tag at intake (Receipt vs Invoice) | Step 1 | Routes the two flows correctly from t=0; drives the 72h SimpleFIN SLA on Stream R |

**Stream R vs Stream I divergence in THIS spec:**

- **Both streams** get a `stream` value and a `stream_provisional_source` at intake; tagging logic is identical (one classifier, one rule table).
- **Stream R only:** `sla_due_at = received_at + 72h` is computed and persisted. This is the only field whose *value* depends on the stream. Stream I and Unclassified leave `sla_due_at` NULL (their SLA is approval/payment-driven, owned by [[11-approval-sod-workflow]] / [[12-payment-execution]], not the SimpleFIN clock).
- **Downstream (out of scope here, but the tag is what gates it):** Stream R skips approval ([[11-approval-sod-workflow]]) and payment execution ([[12-payment-execution]]); Stream I carries the full approval+payment+observability load. This spec only *sets* the tag those specs read.

## 3. Current state

What is shipped today (the substrate this spec extends — corrections to the brief noted inline):

- **One intake channel.** `INTAKE_MANUAL_UPLOAD = "Manual ERPNext Upload"` (`ap_invoice_capture.py:93`) is the only value. The JSON field `intake_channel` is a **Select** with `options: "Manual ERPNext Upload"`, `reqd: 1`, `in_list_view: 1`, default `"Manual ERPNext Upload"` (`ap_invoice_capture.json:110-119`), mirrored in the auto-generated types as `intake_channel: DF.Literal["Manual ERPNext Upload"]` (`ap_invoice_capture.py:161`).
- **`received_at` (the SLA anchor) is set in two places:** `validate()` falls back to `now_datetime()` if unset (`ap_invoice_capture.py:237-239`); the factory `create_capture_from_file(...)` accepts an explicit `received_at` and falls back to `now_datetime()` (`ap_invoice_capture.py:554`). The JSON field has `default: "now"` (`ap_invoice_capture.json:139-147`). **This dual-set is exactly what spec 13's SLA needs** — the email adapter can pass the real receipt time.
- **Deterministic core factory** `create_capture_from_file(file_doc=None, file_name=None, file_url=None, source_context=None, intake_channel=INTAKE_MANUAL_UPLOAD, received_at=None)` (`ap_invoice_capture.py:521-560`) **already parametrizes `intake_channel` and `received_at`**, so new adapters just call it with a different channel + the real receipt time. It resolves a File-doc-or-name, derives filename/url, and inserts.
- **Whitelisted manual/mobile entry point** `create_capture_from_uploaded_file(file_name, source_context=None)` (`ap_invoice_capture.py:563-571`) — a thin wrapper over the factory returning `.name`. **It does NOT yet accept an `intake_channel` arg** (the brief says "add one"). This is the function mobile glue reuses.
- **`validate()` flow** (`ap_invoice_capture.py:237-279`) already: stamps `received_at`, runs `_hydrate_from_linked_file()` (pulls `file_name`/`file_url` off the linked File via `frappe.db.get_value`, `:406-424`), runs `_require_source_reference()` (raises `AmbiguousSourceError` if no source ref, `:426-436`), normalizes extension, and sets `is_supported_format`. **Stream tagging slots into this method** after the source is hydrated.
- **`after_insert()` -> `_kick_next_step()`** (`ap_invoice_capture.py:281-290`) cascades intake -> OCR via `_determine_next_step()` (`:321-366`). The stream tag must be set **in `validate()`** (before insert) so it persists with the record and is visible to the cascade and to queue-priority consumers.
- **Settings home exists:** `AP Closed Loop Settings` (Single, `issingle:1`) with an established read pattern — `frappe.db.get_singles_dict("AP Closed Loop Settings")` plus typed accessors `get_promote_defaults()` / `get_ocr_config()` (`ap_closed_loop_settings.py:85-148`). This is where the stream rule table lands; we add a `get_stream_rules()` accessor mirroring `get_ocr_config()`. Permissions: System Manager + Accounts Manager read/write, Accounts User read.
- **Registry/ABC precedent for portal-pull:** `extractors/base.py` (`OCRProvider(ABC)` + `@dataclass ExtractionResult`, `:41-89`) and `extractors/registry.py` (`_PROVIDERS` dict + `get_extractor(name)` raising `ValueError` on unknown key, `:21-42`). `portal_pull.py` mirrors this shape exactly.

**Correction to the brief:** the brief says "hooks.py already registers `Communication.after_insert`" and to "ADD the new handler there." Confirmed — but note it is **already a list** (`erpnext/hooks.py:375-378` has `"after_insert": [ ... two erpnext.crm handlers ... ]`), so wiring is a one-line append to that list, **not** a list conversion. No risk of clobbering an existing scalar.

**Gap, precisely:** there is **no** `stream`, `stream_provisional_source`, `stream_revised_from`, or `sla_due_at` field; **no** `classify_stream_at_intake`; **no** `create_capture_from_email`; **no** `portal_pull.py`; the `intake_channel` Literal/Select has only one option; and `create_capture_from_uploaded_file` has no `intake_channel` param.

## 4. Upstream grounding

All framework surfaces this spec touches, with verified upstream citations from the research brief.

| # | URL | Confirms | Quoted signature/section |
|---|---|---|---|
| 1 | `https://docs.frappe.io/framework/v15/user/en/basics/doctypes/controllers` | The v15 controller lifecycle hooks this spec uses: compute the derived `stream`/`sla_due_at` inside `validate()` so they persist, and use `after_insert()` only for the cascade kick. Also notes typed annotations were introduced in v15 (the `DF.Literal` block). | `validate()`: "Use this method to throw any validation errors and prevent the document from saving." … `after_insert()`: "This is called after the document is inserted into the database." |
| 2 | `https://github.com/frappe/frappe/blob/version-15/frappe/email/doctype/email_account/email_account.py` | The email-in adapter is configured on a **dedicated inbound Email Account** whose "Append To" setting selects the reference doctype, and that **one `Communication` is produced per inbound mail**. Grounds "configured via a dedicated Email Account." | `mails.append(InboundMail(message, self, frappe.safe_decode(uid), seen_status, append_to))` … `append_to=folder.append_to` … `communication = mail.process()` |
| 2b | `https://github.com/frappe/frappe/blob/version-15/frappe/email/receive.py` (installed copy: `apps/frappe/frappe/email/receive.py:708-711`) | The native `append_to` path that §5.3.3 **considers and rejects**: `InboundMail._create_reference_document(<append_to>)` instantiates **one** record of an arbitrary reference doctype per inbound mail and links the Communication to it. This is the 1:1 mechanism that **cannot** express the spec's one-email→many-captures fan-out or per-attachment skipping — the documented reason the `Communication.after_insert` hook is used instead. | `def _create_reference_document(self, destination): """Create reference document if it does not exist in the system."""  doc = frappe.new_doc(destination)  …  doc.insert(ignore_permissions=True)` |
| 3 | `https://github.com/frappe/frappe/blob/version-15/frappe/email/receive.py` | `InboundMail.process()` ("Create communication record from email.") builds a `Communication`, sets `reference_doctype`/`reference_name`, inserts, then attaches files via `save_attachments_in_doc`, which creates **File docs with `attached_to_doctype="Communication"`, `attached_to_name=doc.name`, `is_private=1`**. This is the exact mechanism `create_capture_from_email` queries to find a Communication's attachments. | `def process(self): """Create communication record from email."""` … `data["doctype"]="Communication"; communication=frappe.get_doc(data); communication.insert(ignore_permissions=True); communication._attachments=self.save_attachments_in_doc(communication)` … File doc `{"doctype":"File","file_name":…,"attached_to_doctype":doc.doctype,"attached_to_name":doc.name,"is_private":1,"content":attachment["fcontent"]}` |
| 4 | `https://github.com/frappe/frappe/blob/version-15/frappe/core/doctype/communication/email.py` | Independently confirms the **File ↔ Communication linkage fields** (`attached_to_doctype` / `attached_to_name`) the adapter queries. Grounds the File-doctype linkage half (the original `basics/doctypes/file` candidate 404'd). | `def add_attachments(name, attachments): … file_args.update({"attached_to_doctype":"Communication","attached_to_name":name,"folder":"Home/Attachments"})` |
| 5 | `https://github.com/frappe/frappe/blob/version-15/frappe/utils/data.py` (installed copy: `apps/frappe/frappe/utils/data.py:238`) | The `sla_due_at` computation helper. `add_to_date(date, hours=72)` returns a `datetime` when an `hours` value is passed (the `as_datetime` overload). `now_datetime()` (`:371`) is the receipt-time fallback. **Verified present in the installed frappe**, not just version-15. | `def add_to_date(date, years=0, months=0, weeks=0, days=0, hours=0, minutes=0, seconds=0, as_string=…, as_datetime=…)` ; `def now_datetime() -> datetime.datetime` |
| 6 | `https://docs.frappe.io/framework/v15/user/en/api/document` | Requested candidate for `DF.Literal`/Select + validate-derived fields. **NOT verified — this exact path 404'd on fetch.** The authoritative v15 page for controller hooks / `DF.Literal` is citation #1 (`.../basics/doctypes/controllers`). Recorded here so the delta is explicit; no quote fabricated. | (unverified — see citation #1) |
| 7 | `https://docs.frappe.io/framework/v15/user/en/email` | Requested candidate for inbound Email Account / `append_to`. **NOT verified — this bare path and its children 404'd in v15.** Email-in grounding obtained from frappe source instead (citations #2, #3, #4, all verified). | (unverified — see citations #2–#4) |

**Version note (risk-carried):** the branch is `russ/migrateToV16` while the docs cited are v15. The **installed frappe** under `apps/frappe` is the source of truth — `add_to_date`/`now_datetime` are confirmed present there (citation #5). Before wiring the email handler, re-verify that v16 has not moved `Communication.after_insert` semantics or File field names; pin source citations to the **installed commit**, not `version-15`, at implementation time.

## 5. Design

### 5.1 Data model

#### 5.1.1 New fields on `AP Invoice Capture` (`ap_invoice_capture.json`)

Insert a new section break `intake_classification_section` into `field_order` immediately after `received_at` (line 17) and before `lifecycle_section`. Follow the existing **Select-as-Literal** convention (a JSON `Select` mirrored in the auto-generated `DF.Literal` block).

| fieldname | fieldtype | options / default | reqd / flags | purpose |
|---|---|---|---|---|
| `intake_classification_section` | Section Break | label "Intake Classification" | — | groups the stream fields |
| `stream` | Select | options `Receipt (R)\nInvoice (I)\nUnclassified`; default `Unclassified` | `reqd: 1`, `in_list_view: 1`, `in_standard_filter: 1` | **The stream tag this spec owns.** Persisted value is self-describing (parenthesized R/I, matching the `Fake (Deterministic)` label style). `DF.Literal["Receipt (R)", "Invoice (I)", "Unclassified"]`. |
| `stream_provisional_source` | Data | — | `read_only: 1` | Which signal fired (`filename:receipt_*`, `sender_domain`, `body:PAID+last4`, `label`, `default`). Feeds [[10-ap-review-observability]] disagreement-rate tuning. |
| `stream_revised_from` | Data | — | `read_only: 1` | Set by [[07-classification-doctype-branching]] (Step-6 revision) to the prior `stream` value when re-tagged; empty until revised. The audit trail for "the heuristic was wrong." |
| `sla_due_at` | Datetime | — | `read_only: 1`, `in_standard_filter: 1` | "72h SimpleFIN match deadline (Stream R only)." Computed in `validate()` only when `stream == "Receipt (R)"`; NULL otherwise. [[13-bank-feed-reconciliation]] reports breaches via `sla_due_at < now() AND <unmatched>`. |

**Extend existing `intake_channel`** (`ap_invoice_capture.json:110-119` + `ap_invoice_capture.py:161`): add three options so it becomes `Manual ERPNext Upload\nEmail Inbound\nMobile Upload\nVendor Portal Pull`. New sibling constants in `ap_invoice_capture.py` next to `INTAKE_MANUAL_UPLOAD` (`:93`):

```
INTAKE_MANUAL_UPLOAD = "Manual ERPNext Upload"   # unchanged
INTAKE_EMAIL_INBOUND  = "Email Inbound"
INTAKE_MOBILE_UPLOAD  = "Mobile Upload"
INTAKE_PORTAL_PULL    = "Vendor Portal Pull"
```

The `DF.Literal` becomes `DF.Literal["Manual ERPNext Upload", "Email Inbound", "Mobile Upload", "Vendor Portal Pull"]`. **Regenerate the auto-generated types block via bench** (`bench --site <site> build` / the DocType save regenerates `# begin: auto-generated types`); do **not** hand-edit only the JSON or only the `.py` — they desync (risk #3).

#### 5.1.2 New child DocType `AP Stream Rule` (data-driven tuning table)

A child table referenced by a `Table` field on `AP Closed Loop Settings`, so non-engineers tune classification with **no code change** (the explicit intent of plan-guidance #1). Recommended over a single JSON/Code field because it gives field-level validation + grid UI (see Open Decision OD-1).

> **Native prior-art: `Assignment Rule`.** Frappe ships `Assignment Rule` (`apps/frappe/frappe/automation/doctype/assignment_rule`) — a priority-ordered, condition-driven engine that is the obvious "have we reinvented this?" comparison for `AP Stream Rule`. We use a custom table anyway because of a hard capability gap: **`Assignment Rule` can only ASSIGN users (create `ToDo`s / set `_assign`) on matching documents — it cannot WRITE a derived field** like `stream` or `sla_due_at`. Stream tagging's whole job is to set a field value, which `Assignment Rule` structurally cannot do, so it can't replace the custom table. **However**, its condition language *is* strictly more expressive than our `signal`+`pattern` rows: `Assignment Rule.assign_condition` is a **safe-eval `Code` expression** over the doc's fields (e.g. `total > 1000 and supplier_group == "X"`), which is far richer than a glob/substring match. For the **`body` signal specifically** — where the plan wants last-4 / auth-code / multi-token patterns — a safe-eval `Code` condition would express those more cleanly than stacking regex rows. This is the open trade-off captured in **OD-2** (substring-vs-regex for `body`): weigh adopting an `Assignment Rule`-style safe-eval `Code` condition for body rules against the simpler-but-less-expressive regex-per-row approach.

| fieldname | fieldtype | options / default | purpose |
|---|---|---|---|
| `priority` | Int | default `100` | Lower number = evaluated first. Deterministic ordering. |
| `signal` | Select | `filename\nsender_domain\nbody\nlabel` | Which input the `pattern` matches against. |
| `pattern` | Data | — | Glob (for `filename`/`label`), substring/regex (for `sender_domain`/`body`). Interpretation per `signal` (OD-2). |
| `assign_stream` | Select | `Receipt (R)\nInvoice (I)` | Stream assigned on match. (No rule assigns `Unclassified` — that is the no-match fallthrough.) |
| `enabled` | Check | default `1` | Soft-disable a rule without deleting it. |

`AP Stream Rule` is `istable: 1`, `editable_grid: 1`. Parent field on `AP Closed Loop Settings`: `stream_rules` (`Table`, options `AP Stream Rule`) inside a new `stream_section` Section Break. Permissions inherit from the parent Single (System Manager + Accounts Manager write, Accounts User read).

**Seed rules** (shipped as the doctype's default child rows / a `fixtures`-style migration, OD-3):

| priority | signal | pattern | assign_stream | enabled |
|---|---|---|---|---|
| 10 | filename | `receipt_*` | Receipt (R) | 1 |
| 20 | filename | `invoice_*` | Invoice (I) | 1 |
| 30 | sender_domain | `stripe.com` | Receipt (R) | 1 |
| 40 | body | `PAID` | Receipt (R) | 1 |

#### 5.1.3 New accessor on `AP Closed Loop Settings`

`get_stream_rules() -> list[dict]` mirroring `get_ocr_config()` (`ap_closed_loop_settings.py:111-148`). Reads the child rows, filters `enabled`, sorts by `priority`, returns a list of plain dicts `[{"priority":…, "signal":…, "pattern":…, "assign_stream":…}, …]`. Because child tables don't round-trip through `get_singles_dict`, this accessor uses `frappe.get_all("AP Stream Rule", filters={"parent": "AP Closed Loop Settings", "enabled": 1}, fields=[…], order_by="priority asc")` (child rows carry `parent`/`parenttype`). Returns `[]` on a fresh site (no rules => everything Unclassified, which is correct).

### 5.2 Endpoints

All whitelisted methods live in `erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.py`. The controller's string/dict normalization convention (a `str` JSON arg parsed to a dict; `bool`-ish strings coerced) is already established in `confirm_extracted_fields_for` (`:949-967`) and `record_manager_decision_for` (`:1719-1731`) — new endpoints follow it.

| Dotted path | Signature | Returns | Notes |
|---|---|---|---|
| `erpnext.accounts.doctype.ap_invoice_capture.ap_invoice_capture.create_capture_from_email` | `create_capture_from_email(communication: str) -> list[str]` | List of created capture `name`s. | **New, whitelisted.** Iterates the Communication's supported attachments; one capture per supported attachment. Idempotent (OD-5). |
| `erpnext.accounts.doctype.ap_invoice_capture.ap_invoice_capture.create_capture_from_uploaded_file` | `create_capture_from_uploaded_file(file_name: str, source_context: str \| None = None, intake_channel: str = INTAKE_MANUAL_UPLOAD) -> str` | Capture `name`. | **Extend existing** (`:563-571`) — add the `intake_channel` param (default unchanged) so the mobile client passes `INTAKE_MOBILE_UPLOAD`. Threaded straight into the factory. |
| `erpnext.accounts.doctype.ap_invoice_capture.ap_invoice_capture.handle_inbound_ap_communication` | `handle_inbound_ap_communication(doc, method=None) -> None` | — | **New, NOT whitelisted** — a `doc_events` hook target for `Communication.after_insert`. Guards on inbound + the AP intake Email Account, then calls `create_capture_from_email(doc.name)`. (See 5.3.) |

**Pure function (module-level, not whitelisted, must be import-clean and DB-free):**

```python
def classify_stream_at_intake(
    filename: str | None,
    sender_domain: str | None,
    intake_channel: str | None,
    body_text: str | None,
    rules: list[dict] | None = None,
) -> tuple[str, str]:
    """Return (stream_value, provisional_source). Side-effect free.

    rules=None -> load via AP Closed Loop Settings.get_stream_rules().
    Inject `rules` in tests to avoid the DB. Iterates rules by priority;
    first match wins; no match -> ("Unclassified", "default").
    """
```

**Portal-pull base** (`erpnext/accounts/ap_closed_loop/portal_pull.py`, mirroring `extractors/base.py` + `registry.py`):

```python
@dataclass
class PulledDocument:
    file_name: str
    content: bytes
    received_at: datetime | None = None
    source_context: str | None = None

class PortalPullAdapter(ABC):
    @abstractmethod
    def name(self) -> str: ...
    @abstractmethod
    def pull(self) -> list["PulledDocument"]: ...

def register_portal_adapter(name: str):          # decorator -> populates _ADAPTERS
def get_portal_adapter(name: str) -> PortalPullAdapter:  # raises ValueError on unknown key
```

Phase 3 ships **base + decorator + empty `_ADAPTERS` registry + tests only**. No concrete vendor adapter.

### 5.3 Logic

#### 5.3.1 `classify_stream_at_intake` (pure)

1. `rules = rules if rules is not None else get_stream_rules()` (DB read only when not injected).
2. For each rule in priority order:
   - `filename` signal: `fnmatch.fnmatch((filename or "").lower(), pattern.lower())` -> on match return `(rule.assign_stream, f"filename:{pattern}")`.
   - `sender_domain` signal: `pattern.lower() in (sender_domain or "").lower()` -> `(assign_stream, "sender_domain")`.
   - `label` signal: match against `intake_channel` (or an email label passed as the label slot) -> `(assign_stream, "label")`.
   - `body` signal: pattern found in `body_text` (substring or regex per OD-2; the seed `PAID` is a case-insensitive substring) -> `(assign_stream, f"body:{pattern}")`. The plan also names last-4 (`\b\d{4}\b` near card keywords) and auth codes; these are expressible as `body` regex rules (OD-2), so the function needs no special-casing.
3. No match -> `("Unclassified", "default")`.
4. **The function never writes the doc** — the caller assigns the result (mirrors how `OCRProvider.extract` returns `ExtractionResult` and `run_extraction` does the writing, `base.py:14-17`). `None`/empty `filename` and `body_text` must not raise (guarded with `or ""`).

#### 5.3.2 Wiring into `validate()` (`ap_invoice_capture.py:237`)

Inserted **after** `received_at` is stamped (`:238-239`) and source is hydrated (`:241-242`), **before** the extension/support block:

1. **Idempotency / human-override guard:** derive the provisional tag **only when `stream_provisional_source` is empty** (i.e. it has never been classified). The guard is exactly:
   ```python
   if not self.stream_provisional_source:
       # ... derive stream + provisional_source ...
   ```
   This makes Step-6 revisions ([[07-classification-doctype-branching]]) and manual overrides **survive every re-save** — once `stream_revised_from` or a non-default `stream_provisional_source` is set, `validate()` leaves `stream` alone.
   - **⚠ Do NOT write the guard as** `if not self.stream or self.stream == "Unclassified" and not self.stream_provisional_source:`. Python binds `and` tighter than `or`, so that expression parses as `not self.stream or (self.stream == "Unclassified" and not self.stream_provisional_source)` — i.e. it would **re-derive whenever `stream` is falsy regardless of `stream_provisional_source`**, and would also re-derive any capture still sitting at `"Unclassified"` even after it was deliberately classified-as-unclassified, contradicting the prose ("derive only when never classified"). The single-clause `if not self.stream_provisional_source:` is the correct, unambiguous guard; code and prose now agree.
2. Call `stream_value, source = classify_stream_at_intake(self.source_filename, getattr(self, "_sender_domain", None), self.intake_channel, getattr(self, "_body_text", None))`. The `_sender_domain` / `_body_text` are **transient attributes** the email adapter sets on the in-memory doc before insert (NOT persisted — privacy, risk #7, OD-4). Manual/mobile uploads leave them `None` => `Unclassified`, which is correct (no body to read).
3. `self.stream = stream_value`; `self.stream_provisional_source = source`.
4. **SLA computation (Stream R only):** `self.sla_due_at = add_to_date(self.received_at, hours=72) if self.stream == "Receipt (R)" else None`. Passing `hours` makes `add_to_date` return a `datetime` (citation #5). Recomputed on every save so a Step-6 revision R->I correctly **clears** `sla_due_at`, and I->R sets it. (This recompute is intentionally NOT behind the idempotency guard — it derives purely from the current `stream` + `received_at`.)
5. Nothing else in `validate()` changes; the existing support/status logic runs after.

No new exception type. A malformed rule table (e.g. an unknown `signal`) is treated defensively: `classify_stream_at_intake` skips rules whose `signal` it doesn't recognize and logs once via `frappe.log_error` rather than raising — intake must never be blocked by a tuning typo. (Validation of rule rows themselves can be added on `AP Closed Loop Settings.validate`, OD-1.)

#### 5.3.3 Email-in adapter

**Native `append_to` was considered and rejected — here's why.** Frappe's inbound `Email Account` has a native `append_to = <target doctype>` setting: when set, each inbound mail makes `InboundMail._create_reference_document` (`apps/frappe/frappe/email/receive.py:708-711`) instantiate **one** record of that arbitrary reference doctype and link the Communication to it. So in principle we could set `append_to = "AP Invoice Capture"` and skip the `Communication.after_insert` hook entirely. We **don't**, for two structural reasons the native path can't express:
1. **Fan-out (1 email → N captures).** One inbound email can carry **multiple attachments**, and this spec creates **one capture per supported attachment** (§5.3.3 step 4, AC-02-11). `append_to` is strictly **1:1** — one mail makes exactly one reference doc — so it cannot model the one-email-to-many-captures fan-out. The hook approach lets `create_capture_from_email` iterate attachments and insert N captures.
2. **Selective skipping.** Email attachments are noisy (signature images, logos, `.txt`) and we **skip unsupported attachments** rather than create `Unsupported` captures (§5.3.3 step 5, OD-7). `append_to`'s auto-instantiation gives no hook to filter which attachments do/don't become records.

The native `append_to` mechanism is therefore the wrong tool *here* specifically because of fan-out + filtering — not because the hook is "more powerful" in general. (If the requirement were ever "exactly one capture per email, attach everything," native `append_to` would be the simpler, preferred route and this hook should be revisited.)

`handle_inbound_ap_communication(doc, method=None)` (the `doc_events` target):

1. **Guard (highest-risk wiring, risk #4):** return immediately unless **all** of: `doc.communication_type == "Communication"`, `doc.sent_or_received == "Received"`, and `doc.email_account == <configured AP intake account>`. The configured account name is read from a new `AP Closed Loop Settings` field `ap_intake_email_account` (Link -> Email Account; OD-6) — never hard-coded. If that setting is empty, the handler is a no-op (feature off by default).
2. Call `create_capture_from_email(doc.name)` inside a try/except that logs to Error Log on failure (never let an inbound-email hook raise and break mail sync).

`create_capture_from_email(communication: str) -> list[str]`:

1. Load the Communication (`frappe.get_doc("Communication", communication)`).
2. Find attachments: `frappe.get_all("File", filters={"attached_to_doctype": "Communication", "attached_to_name": communication, "attached_to_field": ["is", "not set"]} or simply {attached_to_doctype, attached_to_name}, fields=["name", "file_name", "file_url"])` — the linkage fields are verified (citations #3, #4).
3. Parse `sender_domain` from `communication.sender` (split on `@`, take the domain); take a bounded snippet of `communication.content` for the body classifier (strip HTML; cap length — do **not** persist raw body, OD-4).
4. For each File whose extension is in `SUPPORTED_EXTENSIONS` (`ap_invoice_capture.py:34`):
   - Build the capture via the factory, **but** set the transient classifier inputs first. Recommended shape: a small helper that does `cap = frappe.new_doc("AP Invoice Capture")`, sets `cap._sender_domain`, `cap._body_text`, then assigns the same fields the factory assigns (channel, `received_at`, source refs) and inserts — OR (simpler) extend `create_capture_from_file` with optional `sender_domain`/`body_text` params that it stashes as transient attrs before `insert()` (OD-4 picks the transport).
   - Call with `intake_channel=INTAKE_EMAIL_INBOUND`, `received_at=communication.communication_date` (**the true receipt time — risk #5; must not fall back to now()**), `source_context=f"Email: {communication.subject}"`.
   - Append the new capture's `.name` to the result.
5. **Skip + log** unsupported attachments (signature images, `.txt`, etc.) rather than creating `Unsupported` captures — email attachments are noisy (OD-7 picks skip vs record; default = skip). Return the list of created capture names (possibly empty).
6. **Idempotency (OD-5):** before creating, check whether a capture already links the same `source_file` (re-delivery / handler re-fire). Recommended: `if frappe.db.exists("AP Invoice Capture", {"source_file": file.name}): skip`. This is a lightweight guard; the stronger content-hash dedupe is [[03-deduplication]]'s job (this only prevents *exact File re-link* double-creation from a re-fired hook).

The cascade then runs normally from `after_insert` (intake -> OCR), now carrying the stream tag.

#### 5.3.4 Mobile

No new server flow. The Frappe mobile client uploads a File, then calls `create_capture_from_uploaded_file(file_name=<File name>, intake_channel="Mobile Upload")`. The new `intake_channel` param (5.2) is threaded by the factory, which already supports it (`:526, 553`). `received_at` falls back to `now()` (upload time ≈ receipt time for a phone photo, acceptable).

#### 5.3.5 Portal-pull (Phase 3, base only)

`portal_pull.py` ships the ABC + `register_portal_adapter` decorator + `get_portal_adapter` (raises `ValueError` on unknown key, same loud-failure contract as `registry.py:38-41`) + an empty `_ADAPTERS` dict. A concrete adapter would `pull()` `PulledDocument`s and feed each through `create_capture_from_file(..., intake_channel=INTAKE_PORTAL_PULL, received_at=<portal timestamp>)`. **No concrete adapter is in scope.**

### 5.4 Cascade & stream-awareness

- **Where it slots:** stream tagging happens entirely **inside `validate()`** (5.3.2), i.e. *before* `after_insert` -> `_kick_next_step` (`ap_invoice_capture.py:281-319`). The cascade's `_determine_next_step` (`:321-366`) is **unchanged by this spec** — intake still advances to OCR for any supported capture regardless of stream. Stream-aware *branching* of the cascade (Stream R -> Journal Entry skipping approval/payment; Stream I -> PI -> approval -> payment) is owned by [[07-classification-doctype-branching]], [[11-approval-sod-workflow]], and [[12-payment-execution]]; they read the `stream` field this spec sets.
- **Pause vs auto-advance:** intake never pauses on stream tagging — it is a synchronous derivation in `validate()`, so the capture lands already-tagged and the existing OCR cascade fires immediately. No new pause point is introduced.
- **Stream R vs Stream I divergence here:** only `sla_due_at` differs by value (Stream R gets a 72h deadline; I/Unclassified get NULL). The tag itself is set for all three.
- **Queue priority:** the plan says the provisional tag "drives queue priority." Phase 1 realizes this as a **filterable/sortable signal** (`stream` + `sla_due_at` are `in_standard_filter`), consumed by the AP review list and [[10-ap-review-observability]]; an active queue-reordering scheduler is out of scope here (OD-8). **Native hook for Phase 2:** Frappe's `ToDo` carries a native `priority` field (`Select` `High`/`Medium`/`Low`, `apps/frappe/frappe/desk/doctype/todo/todo.json`). When the active queue *is* built, Stream-R-near-SLA items should map to a `ToDo` with `priority="High"` rather than inventing a parallel priority field — `ToDo.priority` is the framework-native ordering signal the desk already understands (list views, the assignment sidebar). Phase 1 stays filter/sort on `stream`/`sla_due_at`; Phase 2 layers `ToDo.priority` on top.

### 5.5 Cross-cutting

- **Permissions / SoD:** intake creation is unchanged — Accounts User / Accounts Manager (`ap_invoice_capture.json:640-664`). `create_capture_from_email` is whitelisted but the realistic caller is the `Communication.after_insert` hook running as the inbound-mail context; it is also callable manually by a permitted user for re-processing. `stream`, `stream_provisional_source`, `stream_revised_from`, `sla_due_at`, and `AP Stream Rule` rows are read/written under the existing role set; the rule table is editable only by System Manager + Accounts Manager (parent Single perms). No new role is introduced by this spec.
- **Idempotency:** intake idempotency uses the per-`source_file` existence guard (OD-5) to stop a re-fired email hook from double-creating; the stream-tag derivation is itself idempotent via the `stream_provisional_source`-empty guard (5.3.2 step 1). Content-level dedupe (the real double-pay firewall) is [[03-deduplication]]. The general idempotency-key infrastructure ([[01-foundations-settings-async-idempotency]]) is available if a stronger key is wanted for the adapters.
- **Async / enqueue:** the email handler runs synchronously in the `after_insert` hook (cheap: a couple of `frappe.get_all` + N inserts). If an inbound batch is large, the handler MAY enqueue `create_capture_from_email` via `frappe.enqueue` (OD-9); the default is synchronous for simplicity and immediate visibility. The downstream OCR cascade is already async (`_enqueue_next`, `:368-404`).
- **Observability:** the `stream_provisional_source` vs (later) `stream_revised_from` delta is the **stream-mistag signal** consumed by [[10-ap-review-observability]] (root-cause tag `stream_mistag`). This spec only *persists* the two fields; the disagreement-rate report and the `AP Review Event` emission on revision are [[10-ap-review-observability]] / [[07-classification-doctype-branching]].

## 6. Acceptance criteria

- **AC-02-1 (positive, filename):** A capture whose `source_filename` matches a `filename:receipt_*` rule is saved with `stream == "Receipt (R)"`, `stream_provisional_source == "filename:receipt_*"`, and `sla_due_at == add_to_date(received_at, hours=72)`.
- **AC-02-2 (positive, body):** With a neutral filename but `body_text` containing `PAID` and a `body:PAID` rule, the capture classifies as `Receipt (R)` with `stream_provisional_source == "body:PAID"`.
- **AC-02-3 (positive, sender):** A configured `sender_domain` rule (e.g. `stripe.com`) classifies an email-in capture as `Receipt (R)`.
- **AC-02-4 (negative / fallthrough):** No signal matches => `stream == "Unclassified"`, `stream_provisional_source == "default"`, `sla_due_at` is NULL.
- **AC-02-5 (precedence/edge):** Given both a `filename:invoice_*` rule (priority 20) and a `body:PAID` rule (priority 40) where the doc matches both, the **lower-priority-number rule wins** (`Invoice (I)`); ordering is deterministic across runs.
- **AC-02-6 (edge, no inputs):** `classify_stream_at_intake(None, None, None, None, rules=[…])` returns `("Unclassified","default")` and raises nothing.
- **AC-02-7 (SLA stream-gating):** A `Receipt (R)` capture has non-NULL `sla_due_at`; an `Invoice (I)` and an `Unclassified` capture have NULL `sla_due_at`.
- **AC-02-8 (idempotency of tag):** Re-saving a capture whose `stream` was manually changed `Receipt (R)` -> `Invoice (I)` (with `stream_provisional_source` already set / `stream_revised_from` populated) does **not** re-derive `stream` back to `Receipt (R)`, and correctly clears `sla_due_at` to NULL.
- **AC-02-9 (channel persistence):** `create_capture_from_file(..., intake_channel="Email Inbound", received_at=<explicit>)` persists `intake_channel == "Email Inbound"` and `received_at == <explicit>` (not `now()`).
- **AC-02-10 (mobile param):** `create_capture_from_uploaded_file(file_name, intake_channel="Mobile Upload")` persists `intake_channel == "Mobile Upload"`.
- **AC-02-11 (email-in positive):** A `Communication` with two attached Files (one supported `.pdf`, one unsupported `.txt`) yields exactly **one** capture, linked to the `.pdf` File, with `intake_channel == "Email Inbound"`, `received_at == communication.communication_date`, and `stream` classified from sender/filename.
- **AC-02-12 (email-in negative, no supported attachments):** A `Communication` with only unsupported attachments returns `[]` and creates no capture.
- **AC-02-13 (email-in guard):** The `Communication.after_insert` handler is a no-op when `sent_or_received != "Received"` or the `email_account` is not the configured AP intake account (no capture created).
- **AC-02-14 (portal registry):** `register_portal_adapter("x")` then `get_portal_adapter("x")` resolves the adapter; `get_portal_adapter("missing")` raises `ValueError`.
- **AC-02-15 (data-driven, no code change):** Adding an `AP Stream Rule` row (e.g. `sender_domain: square.com -> Receipt (R)`) changes classification of a matching new capture **without any code edit** (tuning happens in Settings only).

## 7. Tests

### 7.1 Automated

Base class `from frappe.tests import IntegrationTestCase` (matches `test_ap_invoice_capture.py:8`); roll back all DB writes in `tearDown` (use `frappe.db.rollback()` / delete created Communications, Files, captures, and rule rows so suites are reentrant). Run: `bench --site <site> run-tests --module <dotted.path>`.

**Module 1 — `erpnext.accounts.doctype.ap_invoice_capture.test_ap_invoice_capture`** (extend existing; the suite already asserts `intake_channel == INTAKE_MANUAL_UPLOAD` at `:153,265`):

- `classify_stream_at_intake` (pure, **inject `rules`** dict — no DB):
  - positive filename: `"receipt_2026.pdf"` -> `("Receipt (R)", "filename:receipt_*")`; `"invoice_88.pdf"` -> `("Invoice (I)", "filename:invoice_*")` — **AC-02-1, AC-02-5**.
  - positive body: `PAID` + 4-digit + auth code, neutral filename -> `Receipt (R)` via body — **AC-02-2**.
  - positive sender: configured card-receipt domain -> `Receipt (R)` — **AC-02-3**.
  - negative/edge: all signals empty/unknown -> `("Unclassified","default")` — **AC-02-4, AC-02-6**.
  - precedence: filename `invoice_*` (pri 20) vs body `PAID` (pri 40) -> filename wins; assert deterministic ordering — **AC-02-5**.
  - edge: `None` filename + `None` body don't raise — **AC-02-6**.
- `sla_due_at` computation (full capture insert):
  - Stream R capture -> `sla_due_at == add_to_date(received_at, hours=72)`; Stream I and Unclassified -> `sla_due_at is None` — **AC-02-7**.
  - idempotency: insert as `Receipt (R)`, then set `stream="Invoice (I)"` + a non-default `stream_provisional_source` and re-save -> `stream` stays `Invoice (I)`, `sla_due_at` becomes NULL — **AC-02-8**.
- `intake_channel` extension:
  - `create_capture_from_file(..., intake_channel=INTAKE_EMAIL_INBOUND, received_at=<explicit>)` persists channel + explicit `received_at` — **AC-02-9**.
  - `create_capture_from_uploaded_file(file_name, intake_channel=INTAKE_MOBILE_UPLOAD)` persists `Mobile Upload` — **AC-02-10**.
- `create_capture_from_email`:
  - build a `Communication` with 2 attached Files (one `.pdf`, one `.txt`) via `attached_to_doctype`/`attached_to_name`; assert exactly one capture, linked to the right File, `intake_channel == "Email Inbound"`, `received_at == communication_date`, stream classified — **AC-02-11**.
  - negative: Communication with no supported attachments -> `[]`, no capture — **AC-02-12**.
  - negative: `handle_inbound_ap_communication` on a `sent_or_received != "Received"` Communication (or non-AP `email_account`) is a no-op — **AC-02-13**.
  - data-driven: add an `AP Stream Rule` row, then a matching email-in capture classifies per the new rule with no code change — **AC-02-15**.

**Module 2 — `erpnext.accounts.ap_closed_loop.test_portal_pull`** (new file, mirrors a registry test):

- `register_portal_adapter("x")` + `get_portal_adapter("x")` resolves; `get_portal_adapter("missing")` raises `ValueError` — **AC-02-14**.
- (edge) double-registration of the same key behaves per the registry contract (last-wins or raise — match whatever `registry.py` does; document the choice).

**Module 3 — `erpnext.accounts.doctype.ap_closed_loop_settings.test_ap_closed_loop_settings`** (extend existing):

- `get_stream_rules()` returns rows ordered by `priority`, excludes `enabled=0` rows, and returns `[]` on a settings doc with no rule rows.

### 7.2 Clean-room test plan

- **`test/testplans/intake-stream-tagging.md`** (slug `intake-stream-tagging`) — the primary runbook. Scope: configure `AP Closed Loop Settings` stream rules; manual upload -> `Unclassified`; verify `stream_provisional_source`; verify the Stream-R 72h `sla_due_at` computation; confirm a (simulated) Step-6 revision leaves `stream_revised_from`. Includes the rule-table tuning walkthrough (add a row, re-classify, no code change).
- **`test/testplans/intake-email-inbound.md`** (slug `intake-email-inbound`) — split-out companion. Scope: stand up the dedicated inbound **Email Account**, set its "Append To" + the `ap_intake_email_account` setting, email a `receipt_*.pdf` to it, and confirm a capture is auto-created as **Stream R** with a 72h `sla_due_at` and `intake_channel = Email Inbound`, driven by the `Communication.after_insert` trigger. Covers the no-op guard (send from a non-AP account -> nothing created). This plan also documents how the operator obtains/configures inbound mail credentials (named, never the secret).

### 7.3 UI testing (Playwright MCP)
Browser-driven verification of the desk UI this slice adds, executed by driving a real browser through the **Playwright MCP** server. These are the UI steps of the §7.2 clean-room runbook.
- **Prereq:** Playwright MCP set up per `test/testplans/BROWSER-TESTING-SETUP.md` (`claude mcp list` must list `playwright`; restart Claude Code after registering). `.mcp.json` and `.playwright-mcp/` stay gitignored.
- **Evidence:** save screenshots to `test/testplans/screenshots/intake-stream-tagging/<name>.png` (committed) — always pass that path as the screenshot `filename`.
- **Source of truth stays the DB:** screenshots are UI evidence, but after every UI action that writes data, verify the actual write via `bench --site <site> mariadb` / `bench … execute` (consistent with §7.2), then delete data created through the UI.

**Scenarios** (each `route → action → expected UI → DB assertion`):
- `/app/ap-invoice-capture/new` (or the list-view **Upload** action) → attach a supported file named to trigger a stream signal (e.g. `receipt_acme.pdf` vs `invoice_acme.pdf`) and **Save** → the capture is created in `Pending Review` with the `stream` field showing the correct provisional tag (`Receipt (R)` / `Invoice (I)`) and `stream_provisional_source` populated; screenshot the saved form → DB-assert `stream` + `stream_provisional_source` on the new capture.
- Stream-R upload (`receipt_*.pdf`) → `sla_due_at` is populated (`received_at + 72h`) and visible on the form; screenshot → DB-assert `sla_due_at == add_to_date(received_at, hours=72)`.

**Not browser-testable in this slice** (covered by §7.1/§7.2): the email-in intake path (`Communication.after_insert` hook + `create_capture_from_email` fan-out / guard) and the Phase-3 portal-pull adapter registry — both are backend flows with no desk surface, verified by the §7.1 automated suites and the `intake-email-inbound` clean-room runbook.

## 8. Open decisions

| ID | Decision | Options | Recommended default | Owner | Must lock by |
|---|---|---|---|---|---|
| OD-1 | Rule-table representation | (a) child DocType `AP Stream Rule` (validated, grid UI) ; (b) single `Long Text`/`Code` JSON field on Settings | **(a) child DocType** — tunable + validated, matches "no code change to tune"; bigger schema change but worth it | Eng + AP lead | Before build start (drives schema) |
| OD-2 | `body` / `sender_domain` pattern semantics | (a) plain case-insensitive substring only ; (b) substring for `sender_domain`, **regex** for `body` (enables last-4 `\b\d{4}\b` + auth-code rules) ; (c) adopt an `Assignment Rule`-style **safe-eval `Code` condition** for `body` rules (`frappe.safe_eval` over the body text / parsed tokens) — strictly more expressive than regex-per-row, at the cost of a richer (riskier) rule grammar | **(b)** — the plan explicitly wants last-4/auth-code body patterns, which need regex; **(c)** is the upgrade path if body rules outgrow regex (see the `Assignment Rule` prior-art note in §5.1.2) — keep it in view but don't ship the safe-eval grammar in Phase 1 | Eng | Build start |
| OD-3 | Ship seed rules? | (a) ship the 4 seed rules as defaults/fixture ; (b) ship empty (operator authors all) | **(a)** — receipt_*/invoice_*/stripe/PAID are universally safe and make the feature demo-able out of the box | AP lead | Build start |
| OD-4 | Transport for `sender_domain` / `body_text` to the classifier | (a) transient attrs (`_sender_domain`, `_body_text`) on the in-memory doc, never persisted ; (b) extra params on `create_capture_from_file` that stash transient attrs ; (c) persist a redacted body field | **(b)** — explicit factory params, stashed as transient attrs; **never persist raw body** (privacy) | Eng | Build start |
| OD-5 | Email-in re-fire idempotency | (a) per-`source_file` `frappe.db.exists` guard ; (b) rely solely on [[03-deduplication]] content hash ; (c) idempotency key via [[01-foundations-settings-async-idempotency]] | **(a)** now, defer content-level dedupe to [[03-deduplication]] | Eng | Build start |
| OD-6 | How the AP intake Email Account is identified | (a) new `ap_intake_email_account` Link field on Settings ; (b) a fixed account name convention ; (c) a flag on the Email Account itself | **(a)** Settings Link — explicit, no hard-coding, off-by-default when empty | Eng + AP lead | Build start (guard depends on it) |
| OD-7 | Unsupported email attachments | (a) **skip + log** ; (b) create `Unsupported` captures (current manual-factory behavior) | **(a) skip** — email attachments include signatures/logos; recording them as captures is noise | AP lead | Build start |
| OD-8 | Queue priority realization | (a) filter/sort signal only (Phase 1) ; (b) active queue-reordering scheduler ; (c) Phase-2 maps SLA-urgency onto **native `ToDo.priority`** (High/Medium/Low — `frappe/desk/doctype/todo/todo.json`) so the desk's existing prioritization UI surfaces it | **(a)** Phase 1; **(c)** for Phase 2 (reuse native `ToDo.priority` rather than a custom priority field) ; revisit if SLA breaches accumulate | AP lead | Phase 1 acceptable as-is |
| OD-9 | Email handler sync vs async | (a) synchronous in `after_insert` ; (b) `frappe.enqueue` the parse | **(a) sync** (cheap, immediately visible); switch to (b) only if inbound batches are large | Eng | Build start |
| OD-10 | `stream` Select labels | (a) `Receipt (R)` / `Invoice (I)` / `Unclassified` (self-describing) ; (b) bare `R` / `I` / `Unclassified` | **(a)** — matches the `Fake (Deterministic)` label style; persisted value reads clearly in reports | Eng | Build start (schema) |

## 9. Dependencies & sequencing

**Must land first:**
- [[01-foundations-settings-async-idempotency]] — provides the `AP Closed Loop Settings` extension pattern + (optional) idempotency-key infra the adapters can lean on. The settings Single + `get_*` accessor convention this spec extends already exist (`ap_closed_loop_settings.py:85-148`), so this is a soft dependency for the rule-table accessor's style, not a hard blocker.

**This spec unblocks (it OWNS the `stream` concept all of these read):**
- [[07-classification-doctype-branching]] — Step-6 stream **revision** writes `stream_revised_from` and branches the doctype on `stream`.
- [[10-ap-review-observability]] — disagreement-rate tuning reads `stream_provisional_source` vs `stream_revised_from` (root-cause `stream_mistag`).
- [[13-bank-feed-reconciliation]] — the Stream-R 72h SLA breach report consumes `stream` + `sla_due_at`; the SimpleFIN matcher gates on `stream == "Receipt (R)"`.
- [[11-approval-sod-workflow]] / [[12-payment-execution]] — gate on `stream == "Invoice (I)"` to apply approval + payment (Stream R skips both).
- Phase-3 vendor portal adapters — the `portal_pull.py` base + registry is the seam they plug into.

**Estimated size: L.** Breakdown (IMPLEMENTATION-PLAN units): the schema changes (4 capture fields + child DocType + accessor) and the pure classifier are **M**; the email-in adapter + `Communication.after_insert` wiring + its guard (the highest-risk piece, risk #4) plus the two test plans push it to **L**. The portal-pull base is **S** on its own. Mobile is **S** (one param). Recommend building in the order: schema + classifier (+ tests) -> mobile param -> email-in adapter + hook -> portal-pull base, so each lands testable independently.
