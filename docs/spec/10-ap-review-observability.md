---
spec: 10-ap-review-observability
title: AP Review (Exception Handling) — instrumented feedback gate
plan_step: Step 9 (AP Review with the v2 observability requirement)
stream: both
status: Draft
depends_on: [01-foundations-settings-async-idempotency]
related: [02-intake-stream-tagging, 04-extraction-confidence-line-items, 05-supplier-resolution, 07-classification-doctype-branching, 08-validation-gates, 09-confidence-routing, 11-approval-sod-workflow, 12-payment-execution]
---

# 10 — AP Review (Exception Handling) — instrumented feedback gate
> _Revised 2026-05-31: applied native-vs-custom review findings; added Playwright UI test plan (§7.3)._

## 1. Summary

This spec turns Step 9 from a silent exception handler into an instrumented **feedback gate**. It adds (a) a clerk-facing **reject-back-to-vendor / reopen** transition pair the document currently lacks, recorded in a new child table `AP Capture Rejection Log`; (b) a new standalone log DocType **`AP Review Event`** that every Step-9 clerk action emits exactly once, carrying a fixed-vocabulary root-cause tag; and (c) a weekly "Top step-9 root causes" Query Report plus an auto-rate Dashboard Chart that answer the plan's two governance questions. Instrumentation is **stream-agnostic** — Stream R (already-paid receipts) and Stream I (unpaid payables) both emit events — but Stream R emits a lighter subset (no approval/rejection root causes). Current-state delta: `STATUS_REJECTED` is declared and listed in the `status` Select but **no function ever assigns it** (`ap_invoice_capture.py:38`, `ap_invoice_capture.json:162`); the only `*_REJECTED` writes target the *payment* `approval_status` field — so there is no clerk reject path and zero step-9 telemetry today.

## 2. Plan alignment

From `docs/planning/workflow-v2-plan.md` Step 9 ("AP Review (Exception Handling) — instrumented as a feedback gate"):

> "For items in the review queue, an AP clerk addresses the surfaced exception: correcting a misread field, resolving a supplier ambiguity, completing GL coding, or rejecting the document back to the vendor with a reason. Rejected items are not dead-ends — they re-enter the workflow when corrected, and the rejection trail is preserved for audit."

> "**Observability requirement.** Step 9 is not just an exception handler — it is the **gate that tells us whether we are automating everything we can automate** … Each `AP Review Event` captures: original exception reason code, action taken (field corrected / supplier created / rejected / classified-other), field(s) changed, time-to-resolve, the clerk's chosen **root-cause tag** from a fixed vocabulary (`extraction_miss`, `supplier_unmapped`, `confidence_threshold_too_tight`, `stream_mistag`, `policy_violation`, `vendor_error`, `missing_po`, `other`), and any free-text note. A weekly 'Top step-9 root causes' report drives the auto-rate dashboard and surfaces the highest-leverage tuning changes."

Control-Summary row this spec owns:

| Control | Where it lives | Why it matters |
|---|---|---|
| **AP Review Event instrumentation** | Step 9 | Measures avoidable-exception rate and drives the auto-rate tuning loop |

It also operationalizes the principle row "**Exceptions loop, they don't dead-end.**" (reject/reopen with audit trail preserved) and the "**PO-as-upstream-control**" row — this spec's report is explicitly the feedback loop quantifying whether adopting [[08-validation-gates]]'s PO control is worth it (the `missing_po` tag rate is the metric).

**Stream R vs Stream I divergence here:**
- **Stream I** (unpaid payable): full instrumentation. All action types fire, including `rejected` from the manager-approval path, and root causes `policy_violation` / `vendor_error` / `missing_po`. Reject-back-to-vendor is a real clerk action because an invoice can be bounced before a payable exists.
- **Stream R** (already-paid receipt): lighter instrumentation. The money already moved on the card, so there is no approval to reject and no payment to block — root causes are limited to the reconciliation-relevant set (`extraction_miss`, `supplier_unmapped`, `stream_mistag`, `other`). A Stream R capture rejected back to vendor is rare (you cannot un-charge a card); the reject path still exists for true junk/duplicate-not-caught cases, but `action_taken="rejected"` with a payment/approval root cause must NOT appear on Stream R. Gating lives at the call sites, not in the helper.

## 3. Current state

All file:line refs are against branch `russ/migrateToV16`. Spec-10 surface lives almost entirely in one controller + its JSON.

**The core gap (confirmed against code):** `STATUS_REJECTED = "Rejected"` is declared at `ap_invoice_capture.py:38` and `"Rejected"` is a valid option of the document `status` Select (`ap_invoice_capture.json:162`, options `Pending Review\nUnsupported\nRejected\nProposed\nNeeds Correction\nConfirmed`; mirrored in the `DF.Literal` type hint at `ap_invoice_capture.py:182-189`). **No function assigns `capture.status = STATUS_REJECTED`.** The only `*_REJECTED` writes in the file target a *different* field, `approval_status` (`APPROVAL_STATUS_REJECTED = "Rejected"`, line 71), at `ap_invoice_capture.py:1355`, read by `is_payment_blocked` at `:1383`. So the document-level "Rejected" state is reachable only by a direct DB write today.

**What "reject" means today (and why it is NOT a step-9 reject):** `record_manager_decision(capture, approve, actor, notes, save)` (`:1321-1362`) is a **manager over-threshold payment decision**, gated by `frappe.only_for(capture.assigned_approver_role or MANAGER_APPROVAL_ROLE_DEFAULT)` (`:1336`), requires `approval_status == "Pending Manager"` (`:1338`), and on `approve=False` sets `approval_status=Rejected`, `payment_readiness=Blocked`, `action_required=1` (`:1355-1358`). The form's "Reject" button calls `record_manager_decision_for` (`:1719`) — it rejects a *payment*, not the capture document. There is **no** UI or server path for a clerk to bounce a capture back to the vendor.

**Status state machine:** `validate()` at `:237-279` derives `status` + `action_required` + `action_required_reason` from format-support (`Unsupported`) and the in-progress states (`Pending Review` / `Proposed` / `Needs Correction`). It has **no `Rejected` branch** — a manually-set `status=Rejected` is at risk of being re-derived/clobbered on the next `save()` (the highest-risk integration point; see §5.3 and §8). The terminal positive end-state is `promotion_status == "Promoted"` (`PROMOTION_STATUS_PROMOTED`, `:62`); the plan's "reject allowed from any non-terminal state except Promoted" therefore maps to `promotion_status != "Promoted"`.

**Existing step-9 touchpoints that must each emit one `AP Review Event`:**
- `confirm_extracted_fields(capture, corrections, reviewer, notes, save)` (`:867-933`) — the field-correction / coding action. Merges `proposed_*` → `final_*` overridden by `corrections`; records `reviewed_by` / `reviewed_at` / `review_notes` (`:912-915`); parks at `Needs Correction` if mandatory fields still missing (`:917-924`) else `Confirmed` (`:925-929`). Whitelisted wrapper `confirm_extracted_fields_for` (`:949-967`). → `action_taken` in `{field_corrected, coding_completed}`.
- supplier resolution: `_match_supplier(supplier_name)` (`:975-1002`) + `supplier_match_status` Select (`json:387`). A clerk creating/mapping a supplier → `action_taken=supplier_created`, root cause `supplier_unmapped` (the create request itself lives in [[05-supplier-resolution]]).
- `record_manager_decision` reject (`:1355`) → `action_taken=rejected` with payment context (Stream I only).
- `validate_for_purchase_invoice` (`:1020-1102`) and `_classify_purchase_reference` (`:1005-1017`) — stream/PO classification touchpoints (root causes `stream_mistag`, `missing_po`).

**Audit trail already exists:** the capture sets `track_changes: 1` (`json:669`), so Frappe auto-writes a `Version` row on each field change. This is the "preserve audit trail (Frappe Version)" mechanism the plan relies on. Reject/reopen MUST mutate through `doc.save()` / `doc.append()` — **not** `frappe.db.set_value` — or versioning is bypassed (see §8 risk).

**No existing report or Dashboard Chart references "AP Invoice Capture"** (grep of `erpnext/accounts/report/` and `erpnext/accounts/dashboard_chart/` returned nothing). The weekly report and auto-rate chart are net-new. Module is `Accounts` (`json:636`); standard reports live under `erpnext/accounts/report/<slug>/` and charts under `erpnext/accounts/dashboard_chart/<slug>/`. `hooks.py` has a populated `scheduler_events["weekly"]` list (the `auto_create_exchange_rate_revaluation_weekly` entry) where an optional weekly rollup job slots in.

**Correction to the brief:** none required — every current-state claim in the brief was confirmed against the code as read. One precision note: the brief's "reject allowed from any non-terminal state except Promoted" is stated against the doc `status`, but `Promoted` is not a `status` value — it is a `promotion_status` value. The guard in §5.3 is therefore written against `promotion_status`, which is correct.

### 3.1 Per-candidate native-logging verdict (why a custom `AP Review Event` is required)

Before committing to a new DocType, each native Frappe logging/audit carrier was evaluated against the four hard requirements this spec must satisfy: a **fixed 8-value `root_cause_tag` vocabulary**, a `time_to_resolve_seconds` measure, a per-action `action_taken` class, and **single-SQL-`GROUP BY` reportability** for the weekly "Top step-9 root causes" rollup. Each verdict below was VERIFIED against the installed source on branch `russ/migrateToV16`:

| Native candidate | Source checked | Why it does NOT fit | Verdict |
|---|---|---|---|
| **`Activity Log`** | `apps/frappe/frappe/core/doctype/activity_log/` | Its vocabulary is a **fixed auth/operation set** (Login / Logout / and the framework's own operation types) — there is no slot for a custom AP root-cause tag, and the schema is not meant for app-defined event classes. Cannot carry `root_cause_tag` or `action_taken`. | **Reject.** |
| **`Comment`** | `apps/frappe/frappe/core/doctype/comment/` | `comment_type` is drawn from a **fixed system vocabulary** (Comment / Like / Workflow / Assignment / …) and the payload is **free HTML** — it is **NOT queryable by a custom tag**, so it cannot back a `GROUP BY root_cause_tag`. Using it would defeat the weekly report. | **Reject explicitly** — it looks tempting (it's the obvious "leave a note" doctype) but it cannot be grouped by an app tag. |
| **`Version`** | `apps/frappe/frappe/core/doctype/version/` (capture sets `track_changes: 1`, `json:669`) | A **diff blob** — it records **THAT** fields changed, not **WHY**. No root-cause, no action class, no resolve-time. It is **complementary** (this spec deliberately keeps `track_changes` for the field-level audit), not a substitute for the event sink. | **Complementary, not a substitute.** |
| **`Energy Point Log`** | grep of `apps/frappe/frappe/social/` / core | **Does NOT exist in this Frappe build** — the energy-points feature was removed upstream and there is no `Energy Point Log` DocType on the installed `16.18.3`. A non-existent doctype cannot be a carrier. | **Reject — not present.** |
| **`Audit Trail`** | the Audit Trail viewer page (renders `Version` data) | A **Single VIEWER UI** that renders existing `Version` records — it is **not an append-per-action sink** with its own rows. Nothing to write a per-action tagged event into. | **Reject — viewer, not a sink.** |

**Conclusion:** the combination of (1) the **fixed 8-value `root_cause_tag`** vocabulary, (2) `time_to_resolve_seconds`, (3) a per-action `action_taken`, and (4) **single-SQL-`GROUP BY` reportability** has **no native carrier** — `Activity Log`/`Comment` can't hold or group the tag, `Version`/`Audit Trail` only record/show field diffs, and `Energy Point Log` doesn't exist in this build. Therefore the custom **`AP Review Event`** DocType (§5.1 B) is justified. `Version` is retained alongside it for the field-level "what changed" audit (§3 "Audit trail already exists"); `AP Review Event` answers the "why, and how long it took" that no native doctype can.

## 4. Upstream grounding

| URL | Confirms | Verified quote / signature |
|---|---|---|
| https://docs.frappe.io/framework/v15/user/en/basics/doctypes/child-doctype | How to define the new child table `AP Capture Rejection Log` and attach it to the parent. | "A Child DocType is doctype which can only be linked to a parent DocType." • "To make a Child DocType make sure to check **Is Child Table** while creating the doctype." • "To link a Child Doctype to its parent, add another row in Parent Doctype with field type **Table** and options as **Child Table**." |
| https://docs.frappe.io/framework/v15/user/en/api/document | Server-side creation of `AP Review Event` log docs and appending Rejection-Log child rows. | `doc = frappe.new_doc('Task'); doc.title = 'New Task 2'; doc.insert()` • `doc.append("childtable", {"child_table_field": "value", ...})` • `doc.insert(ignore_permissions=True)` (bypasses write permissions during insert). |
| https://docs.frappe.io/framework/v15/user/en/desk/reports/query-report | The weekly "Top step-9 root causes" Query Report: single SQL, filter placeholders, standard JSON checked into version control under the module. | "Query Reports are reports that can be generated using a single SQL query." • "Filters can be used as formatting variables in the query. For example a filters of type `customer` can be used as `%(customer)s` in the query." • "If you set Standard as \"Yes\" and Developer Mode is enabled, then a JSON file will be generated which you will have to check in to your version control… The Module will decide where the JSON file will go." |
| https://docs.frappe.io/framework/v15/user/en/desk/reports/script-report | Script Report fallback if the auto-rate % exceeds a single SQL: `execute()` signature, return shape, file layout. | `def execute(filters=None):\n  columns, data = [], []\n  return columns, data` — "A developer can optionally return a few paramters like `message`, `chart`, `report_summary`, `skip_total_rows`." File layout `{module-folder}/report/{report-name}/` with `{report-name}.py` + `{report-name}.js`. |
| https://docs.frappe.io/framework/v15/user/en/basics/doctypes | General DocType creation for the new `AP Review Event` DocType (JSON object → `tab<DocType>` table; singular naming). | "When you create a DocType, a JSON object is created which in turn creates a database table." • "DocType is always singular." • "Table names are prefixed with `tab`." |
| https://docs.frappe.io/erpnext/user/manual/en/dashboard | Dashboard Chart for the auto-rate dashboard (Group By over `AP Review Event` keyed by `root_cause_tag`; Count over a date field for the trend). **Brief flagged this citation `verified: false`** — the bare URL 404'd on direct fetch (trailing-slash/redirect quirk) and the field vocabulary was pulled via the docs search index. Cite the canonical URL; **re-verify the exact Chart Type / Group By field names against the running site's Dashboard Chart DocType before writing the chart JSON** (see §8). | Canonical URL only — no fabricated quote. The v15 Frappe Charts guide https://docs.frappe.io/framework/user/en/guides/desk/making_charts (resolves 200) confirms: "Frappe Charts enables you to render simple line, bar or percentage graphs for single or multiple discreet sets of data points." |

## 5. Design

### 5.1 Data model

Two **new** DocTypes, both non-submittable (`is_submittable: 0`), both `module: "Accounts"`, developer-mode standard JSON checked into the repo, plus one new `Table` field on the existing `AP Invoice Capture`.

#### (A) New child table — `AP Capture Rejection Log`

`istable: 1` ("Is Child Table" checked, per the child-doctype citation). Directory `erpnext/accounts/doctype/ap_capture_rejection_log/`. Co-locating the reject/reopen trail with the capture (rather than a separate log doctype) keeps it visible in-form and lets the parent's `track_changes` Version row capture the mutation.

| fieldname | fieldtype | options / default | purpose |
|---|---|---|---|
| `action` | Select | `Rejected\nReopened` | The transition recorded by this row. |
| `reason` | Small Text | — | Clerk's free-text reason (rejection reason or reopen rationale). |
| `from_status` | Data | — | Document `status` immediately **before** the transition. On a `Rejected` row this is the value `reopen` deterministically restores. |
| `to_status` | Data | — | Document `status` immediately **after** the transition. |
| `actor` | Link → User | default `frappe.session.user` | Who performed the transition. |
| `timestamp` | Datetime | default `now` | When (explicit mirror of `creation` for queryability). |

`parent` / `parenttype` / `parentfield` / `idx` are auto-managed by Frappe. Rows are appended via `doc.append("rejection_log", {...})` — never raw SQL — so child linkage + parent versioning stay correct.

**New field on `AP Invoice Capture`** (parents the child table; child-doctype citation):

| fieldname | fieldtype | options | purpose |
|---|---|---|---|
| `rejection_log` | Table | `AP Capture Rejection Log` | Holds the reject/reopen audit rows. Place in a new `Section Break` (e.g. `rejection_section`, label "Rejection / Reopen Trail") after the `mock_payment_section` block in `field_order`. |

#### (B) New DocType — `AP Review Event`

Standalone log (NOT a child table, NOT submittable). Directory `erpnext/accounts/doctype/ap_review_event/`. `naming_rule: "Expression"`, `autoname: "format:APRE-{YYYY}-{#####}"` (mirrors the capture's expression naming at `json:3,638`).

| fieldname | fieldtype | options / default | purpose |
|---|---|---|---|
| `capture` | Link → AP Invoice Capture | `reqd: 1`, `in_list_view: 1` | The capture this clerk action was performed on. |
| `exception_reason_code` | Data | — | The original surfaced-exception code (free identifier, e.g. the `action_required_reason` slug or a confidence/validation code from [[09-confidence-routing]]). |
| `action_taken` | Select | `field_corrected\nsupplier_created\nrejected\nclassified_other\ncoding_completed` | The clerk action class. (See §8 for the `reopened` open decision.) |
| `fields_changed` | Small Text | — | JSON string of `{logical_field: {from, to}}`. Small Text chosen over a native JSON fieldtype for v15/v16 portability (see §8). |
| `time_to_resolve_seconds` | Int | — | Seconds from review-queue entry to this action (see §5.3 step 3 + §8 for the source-timestamp dependency). |
| `root_cause_tag` | Select | `extraction_miss\nsupplier_unmapped\nconfidence_threshold_too_tight\nstream_mistag\npolicy_violation\nvendor_error\nmissing_po\nother` | **Fixed vocabulary** (the plan's list, verbatim). Drives the weekly report + chart. |
| `note` | Small Text | — | Free-text clerk note. |
| `clerk` | Link → User | default `frappe.session.user` | Acting clerk (explicit, queryable mirror of `owner`). |
| `created` | Datetime | default `now` | Action timestamp (explicit, queryable mirror of `creation`). |

**Deliberate redundancy:** Frappe gives every doc `owner` + `creation`. `clerk` / `created` are explicit mirrors so the report/chart query stable columns rather than framework meta columns — call this out as intentional, not an oversight.

**Permissions (both new DocTypes):**

| Role | read | write | create | delete | report | Notes |
|---|---|---|---|---|---|---|
| Accounts Manager | ✓ | — | — | — | ✓ | Append-only telemetry; the controller helper inserts events. No clerk update/delete. |
| Accounts User | ✓ | — | — | — | ✓ | Same. |
| Auditor (Read Only) *(new role — see Bible)* | ✓ | — | — | — | ✓ | Read access for governance review; **call out as a new role when introduced.** |

`AP Review Event` rows are written by `emit_review_event` (§5.2) which calls `ev.insert(ignore_permissions=False)` so the acting user owns the row but doesn't need an explicit `create` perm gap — **decision to confirm in §8**: insert with `ignore_permissions=True` vs granting `create` to the AP roles. The `AP Capture Rejection Log` child rows inherit the parent capture's permissions (child tables have no independent permission set).

**Status enum reconciliation:** `"Rejected"` already exists in the capture `status` options (`json:162`) — **no enum migration needed** for reject. Reopen restores the prior captured stage by reading the most-recent `Rejected` row's `from_status` from `rejection_log`, so the restore is deterministic, not guessed.

### 5.2 Endpoints

All new server logic goes in `ap_invoice_capture.py` (or a sibling module under `accounts/ap_closed_loop/` that imports the status constants). It follows the existing controller convention exactly: a core `fn(capture: "APInvoiceCapture | str", ..., save: bool = True) -> "APInvoiceCapture"` that accepts str-or-doc (`if isinstance(capture, str): capture = frappe.get_doc("AP Invoice Capture", capture)`, pattern at `:887-888`, `:1330-1331`), plus a thin `@frappe.whitelist()` `_for(capture: str, ...)` wrapper (pattern at `:949-973`, `:1719-1732`).

```python
# Core transitions (str-or-doc, save-toggle)
def reject_capture(
    capture: "APInvoiceCapture | str",
    reason: str,
    actor: str | None = None,
    root_cause_tag: str | None = None,
    save: bool = True,
) -> "APInvoiceCapture": ...

def reopen_capture(
    capture: "APInvoiceCapture | str",
    reason: str,
    actor: str | None = None,
    save: bool = True,
) -> "APInvoiceCapture": ...

# Shared instrumentation primitive — OTHER SPECS IMPORT THIS. Stabilize early.
def emit_review_event(
    capture: "APInvoiceCapture | str",
    *,
    action_taken: str,
    root_cause_tag: str | None = None,
    exception_reason_code: str | None = None,
    fields_changed: dict | None = None,        # serialized to JSON string on write
    time_to_resolve_seconds: int | None = None,
    note: str | None = None,
    clerk: str | None = None,
) -> str:  # returns AP Review Event name
    ...

# Whitelisted wrappers for the form / JS (corrections-style JSON normalization)
@frappe.whitelist()
def reject_capture_for(capture: str, reason: str, root_cause_tag: str | None = None) -> str: ...

@frappe.whitelist()
def reopen_capture_for(capture: str, reason: str) -> str: ...

# Read helper for the form's rejection-trail panel (mirrors get_ap_lifecycle_rows_for)
@frappe.whitelist()
def get_rejection_log_for(capture: str) -> list[dict]: ...
```

**Normalization convention:** the `_for` wrappers mirror `confirm_extracted_fields_for` (`:949-967`) — any dict-bearing arg passed as a JSON string from the client is parsed with `json.loads`; `bool`-ish args (none here) use the `record_manager_decision_for` coercion (`:1727-1728`). `emit_review_event` is **not** whitelisted — it is an internal primitive called from other server functions, never from the client directly.

### 5.3 Logic

**1) `reject_capture` / `reject_capture_for`**
1. Resolve `capture` (str→doc).
2. **Guard — terminal:** if `capture.promotion_status == PROMOTION_STATUS_PROMOTED` → raise `CaptureValidationError` (reuse existing class, `:128`). Rationale: a promoted capture has handed off to the native Purchase Invoice lifecycle; reject-to-vendor is no longer a capture-level action.
3. **Guard — idempotency:** if `capture.status == STATUS_REJECTED` → raise `CaptureValidationError` (already rejected; reopen first). (Recommended default; the no-op-instead-of-raise alternative is §8.)
4. `from_status = capture.status`.
5. Set `capture.status = STATUS_REJECTED`; `capture.action_required = 0`; `capture.action_required_reason = None`. **Note the deliberate divergence:** every other terminal/blocked state sets `action_required = 1`; `Rejected` sets it to `0` because a rejected item is terminal-and-quiet (it drops off the clerk queue until reopened — see §8 and the queue impact on `get_ap_lifecycle_rows`, `:1634`).
6. Persist the reason: `capture.append("rejection_log", {"action": "Rejected", "reason": reason, "from_status": from_status, "to_status": STATUS_REJECTED, "actor": actor or frappe.session.user, "timestamp": now_datetime()})`.
7. Emit **one** `AP Review Event` via `emit_review_event(capture, action_taken="rejected", root_cause_tag=root_cause_tag, note=reason)`.
8. `if save: capture.save()` — so `track_changes` writes the Version row.
9. **validate() interaction (highest risk):** add an early short-circuit at the top of `validate()`'s status-derivation block — `if self.status == STATUS_REJECTED: return` (after `received_at`/source/format hydration, before the `Pending Review`/`Proposed`/`Needs Correction` derivation) — so a saved `Rejected` survives the round-trip and isn't re-derived. Equivalent alternative: add an explicit `Rejected` branch. The reject path is incomplete without this change; it is the single integration point that must be settled before build (§8).

**2) `reopen_capture` / `reopen_capture_for`**
1. Resolve `capture`.
2. **Guard:** allowed only from `capture.status == STATUS_REJECTED` else `CaptureValidationError`.
3. **Deterministic restore:** read the most-recent `rejection_log` row with `action == "Rejected"` and restore `capture.status = row.from_status`. Do **not** hardcode `Pending Review`.
4. Set `action_required` for the restored stage. Default: `action_required = 1` with reason "Reopened for correction" (a reopened item by definition needs work), rather than re-running validate()'s full derivation.
5. Append `{"action": "Reopened", "reason": reason, "from_status": STATUS_REJECTED, "to_status": <restored>, "actor": ..., "timestamp": now_datetime()}`.
6. Emit an `AP Review Event`. **Open decision (§8):** `action_taken` has no `reopened` value. Default = log the reopen **only** in the child table and emit the event with `action_taken="classified_other"` + `note="reopened: <reason>"`; the alternative is to extend the Select vocab with `reopened`.
7. `if save: capture.save()`.

**3) `emit_review_event` (the shared primitive)**
1. Resolve `capture` (accept name or doc; use `.name` for the Link).
2. `ev = frappe.new_doc("AP Review Event")`; set `ev.capture`, `ev.action_taken`, `ev.root_cause_tag`, `ev.exception_reason_code`, `ev.note`.
3. `ev.fields_changed = json.dumps(fields_changed, default=str, sort_keys=True) if fields_changed else None`.
4. `ev.time_to_resolve_seconds = time_to_resolve_seconds` (caller computes; see step below).
5. `ev.clerk = clerk or frappe.session.user`; `ev.created = now_datetime()`.
6. `ev.insert(...)` (permission flag per §5.1 / §8); return `ev.name`.
7. **`time_to_resolve_seconds` source:** there is no clean "review-started" stamp today — `reviewed_at` (`:913`) is set *at* confirm, not at queue entry. Default: compute `(now - capture.creation).total_seconds()` (conflates queue wait with active handling, acceptable for v1 trend signal). Better: add a `review_queue_entered_at` Datetime to the capture stamped when `status` first becomes `Proposed`/`Pending Review` — flagged as a small data dependency in §8.
- **Idempotency:** `emit_review_event` is **not** idempotent and is not meant to be — each clerk action is a distinct event. The "exactly one event per action" guarantee comes from each call site invoking it once on the success branch (not from dedup). The persisted artifact is one `AP Review Event` row; the reject/reopen path additionally persists a `rejection_log` child row + a Version row.

**4) Instrumentation wiring (the actual step-9 gate).** Add an `emit_review_event` call on the success branch of each clerk action. Root-cause tags map to other specs:

| Call site (path:line) | `action_taken` | Default `root_cause_tag` | Owning spec |
|---|---|---|---|
| `confirm_extracted_fields` confirmed branch (`:925-929`) | `field_corrected` or `coding_completed`* | `extraction_miss` | [[04-extraction-confidence-line-items]] |
| `confirm_extracted_fields` needs-correction branch (`:917-924`) | `field_corrected` | `extraction_miss` | [[04-extraction-confidence-line-items]] |
| supplier create/map (the [[05-supplier-resolution]] flow that follows `_match_supplier`, `:975`) | `supplier_created` | `supplier_unmapped` | [[05-supplier-resolution]] |
| `record_manager_decision` reject (`:1355`) — **Stream I only** | `rejected` | `policy_violation` / `vendor_error` | [[11-approval-sod-workflow]] |
| confidence-threshold park (the routing decision in [[09-confidence-routing]]) | `field_corrected` | `confidence_threshold_too_tight` | [[09-confidence-routing]] |
| stream/PO reclassification (`_classify_purchase_reference` `:1005`, `validate_for_purchase_invoice` `:1020`) | `classified_other` | `stream_mistag` / `missing_po` | [[02-intake-stream-tagging]] / [[07-classification-doctype-branching]] / [[08-validation-gates]] |

\* `field_corrected` when `corrections` changed at least one `final_*` value; `coding_completed` when the clerk supplied GL coding (cost center / expense account — a [[06-gl-coding-tax-costcenter]] concern) with no header field change. Distinguishing the two: compare the merged `final_*` against the pre-merge values; if only coding fields changed → `coding_completed`. **Decision to lock (§8):** exact discriminator.

Each call site passes the stream context; Stream R call sites must NOT pass approval/rejection root causes. The helper stays stream-agnostic; gating is at the call site.

**5) Weekly "Top step-9 root causes" report.** Query Report (per citation) under `erpnext/accounts/report/top_step_9_root_causes/`, `ref_doctype: "AP Review Event"`, `is_standard: "Yes"`, `module: "Accounts"`, `report_type: "Query Report"`. Single SQL `GROUP BY root_cause_tag` over `` `tabAP Review Event` `` within a date window using `%(from_date)s` / `%(to_date)s` filter placeholders (citation: "Filters can be used as formatting variables… `%(customer)s`"). Columns: `root_cause_tag`, `event_count`, `pct_of_total`, `distinct_captures`. Escalate to a **Script Report** (`execute(filters)` returning `columns, data, report_summary`, per citation) only if the auto-rate % / "what input change would have eliminated this" derivation needs Python beyond a single SQL — default to Query Report. Optionally register a `weekly` scheduler entry in `hooks.py` (alongside `auto_create_exchange_rate_revaluation_weekly`) to snapshot/email the rollup; default = report-on-demand, no scheduler job in v1 (§8).

**6) Auto-rate Dashboard Chart.** Two charts composed into a Dashboard:
- **Top root causes (bar):** Document-Type source over `AP Review Event`, Chart Type `Group By`, Group By field `root_cause_tag`, Group By Type `Count`.
- **Trend (line):** Document-Type source over `AP Review Event`, Chart Type `Count`, based on `created` (time series).
Plus a Number Card for the auto-rate %. **Re-verify the exact Chart Type / Group By field names against the running site's Dashboard Chart DocType before writing JSON** — the dashboard citation is `verified:false` (§8, risk 4).

### 5.4 Cascade & stream-awareness

This spec adds **no new auto-advance hop** to `_determine_next_step` (`:321-366`). Reject and reopen are explicit clerk actions, never auto-triggered, so the pure state machine is untouched except for one **negative** guard:

- **Exclude `Rejected` from auto-progression.** `_determine_next_step` branches all gate on positive in-progress states (`Pending Review` + `Not Extracted` → OCR; `Confirmed` → validate; etc.). A `Rejected` capture matches none of them, so it already returns `None` (no hop) — but add an explicit early `if self.status == STATUS_REJECTED: return None` at the top of `_determine_next_step` for clarity and to harden against any future positive branch that might otherwise pick up a rejected row. This mirrors `is_payment_blocked` (`:1378`) excluding blocked captures from payment: a `Rejected` capture must never auto-advance and must be excluded from any payment gate ([[12-payment-execution]]).
- **Pause vs auto-advance:** reject → terminal-quiet (`action_required = 0`), pauses permanently until a clerk reopens. Reopen → restores the prior in-progress stage with `action_required = 1`, re-entering the normal cascade pause/advance behavior for that stage.

**Stream R vs Stream I in the cascade:** instrumentation is emitted from clerk-action functions, which sit *off* the auto-progression path (the cascade pauses at exactly these human-decision points — OCR review at `Proposed`, manual promote at `Validated`, manager approval at `Pending Manager`, per `:296-305`). So events fire when a human acts, regardless of stream. The stream split is purely in *which* root causes are valid (Stream R: no approval/rejection causes), enforced at the call site.

### 5.5 Cross-cutting

- **Permissions / SoD:** reject/reopen require write on `AP Invoice Capture` (granted to Accounts User + Accounts Manager today, `json:653-663`). No new role-gate on reject itself in v1 (any clerk may bounce a doc to the vendor); the manager-payment reject stays gated by `frappe.only_for` (`:1336`). `AP Review Event` is append-only telemetry (read-only for clerks). The new `Auditor (Read Only)` role (Bible) gets read on both new DocTypes — **flagged as a new role**.
- **Idempotency (via [[01-foundations-settings-async-idempotency]]):** the reject/reopen transitions are guarded by status preconditions (steps 1.3, 2.2) so a double-click can't create a second `Rejected` row from an already-`Rejected` capture. `emit_review_event` itself is intentionally non-idempotent (one event per action). If [[01-foundations-settings-async-idempotency]] ships an idempotency-key helper, the reject transition may adopt a per-capture-per-action key to coalesce duplicate form submits — optional, low priority.
- **Async / enqueue:** none. Reject/reopen and event emission are synchronous, inside the request — they are cheap DB writes and the clerk needs immediate feedback. The weekly rollup is the only optional async piece (§5.3 step 5).
- **Observability emission:** this spec **is** the observability sink. `emit_review_event` is the shared primitive [[04-extraction-confidence-line-items]], [[05-supplier-resolution]], [[07-classification-doctype-branching]], [[08-validation-gates]], [[09-confidence-routing]], and [[11-approval-sod-workflow]] all import and call. Its signature (§5.2) must stabilize before those specs build their call sites.
- **Reconciliation with [[11-approval-sod-workflow]]'s Reject (distinct doctypes, distinct lifecycle stages — NOT duplication).** This spec's `reject_capture` operates at the **CAPTURE level**: it bounces a capture back to the vendor **BEFORE a Purchase Invoice exists**. The capture is a **pre-doc staging record** that has **no `workflow_state` field** and is not under a native Workflow — so its reject is a controller transition writing `status = Rejected` + a `rejection_log` row (§5.3). By contrast, spec 11's Reject is a **native Workflow transition on the PURCHASE INVOICE** — a post-promotion approval reject that emits its **own** `AP Review Event` (`action_taken="rejected"`, `policy_violation`/`vendor_error`) from the manager-approval path (`record_manager_decision`, `:1355`, already wired in §5.3 step 4 table). These are **DISTINCT doctypes at DISTINCT lifecycle stages** (capture pre-promotion vs PI post-promotion), so they are **not duplication**. The one invariant the two paths must hold: **they must NOT double-emit an `AP Review Event` for a single logical action** — a capture-level reject emits exactly one event from `reject_capture`; a PI-level Workflow reject emits exactly one event from the manager-decision path; nothing emits from both for the same act. **Recommendation:** keep the **capture as a non-Workflow staging record** for v1 — native Workflow fits the Purchase Invoice (a real submittable accounting doc), **not** the pre-doc capture. (Reinforces §3 "the document-level Rejected state is reachable only by a direct DB write today" — this spec adds the sanctioned capture-level path; spec 11 owns the PI-level one.)
- **Queue rationale — status-filtered list view, NOT native `ToDo`/`_assign`.** The AP review queue (`get_ap_lifecycle_rows`, `:1634`; `get_manager_approval_queue`, `:1657`) is intentionally a **STATUS-FILTERED LIST VIEW** (filter on `status` / `approval_status` / `action_required`), **not** a per-user work assignment. Native `ToDo` / `_assign` is **per-user** (it assigns a specific document to a specific user's to-do list); the AP queue is a team-wide, status-driven worklist that any eligible clerk pulls from — there is no single assignee. Keeping the existing `get_*_queue` readers (rather than re-modelling the queue on native `ToDo` assignment) matches that semantics and avoids forcing a per-user assignment the process does not have. (Closes the "why not `ToDo`" question.)

## 6. Acceptance criteria

- **AC-10-1 (reject positive):** Given a capture at `status` ∈ {`Proposed`, `Needs Correction`}, calling `reject_capture(capture, reason="bad scan")` sets `status == "Rejected"`, `action_required == 0`, appends exactly one `rejection_log` row with `action == "Rejected"`, `from_status` == the pre-reject status, `actor == frappe.session.user`, and emits exactly one `AP Review Event` with `action_taken == "rejected"`.
- **AC-10-2 (reject blocked when promoted):** Given `promotion_status == "Promoted"`, `reject_capture` raises `CaptureValidationError` and writes no `rejection_log` row and no `AP Review Event`.
- **AC-10-3 (reject idempotency):** Calling `reject_capture` on an already-`Rejected` capture raises `CaptureValidationError` (default) — no second `Rejected` row is appended.
- **AC-10-4 (Rejected survives save):** After `reject_capture(..., save=True)`, reloading the capture (`frappe.get_doc`) still shows `status == "Rejected"` — `validate()` does not clobber it. (Guards the highest-risk integration point.)
- **AC-10-5 (reject audit):** A `Version` row is written for the capture on reject (because `track_changes == 1` and the mutation went through `save()`, not `db_set`).
- **AC-10-6 (reopen positive):** Given a `Rejected` capture whose latest `Rejected` row has `from_status == "Needs Correction"`, `reopen_capture(capture, reason="vendor resent")` restores `status == "Needs Correction"`, appends a `Reopened` row, and sets `action_required == 1`.
- **AC-10-7 (reopen blocked when not rejected):** `reopen_capture` on a non-`Rejected` capture raises `CaptureValidationError`.
- **AC-10-8 (trail preserved across cycles):** reject → reopen → reject again yields two `Rejected` rows + one `Reopened` row in chronological order in `rejection_log`.
- **AC-10-9 (emit each action_taken):** `emit_review_event` persists a row for each of the five `action_taken` values and each of the eight `root_cause_tag` values; `clerk`/`created` default when omitted; returns a valid `AP Review Event` name; the row links to the capture.
- **AC-10-10 (emit Select validation):** `emit_review_event` with an `action_taken` or `root_cause_tag` outside the fixed vocabulary raises a validation error on insert.
- **AC-10-11 (emit fields_changed round-trip):** A dict passed as `fields_changed` is stored as JSON and `json.loads` round-trips it; `time_to_resolve_seconds` is stored as an Int.
- **AC-10-12 (confirm emits one event):** `confirm_extracted_fields_for(capture, corrections={...})` emits exactly one `AP Review Event` with `action_taken` ∈ {`field_corrected`, `coding_completed`} and the corrected logical field present in `fields_changed`.
- **AC-10-13 (manager reject emits one event):** `record_manager_decision(approve=False)` emits exactly one `AP Review Event` with `action_taken == "rejected"`.
- **AC-10-14 (Stream R lighter):** A Stream R capture path does **not** emit any `AP Review Event` carrying an approval/rejection root cause (`policy_violation`, `vendor_error`); event count/shape differs from the equivalent Stream I path.
- **AC-10-15 (Rejected excluded from cascade):** `_determine_next_step` returns `None` for a `Rejected` capture (no auto-hop); a `Rejected` capture is excluded from any payment gate.
- **AC-10-16 (report renders):** The "Top step-9 root causes" Query Report executes against `tabAP Review Event`, returns rows grouped by `root_cause_tag` with `event_count` and `pct_of_total`, and its JSON declares `is_standard == "Yes"` and `ref_doctype == "AP Review Event"`.
- **AC-10-17 (chart groups by root_cause_tag):** The auto-rate Dashboard Chart sources `AP Review Event` and groups/counts by `root_cause_tag`.

## 7. Tests

### 7.1 Automated

Convention (from `test_ap_invoice_capture.py:8,144`): `from frappe.tests import IntegrationTestCase`, one class per concern, `tearDown` → `frappe.db.rollback()`, constants imported from the controller. Structural template for reject/reopen audit: the existing `test_manager_reject_records_audit_and_blocks_payment` test.

**Module:** `erpnext.accounts.doctype.ap_invoice_capture.test_ap_invoice_capture` (new `TestAPReviewGate` class) — covers reject/reopen + instrumentation wiring.
**Module:** `erpnext.accounts.doctype.ap_review_event.test_ap_review_event` (`test_ap_review_event.py`) — covers `emit_review_event` + the DocType.

`reject_capture`:
- POSITIVE — AC-10-1: status `Rejected`, `action_required == 0`, one `rejection_log` row, `from_status` preserved, `actor` == session user, one `AP Review Event`.
- NEGATIVE — AC-10-2: `promotion_status == "Promoted"` → `assertRaises(CaptureValidationError)`; assert no child row and no event.
- NEGATIVE — AC-10-3: second reject on a `Rejected` capture → `assertRaises`.
- EDGE — AC-10-4: reject from each non-terminal status (`Pending Review`, `Unsupported`, `Proposed`, `Needs Correction`, `Confirmed`) succeeds; `reload()` then assert `status` still `Rejected`.
- AUDIT — AC-10-5: assert a `Version` row exists for the capture capturing the status change (query `tabVersion` by `ref_doctype`/`docname`).

`reopen_capture`:
- POSITIVE — AC-10-6: restore to recorded `from_status`, `Reopened` row appended, `action_required == 1`.
- NEGATIVE — AC-10-7: reopen on non-`Rejected` → `assertRaises(CaptureValidationError)`.
- EDGE — AC-10-8: reject → reopen → reject → two `Rejected` + one `Reopened` rows, ordered.

`emit_review_event`:
- POSITIVE — AC-10-9: each `action_taken` value and each `root_cause_tag` value persists; `clerk`/`created` defaulted; returns a valid name; row linked to the capture.
- NEGATIVE — AC-10-10: invalid `root_cause_tag` / `action_taken` → `assertRaises` (Select validation on insert).
- EDGE — AC-10-11: `fields_changed` JSON round-trips; `time_to_resolve_seconds` Int stored; two calls yield two distinct events.

Instrumentation:
- POSITIVE — AC-10-12: `confirm_extracted_fields_for(corrections=...)` emits exactly one event with `action_taken` ∈ {`field_corrected`, `coding_completed`} and the corrected field in `fields_changed`.
- POSITIVE — AC-10-13: `record_manager_decision(approve=False)` emits one event `action_taken == "rejected"`.
- STREAM — AC-10-14: a Stream R capture path emits no approval/rejection-root-cause event; assert event count/shape differs from the Stream I path.
- CASCADE — AC-10-15: `_determine_next_step` returns `None` for a `Rejected` capture.

Report/chart smoke:
- AC-10-16: load the Query Report via `frappe.get_doc("Report", "Top step-9 root causes")` and run it (e.g. `frappe.desk.query_report.run`); assert rows grouped by `root_cause_tag`; assert `is_standard`/`ref_doctype` on the JSON.
- AC-10-17: load the Dashboard Chart doc; assert source `AP Review Event` + group/count by `root_cause_tag`.

Run locally:
```
bench --site <site> run-tests --module erpnext.accounts.doctype.ap_invoice_capture.test_ap_invoice_capture
bench --site <site> run-tests --module erpnext.accounts.doctype.ap_review_event.test_ap_review_event
```
Confirm green before declaring done (per CLAUDE.md "Automated tests").

### 7.2 Clean-room test plan

**`test/testplans/ap-review-event-gate.md`** — scope: create a capture → correct a field via the form (one `AP Review Event` written, verified in DB) → reject-back-to-vendor (status `Rejected`, `rejection_log` child row) → reopen (status restored, trail preserved) → confirm the weekly "Top step-9 root causes" report renders and the auto-rate Dashboard Chart groups by `root_cause_tag`. Must include the required CLAUDE.md sections (Feature under test, Branch/commit, Environment setup, Test data prerequisites, Numbered test cases incl. the promoted-reject-blocked negative case, Cleanup/rollback, Pass/fail summary template).

**`test/testplans/ap-capture-reject-reopen.md`** *(optional companion)* — reject/reopen-only runbook (no report/chart) for fast regression of just the transition pair.

### 7.3 UI testing (Playwright MCP)
Browser-driven verification of the desk UI this slice adds, via the **Playwright MCP** server. These are the UI steps of the §7.2 clean-room runbook.
- **Prereq:** Playwright MCP per `test/testplans/BROWSER-TESTING-SETUP.md` (`claude mcp list` must list `playwright`; restart after registering). `.mcp.json` / `.playwright-mcp/` gitignored.
- **Evidence:** screenshots to `test/testplans/screenshots/ap-review-event-gate/<name>.png` (committed; pass as `filename`).
- **Source of truth stays the DB:** after every UI write, verify via `bench --site <site> mariadb` / `bench … execute`, then delete UI-created data.

**Scenarios** (`route → action → expected UI → DB assertion`):
- On a capture in review, click "Reject" → a reason field + the fixed `root_cause_tag` vocabulary picker appears; submit → status `Rejected`, an `AP Capture Rejection Log` row + an `AP Review Event` are written; screenshot the dialog and the resulting state → DB-assert the rejection-log row and the `AP Review Event` row (with `root_cause_tag`, `action_taken`).
- Click "Reopen" on the rejected capture → it returns to the prior stage, a "Reopened" log row is added; screenshot → DB-assert status reverted + log row.
- Open the weekly "Top step-9 root causes" report at `/app/query-report/<report-name>` → it renders grouped counts by `root_cause_tag`; screenshot.
- Open the auto-rate Dashboard Chart (the Group-By chart) on the workspace/dashboard → it renders; screenshot.

**Not browser-testable in this slice** (covered by §7.1/§7.2): the `emit_review_event` call-site wiring across other specs (each verified in its own §7.1).

## 8. Open decisions

1. **`validate()` Rejected handling (MUST lock before build — highest risk).** Options: (a) early short-circuit `if self.status == STATUS_REJECTED: return` in the status block; (b) explicit `Rejected` branch that sets `action_required = 0`. **Recommended: (a)** — smallest surface, least chance of re-deriving. Owner: build engineer + repo owner (rsmith). Lock: at the start of implementation; the reject path is non-functional without it.
2. **`reopened` in the `action_taken` vocabulary.** Options: (a) keep the five-value enum, log reopen only in `rejection_log`, emit the event as `classified_other` + note; (b) add `reopened` to the Select. The plan lists the enum as fixed → **Recommended: (a)**. Owner: repo owner. Lock: before `AP Review Event` JSON is written (changing a shipped Select option is a migration).
3. **`action_required = 0` on Rejected (queue-behavior divergence).** Every other terminal/blocked state sets `action_required = 1`; Rejected sets `0` so it drops off the clerk queue (`get_ap_lifecycle_rows`, `:1634`). Options: (a) `0` (terminal-quiet, recommended — rejected items shouldn't nag); (b) `1` with reason "Rejected — awaiting reopen". **Recommended: (a)**. Owner: AP process owner (Bryan). Lock: before build (affects queue/report semantics).
4. **Dashboard Chart field names (version-verify).** Branch is `russ/migrateToV16` but mandated docs are v15; the dashboard citation is `verified:false`. Options: (a) re-verify Chart Type / Group By Based On / Group By Type field names against the running v16 site's Dashboard Chart DocType, then write JSON; (b) build the report first and source the chart from the report. **Recommended: (a)** then fall back to (b) if field names differ. Owner: build engineer. Lock: before the chart JSON is committed.
5. **`fields_changed` fieldtype — Small Text (JSON string) vs native JSON.** Options: (a) Small Text holding a `json.dumps` string (portable across v15/v16, recommended); (b) native `JSON` fieldtype (richer querying, verify availability/behavior on the target version first). **Recommended: (a)**. Owner: build engineer. Lock: before `AP Review Event` JSON is written.
6. **`emit_review_event` insert permission.** Options: (a) `ev.insert(ignore_permissions=True)` so clerks needn't hold `create` on `AP Review Event` (keeps the DocType clerk-read-only while the controller writes); (b) grant `create` to Accounts User/Manager and insert with `ignore_permissions=False`. **Recommended: (a)** — telemetry stays append-only-by-controller, not hand-creatable. Owner: build engineer. Lock: before permissions are finalized in the JSON.
7. **`field_corrected` vs `coding_completed` discriminator.** Options: (a) compare merged `final_*` header values against pre-merge — any header change → `field_corrected`, else if GL coding fields changed → `coding_completed`; (b) explicit caller-passed `action_taken`. **Recommended: (a)** for the auto-instrumented path, (b) available as override. Owner: build engineer. Lock: when wiring `confirm_extracted_fields`.
8. **`review_queue_entered_at` timestamp for accurate `time_to_resolve_seconds`.** Options: (a) derive from `creation` (conflates queue wait + handling, recommended for v1); (b) add a `review_queue_entered_at` Datetime stamped when `status` first hits `Proposed`/`Pending Review`. **Recommended: (a)** now, (b) as a fast-follow if the metric proves noisy. Owner: AP process owner. Lock: not blocking v1.
9. **Weekly rollup scheduler job vs report-on-demand.** Options: (a) report-on-demand only (recommended v1); (b) register a `weekly` `hooks.py` job that snapshots/emails the rollup. **Recommended: (a)**. Owner: build engineer. Lock: not blocking v1.
10. **Query Report vs Script Report for the weekly report.** Options: (a) Query Report (single SQL GROUP BY, recommended — counts + `pct_of_total` are expressible in SQL); (b) Script Report if the "what input change would have eliminated this" derivation needs Python. **Recommended: (a)**, escalate only on demonstrated need. Owner: build engineer. Lock: when the report is built.

## 9. Dependencies & sequencing

**Must land first:**
- The `AP Invoice Capture` controller + status enum (this same file) — already shipped; this spec extends it.
- [[01-foundations-settings-async-idempotency]] — for the idempotency-key helper (optional adoption by reject) and the shared async/settings conventions. Soft dependency: this spec works without it but should align with its primitives.

**This spec unblocks (it is the instrumentation sink they feed):**
- [[04-extraction-confidence-line-items]] → `extraction_miss`
- [[05-supplier-resolution]] → `supplier_unmapped`
- [[09-confidence-routing]] → `confidence_threshold_too_tight` (and this spec's report is what tells spec 09 whether to loosen a threshold)
- [[02-intake-stream-tagging]] / [[07-classification-doctype-branching]] → `stream_mistag`
- [[08-validation-gates]] → `missing_po` (this spec's report is the explicit feedback loop quantifying whether adopting spec 08's PO upstream control is worth it)
- [[11-approval-sod-workflow]] → `rejected` (`policy_violation` / `vendor_error`), Stream I only
- [[12-payment-execution]] — consumes the `Rejected` status as a payment-exclusion signal (mirrors `is_payment_blocked`, `:1378`)

`emit_review_event` is a **shared primitive** other specs import — its signature (§5.2) must be defined and stabilized **early** so downstream specs can wire their call sites without churn. Sequence this spec's `emit_review_event` + `AP Review Event` DocType ahead of specs 04/05/08/09/11's instrumentation work.

**Estimated size (per IMPLEMENTATION-PLAN units):** **L**. Two new DocTypes (one child, one standalone log) + one new capture field + three new controller functions + the `validate()`/`_determine_next_step` integration + the cross-spec instrumentation seam + one Query Report + one Dashboard Chart + two test modules + two clean-room test plans. The cross-cutting instrumentation seam (touching six other specs' call sites) is the bulk of the integration cost, but most of that lands in the consuming specs — the core deliverable here (reject/reopen + `emit_review_event` + `AP Review Event` + report/chart) is solidly L, not XL.
