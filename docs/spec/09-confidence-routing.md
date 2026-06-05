---
spec: 09-confidence-routing
title: Confidence-Based Routing (Auto-Post vs Review Queue)
plan_step: Step 8 — Confidence-Based Routing on a combined signal of per-field confidence + validation flags
stream: both
status: Done
depends_on: [04-extraction-confidence-line-items, 08-validation-gates]
related: [00-overview, 01-foundations-settings-async-idempotency, 06-gl-coding-tax-costcenter, 07-classification-doctype-branching, 10-ap-review-observability, 11-approval-sod-workflow, 12-payment-execution]
---

# 09 — Confidence-Based Routing (Auto-Post vs Review Queue)
> _Revised 2026-05-31: applied native-vs-custom review findings; added Playwright UI test plan (§7.3)._
> _Revised 2026-06-02: re-visioned automation-first ([[00-overview]] "Guiding principle")._

> [!abstract] Automation-first stance
> This spec is the **purest expression of the north star** ([[00-overview]] "Guiding principle"): auto-advance the clean + confident + in-policy case with no human touch, and escalate **only** the low-confidence or flagged exception. Confidence routing is not one decision at one seam — it is the general **"auto-advance unless doubtful" engine** (`_evaluate_routing_signals`), and its reach should extend to **every** seam where the cascade would otherwise pause for a human. There are two such seams: the **approval seam** (already shipped — over/under threshold, clean vs flagged → auto-approve vs manager vs review) and, newly, the **OCR-confirm seam** (planned — auto-confirm the OCR proposal instead of pausing at `Proposed`, owned jointly with [[04-extraction-confidence-line-items]]). Applying the same evaluator one step earlier, at the OCR-confirm seam, is the **single highest-leverage automation gap in the whole spec set** ([[00-overview]] "Automation-first doctrine", #9/#4): today every capture needs a human once just to confirm a clean OCR read; with auto-confirm, only the doubtful ones do. **The shipped approval-routing behavior below is unchanged** — this extension reuses the same logic earlier in the cascade; it does not alter the approval seam.

## 1. Summary

This spec replaces the fork's **amount-only** approval gate (`request_approval` in `document_capture.py:1249`, which compares `final_total_amount` against a hard-coded `1000.0`) with a **combined-signal routing evaluator** over three axes: (1) amount vs a configurable `auto_post_amount_threshold` setting, (2) all mandatory-field confidences `>=` threshold (from the [[04-extraction-confidence-line-items]] `Document Capture Confidence` child table), and (3) zero open validation flags (from [[08-validation-gates]]). It implements **plan Step 8** and serves **both streams**, but the auto-post outcome diverges: a clean+confident **Stream R** capture auto-posts a Journal Entry with **no approval**, while a clean+confident **Stream I** capture is `Auto Approved` and still gated by the [[11-approval-sod-workflow]] approval workflow. Current-state delta: routing today is one boolean (`amount <= 1000.0`) with no confidence input, no flag input, no stream-awareness, and no measurement hook — this spec makes "below threshold AND no flags → auto-post; any failure → review queue with the specific failing field/flag surfaced" the formalized decision, and emits an [[10-ap-review-observability]] `AP Review Event` on every route-to-review.

## 2. Plan alignment

`docs/planning/workflow-v2-plan.md` **Step 8** (lines 57-62):

> **8. Confidence-Based Routing (Auto-Post vs. Review Queue)**
> Documents fork based on a combined signal of per-field confidence and validation flags:
> - **All fields above the confidence threshold and no validation flags** → auto-submitted as a draft to the appropriate doctype, queued for approval if over threshold.
> - **Any field below threshold or any validation flag raised** → routed to the AP review queue with the exception reason surfaced (low vendor confidence, total mismatch, duplicate suspect, unrecognized supplier, etc.).
> This routing is what makes the workflow scalable. Without it, every document needs a human, and the throughput benefit of OCR is lost.

Control-Summary row this spec owns (`workflow-v2-plan.md` §"Control Summary"):

| Control | Where it lives | Why it matters |
|---|---|---|
| Confidence-based routing | Step 8 | Scales throughput; isolates exceptions |

It also operationalizes two Key Design Principles: "**Branching, not linear.**" (the confidence-routed branch — auto-post vs review queue — is one of the three mandated forks) and "**Per-field confidence, not document-level.**" (the evaluator reads independent per-field scores, never a single document score).

**Stream R vs Stream I divergence here (the load-bearing distinction):**

- **Stream R** (already-paid card/cash receipt): the money already moved, so there is **nothing to authorize**. A clean+confident Stream R capture auto-posts a **Journal Entry** (built by [[07-classification-doctype-branching]]) with **no `Pending Manager` state, no manager decision, no approval gate**. A flagged/low-confidence Stream R capture still routes to the **same** review queue (the reconciliation must be correct even though no payment is pending).
- **Stream I** (unpaid payable): a clean+confident capture becomes `Auto Approved` and is **still entered into the [[11-approval-sod-workflow]] approval workflow** — "auto-post" here means "auto-advance to the approval gate", **not** an unconditional submit-and-pay. A flagged/low-confidence Stream I capture routes to the review queue first; after a clerk clears the flags, a sanctioned re-route advances it to the approval workflow.
- **Plan-excerpt correction (trust the code over the plan):** the plan's "queued for approval if over threshold" phrasing implies approval is only for over-threshold items. The shipped code routes **at-or-below threshold → auto-approve** and **over threshold → Pending Manager** (`document_capture.py:1291-1314`). This spec preserves that: the confidence/flag axes gate *whether the item can auto-advance at all*; the amount axis gates *which auto-advance lane* (auto-approve vs manager). See the decision matrix in §5.3.

## 3. Current state

All routing logic is in `erpnext/accounts/doctype/document_capture/document_capture.py`. Verified against the file on branch `russ/migrateToV16` (frappe `16.18.3`, erpnext `16.20.0`):

- **Threshold is hard-coded.** `AUTO_APPROVAL_THRESHOLD_DEFAULT = 1000.0` (`:78`). `_resolve_approval_threshold(threshold, source)` (`:1243-1246`) returns that constant when `threshold is None`; **there is no `auto_post_amount_threshold` settings field anywhere**. The `AP Closed Loop Settings` Single carries OCR fields + promote defaults; its only confidence-ish field is `ocr_confidence_threshold` (used at extraction time, `:745`), not a routing/auto-post threshold.
- **`request_approval(capture, threshold=None, source=None, actor=None, approver_role=None, save=True)`** (`:1249-1318`) is the **single routing decision**. Guards raise `CaptureApprovalError` (a `frappe.ValidationError` subclass, `:136`): `validation_status == "Validated"` (`:1267`), `promotion_status == "Promoted"` AND `purchase_invoice` set (`:1274`), `approval_status` empty/`Not Required` (`:1278`). Decision is purely `amount = float(capture.final_total_amount or 0.0)` vs `resolved_threshold`: `amount <= resolved_threshold` → `APPROVAL_STATUS_AUTO_APPROVED` + `payment_readiness = Ready` + `action_required = 0` + `decision_by`/`decision_at` set (`:1291-1302`); else → `APPROVAL_STATUS_PENDING_MANAGER` + `assigned_approver_role = "Accounts Manager"` + `payment_readiness = Not Ready` + `action_required = 1` (`:1304-1314`). It writes `routing_reason` (SmallText) in both branches.
- **Approval status enum** (`:67-71`): `Not Required` / `Auto Approved` / `Pending Manager` / `Manager Approved` / `Rejected`. There is **NO `Auto Posted` value** — the matrix's "Auto Posted" concept must be either a new enum value or expressed via `Auto Approved` + a posted artifact (open decision D-1). The Select options live in the DocType JSON (mirrored in the `DF.Literal` at `:210-216`).
- **Cascade routes only when NOT flagged.** `_determine_next_step` (`:321-366`) Step 3 (`:350-355`) enqueues `request_approval_for` **only** when `promotion_status == "Promoted"` AND `purchase_invoice` set AND `approval_status in (None, "Not Required")`. A blocked capture never reaches that branch: `validate_for_purchase_invoice` (`:1020-1102`) sets `validation_status = Blocked` + `validation_result` + `action_required_reason = "Validation blocked: {issues}"` (`:1084-1089`) when any mandatory field is missing or the supplier is unknown/ambiguous, and never promotes — so the cascade simply stalls with no Step-3 match. **Today "flagged" items already never auto-post; they silently park.** Spec 09's job is to *formalize and enrich* this (name the failing field/flag, emit a Review Event) instead of leaving a silent stall.
- **No confidence on the capture.** `confidence` appears only at extraction (`:745`, the `ocr_confidence_threshold` config). There is **no `Document Capture Confidence` child table and no per-field confidence persisted** — [[04-extraction-confidence-line-items]] adds it (`field_confidences` Table → `Document Capture Confidence`, rows `field_name`/`confidence`/`is_above_threshold`/`score_source`). **Hard dependency.**
- **No `stream` field.** Grep for `stream` / `journal_entry` returns nothing in the controller — [[02-intake-stream-tagging]] adds `stream`, and [[07-classification-doctype-branching]] adds the Journal Entry posting path. **Hard dependency.**
- **Validation "flags" are not itemized.** Today only `validation_status` (`Validated`/`Blocked`/`Not Validated`) + a joined `validation_result` SmallText exist (`:1084-1094`). [[08-validation-gates]] surfaces an itemized open-flag count/list; the evaluator's "zero open flags" = `validation_status == Validated` AND no open spec-08 flags. **Hard dependency.**
- **`AP Review Event` does not exist.** [[10-ap-review-observability]] adds it. **Required for the measurement hook.**
- **Queues already exist (reuse).** `get_ap_lifecycle_rows()` (`:1634-1654`, returns name/status/action_required/action_required_reason/validation_status/approval_status/payment_readiness/...) and `get_manager_approval_queue()` (`:1657-1674`, filters `approval_status == "Pending Manager"`, returns routing_reason/assigned_approver_role/final_supplier/final_total_amount/...). Whitelisted via `*_for` wrappers (`:1752-1759`).
- **`MANDATORY_HEADER_FIELDS`** (`:101-107`): the five `(logical, proposed_field, final_field)` triples — `supplier`, `supplier_invoice_no`, `invoice_date`, `total_amount`, `currency`. This is exactly the set whose per-field confidence the evaluator checks (keyed by the logical name, matching the [[04-extraction-confidence-line-items]] `field_name` header keys).
- **Entrypoint + cascade callers.** `request_approval_for(capture, threshold=None, source=None)` (`:1705-1716`) is the whitelisted entrypoint; the cascade Step 3 calls it post-promotion (`:355`). `record_manager_decision` (`:1321-1362`, gated `frappe.only_for(...)` at `:1336`), `is_ready_for_payment` (`:1365-1375`), `is_payment_blocked` (`:1378-1385`) feed mock-payment issuance `issue_mock_payment` (`:1426`).

**Correction to the brief:** none material. Every line reference in the research brief was confirmed against the code. One precision note: the brief says the over-threshold path sets `action_required 1` "(regression of current behavior, line 1304)" — confirmed, but note `:1304` is the *status* assignment; `action_required = 1` is set at `:1313`. The two-line span `:1304-1314` is the full over-threshold branch.

## 4. Upstream grounding

All four citations were re-verified against the **installed** frappe `16.18.3` on this bench (the CLAUDE.md grounding rule points at the v15 docs; the runtime is v16 — signatures below were checked in the v16 source and are compatible, see risk note in §8 D-5).

| URL | Confirms | Verified signature / quote |
|---|---|---|
| https://docs.frappe.io/framework/v15/user/en/desk/scripting/server-script | Server Script `Script Type` is only `"Document Event"` or `"API"`; the Document Event dropdown is the standard lifecycle set (`Before Validate`, `Before Save`, `Before Submit`, `After Submit`, ...). **There is no first-class "routing decision" script type** — combined-signal routing belongs in the DocType controller (`request_approval`), invoked via whitelisted methods, matching the existing fork pattern, NOT in a Server Script. | Quote: `Script Type "API"`; Document Event types: `Before Validate, Before Save, Before Submit, After Submit ...` |
| https://docs.frappe.io/framework/v15/user/en/api/database | Canonical read APIs for the evaluator: `frappe.db.get_value(doctype, name|filters, fieldname[, as_dict=1])`; `frappe.db.get_single_value(doctype, fieldname)` for a Single doctype field (used for the new `auto_post_amount_threshold` on `AP Closed Loop Settings`); `frappe.db.get_all(doctype, filters, fields, order_by, ...)` for record lists (the pattern `get_manager_approval_queue` already uses). | Quote: `frappe.db.get_value(doctype, name, fieldname)` ... "Returns a document's field value or a list of values." `frappe.db.get_single_value(doctype, fieldname)` ... "a field value from a Single DocType." |
| https://github.com/frappe/frappe/blob/version-16/frappe/model/document.py (local `apps/frappe/frappe/model/document.py:1154`, frappe `16.18.3`) | Reading the spec-04 confidence child table from the in-memory capture needs **no separate DB query** when the doc is loaded. `Document.get_all_children(parenttype=None, *, include_computed=False) -> list[Document]` returns all child rows from Table-type fields; `self.get("field_confidences")` returns the child-table field as a list directly. | Verified locally: `def get_all_children(self, parenttype=None, *, include_computed=False) -> list["Document"]:` docstring "Return all child documents from **Table** type fields in a list. Excludes computed tables by default ...". (v16 adds the `include_computed` keyword; default excludes computed tables — correct for `field_confidences`.) |
| https://github.com/frappe/frappe/blob/version-16/frappe/database/database.py (local `apps/frappe/frappe/database/database.py:878`, frappe `16.18.3`) | Exact v16 signature for pulling the new `auto_post_amount_threshold` from `AP Closed Loop Settings` inside `_resolve_approval_threshold`. Cache-by-default (`cache=True`) matches the `_coalesce_defaults` settings-read pattern. | Verified locally: `def get_single_value(self, doctype, fieldname, cache=True, *, debug=False, for_update=False, run=True, ...):` — "Get property of Single DocType. Cache locally by default." |
| https://github.com/frappe/frappe/blob/version-16/frappe/__init__.py (local `apps/frappe/frappe/__init__.py:530`) | Role-gate primitive for SoD touchpoints reused from the existing controller (`frappe.only_for` at `document_capture.py:1336`, `:1441`). | Verified locally: `def only_for(roles: list[str] | tuple[str] | str, message=False):` |

## 5. Design

### 5.1 Data model

All on `Document Capture` unless noted. The routing axes consume fields **owned by other specs** ([[04-extraction-confidence-line-items]], [[08-validation-gates]], [[02-intake-stream-tagging]]); this spec adds only one settings field and reuses existing capture fields.

**(A) `AP Closed Loop Settings` (Single) — one new field, in a new section.**

| fieldname | fieldtype | options / default | purpose |
|---|---|---|---|
| `routing_section` | Section Break | label "Routing / Auto-Post" | Groups the routing config (sits after the OCR section). |
| `auto_post_amount_threshold` | Currency | default `1000.0`; precision 2 | Replaces the hard-coded `AUTO_APPROVAL_THRESHOLD_DEFAULT = 1000.0` (`document_capture.py:78`). Read via `frappe.db.get_single_value("AP Closed Loop Settings", "auto_post_amount_threshold")` with the constant as a **code-level fallback only** when the settings doctype/field is absent (mirror the `try/except` in `_coalesce_defaults`, `:1130-1137`). |

`get_ocr_config()` (or a sibling `get_routing_config()`) on `ap_closed_loop_settings.py` SHOULD surface `auto_post_amount_threshold` so the evaluator has a single config accessor. Recommend a new `get_routing_config()` returning `{"auto_post_amount_threshold": float, "per_field_confidence_threshold": float, "field_thresholds": dict}` that composes the spec-04 confidence keys — keeps `get_ocr_config` focused on extraction. (Decision D-2.)

**(B) Consumed from [[04-extraction-confidence-line-items]] (NOT created here — declare the dependency):**

| fieldname | fieldtype | owner | how the evaluator uses it |
|---|---|---|---|
| `field_confidences` | Table → `Document Capture Confidence` | spec 04 | Parent Table field on the capture. Read in-memory via `self.get("field_confidences")` / `get_all_children`. |
| (child) `field_name` | Data | spec 04 | Logical key. Header rows are exactly the `MANDATORY_HEADER_FIELDS` logical names (`supplier` / `supplier_invoice_no` / `invoice_date` / `total_amount` / `currency`). |
| (child) `confidence` | Float (0..1) | spec 04 | The numeric score the evaluator compares to the field threshold. |
| (child) `is_above_threshold` | Check | spec 04 | Pre-computed by spec 04's `_resolve_above`. The evaluator MAY read this directly (preferred — single source of truth) rather than re-deriving the comparison. |

**(C) Consumed from [[08-validation-gates]] (NOT created here):** an itemized open-flag count/list. Until spec 08 lands, the evaluator falls back to the scalar `validation_status == "Validated"` (today's only signal). The "zero open validation flags" axis = `validation_status == Validated` AND `open_flag_count == 0` (spec-08 field name TBD by spec 08; the evaluator reads whatever spec 08 exposes).

**(D) Consumed from [[02-intake-stream-tagging]] (NOT created here):** `stream` (Select, options e.g. `Stream I` / `Stream R`). Drives the Stream-R-no-approval branch in §5.4. Until spec 02 lands, the evaluator treats an unset `stream` as `Stream I` (fail-safe: invoices get the full approval load, never auto-post receipts-style).

**(E) Reused capture fields (already exist — only the *text* is enriched):**

| fieldname | fieldtype | line | enrichment |
|---|---|---|---|
| `routing_reason` | SmallText | `:219` | Now names the **specific** failing field/flag, e.g. `"Routed to review: confidence(invoice_date)=0.62 < 0.80"` or `"Routed to review: open flag 'Supplier bank changed since last payment'"`. |
| `action_required_reason` | Data | `:154` | What the queues surface; set to the same human reason on the review branch. |
| `approval_threshold` / `approval_threshold_source` | Float / Data | `:217-218` | `approval_threshold` now records the resolved `auto_post_amount_threshold`; `approval_threshold_source` records `ap-closed-loop-settings` / `explicit-override` / `ap-approval-v1` (constant fallback). |
| `approval_status` | Select | `:210-216` | Enum unchanged unless D-1 adds `Auto Posted`. |
| `payment_readiness` | Select | `:224` | `Ready for Payment` only when the matrix yields a clean auto-advance (Stream I) — Stream R clean+confident leaves payment readiness `Not Ready`/`Not Required` because there is no payment leg (open decision D-3). |

**Permissions:** unchanged from today — `request_approval` is not directly role-gated (the manager *decision* is, at `:1336`). The evaluator is pure read + write-back on the capture the cascade already owns. SoD enforcement is [[11-approval-sod-workflow]]'s job; this spec must NOT auto-approve a Stream I capture past the approval gate (§5.4).

### 5.2 Endpoints

Keep the existing whitelisted shape so both the cascade and the manual button get **identical** routing. The evaluator runs **inside** `request_approval`, not as a new endpoint.

```python
# erpnext/accounts/doctype/document_capture/document_capture.py

# EXISTING — signature unchanged; body extended (§5.3).
def request_approval(
    capture: "APInvoiceCapture | str",
    threshold: float | None = None,
    source: str | None = None,
    actor: str | None = None,
    approver_role: str | None = None,
    save: bool = True,
) -> "APInvoiceCapture": ...

# EXISTING whitelisted entrypoint — unchanged signature (:1705).
@frappe.whitelist()
def request_approval_for(
    capture: str,
    threshold: float | str | None = None,   # str from client → float(threshold) if not in (None, "")
    source: str | None = None,
) -> str: ...

# NEW private helper — pure-ish evaluator (reads settings + in-memory child rows).
def _evaluate_routing_signals(capture: "APInvoiceCapture") -> "RoutingDecision": ...
#   RoutingDecision = namedtuple/dataclass:
#       amount_ok: bool          # final_total_amount <= resolved auto_post_amount_threshold
#       fields_ok: bool          # ALL mandatory confidence rows present AND >= field threshold
#       flags_ok: bool           # validation_status == Validated AND zero open spec-08 flags
#       resolved_threshold: float
#       failing_field: str | None    # first mandatory field that failed (for the reason string)
#       failing_flag: str | None     # first open validation flag (for the reason string)

# NEW sanctioned re-entry entrypoint for the "flagged → cleared → re-route" two-hop (§5.3, D-4).
@frappe.whitelist()
def reroute_after_review_for(capture: str) -> str: ...
#   Allows request_approval to run again from a review/blocked state by first
#   resetting approval_status to Not Required under a guard that the capture is
#   now Validated with zero open flags. Distinct entrypoint so the normal
#   "already routed" guard (:1278) still protects against accidental double-route.
```

**Normalization convention (matches the controller):** whitelisted wrappers accept `str` args from the client and coerce — `float(threshold) if threshold not in (None, "")` (`:1713`), JSON-string dicts via `json.loads` (`:962`, `:1694`), booleans via the `("1","true","yes",...)` set (`:1727-1728`). `reroute_after_review_for` takes only the capture name (no payload to normalize).

### 5.3 Logic

**Evaluator — `_evaluate_routing_signals(capture)`** (pure read; no writes):

1. **Resolve threshold.** `resolved_threshold, source = _resolve_approval_threshold(threshold, source)` — extend `_resolve_approval_threshold` (`:1243-1246`) so that when the caller passes no explicit `threshold`, it reads `frappe.db.get_single_value("AP Closed Loop Settings", "auto_post_amount_threshold")`; if that returns `None`/raises (doctype/field absent), fall back to `AUTO_APPROVAL_THRESHOLD_DEFAULT = 1000.0` with `source = "ap-approval-v1"`. **Precedence: explicit `threshold` arg > settings field > constant.** (Mirror the `_coalesce_defaults` `try/except`, `:1130-1137`.)
2. **Amount axis.** `amount_ok = float(capture.final_total_amount or 0.0) <= resolved_threshold`. Boundary is `<=` (exactly-at-threshold stays auto, preserving `:1291`).
3. **Confidence axis.** Read `rows = capture.get("field_confidences") or []` (in-memory; no DB query). Build a `{field_name: row}` map. For each `logical_name, _proposed, _final in MANDATORY_HEADER_FIELDS`:
   - if no row exists for `logical_name` → **fail-closed**: `fields_ok = False`, `failing_field = logical_name`, break (a missing confidence row is treated as below-threshold — never auto-post an unscored field).
   - else read `row.is_above_threshold` (preferred — spec-04 already resolved per-field/override thresholds). If falsy → `fields_ok = False`, `failing_field = logical_name`, break.
   - if all five pass → `fields_ok = True`, `failing_field = None`.
   - (Only the **header** mandatory fields gate routing. Line-row confidences `line_<i>_<field>` are advisory for review, not a routing gate, in v1 — open decision D-6.)
4. **Flag axis.** `flags_ok = (capture.validation_status == VALIDATION_STATUS_VALIDATED)` AND (spec-08 open-flag count `== 0`). Capture the first open flag label into `failing_flag` for the reason. Until spec 08 lands, `flags_ok = capture.validation_status == VALIDATION_STATUS_VALIDATED`.
5. Return `RoutingDecision(amount_ok, fields_ok, flags_ok, resolved_threshold, failing_field, failing_flag)`.

**Decision matrix — wired into `request_approval` AFTER the existing guards** (`:1267-1283`). Let `clean = decision.fields_ok and decision.flags_ok`:

| amount | clean? | stream | outcome |
|---|---|---|---|
| `<= thr` | clean | **R** | **Auto-post Journal Entry**, NO approval. `approval_status = Auto Approved` (or `Auto Posted` if D-1), `action_required = 0`, NO `Pending Manager`, NO manager decision. JE built via [[07-classification-doctype-branching]]. |
| `<= thr` | clean | **I** | `approval_status = Auto Approved` + **enter [[11-approval-sod-workflow]] approval workflow** (NOT an unconditional submit). `payment_readiness` per D-3. `routing_reason` = auto-approved text. |
| `<= thr` | **flagged** | R or I | **Review Queue.** `routing_reason` names the failing field/flag. `action_required = 1`. **Emit `AP Review Event`** (§5.5). NOT auto-posted. |
| `> thr` | clean | **I** | `approval_status = Pending Manager`, `assigned_approver_role = "Accounts Manager"`, `payment_readiness = Not Ready`, `action_required = 1` (regression of current `:1304-1314`). |
| `> thr` | clean | **R** | Stream R has no amount gate (money moved) → treated as the `<= thr, clean, R` row: **auto-post JE, no approval** regardless of amount. (Open decision D-7: whether large Stream R receipts should still flag for review.) |
| `> thr` | **flagged** | R or I | **Review Queue first.** After a clerk clears the flags, a sanctioned re-route (`reroute_after_review_for`) yields `Pending Manager` (Stream I) / auto-post JE (Stream R). Two-hop. Emit `AP Review Event` on the first hop. |

**Persistence + idempotency:**

6. The evaluator does not write; `request_approval` writes exactly the fields it writes today (`approval_status`, `routing_reason`, `assigned_approver_role`, `decision_by`/`decision_at`, `payment_readiness`, `action_required`, `action_required_reason`, `approval_threshold`, `approval_threshold_source`) plus, on the Stream R auto-post branch, the JE link (field owned by [[07-classification-doctype-branching]]).
7. **Re-route guard.** The existing guard at `:1278` (`approval_status` set → raise `CaptureApprovalError`) **stays** for the normal entrypoint, so a double-route raises. The two-hop re-route goes through `reroute_after_review_for`, which (a) asserts `validation_status == Validated` AND zero open flags AND `stream`/promotion preconditions, (b) resets `approval_status = Not Required` + `routing_reason = None`, (c) calls `request_approval` again. If the re-route preconditions are not met it raises `CaptureApprovalError("Capture not eligible for re-route: <reason>")`. (Decision D-4: distinct entrypoint vs relaxing the guard — recommend distinct entrypoint.)
8. **Guard the JE path.** Before building a Stream R Journal Entry, `frappe.db.exists("DocType", "Journal Entry")` (mirror `_bank_transaction_count_for_payment_entry`'s existence guard, `:1394`). If the JE path or [[07-classification-doctype-branching]]'s builder is unavailable, route to review with reason `"Stream R auto-post unavailable (Journal Entry path not installed)"` rather than crash.
9. **Guard the Review Event emission.** `frappe.db.exists("DocType", "AP Review Event")` before emitting (spec 10 may not be installed). If absent, log a debug and proceed — routing must not fail because the telemetry doctype is missing.

**Exceptions raised:** all guard failures raise `CaptureApprovalError` (subclass of `frappe.ValidationError`, `:136`), consistent with the existing `request_approval` guards. No new exception class is needed.

### 5.4 Cascade & stream-awareness

`_determine_next_step` (`:321-366`) is where routing slots in. Today **Step 3** (`:350-355`) enqueues `request_approval_for` only for promoted, not-yet-routed captures. Changes:

1. **Step 3 stays the trigger** — it still enqueues `request_approval_for` post-promotion. The combined-signal evaluation happens inside `request_approval`, so the cascade does not need a new branch for the confidence/flag axes (it already only reaches Step 3 for `Validated` + `Promoted` captures — flagged/blocked captures never get here, which is correct: they wait in review).
2. **NEW Step 3a (Stream R no-approval).** [[07-classification-doctype-branching]] introduces the Stream-R promote-to-Journal-Entry path; for Stream R, "promotion" is JE creation, not PI creation. The cascade's Stream-R branch (owned by spec 07) calls into `request_approval`, which — seeing `stream == Stream R` + clean + confident — auto-posts the JE and sets `approval_status = Auto Approved` with NO `Pending Manager`. The cascade then **does not** advance to a manager-decision or payment step for Stream R (the Step-4 mock-payment branch at `:357-364` is Stream-I-only; spec 12 gates it on `stream == Stream I`).
3. **Pause vs auto-advance:**
   - **Auto-advance:** `<= thr` + clean → Stream R auto-posts JE (terminal until bank-feed match, spec 13); Stream I becomes `Auto Approved` and the cascade hands to [[11-approval-sod-workflow]].
   - **Pause (review queue):** any flagged/low-confidence capture parks at the review state with `action_required = 1`. This is the formalized version of today's silent stall (§3) — now with a named reason + a Review Event.
   - **Pause (manager):** `> thr` + clean (Stream I) parks at `Pending Manager` exactly as today.
4. **Stream discriminator placement.** The `stream` check lives **inside `request_approval`** (so both the cascade and the manual button honor it), with a thin guard in `_determine_next_step` Step 4 (spec 12) so a Stream R capture is never enqueued for mock payment. This spec's evaluator reads `capture.stream`; treats unset as `Stream I` (fail-safe).

### 5.5 Cross-cutting

- **Threshold single source of truth (canonical, owned by this spec).** `auto_post_amount_threshold` on `AP Closed Loop Settings` (§5.1 A) is the **one canonical approval-threshold value** for the whole AP closed loop, and it is **owned by this spec**. The hard-coded `AUTO_APPROVAL_THRESHOLD_DEFAULT = 1000.0` constant (`document_capture.py:78`) survives **only** as the empty-settings code-level fallback (when the settings doctype/field is absent — §5.3 step 1), never as a second authority. **Critically, [[11-approval-sod-workflow]]'s native Workflow transition condition MUST READ this same setting** rather than hard-coding `doc.grand_total > 1000`: the transition condition expression must call `frappe.db.get_single_value("AP Closed Loop Settings", "auto_post_amount_threshold")`, which **is in the verified Workflow `safe_eval` whitelist** (`frappe.db.get_single_value` is exposed to Workflow transition `condition` evaluation — confirmed in the v16 `frappe/workflow` safe-eval globals). Concretely, spec 11's "over threshold → manager" transition condition reads e.g. `doc.grand_total > frappe.db.get_single_value("AP Closed Loop Settings", "auto_post_amount_threshold")` so the native Workflow gate (PI level) and this spec's evaluator (capture level) share **one** source for the number — change the setting once, both lanes move together. See the cross-reference in [[11-approval-sod-workflow]] and open decision D-9. **Do NOT introduce a second hard-coded `1000` in the Workflow JSON or any transition condition.**
- **Permissions / SoD.** This spec does NOT add a role gate to `request_approval` (it is invoked by the cascade worker and the clerk button alike). It must NOT bypass [[11-approval-sod-workflow]]: a clean+confident **Stream I** capture is `Auto Approved` *into the workflow*, never submitted-and-paid. The `submitter != approver` identity check is spec 11's; spec 09 only decides the *lane*.
- **Idempotency** (via [[01-foundations-settings-async-idempotency]]). The Stream R JE auto-post is a GL-moving operation and MUST carry an idempotency key (spec 01's `AP Posting Ledger`) so a retried cascade job cannot double-post the JE. Re-running `request_approval` on an already-routed capture is blocked by the `:1278` guard (idempotent no-op via raise); the sanctioned re-route is the only re-entry and is itself guarded (§5.3 step 7).
- **Async / enqueue.** No new enqueue — routing runs inside the already-enqueued `request_approval_for` cascade job (`:395-404`, `enqueue_after_commit=not in_test`, `deduplicate=True`, `job_id=ap-progress-<name>-request_approval_for`). Under `frappe.flags.in_test` it runs synchronously inside the rollback boundary.
- **Observability** (via [[10-ap-review-observability]]). On **every** route-to-review (the matrix's "Review Queue" rows), emit exactly one `AP Review Event` at the point `routing_reason` is set, carrying the triggering signal: which axis failed (`confidence` / `validation_flag` / both), the `failing_field` / `failing_flag` name, and `amount` vs `resolved_threshold`. This is the measurement hook for avoidable exceptions (spec 10's "what fraction had a fixable upstream root cause"). Emission is guarded by `frappe.db.exists("DocType", "AP Review Event")` (§5.3 step 9). Do NOT emit a Review Event on the clean auto-advance or the clean `Pending Manager` paths — only on route-to-review.

### 5.6 The evaluator at TWO seams — extending auto-advance to OCR-confirm (BUILT — T-015, 2026-06-02)

> **Status:** **built and tested** (T-015). The **approval seam** (§5.3 decision matrix) is unchanged. The **OCR-confirm seam** is now live: `_evaluate_confirm_signals` shares the confidence axis (`_confidence_fields_ok`) with the approval evaluator — one copy of the gate — and the cascade auto-confirms a clean+confident freshly-extracted capture (`_determine_next_step` Step 1a, gated by `auto_confirm_enabled`, default OFF). Owned jointly with [[04-extraction-confidence-line-items]] §5.6; this spec owns the shared evaluator so the two seams never diverge.

`_evaluate_routing_signals` is not a single-seam decision — it is the reusable test for **"is this capture clean and confident enough to auto-advance past a human pause?"** The cascade pauses for a human at two seams, and the same engine should govern both:

| Seam | When it fires | Axes that apply | Shipped? |
|---|---|---|---|
| **Approval seam** | post-promotion, inside `request_approval` (§5.3) | `amount_ok` + `fields_ok` + `flags_ok` | **shipped** (this spec's §5.3 matrix) |
| **OCR-confirm seam** | post-extraction, before the capture pauses at `Proposed` | `fields_ok` + `flags_ok` (no amount axis at this seam) | **planned** (this subsection + [[04-extraction-confidence-line-items]] §5.6) |

**The OCR-confirm application.** Today, immediately after `run_extraction` writes `field_confidences`, every capture pauses at `status = Proposed` / `action_required = 1` for a human to confirm the OCR proposal — **regardless of confidence**. The signal needed to skip that pause on a clean read already exists (this spec's confidence axis: all mandatory header fields `is_above_threshold = 1`) and is only consumed later at the approval seam. The planned extension applies the **same `fields_ok` + `flags_ok` evaluation** at the OCR-confirm seam:

1. Reuse `_evaluate_routing_signals` (or a thin `_evaluate_confirm_signals` that calls the same `fields_ok` / `flags_ok` logic without the amount axis). **No second copy of the gate.**
2. **Gate:** all five `MANDATORY_HEADER_FIELDS` confidence rows present and `is_above_threshold = 1` (fail-closed on a missing row) **AND** zero open validation flags **AND** the new `AP Closed Loop Settings.auto_confirm_enabled` Check is ON (**default `0` / OFF**, so shipped behavior is unchanged until a site opts in; the pilot turns it ON — field owned/added jointly with [[04-extraction-confidence-line-items]] §5.6).
3. **On pass:** the cascade auto-calls the existing `confirm_extracted_fields` (the same path the clerk's "Confirm Fields" click takes) — capture advances to `Confirmed`, `action_required = 0`, no human pause.
4. **On fail (fail-safe):** any missing/low confidence row OR any open flag OR `auto_confirm_enabled = 0` → fall back to the **existing** human review pause at `status = Proposed` / `action_required = 1`. Escalate only the doubtful.

**Consistency with [[04-extraction-confidence-line-items]] §5.6.** The setting name (`auto_confirm_enabled`), the gate (all mandatory header fields `is_above_threshold = 1` + zero open flags), and the fail-safe (fall back to the `Proposed` human pause) are **identical** in both specs. Spec 04 owns the confidence **signal** and the `auto_confirm_enabled` flag; **this spec owns the shared evaluator** so the OCR-confirm gate and the approval gate never diverge. The amount axis (`amount_ok`) does **not** apply at the OCR-confirm seam — there is no posting/authorization decision at confirm time, only "is the read trustworthy enough to skip the human eyeball."

## 6. Acceptance criteria

- **AC-09-1 (positive, clean auto-approve, Stream I):** Given `final_total_amount <= auto_post_amount_threshold`, all five `MANDATORY_HEADER_FIELDS` confidence rows with `is_above_threshold = 1`, zero open validation flags, and `stream = Stream I` → `approval_status = Auto Approved`, `payment_readiness` per D-3, `action_required = 0`, `routing_reason` mentions auto-post, AND the capture is entered into the [[11-approval-sod-workflow]] workflow (not unconditionally submitted).
- **AC-09-2 (positive, Stream R auto-post):** Same signals but `stream = Stream R` → a Journal Entry is auto-posted (one JE exists, linked to the capture), `approval_status` is the auto state, **no `Pending Manager`**, **no manager decision required**, **no approval gate**, and `payment_readiness` reflects "no payment leg".
- **AC-09-3 (positive, over-threshold manager, Stream I):** `final_total_amount > threshold`, clean + confident, `stream = Stream I` → `approval_status = Pending Manager`, `assigned_approver_role = "Accounts Manager"`, `action_required = 1` (regression of `:1304-1314`).
- **AC-09-4 (negative, one low-confidence field):** `amount <= threshold`, but the `invoice_date` confidence row has `is_above_threshold = 0` (others pass), zero flags → **Review Queue**: `approval_status` NOT an auto state, `action_required = 1`, `routing_reason` contains `invoice_date`, an `AP Review Event` row exists with axis `confidence` and `failing_field = invoice_date`, and **no PI submit / no JE post** occurred.
- **AC-09-5 (negative, open validation flag):** `amount <= threshold`, all confidences pass, but one open spec-08 validation flag present → **Review Queue**: `routing_reason` names the specific flag, `AP Review Event` row exists with axis `validation_flag`, not auto-posted.
- **AC-09-6 (edge, missing confidence row → fail-closed):** A mandatory confidence row (e.g. `currency`) is **absent** from `field_confidences` → treated as below-threshold → **Review Queue**, `routing_reason` names the missing field, not auto-posted.
- **AC-09-7 (edge, boundary):** `final_total_amount == auto_post_amount_threshold` exactly, clean + confident, Stream I → stays the auto lane (`<=`), `approval_status = Auto Approved` (not `Pending Manager`).
- **AC-09-8 (edge, two-hop re-route):** `amount > threshold` AND flagged → first hop yields Review Queue + Review Event; after the flags are cleared (`validation_status = Validated`, zero open flags) a call to `reroute_after_review_for` yields `Pending Manager` (Stream I).
- **AC-09-9 (negative, double-route guard):** Calling `request_approval` (the normal entrypoint) when `approval_status` is already set → raises `CaptureApprovalError` (`:1278` preserved). Calling `reroute_after_review_for` when the capture is NOT eligible (e.g. still has open flags) → raises `CaptureApprovalError`.
- **AC-09-10 (edge, settings fallback):** With no `auto_post_amount_threshold` field/value on `AP Closed Loop Settings`, `_resolve_approval_threshold(None, None)` falls back to `1000.0` with `approval_threshold_source = "ap-approval-v1"` — existing amount-only tests stay green.
- **AC-09-11 (edge, axis independence / AND combination):** Toggling each axis (amount, fields, flags) independently while holding the other two clean proves the AND: any single failing axis routes to review; only all-three-clean auto-advances.
- **AC-09-12 (positive, single-field short-circuit):** Exactly one of the five mandatory confidences failing (the other four pass) routes to review and names *that* field — confirms all five must pass.
- **AC-09-13 (edge, stream unset fail-safe):** With `stream` unset, a clean+confident capture is treated as Stream I (enters the approval workflow), never auto-posts a JE.
- **AC-09-14 (edge, telemetry-doctype absent):** With the `AP Review Event` doctype not installed, a route-to-review still completes (routing_reason set, capture parked) and does not raise — only the Review Event emission is skipped.
- **AC-09-15 (built; positive, auto-confirm at OCR seam):** With `auto_post_amount_threshold` irrelevant at this seam and `AP Closed Loop Settings.auto_confirm_enabled = 1`, a freshly-extracted capture whose five `MANDATORY_HEADER_FIELDS` confidence rows are all `is_above_threshold = 1` with zero open flags is auto-confirmed: the shared `fields_ok` + `flags_ok` evaluation passes, `confirm_extracted_fields` runs without a human click, `status = Confirmed`, `action_required = 0` — no pause at `Proposed`. (Joint with [[04-extraction-confidence-line-items]] AC-04-16.)
- **AC-09-16 (built; negative, fail-safe at OCR seam):** With `auto_confirm_enabled = 1`, a capture with any mandatory confidence row missing or `is_above_threshold = 0`, OR any open validation flag, falls back to the existing `Proposed` human review pause (`action_required = 1`); no auto-confirm — the same `fields_ok`/`flags_ok` fail paths used at the approval seam gate the OCR-confirm seam identically.
- **AC-09-17 (built; regression, default-OFF and shipped approval seam unchanged):** With `auto_confirm_enabled = 0` (default), the OCR-confirm seam never auto-confirms (capture pauses at `Proposed` as shipped), AND the shipped approval-seam matrix (AC-09-1 … AC-09-14) is unaffected — extending the evaluator earlier does not change approval routing.

## 7. Tests

### 7.1 Automated

Module: `erpnext/accounts/doctype/document_capture/test_document_capture.py`, extending the existing `TestAPInvoiceCaptureApproval` class (the home of `test_auto_approval_below_threshold_records_reason_and_decision`, `:828`). Base class `from frappe.tests import IntegrationTestCase`; roll back DB writes in `tearDown` (the suite already does, via the cascade's in-test synchronous-inside-rollback enqueue, `:394-404`). Settings reads use a settings fixture or `frappe.flags`; child-table confidence rows are appended directly on the in-memory capture for unit isolation.

Run: `bench --site <site> run-tests --module erpnext.accounts.doctype.document_capture.test_document_capture`.

New test cases (map 1:1 to the ACs):

- **`_evaluate_routing_signals`** (positive/negative/edge per axis):
  - all-clean → `(amount_ok, fields_ok, flags_ok) == (True, True, True)`, `failing_field is None`, `failing_flag is None` (AC-09-1).
  - one mandatory confidence row with `is_above_threshold = 0` → `fields_ok = False`, `failing_field == "<that field>"` (AC-09-4, AC-09-12).
  - missing confidence row → `fields_ok = False`, `failing_field == "<missing>"` (fail-closed, AC-09-6).
  - `validation_status != Validated` or open flag present → `flags_ok = False`, `failing_flag` set (AC-09-5).
  - amount exactly at threshold → `amount_ok = True` (AC-09-7).
  - each axis toggled independently (AC-09-11).
- **`request_approval` matrix:**
  - clean + `<= thr` + Stream I → `Auto Approved`, entered into workflow, `routing_reason` mentions auto-post (AC-09-1).
  - clean + Stream R → JE exists, no `Pending Manager`, no manager decision (AC-09-2).
  - clean + `> thr` + Stream I → `Pending Manager`, role `Accounts Manager`, `action_required = 1` (AC-09-3).
  - flagged/low-confidence → Review Queue, `routing_reason` names field/flag, **Review Event row asserted** (AC-09-4, AC-09-5), no PI submit / no JE post.
  - double-route via normal entrypoint → `CaptureApprovalError` (AC-09-9).
  - stream unset → treated as Stream I (AC-09-13).
  - `AP Review Event` doctype absent (patch `frappe.db.exists`) → route-to-review still completes (AC-09-14).
- **`reroute_after_review_for`:**
  - flagged-then-cleared two-hop → `Pending Manager` (AC-09-8).
  - re-route while still flagged → `CaptureApprovalError` (AC-09-9).
- **`_resolve_approval_threshold`** (in `ap_closed_loop_settings` test or co-located): explicit arg > settings field > constant; settings absent → `1000.0` + `ap-approval-v1` source (AC-09-10).

Assertions per case (per the brief's test surface): `approval_status`, `payment_readiness`, `action_required`, `routing_reason` substring, and where relevant the `AP Review Event` row count/fields, the Stream-R JE existence, and Stream-I no-direct-submit.

### 7.2 Clean-room test plan

`test/testplans/confidence-based-routing.md` — scope: on a clean bench with [[04-extraction-confidence-line-items]], [[08-validation-gates]], [[02-intake-stream-tagging]], [[07-classification-doctype-branching]], and [[10-ap-review-observability]] installed, configure `AP Closed Loop Settings.auto_post_amount_threshold` and `per_field_confidence_threshold`, then drive a capture through the four matrix corners (clean-low-StreamI, clean-StreamR, low-confidence, over-threshold) via the desk UI + whitelisted endpoints, asserting `approval_status`, the surfaced `routing_reason`/`action_required_reason`, the auto-posted Journal Entry (Stream R) vs the approval-workflow entry (Stream I), and the `AP Review Event` rows for the review-routed cases — verifying state in the DB, not the screenshot.

### 7.3 UI testing (Playwright MCP)
Browser-driven verification of the desk UI this slice adds, via the **Playwright MCP** server. These are the UI steps of the §7.2 clean-room runbook.
- **Prereq:** Playwright MCP per `test/testplans/BROWSER-TESTING-SETUP.md` (`claude mcp list` must list `playwright`; restart after registering). `.mcp.json` / `.playwright-mcp/` gitignored.
- **Evidence:** screenshots to `test/testplans/screenshots/confidence-based-routing/<name>.png` (committed; pass as `filename`).
- **Source of truth stays the DB:** after every UI write, verify via `bench --site <site> mariadb` / `bench … execute`, then delete UI-created data.

**Scenarios** (`route → action → expected UI → DB assertion`):
- A clean + all-fields-high-confidence + under-threshold capture → auto-approves with ZERO manual clicks (observe the form reach Auto Approved / auto-post); screenshot → DB-assert `approval_status` auto-approved. (Stream R: the JE auto-posts with no approval.)
- A flagged capture (low confidence on e.g. `total_amount`) → lands in the review queue with `routing_reason` naming the field; screenshot the queue list (`get_ap_lifecycle_rows`) → DB-assert `routing_reason` + queue membership.

**Not browser-testable in this slice** (covered by §7.1/§7.2): the combined-signal evaluator internals (§7.1).

## 8. Open decisions

- **D-1 — "Auto Posted" representation.** The matrix names "Auto Posted" but the `approval_status` enum (`:67-71`) has no such value. Options: (a) add an `Auto Posted` enum value; (b) represent it as `Auto Approved` + the posted artifact (JE/PI link). **Recommended default: (b)** — fewer enum/migration churn; "posted" is derivable from `Auto Approved` + a linked JE (Stream R) or the workflow state (Stream I). **Owner:** spec-09 + [[07-classification-doctype-branching]] (it owns the JE link). **Must lock:** before the matrix write-back is implemented.
- **D-2 — Routing config accessor.** Options: extend `get_ocr_config()` to also return `auto_post_amount_threshold`; OR add a dedicated `get_routing_config()`. **Recommended default: `get_routing_config()`** composing the spec-04 confidence keys, keeping `get_ocr_config` extraction-focused. **Owner:** spec-09 + [[01-foundations-settings-async-idempotency]] (settings). **Must lock:** before the settings field accessor is written.
- **D-3 — Stream R `payment_readiness` semantics.** A Stream R capture has no payment leg, but `payment_readiness` is a required Select (`Not Ready`/`Ready for Payment`/`Blocked`). Options: (a) leave `Not Ready`; (b) add a `Not Applicable` option. **Recommended default: (a) leave `Not Ready`** for v1 (no new enum value); the absence of a payment step is conveyed by the Stream R JE + the spec-12 no-op. **Owner:** spec-09 + [[12-payment-execution]]. **Must lock:** before the Stream R write-back is implemented.
- **D-4 — Re-route mechanism (the two-hop blocker).** `request_approval` refuses when `approval_status` is already set (`:1278`), which blocks the "flagged → cleared → Pending Manager" hop. Options: (a) a distinct `reroute_after_review_for` entrypoint that resets `approval_status` under guards; (b) relax the `:1278` guard for review/blocked states inline. **Recommended default: (a) distinct entrypoint** — keeps the accidental-double-route protection intact for the normal path. **Owner:** spec-09. **Must lock:** before the re-route path is implemented.
- **D-5 — v15-doc vs v16-runtime signature check.** CLAUDE.md grounds against v15 docs; the bench runs frappe `16.18.3`. `get_single_value` and `get_all_children` were re-verified in the installed v16 source (§4) and are compatible. Options: (a) accept the v16-verified signatures as authoritative; (b) pin the spec to a frappe version. **Recommended default: (a)** — the local v16 source is the source of truth this fork ships against. **Owner:** spec-09. **Must lock:** before coding (already verified — informational).
- **D-6 — Line-row confidence as a routing gate.** Options: (a) only the five **header** mandatory fields gate routing; line-row `line_<i>_<field>` confidences are advisory; (b) require all line rows above threshold too. **Recommended default: (a)** for v1 — header fields drive the GL-material total; line-level confidence is a review aid (and Stream R receipts may have noisy line OCR). **Owner:** spec-09 + [[04-extraction-confidence-line-items]]. **Must lock:** before the confidence-axis loop is implemented.
- **D-7 — Large Stream R receipts.** Stream R has no amount gate (money already moved), so a large receipt auto-posts its JE regardless of amount. Options: (a) auto-post all clean+confident Stream R regardless of amount; (b) still flag Stream R receipts over a (separate) amount ceiling for a human spot-check even though no payment is pending. **Recommended default: (a)** for v1 (reconciliation, not authorization); revisit if fraud-pattern data warrants (b). **Owner:** spec-09 + [[13-bank-feed-reconciliation]]. **Must lock:** before the Stream R branch is implemented.
- **D-8 — Read `is_above_threshold` vs re-derive.** Options: (a) the evaluator reads spec-04's pre-computed `is_above_threshold` Check; (b) re-derive the comparison from `confidence` + the resolved threshold. **Recommended default: (a)** — single source of truth, no threshold-resolution drift between spec 04 and spec 09. **Owner:** spec-09 + [[04-extraction-confidence-line-items]]. **Must lock:** before the confidence-axis loop is implemented.
- **D-9 — How [[11-approval-sod-workflow]]'s native Workflow reads the canonical threshold.** This spec owns `auto_post_amount_threshold`; spec 11's native Workflow transition gate must consume the *same* value, not a duplicate literal. Options: (a) the Workflow transition `condition` calls `frappe.db.get_single_value("AP Closed Loop Settings", "auto_post_amount_threshold")` inline (it is in the verified Workflow `safe_eval` whitelist) — one source, zero drift; (b) hard-code `doc.grand_total > 1000` in the transition condition (rejected — reintroduces the very magic number this spec removes); (c) stamp a resolved per-document threshold field onto the PI at promotion and have the condition compare against that field. **Recommended default: (a)** — direct settings read in the condition keeps a single authority and survives a settings change with no redeploy. **Owner:** spec-09 (owns the setting) + [[11-approval-sod-workflow]] (owns the Workflow JSON). **Must lock:** before spec 11's Workflow transitions are authored. (See §5.5 "Threshold single source of truth".)

## 9. Dependencies & sequencing

**Must land first (hard blockers):**
- [[04-extraction-confidence-line-items]] — the `Document Capture Confidence` child table (`field_confidences` Table; rows `field_name`/`confidence`/`is_above_threshold`) is the entire confidence axis. **Hard dependency.**
- [[08-validation-gates]] — itemized open-flag count/list is the flag axis. Until it lands, the evaluator degrades to the scalar `validation_status == Validated`. **Hard dependency for the full matrix.**

**Strongly coupled (land together or just after):**
- [[02-intake-stream-tagging]] — the `stream` field drives the Stream-R-no-approval branch. Without it the evaluator fails safe to Stream I.
- [[07-classification-doctype-branching]] — owns the Stream R Journal Entry posting path that the clean+confident Stream R branch calls into; owns the JE↔capture link.
- [[10-ap-review-observability]] — the `AP Review Event` doctype is the route-to-review measurement hook; guarded by `frappe.db.exists` so spec 09 does not hard-fail without it.
- [[01-foundations-settings-async-idempotency]] — the idempotency key / `AP Posting Ledger` that protects the Stream R JE auto-post from double-posting.

**This unblocks:**
- [[11-approval-sod-workflow]] — receives clean+confident Stream I captures as `Auto Approved` entering the workflow.
- [[12-payment-execution]] — the Stream-I-only payment step keys off the auto-approve / manager-approved states this spec sets; the Stream R no-op is honored here.
- Removes the hard-coded `1000.0` (`:78`) site-wide and introduces the reusable `auto_post_amount_threshold` settings field and `stream`-aware routing other specs read.

**Estimated size: S** (per IMPLEMENTATION-PLAN units) once 04 and 08 are in — it **reuses** `request_approval` (`:1249`), the queues (`:1634`/`:1657`), and the existing `routing_reason`/`action_required_reason` fields; the genuinely-new surface is the `auto_post_amount_threshold` settings field, the `_evaluate_routing_signals` helper, the `reroute_after_review_for` entrypoint, and the Stream-R JE auto-post wiring (the JE *builder* itself belongs to spec 07, which makes the new GL-moving path that spec's risk, not this one's). The Stream R Journal Entry auto-post is the **highest-risk** new behavior (posting GL with no approval) and must be gated by `frappe.db.exists("DocType", "Journal Entry")` and an idempotency key.
