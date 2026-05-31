---
spec: 11-approval-sod-workflow
title: Approval Routing with Segregation of Duties (native Workflow)
plan_step: Step 10 — Approval Routing with Segregation of Duties (Stream I only)
stream: I
status: Draft
depends_on: [05-supplier-resolution, 08-validation-gates, 02-intake-stream-tagging]
related: [00-overview, 01-foundations-settings-async-idempotency, 06-gl-coding-tax-costcenter, 07-classification-doctype-branching, 09-confidence-routing, 10-ap-review-observability, 12-payment-execution]
---

# 11 — Approval Routing with Segregation of Duties (native Workflow)
> _Revised 2026-05-31: applied native-vs-custom review findings._

## 1. Summary

This spec replaces the fork's hand-rolled approval engine (`request_approval` / `record_manager_decision` in `ap_invoice_capture.py`) with ERPNext's **native `Workflow` doctype** as the single source of truth, layered with a **defense-in-depth Segregation-of-Duties (SoD) control**: the native `allow_self_approval=0` Workflow lever PLUS an app-code `Before Save` backstop that throws if the approving user is the same person who extracted/coded/promoted the document. It serves **Stream I only** (unpaid Purchase Invoices, plus Expense Claims once `hrms` is installed) — implementing **plan Step 10**. A second Workflow, `Supplier Bank Change Approval`, routes vendor bank-field changes to a separate `Treasury Approver` role. Current-state delta: today there is **no `Workflow` record, no `workflow_state` field, and no `submitter != approver` identity guard anywhere** — the only control is a *role* check (`frappe.only_for`) that cannot stop a manager-role holder from approving a document they themselves promoted.

## 2. Plan alignment

`workflow-v2-plan.md` **Step 10** (lines 76-79):

> **10. Approval Routing with Segregation of Duties — Stream I only**
> **Applies only to Stream I (unpaid invoices and employee expense claims).** Stream R receipts skip this step — the money already moved, so there is nothing to authorize. Items in scope are routed to the appropriate approver(s) based on policy — typically driven by amount thresholds, department, cost center, or supplier risk profile. Segregation of duties is enforced: the role that extracted/coded the document cannot also approve it above a defined threshold, and vendor master changes (especially bank-detail changes) follow a separate approval path from invoice approvals. This is the formal authorization gate.

> **ERPNext build sketch.** Approval is built on ERPNext's native `Workflow` doctype, not custom code. One Workflow record (`AP Document Approval`) applies to `Purchase Invoice` and `Expense Claim` with states `Draft → Pending Review → Pending Approval → Approved → Submitted`. Each transition is a `Workflow Transition` row with an `Allowed Role` and a Python `Condition` (e.g., `doc.grand_total > 5000`). The `Workflow Transition` doctype also exposes an **`allow_self_approval`** field … **the runtime behavior must be verified on our target ERPNext version** … **backstop SoD with a Server Script `validate` hook** … A second Workflow record (`Supplier Bank Change Approval`) routes any change to vendor bank fields through a separate approver.

Control-Summary rows this spec owns:

| Control | Where it lives | Why it matters |
|---|---|---|
| Segregation of duties via Workflow + `allow_self_approval` off | Step 10 | Internal-control standard; native ERPNext config |
| Vendor bank-detail change workflow | Step 7 (built here) | Defends against social-engineering fraud |

**Stream R vs Stream I.** This step is **Stream I only**. Stream R captures (already-paid card/cash receipts) **must short-circuit** the approval cascade entirely — there is nothing to authorize. The spec adds a stream discriminator gate to `_determine_next_step` (§5.4) so a Stream R capture is never routed into `AP Document Approval` and is never auto-approved-under-threshold by the legacy cascade.

> **Plan-excerpt corrections (trust the code over the plan):**
> 1. The plan's `doc.grand_total > 5000` example is illustrative — the **shipped default threshold is `1000.0`** (`AUTO_APPROVAL_THRESHOLD_DEFAULT`, `ap_invoice_capture.py:78`), overridable via `approval_threshold` / an `explicit-override` source. All Conditions in this spec use `1000` unless the matrix overrides it.
> 2. The plan says backstop with a Server Script **`validate`** hook. When shipped as **app code** via `hooks.py` `doc_events`, `"validate"` is a valid Python hook key (ERPNext already registers `"*": {"validate": [...]}` at `hooks.py:353`). When shipped as a **Server Script record**, there is **no bare "Validate"** Document Event in the dropdown — use **`Before Save`** / `Before Submit` (see §4). The spec recommends app code (§5.3, §8 D-3), so the existing `"validate"` doc_events surface is available.
> 3. `Expense Claim` is **aspirational** — `hrms` is not installed (apps = `erpnext`, `frappe`, `payments`). The buildable Workflow `document_type` today is **Purchase Invoice only**. Do not assert Expense Claim coverage as shipped.

## 3. Current state

All approval logic lives in `erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.py`. Verified against the file:

- **`request_approval(capture, threshold=None, source=None, actor=None, approver_role=None, save=True)`** — `:1249`. Preconditions raise `CaptureApprovalError` (`frappe.ValidationError` subclass, `:136`): `validation_status == "Validated"` (`:1267`), `promotion_status == "Promoted"` AND `purchase_invoice` set (`:1274`), `approval_status` empty/`Not Required` (`:1278`). Resolves threshold via `_resolve_approval_threshold` (`:1243`). If `final_total_amount <= threshold` → `Auto Approved` + `Ready for Payment` + `decision_by` set (`:1291-1302`); else → `Pending Manager`, `assigned_approver_role = approver_role or "Accounts Manager"`, `Not Ready`, `action_required=1` (`:1303-1314`).
- **`record_manager_decision(capture, approve, actor=None, notes=None, save=True)`** — `:1321`. **Today's only SoD-ish control** is `frappe.only_for(capture.assigned_approver_role or "Accounts Manager")` at `:1336`. The comment at `:1333-1335` admits that without it "any AP clerk could approve their own over-threshold capture." Requires `approval_status == "Pending Manager"` (`:1338`). Sets `Manager Approved` + `Ready` or `Rejected` + `Blocked`.
  - **GAP (verified):** `frappe.only_for` is a **role** check, not an **identity** check. A user who holds `Accounts Manager` and who *also* promoted the capture passes it — **there is no `submitter != approver` guard anywhere in the fork.** This is the central control gap this spec closes.
- **`is_ready_for_payment`** (`:1365`) / **`is_payment_blocked`** (`:1378`) — predicates gating downstream mock payment. These read `approval_status` + `payment_readiness`. **They are the downstream contract** other code depends on; the migration must keep them working unchanged via an adapter (§5.3).
- **Whitelisted wrappers (the reuse seam):** `request_approval_for` (`:1705`) and `record_manager_decision_for` (`:1719`); each calls the pure fn then `doc._kick_next_step()` (`:1715`, `:1730`). String/int coercion happens here (`:1713`, `:1727-1728`).
- **Cascade:** `_kick_next_step` (`:292`) → `_determine_next_step` (`:321`). **Step 3** (`:350-355`) auto-enqueues `request_approval_for` once `Promoted`; **Step 4** (`:358-364`) auto-enqueues `issue_mock_payment_for` once `Auto Approved`/`Manager Approved` + `Ready`. **This cascade auto-approves anything `<= 1000.0` with no human and no stream gate** — Stream R discrimination does not exist (`:329-366` carry no stream concept).
- **State constants** (`:67-79`): `approval_status` Literal = `{Not Required, Auto Approved, Pending Manager, Manager Approved, Rejected}`; `MANAGER_APPROVAL_ROLE_DEFAULT = "Accounts Manager"` (`:79`); `AUTO_APPROVAL_THRESHOLD_DEFAULT = 1000.0` (`:78`); `APPROVAL_SOURCE_DEFAULT = "ap-approval-v1"` (`:77`).
- **Capture fields** (DF types `:209-234`): `approval_status` (Literal), `approval_threshold` (Float), `approval_threshold_source` (Data), `routing_reason` (SmallText), `assigned_approver_role` (**Data — NOT a Link to Role**, `:220`), `decision_by` (Link), `decision_at` (Datetime), `decision_notes` (SmallText), `payment_readiness` (Literal). **No `workflow_state` field; no `supplier` / bank-change linkage; no `stream` field on the capture.**
- **`doc_events`** exists at `hooks.py:351`; the `"*": {"validate": [...]}` entry at `:352-356` is the alternative wiring point for the SoD backstop as app code. **There is no `fixtures` key in `hooks.py` yet** (verified) — it must be added to export the Workflow + Role + Approval-Matrix fixtures.
- **Native `Authorization Rule` + `Authorization Control` STILL ship in v16 and are already WIRED into Purchase Invoice** (do **not** reinvent the amount-threshold approval-limit concept). The Purchase Invoice controller calls `AuthorizationControl().validate_approving_authority(...)` on submit (`erpnext/accounts/doctype/purchase_invoice/purchase_invoice.py:762`, v15 line); the rule doctype is `erpnext/setup/doctype/authorization_rule/authorization_rule.json`. An `Authorization Rule` natively models an amount/role/company-scoped approval **limit**: `based_on = "Grand Total"`, an authorized `value`, and an `approving_role` / `approving_user` required for documents **above** that value — i.e. exactly the **AMOUNT leg** of the proposed `AP Approval Matrix` (§5.1 C), enforced **for free** on PI `on_submit`. **Limits (verified):** it gates only at **submit-time** (it is not a `Workflow` routing input, so it cannot pause a document at `Pending Approval`), it covers **only** the amount/role/company/transaction axes — **not** department, cost-center, or supplier-risk — and the control evaluates via **raw SQL**. So it is a real native partial of the matrix's amount gate, but does **not** fully replace the matrix. See **D-8** for the recommendation.

**Confirmed absences (grep-verified):** no `"doctype": "Workflow"` fixture under `erpnext/` (only a `test_sales_order.py` match), no `workflow_state` field on the capture, no Server Script record. New roles `AP Clerk` / `Treasury Approver` / `Auditor (Read Only)` **do not exist**; capture DocType permissions grant only `Accounts Manager` and `Accounts User`.

## 4. Upstream grounding

| URL | Confirms | Quoted signature / section |
|---|---|---|
| `https://docs.frappe.io/erpnext/workflows` (verified) | Canonical Workflow doc. Workflow **States** carry Doc Status (`Saved=0`/`Submitted=1`/`Cancelled=2`) + Update Field + Update Value; **Transition** rows carry State, Action, Next State, **Allowed** (role), **Condition**. A Condition is a doc-property expression and whitelists `frappe.db.get_value`, `frappe.db.get_list`, `frappe.session`, `frappe.utils.now_datetime()/get_datetime()/add_to_date()/now`. **Authoritative grounding for states/transitions/Allowed-role/Condition.** (The `/framework/v15/user/en/workflows` and `/concepts-and-tasks/*` variants 404 — this is the correct page.) | Condition example: `"doc.grand_total <= 100000"` … "This can be extended to any property of the document." |
| `https://raw.githubusercontent.com/frappe/frappe/version-15/frappe/model/workflow.py` (verified) | **Authoritative runtime SoD semantics.** `has_approval_access` (L166-167) returns `True` (permissive) when user is Administrator OR `allow_self_approval` is truthy OR `user != doc.owner`. `apply_workflow` (L127-128) throws `Self approval is not allowed` when `has_approval_access` is False. ⇒ to BLOCK self-approval, `allow_self_approval` MUST be `0`, AND the check is keyed on **`doc.owner` (the record CREATOR), not the prior workflow actor** — a multi-hop draft whose owner is reassigned can defeat it; **Administrator always bypasses.** `is_transition_condition_satisfied` (L83-87) evaluates the Condition via `frappe.safe_eval` with `get_workflow_safe_globals` + `dict(doc=doc.as_dict())` — a Condition can read any doc field and do whitelisted DB lookups (e.g. supplier risk via `frappe.db.get_value`) but cannot call arbitrary code. | `def has_approval_access(user, doc, transition):` `\treturn user == "Administrator" or transition.get("allow_self_approval") or user != doc.get("owner")` |
| `https://github.com/frappe/frappe/blob/version-15/frappe/workflow/doctype/workflow_transition/workflow_transition.json` (verified) | **Workflow Transition field schema.** `allow_self_approval` is `Fieldtype=Check`, **`Default=1`**, Label `"Allow Self Approval"`, Description `"Allow approval for creator of the document"` — **the permissive behavior is the out-of-box default and must be explicitly unchecked per transition.** `condition`=Code(Options=Python); `allowed`=Link(Role); `state`=Link(Workflow State); `action`=Link(Workflow Action Master); `next_state`=Link(Workflow State); `send_email_to_creator`=Check. | `allow_self_approval`: Fieldtype Check; Default 1; Description "Allow approval for creator of the document" |
| `https://docs.frappe.io/framework/user/en/desk/scripting/server-script` (verified) | **Server Script grounding for the backstop.** Script Type options = `Document Event | API`. Document Events list includes `Before Insert, After Insert, Before Validate, Before Save, After Save, Before Submit, After Submit, Before Cancel, After Cancel` — **there is NO bare "Validate" event; use "Before Save" or "Before Submit."** `doc` is an implicit variable; block a write with `frappe.throw()` / `raise frappe.ValidationError`. Note: Server Scripts may be disabled by the `server_script_enabled` site config. (The `/v15/` variant 404s; the no-version path is canonical.) | "Script Type: Document Event / API"; events include "Before Validate, Before Save, Before Submit"; block via "raise frappe.ValidationError" |
| `https://docs.frappe.io/framework/v15/user/en/python-api/hooks` (canonical — used for the app-code wiring path) | **`doc_events` hook** maps a doctype → event → dotted method. Confirms `"validate"` is a valid app-code `doc_events` key (distinct from the Server Script dropdown). The fork already uses `"*": {"validate": [...]}` at `hooks.py:352`. | `doc_events = { "DocType": { "validate": "app.module.method" } }` |
| `https://docs.frappe.io/framework/v15/user/en/python-api/document` (canonical — `apply_workflow` driver) | `frappe.model.workflow.apply_workflow(doc, action)` is the programmatic transition driver invoked by the wrappers in §5.2; it runs `has_approval_access` (self-approval guard) + the transition Condition before mutating `workflow_state`. | `from frappe.model.workflow import apply_workflow` |
| `erpnext/accounts/doctype/purchase_invoice/purchase_invoice.py:762` + `erpnext/setup/doctype/authorization_rule/authorization_rule.json` (in-repo source, v16) | **Native amount-threshold approval limit already wired into PI.** PI `on_submit` calls `AuthorizationControl().validate_approving_authority(self.doctype, self.company, self.grand_total, self)`; `Authorization Rule` models `based_on="Grand Total"` + authorized `value` + `approving_role`/`approving_user` required above that value. Confirms the **amount leg** of the matrix ships free on submit, evaluated via raw SQL, scoped to amount/role/company only (no dept/cost-center/risk), and fires at submit-time (not as a Workflow routing input). | `AuthorizationControl().validate_approving_authority(self.doctype, self.company, self.grand_total, self)` |

> **Version note (line numbers are v15; behavior verified on v16).** The native Workflow runtime semantics cited above — `has_approval_access`, the `allow_self_approval` lever, and the `Self approval is not allowed` throw — were **verified against the installed v16 frappe source and match** what the v15 rows describe. However, the **cited line numbers** (`workflow.py` L83-87/L127-128/L166-167; `purchase_invoice.py:762`; the Transition JSON fields) are **per the v15 source**. The build MUST NOT assume the v15 line numbers hold on v16 — re-resolve each citation by symbol (`has_approval_access`, `apply_workflow`, `validate_approving_authority`) against the checked-out v16 tree before relying on a line. The *behavior* is the contract; the line is a pointer that may have drifted.

## 5. Design

### 5.1 Data model

Three deliverables: **(A)** two native `Workflow` records as fixtures, **(B)** a `workflow_state` field on each target doctype + a mirror on the capture, **(C)** an optional `AP Approval Matrix` doctype + new Role fixtures. All fork-only artifacts live under `erpnext/accounts/` and are exported via a new `fixtures` key in `hooks.py`.

#### (A) Workflow `AP Document Approval` (fixture, Stream I PI approval)

`Workflow` parent record:

| field | value | purpose |
|---|---|---|
| `name` / `workflow_name` | `AP Document Approval` | identity |
| `document_type` | `Purchase Invoice` | target (Expense Claim added when `hrms` lands — D-5) |
| `is_active` | `1` | enable |
| `workflow_state_field` | `workflow_state` | the field driven on the target (B) |
| `send_email_alert` | `0` (pilot) | notifications deferred |

`Workflow Document State` child rows (`states`):

| state | doc_status | allow_edit (role) | purpose |
|---|---|---|---|
| `Draft` | 0 | `AP Clerk` | newly promoted PI, pre-routing |
| `Pending Review` | 0 | `AP Clerk` | clerk completes coding |
| `Pending Approval` | 0 | `Accounts Manager` | above-threshold, awaiting approver |
| `Approved` | 0 | `Accounts Manager` | approved, not yet submitted |
| `Submitted` | 1 | `Accounts Manager` | docstatus 1 → eligible for payment (Step 11 / [[12-payment-execution]]) |

`Workflow Transition` child rows (`transitions`) — **`allow_self_approval=0` is set EXPLICITLY on every approve hop** because upstream Default=1:

| state | action | next_state | allowed (role) | condition (Python) | allow_self_approval |
|---|---|---|---|---|---|
| Draft | Submit for Review | Pending Review | `AP Clerk` | *(blank)* | 1 |
| Pending Review | Auto-Approve | Approved | `AP Clerk` | `doc.grand_total <= THRESHOLD` †  | 1 *(under-threshold; submitter may self-advance)* |
| Pending Review | Send for Approval | Pending Approval | `AP Clerk` | `doc.grand_total > THRESHOLD` †  | 1 |
| Pending Approval | Approve | Approved | `Accounts Manager` | `doc.grand_total > THRESHOLD` †  | **0** |
| Pending Approval | Reject | Draft | `Accounts Manager` | *(blank)* | **0** |
| Approved | Submit | Submitted | `Accounts Manager` | *(blank)* | **0** |

† `THRESHOLD` is **not** a hard-coded literal — the shipped Condition substitutes `frappe.db.get_single_value("AP Closed Loop Settings", "auto_post_amount_threshold")` (the canonical setting owned by [[09-confidence-routing]]; this call is in the verified `safe_eval` whitelist). See the note below the table.

Condition strings use only the verified `safe_eval` whitelist. **Threshold single source (do not hard-code the number):** the `1000` literal in the table above is shown for readability only. The shipped Conditions MUST read the canonical policy number via `frappe.db.get_single_value("AP Closed Loop Settings", "auto_post_amount_threshold")` — this call **is** in the verified Workflow `safe_eval` whitelist (`get_workflow_safe_globals`, §4 row 2) — e.g. the above-threshold approve Condition is `doc.grand_total > frappe.db.get_single_value("AP Closed Loop Settings", "auto_post_amount_threshold")` and the under-threshold hop is `<=` the same call. One policy number, one source: the setting is **owned by [[09-confidence-routing]]** (`auto_post_amount_threshold` on `AP Closed Loop Settings`); this spec reads it, never redefines it. Department / cost-center / supplier-risk routing extends the Condition, e.g. `doc.grand_total > frappe.db.get_single_value("AP Closed Loop Settings", "auto_post_amount_threshold") and doc.cost_center == 'OPS-01'` or supplier-risk via `frappe.db.get_value('Supplier', doc.supplier, 'custom_risk') == 'High'` (the `custom_risk` field is owned by [[08-validation-gates]] / [[05-supplier-resolution]]).

#### (B) `workflow_state` fields (fixtures / Custom Field)

| doctype | fieldname | fieldtype | options | purpose |
|---|---|---|---|---|
| `Purchase Invoice` | `workflow_state` | `Link` | `Workflow State` | native field the Workflow drives (Frappe convention) |
| `AP Invoice Capture` | `workflow_state` | `Data` (read-only, synced) | — | mirror so `_determine_next_step` can read the PI's state without a cross-doc fetch (D-1 — recommend a thin sync, not a second engine) |

> **D-1 recommendation:** add a read-only `workflow_state` mirror on the capture, synced from the PI on each cascade tick, rather than reusing `approval_status` directly. Keeps the legacy `approval_status` Literal intact for the downstream adapter (§5.3) while giving the cascade a single field to branch on.

#### (C) `AP Approval Matrix` (new doctype, optional — D-2) + Roles

`AP Approval Matrix` (fork-only, module = Accounts, `is_submittable=0`):

| fieldname | fieldtype | options/default | purpose |
|---|---|---|---|
| `amount_from` | Currency | default 0 | lower bound (inclusive) |
| `amount_to` | Currency | nullable = unbounded | upper bound (inclusive) |
| `department` | Link | Department (optional filter) | dept-scoped routing |
| `cost_center` | Link | Cost Center (optional filter) | cost-center-scoped routing |
| `supplier_risk` | Select | `Low\nMedium\nHigh` (optional) | risk-scoped routing |
| `approver_role` | Link | **Role** | the approver this row routes to |
| `priority` | Int | default 0 | tie-break for overlapping rows (higher wins) |

Permissions: read for `Accounts User`, `Accounts Manager`, `Auditor (Read Only)`; create/write/delete for `Accounts Manager` only.

**New Role fixtures** (none exist today — create as `Role` records exported via `fixtures`):

| role | scope | used by |
|---|---|---|
| `AP Clerk` | extract / code / promote — the **submitter**; allowed on Draft→Pending hops | this spec; [[06-gl-coding-tax-costcenter]]; [[10-ap-review-observability]] |
| `Treasury Approver` | **bank-change approver only** — distinct from invoice approvers | Workflow (B) below; [[05-supplier-resolution]]; [[08-validation-gates]] |
| `Auditor (Read Only)` | read across AP doctypes + the audit log | [[14-closure-audit-retention]] |

Existing `Accounts Manager` remains the invoice approver. `assigned_approver_role` stays `Data` for back-compat but **D-4** recommends validating it against existing Roles (or upgrading to `Link → Role`) so a typo cannot route to a nonexistent role.

#### Second Workflow `Supplier Bank Change Approval` (fixture)

| field | value |
|---|---|
| `document_type` | the **Supplier Master Change Request** doctype from [[05-supplier-resolution]] (exact name TBC — D-6) |
| `is_active` | `1` |
| `workflow_state_field` | `workflow_state` |

Transitions route bank-field change requests to `allowed = "Treasury Approver"` with `allow_self_approval=0`. The Condition gates on the change **category/flag** set by the [[08-validation-gates]] bank-change detector (e.g. `doc.change_category == 'bank_detail'`), so only bank-detail changes require Treasury sign-off; non-bank field changes route on the lighter `Accounts Manager` path.

### 5.2 Endpoints

The existing whitelisted wrappers are **kept** as the public seam; their bodies are re-pointed to drive the native Workflow. Full dotted paths under `erpnext.accounts.doctype.ap_invoice_capture.ap_invoice_capture`:

```python
@frappe.whitelist()
def request_approval_for(capture: str, threshold: float | str | None = None, source: str | None = None) -> str:
    """Route a promoted Stream-I capture into AP Document Approval.

    NEW body: resolve threshold + matrix → set capture.assigned_approver_role,
    then drive the PI via frappe.model.workflow.apply_workflow(pi, action) to
    'Pending Review' (and onward to 'Pending Approval' or 'Approved' per the
    Condition). Translate the resulting workflow_state back into the legacy
    approval_status Literal via _sync_approval_from_workflow (adapter). Then
    doc._kick_next_step(). Stream R → no-op (CaptureApprovalError guard, see 5.4).
    Returns capture.name. (string→float coercion unchanged at the wrapper.)
    """

@frappe.whitelist()
def record_manager_decision_for(capture: str, approve: bool | int | str, notes: str | None = None) -> str:
    """Record an approver decision by driving the Workflow Approve/Reject action.

    NEW body: coerce `approve` (str 'yes'/'1'/'approve' → True, unchanged).
    Call apply_workflow(pi, 'Approve' if approve else 'Reject'); the native
    has_approval_access guard + Condition fire here. _sync_approval_from_workflow
    maps the new workflow_state → approval_status / payment_readiness so
    is_ready_for_payment / is_payment_blocked keep working. doc._kick_next_step().
    Returns capture.name.
    """

# New helper (NOT whitelisted) — the matrix resolver:
def resolve_approver_role(capture) -> str:
    """Return the approver Role for this capture.

    If AP Approval Matrix has an active row matching amount/department/
    cost_center/supplier_risk → its approver_role (highest `priority` wins on
    overlap). Else fall back to the threshold-driven default
    (MANAGER_APPROVAL_ROLE_DEFAULT = 'Accounts Manager'). Never raises on an
    empty/absent matrix — returns the default. Preserves _resolve_approval_threshold.
    """
```

**Normalization convention** (unchanged from the controller): whitelisted args arrive as strings; numeric thresholds coerced via `float(threshold) if threshold not in (None, "") else None` (`:1713`); booleans coerced via the `("1","true","yes","approve","approved")` set (`:1727-1728`). `capture` accepts a name string or a doc and is resolved by `frappe.get_doc` at the top of the pure fn.

`frappe.model.workflow.apply_workflow` is the driver; per §4 it runs `has_approval_access` (self-approval guard) + the transition Condition before mutating `workflow_state`.

### 5.3 Logic

**SoD enforcement — two layers (defense-in-depth):**

1. **Native Workflow lever.** `allow_self_approval=0` on every above-threshold approve transition. Verified rule (`frappe/model/workflow.py`): `apply_workflow` throws `Self approval is not allowed` when `user != "Administrator"` AND `allow_self_approval` falsy AND `user == doc.owner`. **Caveats the build MUST respect:** (a) the check is keyed on `doc.owner` = the PI's **creator**, not the prior transition actor — if the `AP Clerk` creates the PI and the owner is later reassigned, the guard weakens; (b) **Administrator bypasses entirely.** The plan's "verification task" is **resolved by source** (`allow_self_approval=0` *does* block `owner == approver`); the only live verification left is the `doc.owner`-vs-actor nuance on our v16 (test case in §7.1).

2. **App-code backstop (`Before Save`, stronger than native).** Wired via `hooks.py` `doc_events` on `Purchase Invoice` (the `"validate"` doc_events surface already exists at `hooks.py:352`; recommend a dedicated `"Purchase Invoice": {"validate": "...sod_backstop"}` entry — `"validate"` runs on every save before submit). Pseudocode:

   ```
   def sod_backstop(doc, method):
       if doc.doctype not in STREAM_I_WORKFLOW_DOCTYPES: return        # PI (+ Expense Claim later)
       if not _is_above_threshold_approval_target(doc.workflow_state): return
       coder = _recorded_coder_for(doc)        # the AP Invoice Capture's validated_by/decision_by/promoted-by
       if coder and frappe.session.user == coder and flt(doc.grand_total) > _threshold_for(doc):
           frappe.throw(_("SoD: the user who coded/promoted this document may not approve it above threshold."))
   ```

   This compares `frappe.session.user` against the **recorded extractor/coder** (`decision_by` / `validated_by` on the linked capture), which is **stronger than the native `doc.owner` check** — it survives owner reassignment and is not defeated by an Administrator who is also the coder. Ship as **app code** (D-3) for testability and because Server Scripts may be disabled by `server_script_enabled` site config.

**Adapter (`_sync_approval_from_workflow`) — the migration glue:**

| `workflow_state` | → `approval_status` | → `payment_readiness` |
|---|---|---|
| Draft / Pending Review | `Not Required` | `Not Ready` |
| Pending Approval | `Pending Manager` | `Not Ready` |
| Approved (via under-threshold hop) | `Auto Approved` | `Ready for Payment` |
| Approved (via manager Approve hop) | `Manager Approved` | `Ready for Payment` |
| Submitted | (unchanged from Approved) | `Ready for Payment` |
| Draft after Reject | `Rejected` | `Blocked` |

This keeps `is_ready_for_payment` (`:1365`) and `is_payment_blocked` (`:1378`) — and therefore the downstream mock-payment guard — working **unchanged**. **No two parallel engines:** the native Workflow is the source of truth; `approval_status` becomes a *derived* mirror, never hand-set in two places (risk R-7).

**Migration steps (reconcile custom engine → native Workflow):**

1. Keep `request_approval_for` / `record_manager_decision_for` signatures; re-point bodies to `apply_workflow` + adapter (§5.2).
2. **Remove** the role-only `frappe.only_for(...)` gate at `:1336`; rely on the Workflow Transition `allowed` role **plus** the two SoD layers (the `only_for` is a role check, the current weak point).
3. `_determine_next_step` Step 3 (`:350`) keeps auto-routing into the Workflow; **Step 4** mock-payment (`:358`) gates on `workflow_state == "Submitted"` (or adapter-mapped `Approved`) instead of legacy `approval_status` alone.

**Idempotency** (via [[01-foundations-settings-async-idempotency]]): each `apply_workflow` call is guarded by the per-capture-per-step `job_name` dedupe already in `_enqueue_next` (`:368`); re-running an already-applied transition is a no-op because the precondition state has advanced (Frappe rejects an action not valid from the current state). Posting operations downstream carry the foundations idempotency key.

**Observability** (via [[10-ap-review-observability]]): every Approve/Reject transition emits an `AP Review Event` (decision, actor, root-cause vocabulary where a reject) — the `decision_by`/`decision_at` already captured feed it.

### 5.4 Cascade & stream-awareness

**Stream gate (new, at the top of the approval branches):** add a stream discriminator to the capture (consumed from [[02-intake-stream-tagging]] — this spec does **not** define `stream`; flag if undefined upstream). `_determine_next_step`:

- **Step 3** (`:350`) gains a precondition `self.stream == "I"`. A **Stream R** capture returns `None` here → never routed into `AP Document Approval`.
- **Step 4** (`:358`) likewise short-circuits for Stream R (its payment path is [[12-payment-execution]]'s Stream R no-op; closure flows to [[13-bank-feed-reconciliation]]).

So:

| Stream | Step 3 (approval) | Step 4 (payment) |
|---|---|---|
| **I** (invoice) | enqueue `request_approval_for` → Workflow | gated on `workflow_state == Submitted/Approved` |
| **R** (receipt) | **skipped** (returns None) | **skipped** here (handled by [[12]]/[[13]]) |

**Pause vs auto-advance:** under-threshold Stream I (`grand_total <= 1000`) auto-advances through the Workflow (under-threshold hop, no human) — but **only** if the SoD layers permit (an under-threshold self-advance is allowed by design; the SoD bar is the *above-threshold* approve hop). Above-threshold Stream I **pauses** at `Pending Approval` for a human Approve/Reject. This preserves the current pause semantics while moving the engine to native Workflow.

### 5.5 Cross-cutting

- **Permissions / SoD:** new Roles (§5.1 C); Workflow Transition `allowed` roles; `allow_self_approval=0`; app-code backstop. Capture DocType permissions extended to grant `AP Clerk` (write through Pending) and `Auditor (Read Only)` (read).
- **Idempotency:** via [[01-foundations-settings-async-idempotency]] — `apply_workflow` calls are dedupe-guarded by the existing `_enqueue_next` `job_name`.
- **Async / enqueue:** reuses `_kick_next_step` / `_enqueue_next` (`:292`/`:368`) with `enqueue_after_commit=True`, `deduplicate=True`; under `in_test` runs `now=True`.
- **Observability:** Approve/Reject emit `AP Review Event` (via [[10-ap-review-observability]]).
- **Foundations dependency:** the `workflow_state` mirror sync and the adapter live alongside the foundations idempotency ledger.

## 6. Acceptance criteria

- **AC-11-1** (native SoD, positive): an above-threshold (`grand_total > 1000`) Approve transition applied by a user **other than** `doc.owner`, with `allow_self_approval=0`, **succeeds** and `workflow_state` advances to `Approved`.
- **AC-11-2** (native SoD, negative): the same transition applied **by `doc.owner`** (the creator) with `allow_self_approval=0` **raises** `frappe.throw("Self approval is not allowed")`.
- **AC-11-3** (native SoD, edge / default risk): the same transition by `doc.owner` with `allow_self_approval=1` **succeeds** — proving the flag is the lever and documenting the upstream Default=1 hazard.
- **AC-11-4** (backstop, negative — stronger than native): with the backstop installed, the **recorded coder** (`decision_by`/`validated_by`) attempts an above-threshold approve **even though they are NOT `doc.owner`** → `frappe.throw` with the SoD message.
- **AC-11-5** (backstop, positive): a clean approver (not the coder, not the owner) above threshold → passes the backstop and the transition applies.
- **AC-11-6** (threshold routing): `grand_total <= 1000` → under-threshold/auto hop, no `Pending Approval`; `grand_total > 1000` → lands in `Pending Approval`, and the adapter sets `approval_status == "Pending Manager"` with `assigned_approver_role` + `routing_reason` populated.
- **AC-11-7** (Stream gate): a **Stream R** capture → `_determine_next_step` returns `None` at Step 3 (no approval enqueued) and Step 4 mock-payment is **not** enqueued for the approval reason; a **Stream I** capture → Step 3 enqueues `request_approval_for`.
- **AC-11-8** (matrix resolver): a matched `AP Approval Matrix` row returns its `approver_role`; an unmatched amount falls back to `Accounts Manager`; an **empty/absent** matrix returns the default and **does not raise**.
- **AC-11-9** (Condition safe_eval): a transition Condition using `frappe.db.get_value` for supplier risk evaluates with **no** `SecurityException`; a Condition calling a non-whitelisted function is rejected by `safe_eval`.
- **AC-11-10** (bank-change separation): a bank-field change request routes to `Treasury Approver`; an invoice-approver (`Accounts Manager`, no Treasury role) attempting the Treasury transition is **blocked** by the `allowed` role.
- **AC-11-11** (regression / no split-brain): after migration, `is_ready_for_payment` / `is_payment_blocked` return the same values for equivalent states as before, driven solely by the adapter — never by a second hand-set `approval_status` path.
- **AC-11-12** (Expense Claim deferred): the build asserts the Workflow `document_type` is `Purchase Invoice` only on a no-`hrms` bench; an attempt to add `Expense Claim` is documented as deferred (D-5), not shipped.

## 7. Tests

### 7.1 Automated

- **Module (existing, extend):** `erpnext.accounts.doctype.ap_invoice_capture.test_ap_invoice_capture` — add the stream-gate, adapter, and threshold-routing regression cases (AC-11-6, -7, -11).
- **Module (new):** `erpnext.accounts.tests.test_ap_approval_workflow` (new `erpnext/accounts/tests/test_ap_approval_workflow.py`) — the Workflow + SoD + matrix cases. Use `from frappe.tests import IntegrationTestCase`; roll back all DB writes (PIs, requests, role assignments) in `tearDown`.

Cases (positive / negative / edge per public function):

| Case | AC | Type |
|---|---|---|
| Native SoD: approve as non-owner, `allow_self_approval=0` → advances | AC-11-1 | positive |
| Native SoD: approve as `doc.owner`, flag=0 → throws "Self approval is not allowed" | AC-11-2 | negative |
| Native SoD: approve as owner, flag=1 → advances (documents Default=1 risk) | AC-11-3 | edge |
| Backstop: recorded coder (not owner) approves above threshold → throws SoD | AC-11-4 | negative |
| Backstop: clean approver above threshold → passes | AC-11-5 | positive |
| Threshold: `<= 1000` auto-hop (no manager) vs `> 1000` Pending Approval | AC-11-6 | positive/edge |
| Stream gate: Stream R → None at Step 3; Stream I → enqueues approval | AC-11-7 | positive/negative |
| `resolve_approver_role`: matched row → its role | AC-11-8 | positive |
| `resolve_approver_role`: unmatched amount → `Accounts Manager` default | AC-11-8 | negative |
| `resolve_approver_role`: empty/absent matrix → default, no raise | AC-11-8 | edge (registry-style unknown-key) |
| Condition: supplier-risk via `frappe.db.get_value` evaluates, no `SecurityException` | AC-11-9 | edge |
| Bank-change: routes to `Treasury Approver`; invoice approver blocked | AC-11-10 | positive/negative |
| Regression: `is_ready_for_payment`/`is_payment_blocked` unchanged post-migration | AC-11-11 | regression |

Run: `bench --site <site> run-tests --module erpnext.accounts.tests.test_ap_approval_workflow` and `… --module erpnext.accounts.doctype.ap_invoice_capture.test_ap_invoice_capture`. Confirm green before declaring done.

### 7.2 Clean-room test plan

`test/testplans/approval-routing-sod.md` — runbook scope: from a fresh bench, create Roles (`AP Clerk` / `Treasury Approver` / `Auditor (Read Only)`) + a test user per role; import the two Workflow fixtures (`AP Document Approval`, `Supplier Bank Change Approval`); **explicitly verify `allow_self_approval` runtime on this v16** (apply an above-threshold transition as the PI creator, expect the exact throw text `Self approval is not allowed`); run the positive/negative/edge SoD cases with named users and PI `grand_total` values straddling `1000.0`; verify the **Stream R skip**; verify bank-change routing to `Treasury Approver`. Mark Expense Claim cases **"deferred until hrms installed."** Cleanup deletes test PIs/requests and rolls back role assignments.

## 8. Open decisions

- **D-1 — Capture `workflow_state` mirror vs reuse `approval_status`.** Options: (a) add a read-only `workflow_state` Data mirror synced from the PI; (b) reuse the existing `approval_status` Literal for cascade branching. **Recommend (a)** — keeps `approval_status` as the stable downstream contract for the adapter while giving the cascade one field to branch on. Owner: AP eng lead. Lock: before the migration PR (blocks §5.3).
- **D-2 — `AP Approval Matrix` ship-now vs threshold-only for pilot.** Options: (a) ship the matrix doctype now; (b) defer, route on the `1000.0` threshold only. **Recommend (b) for pilot** (threshold-only), schema-stub the matrix so Conditions can grow into it. Owner: AP product. Lock: at pilot scope sign-off.
- **D-3 — SoD backstop as app code vs Server Script record.** Options: (a) app code via `hooks.py doc_events` (`"validate"` surface already exists); (b) a Server Script record (no-deploy editing, but may be disabled by `server_script_enabled` and has no bare "Validate" event → must use "Before Save"). **Recommend (a)** — testable, deploy-controlled, not gated by site config. Owner: AP eng lead. Lock: before the backstop PR.
- **D-4 — `assigned_approver_role` Data vs Link→Role.** Options: (a) keep Data (back-compat), add a validate-against-Roles check; (b) upgrade to `Link → Role`. **Recommend (a) now, (b) when the matrix lands** — avoids a migration on a field other code reads. Owner: AP eng lead. Lock: with D-2.
- **D-5 — Expense Claim coverage.** Options: (a) PI-only Workflow now; (b) add `Expense Claim` to `document_type` once `hrms` is installed. **Recommend (a)** — `hrms` is not installed; do not assert Expense Claim as shipped. Owner: AP product. Lock: now (PI-only), revisit when hrms lands.
- **D-6 — Exact `Supplier Master Change Request` doctype name + bank-field schema.** Depends on [[05-supplier-resolution]]. **Recommend:** the second Workflow's `document_type` and the `change_category` Condition field are pinned **when spec 05 lands**; until then the Workflow fixture is authored against the placeholder name. Owner: [[05-supplier-resolution]] owner. Lock: when 05 is implemented.
- **D-7 — Administrator-bypass policy.** The native lever lets Administrator bypass SoD. Options: (a) accept (Administrator is break-glass); (b) extend the app-code backstop to also block Administrator when Administrator is the recorded coder. **Recommend (b)** — the backstop already compares against the recorded coder, so blocking Administrator-as-coder is free. Owner: AP eng lead + controls reviewer. Lock: before the backstop PR.
- **D-8 — Native `Authorization Rule` for the amount gate vs custom `AP Approval Matrix`.** Native `Authorization Rule` + `Authorization Control` ship in v16 and are already wired into PI `on_submit` (`purchase_invoice.py:762`; rule JSON at `setup/doctype/authorization_rule/authorization_rule.json`), enforcing an amount/role/company-scoped approval **limit** (`based_on="Grand Total"` + authorized `value` + `approving_role`/`approving_user` above it) **for free** on submit — exactly the AMOUNT leg of the proposed `AP Approval Matrix` (§5.1 C, §3). It does **not** cover the department / cost-center / supplier-risk axes, it fires at submit-time (not as a `Workflow` routing input so it cannot pause at `Pending Approval`), and it uses raw SQL — so it does **not** fully replace the matrix. Options: (a) use native `Authorization Rule` for the pilot AMOUNT gate now and reserve `AP Approval Matrix` for the extra (dept / cost-center / risk) axes later; (b) build the matrix amount leg in custom code from day one and ignore the native control; (c) drive both (native limit on submit + Workflow Condition for routing). **Recommend (a)** — do not silently reinvent the amount-threshold approval-limit concept; configure the native rule for the pilot, schema-stub the matrix (per D-2) for the non-amount axes, and revisit when those axes are needed. **Interplay with the Workflow:** the native rule complements — it does not replace — the `Pending Approval` pause; the Workflow still routes/holds the document, the native rule is a hard submit-time backstop on the amount. Owner: AP product + AP eng lead. Lock: with D-2 (matrix scope) at pilot scope sign-off.

## 9. Dependencies & sequencing

**Depends on (must land first or be coordinated):**
- [[02-intake-stream-tagging]] — defines `stream` on the capture; this spec **consumes** it (the Stream R short-circuit). If `stream` is undefined when this builds, flag it — do not define it here.
- [[05-supplier-resolution]] — the `Supplier Master Change Request` doctype is the `document_type` for the `Supplier Bank Change Approval` Workflow (name + bank fields pending — D-6).
- [[08-validation-gates]] — the bank-change detector sets the `change_category` the bank-change Workflow Condition gates on (and the `custom_risk` Supplier field used in PI Conditions).
- [[09-confidence-routing]] — **owns the canonical threshold setting** `auto_post_amount_threshold` on `AP Closed Loop Settings`. This spec's Workflow Conditions **read** it via `frappe.db.get_single_value(...)` (§5.1 A) rather than hard-coding `1000`; the number is defined there, not here.
- [[01-foundations-settings-async-idempotency]] — idempotency keys / async runner the cascade reuses.

**Unblocks / feeds:**
- [[12-payment-execution]] — must consume `workflow_state == Submitted/Approved` (via the adapter) as its precondition instead of legacy `approval_status` alone (the Step 4 gate at `:358`).
- [[10-ap-review-observability]] — Approve/Reject events feed `AP Review Event`.
- [[14-closure-audit-retention]] — `Auditor (Read Only)` role + `decision_by`/`decision_at` already captured feed the audit trail.

**Shared primitives this spec introduces** (other specs may reference): the three new Roles (`AP Clerk`, `Treasury Approver`, `Auditor (Read Only)`), the optional `AP Approval Matrix` doctype, and the two `Workflow` fixtures.

**Estimated size:** **L** (per IMPLEMENTATION-PLAN units) — two Workflow fixtures + two new fields + a new doctype + three Roles + a non-trivial migration of the existing approval engine (adapter + wrapper re-point + cascade gate) + the SoD backstop, with a full positive/negative/edge test matrix and a clean-room runbook.
