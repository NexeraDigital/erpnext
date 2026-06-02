---
spec: 05-supplier-resolution
title: Supplier Resolution (3-tier) + Gated Creation
plan_step: Step 4 — Supplier Resolution
stream: both
status: Done
depends_on: [01-foundations-settings-async-idempotency, 04-extraction-confidence-line-items]
related: [00-overview, 02-intake-stream-tagging, 06-gl-coding-tax-costcenter, 07-classification-doctype-branching, 08-validation-gates, 09-confidence-routing, 10-ap-review-observability, 11-approval-sod-workflow]
---

# 05 — Supplier Resolution (3-tier) + Gated Creation
> _Revised 2026-05-31: applied native-vs-custom review findings; added Playwright UI test plan (§7.3)._
> _Revised 2026-06-02: re-visioned automation-first ([[00-overview]] "Guiding principle")._

> [!info] Automation-first stance
> **Flows with no human:** the 3-tier resolver (alias → exact → fuzzy) auto-resolves the common case — a known vendor variant hits the *learning* alias table at Tier 1, a new variant of a known vendor is caught by Tier-2 fuzzy — and on Stream R an unresolved vendor posts soft against Unmapped Card Spend without ever pausing. No human touches a resolvable supplier.
> **Single escalation seam:** an **unknown vendor on an INVOICE (Stream I)** blocks payment — the one correct control (no payable against an unknown vendor), preserved exactly. Receipts (Stream R) stay soft. Everything else auto-advances.
> **Automation growth target:** today a confident-but-unknown vendor *dead-stops* at a human because the gated auto-create request **defaults OFF** (`enable_gated_supplier_creation=0`) — so a human must both *notice* the unknown **and** *file* the request. The target is to **default the gate ON for high-OCR-confidence vendor names**: the system auto-files the `Supplier Master Change Request` (Draft), and the human only **approves** it (SoD preserved). The alias table then learns the mapping (OD-05-3) so the next variant resolves at Tier 1 with no human at all. The escalation shrinks from "notice + file + approve" to a single approval click, and trends toward zero as aliases accrete.

## 1. Summary
This spec builds a three-tier supplier resolver — deterministic alias table, fuzzy match, then a **gated** create-new-supplier request — that replaces today's single-tier `_match_supplier`, while preserving the existing **never-auto-create** guarantee. It serves **both** streams but diverges sharply: on **Stream I** an unresolved supplier is a *blocking* in-process step (no payable against an unknown vendor); on **Stream R** it is a *soft* flag (the JE posts to an "Unmapped Card Spend" account with the raw vendor string as memo). It implements plan **Step 4**. Current-state delta: today there is exactly one tier (exact name → unique `supplier_name` → Unknown/Ambiguous) at `ap_invoice_capture.py:975-1002`, no alias table, no fuzzy match, no creation gate, and no stream awareness anywhere in the fork.

## 2. Plan alignment

From `docs/planning/workflow-v2-plan.md` **Step 4 — Supplier Resolution**:

> "The extracted vendor string is resolved to an ERPNext Supplier record through a three-tier match. First, a deterministic alias table catches known variants (`AMZN Mktp US*4Z9` → `Amazon`). Second, fuzzy matching against existing suppliers handles new variants of known vendors. Third, if no match is found and confidence is high enough, the system queues a 'create new supplier' request for reviewer approval — auto-creating suppliers without a gate is a known data-quality hazard and a fraud vector."

> **ERPNext reality check:** "ERPNext ships the Supplier doctype natively … but it does **not** ship an approval gate on Supplier creation … The 'reviewer approval' gate described above is a control we build on top, not a native feature we enable."

> "For **Stream I** specifically, an unresolved supplier is **a blocking in-process step**, not a post-hoc cleanup: a payable cannot be created against an unknown vendor, so the gated supplier-creation request short-circuits step 5 onward and the invoice waits in the review queue until the supplier is either approved or the document is rejected back to the sender. For **Stream R** (already-paid card receipts), an unresolved supplier is a softer flag — the GL impact already happened on the card, so the JE can post against a generic 'Unmapped Card Spend' expense account with the original vendor string preserved as a memo, and supplier mapping happens out-of-band without blocking reconciliation."

Control-Summary row this spec implements:

| Control | Where it lives | Why it matters |
|---|---|---|
| **Gated supplier creation (blocking on Stream I)** | Step 4 | Prevents master-data pollution and fraud; payable cannot be created without a known vendor |

**Stream R vs Stream I difference here (explicit):**
- **Stream I (Invoice, unpaid):** Unknown/Ambiguous supplier → `validation_status=BLOCKED`, `action_required=1`; the capture waits in review. If Tier-3 queued a `Supplier Master Change Request`, that request must be approved (and post a Supplier) before re-validation can flip the capture to `Validated`. This generalizes today's behavior, which already treats every unknown as blocking.
- **Stream R (Card Spend, already paid):** Unknown supplier is **non-blocking** — `validation_status=VALIDATED` with a warning recorded in `validation_result`; the raw vendor string is preserved verbatim for the downstream Stream-R Journal Entry, whose posting (owned by [[07-classification-doctype-branching]]) targets `settings.unmapped_card_spend_account` with the vendor string as the line memo. Mapping happens out-of-band; it never holds up the 72h SimpleFIN reconciliation SLA.

Tier-2/Tier-3 disagreement and the unknown-supplier rate are tuning signals consumed by [[10-ap-review-observability]] (root-cause tag `supplier_unmapped`).

## 3. Current state

Single-tier resolver, **no auto-create** — this is the invariant the new design must keep:

`_match_supplier(supplier_name: str | None) -> tuple[str | None, str]` at `erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.py:975-1002`. In order:
1. `None`/blank candidate → `(None, "Unknown")`. Constants: `SUPPLIER_MATCH_NOT_VALIDATED="Not Validated"` (py:48), `SUPPLIER_MATCH_MATCHED="Matched"` (py:49), `SUPPLIER_MATCH_UNKNOWN="Unknown"` (py:50), `SUPPLIER_MATCH_AMBIGUOUS="Ambiguous"` (py:51).
2. `frappe.db.exists("Supplier", candidate)` (exact PK/name) → `(candidate, "Matched")` (py:989-990).
3. `frappe.get_all("Supplier", filters={"supplier_name": candidate}, pluck="name")`: `len==1` → Matched; `len>1` → Ambiguous; `len==0` → Unknown (py:992-1002).

**No branch ever creates a Supplier.** This is the no-auto-create guarantee.

Caller / orchestration: `validate_for_purchase_invoice(capture, actor=None, source=None, save=True)` at `ap_invoice_capture.py:1020-1102`. It requires `status == STATUS_CONFIRMED` (raises `CaptureValidationError`, py:1041-1047), computes `final_supplier_value = (capture.final_supplier or "").strip() or None` (py:1049), calls `_match_supplier`, writes `capture.matched_supplier` / `capture.supplier_match_status` (py:1051-1052), and appends to `issues[]`: Unknown → "Supplier '{0}' is unknown — AP correction required (no auto-create)." (py:1066-1071); Ambiguous → "Supplier '{0}' is ambiguous — multiple existing Suppliers share this name." (py:1072-1077). Any issue ⇒ `validation_status=BLOCKED` + `action_required=1` (py:1083-1089); else `VALIDATED` (py:1090-1098). **No stream branching exists today** — every unknown is treated identically (effectively the future Stream-I blocking path).

Capture DocType supplier/validation fields (auto-generated DF block, `ap_invoice_capture.py:185-229`): `matched_supplier` (`DF.Link`, py:191), `supplier_match_status` (`DF.Literal["Not Validated","Matched","Unknown","Ambiguous"]`, py:192-194), `validation_status` (`DF.Literal["Not Validated","Validated","Blocked"]`, py:203), `validation_result` (`DF.SmallText`, py:204). `proposed_supplier` (`DF.Data`, py:171) and `final_supplier` (`DF.Link`) carry the OCR proposal / AP-reviewed value. **There is no `supplier_match_confidence`, no `supplier_change_request`, and no `proposed_supplier_confidence` field today** (grep confirmed empty). **No `stream` field exists anywhere in the fork.**

Settings: `AP Closed Loop Settings` is a Single at `erpnext/accounts/doctype/ap_closed_loop_settings/`. Existing fields: `default_company/default_item_code/default_expense_account/default_cost_center/default_warehouse/default_uom` (Links), `ocr_provider`, `ocr_model`, `ocr_fallback_model`, `ocr_confidence_threshold` (Float), `ocr_max_file_mb` (Int), `ocr_force_reextract` (Check). The established extension pattern is `get_promote_defaults()` (`ap_closed_loop_settings.py:85-108`) reading via `frappe.db.get_singles_dict` and consumed by `_coalesce_defaults` (`ap_invoice_capture.py:1116-1145`). **No `unmapped_card_spend_account`, no fuzzy-threshold, no auto-create flag exist yet.**

OCR confidence source for the Tier-3 gate: the Anthropic extractor's tool schema emits `confidence_per_field` including `supplier_name` (`erpnext/accounts/ap_closed_loop/extractors/anthropic.py:152` schema; `_to_extraction_result` at ~py:420-431 reads it). **Correction to the brief:** the per-field confidence is consumed only to populate the `ambiguous_fields` *set* and is then **dropped** — it is never threaded into `ExtractionResult` as a numeric value (`ExtractionResult` at `extractors/base.py:41-66` carries `proposal`, `missing_fields`, `ambiguous_fields`, `provider_name`, `raw_response` — **no numeric confidence map**). `run_extraction` persists `proposed_*` fields at `ap_invoice_capture.py:790-834` but writes **no** supplier confidence. So Tier-3's "OCR supplier confidence ≥ threshold" gate has **no data today**; persisting it is a hard dependency on [[04-extraction-confidence-line-items]] (or a minimal field added here — see §8).

Approval/threshold precedent to mirror: `request_approval` + `_resolve_approval_threshold` (`ap_invoice_capture.py:1243-1318`), with the SoD guard `frappe.only_for(capture.assigned_approver_role …)` in `record_manager_decision` (py:1336). Capture fields `approval_threshold` (`DF.Float`, py:217) and `approval_threshold_source` (py:218) show the Settings-driven-threshold + role-gated-decision pattern the gated-creation flow should follow.

Whitelisted-wrapper convention to mirror: `validate_for_purchase_invoice_for(capture, source=None)` (py:1677-1683) and `promote_to_purchase_invoice_for(capture, defaults=None)` (py:1686-1702) — thin `@frappe.whitelist()` wrappers that normalize string args, call the pure function, then `_kick_next_step()`, and return a name (str). Back-compat alias convention: `run_fake_extraction = run_extraction` at py:840.

## 4. Upstream grounding

1. **ERPNext Supplier manual** — <https://docs.frappe.io/erpnext/user/manual/en/supplier> (verified). Confirms Supplier creation is "New → enter name → select supplier group → Save", with **no** approval/review workflow gating creation by default. This is the premise for building `Supplier Master Change Request`. Quote: *"Go to the Supplier list and click on New. Enter a name for the supplier. Select the supplier group … Save."* (no approval workflow required by default).
2. **Supplier DocType JSON** — <https://github.com/frappe/erpnext/blob/version-15/erpnext/buying/doctype/supplier/supplier.json> (verified). Confirms `autoname: "naming_series:"` with series option `SUP-.YYYY.-`; `supplier_name` is `Data`, `reqd:1`; `supplier_group` is `Link`, `supplier_type` is `Select(Company/Individual/Partnership/...)` reqd; and there is **no** `workflow_state` or approval field on Supplier. These are the exact native fields a `proposed_payload` JSON must populate when an Approved request creates a Supplier. Quote: *"autoname: 'naming_series:'; naming_series option 'SUP-.YYYY.-'; supplier_name fieldtype Data, reqd:1."*
3. **DocType naming (v15)** — <https://docs.frappe.io/framework/v15/user/en/basics/doctypes/naming> (verified). Confirms exact syntax for the new request doctype's series: "By Naming Series" requires a field literally named `naming_series`; pattern `PRE.#####` → `PRE00001`. Also documents "By fieldname", "Expression" (dotted `.{fieldname}.` form), and "By script" (`autoname` method). Quote: *"The naming pattern is derived from a specific field in the document (usually `naming_series`)… Field value PRE.##### → PRE00001, PRE00002. Your DocType must include a field named `naming_series`."*
4. **Workflow DocType JSON** — <https://github.com/frappe/frappe/blob/version-15/frappe/workflow/doctype/workflow/workflow.json> (verified). Confirms the fields the **spec-11-owned** Workflow record uses to gate the request: `document_type` (Link → DocType), `is_active` (Check), `override_status` (Check), `send_email_alert` (Check), `workflow_state_field` (Data, default `workflow_state`; auto-creates a hidden Custom Field on the target if absent), `states` (Table → Workflow Document State), `transitions` (Table → Workflow Transition). Confirms the request doctype needs a `workflow_state` field (or lets Frappe inject one) for the Draft → Pending Approval → Approved → Posted states. Quote: *"workflow_state_field default 'workflow_state' — 'Field that represents the Workflow State of the transaction (if field is not present, a new hidden Custom Field will be created)'."*
5. **Bank Account DocType JSON** — `erpnext/accounts/doctype/bank_account/bank_account.json` (verified in-repo). Grounds the Bank-detail correction: the real bank fields live here — `iban` (`:133`), `bank_account_no` (`:145`), `branch_code` (`:202`), `bank` (Link → Bank, `:59`) — and the row is tied to a vendor by `party_type` (Link → DocType, `:112`) + `party` (Dynamic Link, `:122`). `Supplier` itself exposes only `default_bank_account` (Link → Bank Account, `supplier.json:111-114`); SWIFT is on `Bank` (`bank.json:41`). So "Update Bank Details" mutates a `Bank Account`, not the Supplier master.

**Version note:** this branch is `russ/migrateToV16` (`frappe >=16,<17`, `pyproject.toml:44`). Grounding cites v15 docs/source per CLAUDE.md priority and because v16 docs are sparse. `autoname="naming_series:"`, the naming patterns, and the Workflow field names are stable v15→v16, but the build phase MUST verify against the installed frappe (`bench version`; inspect the local `frappe/workflow/doctype/workflow/workflow.json` and `frappe/core/doctype/docfield/docfield.json`) before finalizing — in particular, avoid the deprecated "Expression (Old Style)" braces; use the dotted `.{fieldname}.` form. `rapidfuzz~=3.14.3` is already declared (`pyproject.toml:14`) — **do not add it**.

## 5. Design

### 5.1 Data model

#### NEW master DocType — `AP Supplier Alias` (Tier 1; non-submittable)

Module: Accounts. `autoname`: `format:ALIAS-{#####}` (or script autoname; uniqueness is enforced by a unique index on `(alias_pattern, match_type)`, not by the name). `track_changes: 1`.

| fieldname | fieldtype | options / default | purpose |
|---|---|---|---|
| `canonical_supplier` | Link | → Supplier, `reqd:1` | the Supplier this alias resolves to |
| `alias_pattern` | Data | `reqd:1` | the vendor-string pattern, e.g. `AMZN Mktp US*` |
| `match_type` | Select | `exact`\|`glob`\|`regex`, default `glob` | how `alias_pattern` is compared to the candidate |
| `is_active` | Check | default `1` | inactive aliases never match |
| `priority` | Int | default `0` | tie-break when two patterns of the same type could match (lower = earlier) |
| `notes` | Small Text | optional | human rationale for the alias |
| `source_capture` | Link | → AP Invoice Capture, optional | provenance when the alias was born from an approved Create request |

Permissions: read for `Accounts User`, `Accounts Manager`, `Auditor (Read Only)` (new role, see bible); create/write/delete for `Accounts Manager` only (aliases are master data — clerks propose via Tier-3, managers curate the table). Match precedence is **exact > glob > regex**, then `priority` asc, then `name` asc. `glob` uses `fnmatch.fnmatchcase` (case-sensitive on the literal). `regex` is compiled defensively (catch `re.error` → skip that alias + log; a bad pattern must never block validation).

#### NEW submittable DocType — `Supplier Master Change Request` (Tier 3; `is_submittable: 1`)

Module: Accounts. The gated vehicle for **all** supplier-master mutations — creation here, and (reused by [[08-validation-gates]] / [[11-approval-sod-workflow]]) bank-detail / payment-term / disable changes. `autoname="naming_series:"`. `track_changes: 1`. The Workflow record itself (states/transitions/roles) is owned by [[11-approval-sod-workflow]]; this spec owns the DocType JSON and the controller.

**Bank-detail target (material correction — verified against source).** "Update Bank Details" does **NOT** write fields on the `Supplier` record. Current ERPNext `Supplier` carries **no** inline bank fields — only `default_bank_account` (Link → `Bank Account`, `erpnext/buying/doctype/supplier/supplier.json:111-114`). The actual bank fields — `iban`, `bank_account_no`, `branch_code`, `bank` — live on the **`Bank Account`** doctype (`erpnext/accounts/doctype/bank_account/bank_account.json:133` iban, `:145` bank_account_no, `:202` branch_code, `:59` bank), and **SWIFT** lives on the `Bank` doctype (`erpnext/accounts/doctype/bank/bank.json:41` `swift_number`). Therefore the `change_type = "Update Bank Details"` variant must **CREATE or EDIT a `Bank Account` row** keyed by `party_type = "Supplier"`, `party = <target_supplier>` (the `party_type` Link + `party` Dynamic Link on `bank_account.json:112-125`) — optionally setting the Supplier's `default_bank_account` to point at it — and must **never** attempt to write bank fields onto the Supplier master. The `Treasury Approver` role (see [[11-approval-sod-workflow]]) gates these `Bank Account` mutations.

| fieldname | fieldtype | options / default | purpose |
|---|---|---|---|
| `naming_series` | Select | option `SMCR-.YYYY.-.#####` (default) | required field for `autoname="naming_series:"` |
| `change_type` | Select | `Create`\|`Update Bank Details`\|`Update Payment Terms`\|`Disable`, `reqd:1` | which master mutation this requests |
| `requested_supplier_name` | Data | — | the unresolved vendor string (Create); display name for Update/Disable |
| `target_supplier` | Link | → Supplier | empty for Create; populated for Update/Disable variants (and for Update Bank Details, where it keys the `Bank Account` row via `party`) |
| `proposed_payload` | Code | options `JSON` | the fields to write on approval (Supplier fields for Create/Disable; **`Bank Account` fields for Update Bank Details** — see payload contract below) |
| `evidence_capture` | Link | → AP Invoice Capture | the originating capture (drives re-validation on Posted) |
| `requested_by` | Link | → User, default `frappe.session.user` (set on insert) | the requester — anchors the SoD check |
| `approver_role` | Link | → Role | the role permitted to approve (default from settings, see §5.5) |
| `workflow_state` | Select | `Draft`\|`Pending Approval`\|`Approved`\|`Posted`\|`Rejected`, default `Draft` | declared explicitly so it shows on the form; Workflow record (spec 11) drives transitions |
| `decision_by` | Link | → User | who approved/rejected |
| `decision_at` | Datetime | — | when the decision was recorded |
| `decision_reason` | Small Text | — | free-text rationale / rejection reason |
| `created_supplier` | Link | → Supplier | set after Posted (idempotency + traceability) |

`proposed_payload` JSON contract (Create) — keys are native Supplier fieldnames verified from upstream supplier.json: `supplier_name` (reqd), `supplier_group` (reqd), `supplier_type` (reqd, one of the native Select options), and optional `country`, `default_currency`, `tax_id`, plus Party-Account defaults handled by [[06-gl-coding-tax-costcenter]]. The controller writes only an allow-listed set of keys (never arbitrary fields) to bound the blast radius.

`proposed_payload` JSON contract (**Update Bank Details**) — keys are native **`Bank Account`** fieldnames (NOT Supplier fields), verified from `bank_account.json`: `account_name` (Data, `:41`), `bank` (Link → Bank, `:59`), `iban` (`:133`), `bank_account_no` (`:145`), `branch_code` (`:202`), plus optional `account` (Link → Account, `:51`) and `is_company_account`/`is_default` flags. The party linkage (`party_type="Supplier"`, `party=target_supplier`) is **not** part of the payload — the controller sets it from `target_supplier` so the requester cannot retarget the row. On approval the controller upserts the `Bank Account` (create if none exists for that party, else edit the existing row) and may set `Supplier.default_bank_account` to the resulting row; SWIFT, if present, is written to the linked `Bank` (`bank.json:41`), not the `Bank Account`. Same allow-list discipline as Create.

Permissions: create/read/write for `Accounts User` and `Accounts Manager` (a clerk can raise a request); **submit/cancel and the approve transition** restricted to the `approver_role` (default `Accounts Manager`; bank-detail changes may demand `Treasury Approver`, a new role — see bible). `Auditor (Read Only)` gets read. The submit/approve gate is enforced both by the Workflow transition's Allowed Role (spec 11) **and** by the controller's SoD backstop (§5.3, §5.5).

#### CHANGED — capture DocType additions (`ap_invoice_capture.json` + DF block ~py:185-229)

| fieldname | fieldtype | options / default | purpose |
|---|---|---|---|
| `supplier_match_confidence` | Float | default `0` | the chosen Tier-2 score (0–100) that drove the match; 100.0 for a Tier-1 alias hit |
| `supplier_match_tier` | Select | `None`\|`Alias`\|`Fuzzy`\|`Exact`, default `None` | which tier resolved (audit + observability) |
| `supplier_change_request` | Link | → Supplier Master Change Request | back-link to the gated request when Tier-3 queues one |
| `proposed_supplier_confidence` | Float | default `0` | persisted Anthropic `supplier_name` confidence (0–1) at extract time; feeds the Tier-3 gate. Owned by [[04-extraction-confidence-line-items]]; if 04 lands later, add a minimal version here (see §8) |

`supplier_match_status` `DF.Literal` (py:192-194) is **extended** to add `"Alias"` so Tier-1 hits are visibly distinct: `["Not Validated","Matched","Alias","Unknown","Ambiguous"]`. (See §8 — distinct `Alias` value is a decision-to-lock; recommended default is **yes**.)

Stream field — **net-new to the fork.** The capture-level stream enum is defined **once** by [[02-intake-stream-tagging]] (field `stream`, `DF.Literal["Stream R","Stream I"]` or similar). This spec **consumes** it. If 02 has not landed when this spec is built, introduce the field here and hand ownership to 02 on merge (see §8 / §9). Constant names this spec references: `STREAM_INVOICE` ("Stream I") and `STREAM_CARD_SPEND` ("Stream R").

#### CHANGED — `AP Closed Loop Settings` additions (Single; `ap_closed_loop_settings.json`)

| fieldname | fieldtype | options / default | purpose |
|---|---|---|---|
| `supplier_fuzzy_threshold` | Float | default `90` | rapidfuzz `token_set_ratio` cutoff (0–100) |
| `supplier_autocreate_confidence_threshold` | Float | default `0.85` | OCR supplier-confidence gate for Tier-3 (0–1) |
| `enable_gated_supplier_creation` | Check | default `0` | Tier-3 fires only when on |

> **2026-06-02 automation-first reconsideration (default flip — planned, not yet built).** The shipped default `enable_gated_supplier_creation=0` is the automation gap called out in [[00-overview]]'s doctrine table (row 05): with the gate OFF, a confident-but-unknown vendor dead-stops at a human who must *both* notice the unknown *and* hand-file the request. The automation-first target is to **default the gate ON, scoped to high-OCR-confidence names** — i.e. ship `enable_gated_supplier_creation=1` (or an equivalent `autocreate_request_mode="on-high-confidence"`) so Tier-3 **auto-files** the Draft `Supplier Master Change Request` whenever `proposed_supplier_confidence >= supplier_autocreate_confidence_threshold` (0.85). **No control is weakened:** the request is still only a *Draft* — a human (a different user, per SoD) still **approves** it before any Supplier exists, and the Stream-I capture stays BLOCKED until that approval posts. The human's job shrinks from "notice + file + approve" to a single approve/reject. The shipped OFF default stays documented (above) as the as-built behavior; flipping it is a planned slice gated by the new ACs below. Owner: AP product lead. Lock: before the auto-create-default slice.
| `supplier_change_approver_role` | Link | → Role, default `Accounts Manager` | default `approver_role` stamped onto new requests |
| `unmapped_card_spend_account` | Link | → Account | Stream-R JE target for unresolved card spend |

`unmapped_card_spend_account` is validated at settings save (Account exists, `is_group=0`, company scope sane) so Stream-R card spend can never be silently swallowed. Exposed via a new helper `get_supplier_resolution_settings()` mirroring `get_promote_defaults()` (`ap_closed_loop_settings.py:85-108`), returning the five values with documented defaults and reading via `frappe.db.get_singles_dict` (same `set_missing_values` footgun avoidance as the existing helper).

### 5.2 Endpoints

All new whitelisted methods follow the existing `*_for` convention (`ap_invoice_capture.py:1677-1702`): normalize string args, call the pure function, `_kick_next_step()` where a cascade continuation applies, return the capture/request **name** (str).

```python
# erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.py

@frappe.whitelist()
def resolve_supplier_for(capture: str, stream: str | None = None) -> str:
    """Form-button wrapper: re-run the 3-tier resolver + validation for a capture.
    `stream` overrides the capture's stored stream when provided (string-normalized)."""

# erpnext/accounts/doctype/supplier_master_change_request/supplier_master_change_request.py

@frappe.whitelist()
def approve_supplier_master_change_request(request: str, actor: str | None = None) -> str:
    """Approve a Draft/Pending request: enforce approver_role + SoD (requester != approver),
    drive Approved -> Posted, create the Supplier from proposed_payload (idempotent),
    set created_supplier, then re-run validate_for_purchase_invoice(evidence_capture).
    Returns the request name."""

@frappe.whitelist()
def reject_supplier_master_change_request(request: str, reason: str, actor: str | None = None) -> str:
    """Reject a request with a reason; drives -> Rejected, records decision_by/at/reason.
    On Stream I the linked capture stays BLOCKED (no payable). Returns the request name."""
```

Pure functions behind the wrappers (not whitelisted; called by cascade + tests):
- `_resolve_supplier(supplier_name: str | None, *, stream: str | None = None) -> dict` returning `{"matched_supplier", "match_status", "confidence", "tier", "alias_id", "competing": [...]}`.
- `_match_supplier(supplier_name)` is **kept** as a thin back-compat wrapper returning the existing `(name, status)` tuple, so current callers/tests stay green (mirrors `run_fake_extraction = run_extraction`, py:840).
- `queue_supplier_create_request(capture, candidate, payload) -> str` (Tier-3) — creates the Draft `Supplier Master Change Request`, links `capture.supplier_change_request`, returns request name. **Never creates a Supplier.**

String/normalization convention: booleans arrive as `"1"/"true"/"yes"`-style strings (see `record_manager_decision_for`, py:1727-1728) and are coerced; `stream` is `.strip()`-ed and validated against the enum; JSON args (`proposed_payload`) are `json.loads`-ed when passed as a string (see `promote_to_purchase_invoice_for`, py:1692-1696).

### 5.3 Logic

**Resolver — extend (do not replace) `_match_supplier` into `_resolve_supplier`.** Preserve the never-auto-create guarantee in every branch.

1. Normalize: `candidate = (supplier_name or "").strip() or None`. If `None` → `{"match_status": "Unknown", "confidence": 0, "tier": None, "matched_supplier": None}`. (Mirrors py:982-987.)
2. **Tier 1 — alias (deterministic, highest precedence).** Query active `AP Supplier Alias` (`is_active=1`). Evaluate in precedence order (exact, then glob, then regex; within a type, `priority` asc):
   - `exact`: `pattern == candidate`.
   - `glob`: `fnmatch.fnmatchcase(candidate, pattern)` — `AMZN Mktp US*` matches `AMZN Mktp US*4Z9`.
   - `regex`: `re.fullmatch(pattern, candidate)` wrapped in `try/except re.error` → on error, skip the alias and `frappe.log_error` (never raise into validation).
   Collect the set of **distinct** `canonical_supplier` values that match.
   - exactly one distinct supplier → `{"matched_supplier": supplier, "match_status": "Alias", "confidence": 100.0, "tier": "Alias", "alias_id": <name>}`.
   - >1 distinct supplier → `{"match_status": "Ambiguous", ...}` with the competing supplier names + alias names recorded in `competing` (surfaced in `validation_result`).
   - none → fall through to Tier 2.
3. **Tier 2 — fuzzy (only if Tier 1 empty).** First preserve current exact behavior: `frappe.db.exists("Supplier", candidate)` → Matched (`tier="Exact"`, confidence 100); unique `supplier_name==candidate` → Matched (`tier="Exact"`). Then, only if neither hit, run rapidfuzz: `from rapidfuzz import fuzz; score = fuzz.token_set_ratio(candidate, s.supplier_name)` over the active Supplier `supplier_name` set (disabled suppliers excluded). Collect `score >= settings.supplier_fuzzy_threshold` (default 90):
   - exactly one ≥ threshold → `{"matched_supplier": that, "match_status": "Matched", "confidence": score, "tier": "Fuzzy"}`.
   - >1 ≥ threshold → `{"match_status": "Ambiguous", "confidence": top_score, "competing": [tied names]}` (mirrors the "multiple existing Suppliers share this name" message, py:1072-1077).
   - zero ≥ threshold → `{"match_status": "Unknown", "confidence": best_score_seen, "tier": None}`.
   The chosen score is carried into `capture.supplier_match_confidence`.
4. **Tier 3 — gated creation (only on `Unknown`, only in the caller `validate_for_purchase_invoice`).** Fire iff **all**: `settings.enable_gated_supplier_creation` is on **AND** `capture.proposed_supplier_confidence >= settings.supplier_autocreate_confidence_threshold` **AND** no open `supplier_change_request` already exists for this capture (idempotency). Then call `queue_supplier_create_request(...)`: build `proposed_payload` from the OCR proposal (allow-listed keys), `frappe.get_doc({"doctype": "Supplier Master Change Request", "change_type": "Create", ...})`, `.insert()` (stays `Draft`), set `capture.supplier_change_request = req.name`. **No Supplier is created.** If the gate is off or confidence is below threshold, no request is created (the capture simply stays Unknown).

**Approval → Supplier creation (`approve_supplier_master_change_request`).**
1. Load request. Guard: `workflow_state in ("Draft","Pending Approval")` else raise `CaptureApprovalError` ("already decided").
2. **Role gate:** `frappe.only_for(req.approver_role or settings.supplier_change_approver_role or "Accounts Manager")` (mirrors py:1336).
3. **SoD backstop:** if `actor or frappe.session.user == req.requested_by` → raise `CaptureApprovalError("Segregation of duties: the requester may not approve their own supplier change request.")`. (Mirrors the over-threshold self-approval concern at py:1334-1336; also enforced in the spec-11 Workflow transition Allowed Role.)
4. **Idempotency:** if `req.created_supplier` is set and the Supplier exists → no-op (return name); never create a duplicate.
5. For `change_type == "Create"`: `frappe.get_doc({"doctype": "Supplier", **allowlisted(proposed_payload)}).insert()`; set `req.created_supplier`, `decision_by`, `decision_at`, `workflow_state="Posted"`. The other variants write to **different targets** (bodies owned by [[08-validation-gates]]/[[11-approval-sod-workflow]], but the dispatch + SoD live here): **Update Bank Details** upserts a **`Bank Account`** row keyed by `party_type="Supplier"`, `party=target_supplier` (NOT the Supplier master — see the Bank-detail correction in §5.1) and gates on `Treasury Approver`; **Payment Terms / Disable** write to the `Supplier` (`target_supplier`).
6. **Re-validate:** call `validate_for_purchase_invoice(req.evidence_capture)` so the capture re-resolves (Tier-1/2 now find the new Supplier) and, on Stream I, flips `BLOCKED → VALIDATED`. Optionally `queue_supplier_create_request` may also persist the new mapping as an `AP Supplier Alias` (`source_capture` set) so future variants resolve at Tier 1 (decision-to-lock, §8).
7. Persist via the submit/workflow action (idempotency keys per [[01-foundations-settings-async-idempotency]] guard the Supplier insert against retried jobs).

**Stream-aware branching — inside `validate_for_purchase_invoice` (around py:1066-1098).**
1. After `_resolve_supplier`, read the capture stream (`stream` field from [[02-intake-stream-tagging]]).
2. **Stream R + `match_status == "Unknown"` → SOFT path (early branch, before the blocking append):** do **not** append the unknown-supplier issue. Record a warning in `validation_result` ("Unmapped card spend — vendor '{0}' preserved as memo; posting to Unmapped Card Spend."), keep `supplier_match_status="Unknown"`, and proceed to `VALIDATED` if no other issue exists. The raw vendor string is left on `final_supplier`/`proposed_supplier` verbatim for the Stream-R JE (memo contract owned by [[07-classification-doctype-branching]], which reads `settings.unmapped_card_spend_account`). Ambiguous on Stream R is treated the same soft way unless policy says otherwise (§8).
3. **Stream I (or stream unset) + Unknown/Ambiguous → BLOCKING path (today's behavior, py:1066-1089):** append the issue ⇒ `validation_status=BLOCKED`, `action_required=1`. If a Tier-3 request was queued, set `action_required_reason = "Pending supplier approval (request {req})"` and keep BLOCKED until the request posts and re-validation flips it.

Persisted on every resolution: `matched_supplier`, `supplier_match_status`, `supplier_match_tier`, `supplier_match_confidence`, and (when Tier-3 fires) `supplier_change_request`. `validation_status`/`validation_result`/`action_required` as above.

### 5.4 Cascade & stream-awareness

This spec touches the existing cascade at the **validation hop** (`_determine_next_step` Step 2, `ap_invoice_capture.py:338-343`): `ocr_status == Confirmed` and `validation_status in (None, Not Validated)` → `validate_for_purchase_invoice_for`. The richer resolver runs **inside** that step; the cascade graph is unchanged for the happy path.

- **Stream I, resolved (Matched/Alias):** cascade proceeds exactly as today — validation → (manual Promote seam, py:345-347) → approval routing → … No new pause point.
- **Stream I, Unknown/Ambiguous:** `validate_for_purchase_invoice` sets `BLOCKED` + `action_required`; `_determine_next_step` returns `None` (no auto-step matches a blocked capture) and the capture **pauses in review**. This is a *new pause reason* but not a new cascade branch. When `approve_supplier_master_change_request` posts the Supplier, it re-invokes `validate_for_purchase_invoice` which flips to `VALIDATED`; the caller then `_kick_next_step()`s to resume the cascade toward promotion.
- **Stream R, Unknown:** validation reaches `VALIDATED` (soft), so the cascade **auto-advances** to the Stream-R posting path (Journal Entry, owned by [[07-classification-doctype-branching]]) — no approval/payment hops (Stream R skips steps 10/11 per the plan). The `_determine_next_step` Stream-R divergence (JE vs PI promotion) is owned by [[07-classification-doctype-branching]]; this spec only guarantees the soft path does not block.

Async: re-validation and Tier-3 request creation are synchronous within the triggering request (cheap DB work); the Supplier insert on approval and any downstream re-cascade ride the existing `frappe.enqueue` path (`enqueue_after_commit=True`, `deduplicate=True`, per-capture-per-step `job_id`; `now=True` under `in_test`), per `_enqueue_next` (py:368-404).

### 5.5 Cross-cutting

- **Permissions / SoD:** `Supplier Master Change Request` approval is gated by `approver_role` via `frappe.only_for` **and** a requester≠approver backstop in the controller (independent of the spec-11 Workflow transition Allowed Role). New roles `Treasury Approver` and `Auditor (Read Only)` (bible) appear here: Treasury for bank-detail change approvals, Auditor read-only on the request + alias tables. Alias-table writes are `Accounts Manager`-only.
- **Idempotency ([[01-foundations-settings-async-idempotency]]):** the Supplier insert on approval uses an idempotency key (e.g. `smcr:{request_name}`) recorded in the `AP Posting Ledger`, and `created_supplier` is checked first — a retried approval job cannot create a duplicate Supplier (preserving the no-double-post invariant the plan calls for "everywhere"). Tier-3 request creation is idempotent on `(evidence_capture, change_type, open)`.
- **Observability ([[10-ap-review-observability]]):** every Unknown/Ambiguous outcome and every Tier-3 request emits an `AP Review Event` with reason code `supplier_unmapped`; the Tier-2 vs Tier-1 vs stream-tag disagreement feeds the weekly "Top step-9 root causes" report. The resolver records the chosen tier (`supplier_match_tier`) and score (`supplier_match_confidence`) so the dashboard can show alias-hit-rate vs fuzzy-hit-rate vs gated-create-rate.
- **Async/enqueue:** as in §5.4 — no new queue; reuse `_enqueue_next`.

## 6. Acceptance criteria

- **AC-05-1 (Tier-1 exact):** an `AP Supplier Alias` with `match_type=exact`, `alias_pattern="Amazon Web Services"`, `canonical_supplier=AWS` resolves a candidate `"Amazon Web Services"` → `matched_supplier=AWS`, `supplier_match_status="Alias"`, `supplier_match_confidence=100`, `supplier_match_tier="Alias"`.
- **AC-05-2 (Tier-1 glob — headline):** alias `glob "AMZN Mktp US*"` → Amazon resolves candidate `"AMZN Mktp US*4Z9"` → `matched_supplier=Amazon`, status `"Alias"`.
- **AC-05-3 (Tier-1 regex valid):** alias `regex "^STRIPE.*"` → Stripe resolves `"STRIPE PAYMENTS"` → Matched/Alias.
- **AC-05-4 (Tier-1 bad regex is safe):** an alias with `match_type=regex`, `alias_pattern="(unbalanced"` does **not** raise; it is skipped, logged, and resolution proceeds to Tier 2.
- **AC-05-5 (Tier-1 ambiguous):** two active aliases matching the same candidate but pointing to two **different** suppliers → `supplier_match_status="Ambiguous"`, both supplier names present in `validation_result`.
- **AC-05-6 (Tier-1 inactive ignored):** an alias with `is_active=0` never matches.
- **AC-05-7 (Tier-2 single hit):** with no alias and one Supplier scoring `token_set_ratio >= 90`, candidate resolves to that Supplier, `supplier_match_status="Matched"`, `supplier_match_confidence == score`, `supplier_match_tier="Fuzzy"`.
- **AC-05-8 (Tier-2 boundary):** a candidate scoring exactly `90` against one Supplier is `Matched` (cutoff is inclusive, `>=`).
- **AC-05-9 (Tier-2 multiple):** two Suppliers ≥ 90 → `Ambiguous`, both names in `validation_result`.
- **AC-05-10 (Tier-2 none):** zero Suppliers ≥ 90 → `Unknown`, `supplier_match_confidence` holds the best score seen.
- **AC-05-11 (regression — exact still wins):** `frappe.db.exists("Supplier", candidate)` and unique `supplier_name==candidate` still resolve to `Matched` exactly as py:989-998 (no alias, no fuzzy needed).
- **AC-05-12 (no-auto-create invariant):** for **any** Unknown resolution (Tier-2 zero-hit, Tier-3 gate off, Tier-3 gate on but request only queued), the `Supplier` row count is **unchanged**.
- **AC-05-13 (Stream I blocking):** Stream-I capture, Unknown supplier → `validation_status=BLOCKED`, `action_required=1` (regression of py:1066-1089).
- **AC-05-14 (Stream R soft):** Stream-R capture, Unknown supplier → `validation_status=VALIDATED`, **not** blocked, raw vendor string retained on `final_supplier`/`proposed_supplier`; `validation_result` carries the Unmapped-Card-Spend warning.
- **AC-05-15 (Tier-3 gate off):** `enable_gated_supplier_creation=0` + high `proposed_supplier_confidence` → **no** `Supplier Master Change Request` created.
- **AC-05-16 (Tier-3 gate on, confident):** `enable_gated_supplier_creation=1` + `proposed_supplier_confidence >= threshold` + Unknown → a **Draft** `Supplier Master Change Request` (`change_type=Create`) is created and `capture.supplier_change_request` links it; **no** Supplier yet.
- **AC-05-17 (Tier-3 gate on, not confident):** gate on but `proposed_supplier_confidence < threshold` → no request created.
- **AC-05-18 (approve creates Supplier + re-validates):** approving the Draft request (as a **different** user) creates a Supplier from `proposed_payload`, sets `created_supplier`, sets `workflow_state="Posted"`, and re-runs validation so the Stream-I capture flips `BLOCKED → VALIDATED` with `matched_supplier` set.
- **AC-05-19 (SoD negative):** the requester (`requested_by`) attempting `approve_supplier_master_change_request` on their own request → raises `CaptureApprovalError` (and creates no Supplier).
- **AC-05-20 (approver role negative):** a user lacking `approver_role` calling approve → `frappe.PermissionError` (via `frappe.only_for`).
- **AC-05-21 (approve idempotent):** re-calling approve on an already-`Posted` request does **not** create a second Supplier (`created_supplier` short-circuits).
- **AC-05-22 (settings helper defaults):** `get_supplier_resolution_settings()` on a fresh site returns `supplier_fuzzy_threshold=90`, `supplier_autocreate_confidence_threshold=0.85`, `enable_gated_supplier_creation=False`, `supplier_change_approver_role="Accounts Manager"`, and `unmapped_card_spend_account=None`.
- **AC-05-23 (unmapped account validated):** saving `AP Closed Loop Settings` with `unmapped_card_spend_account` pointing at a group account or a non-existent account → `frappe.throw` at save (fails loudly at config time).

**Automation-first planned ACs** (new 2026-06-02; gate-default-ON slice — see the §5.1 reconsideration and OD-05-9. These are `(planned)`, not yet built; do not tick in STATUS.md until verified):

- **AC-05-24 (built — T-018; gate defaults ON for high-confidence):** on a fresh site with the automation-first default shipped, a Stream-I Unknown supplier whose `proposed_supplier_confidence >= supplier_autocreate_confidence_threshold` **auto-files** a Draft `Supplier Master Change Request` (`change_type=Create`) and links `capture.supplier_change_request` **with no human action** — the human's only remaining step is approval. (Mirrors AC-05-16's outcome, but reached automatically rather than gated behind a setting an operator had to enable.)
- **AC-05-25 (built — T-018; low-confidence still no auto-file):** with the gate defaulting ON, a Stream-I Unknown supplier whose `proposed_supplier_confidence < supplier_autocreate_confidence_threshold` does **not** auto-file a request — it stays BLOCKED for a human to resolve manually (the escalation seam is preserved for genuinely uncertain names). (Mirrors AC-05-17 under the new default.)
- **AC-05-26 (built — T-018; control unchanged: still no Supplier without approval):** even with auto-filing ON, the no-auto-create invariant (AC-05-12) holds — the auto-filed request is Draft-only; `Supplier` row count is unchanged until a **different** user approves it (AC-05-18/AC-05-19 unchanged). Stream R remains soft (AC-05-14 unchanged).

## 7. Tests

### 7.1 Automated (`bench --site <site> run-tests --module <path>`)

Use `from frappe.tests import IntegrationTestCase`; roll back all DB writes in `tearDown` so suites are reentrant. Set `frappe.flags.in_test = True` and `frappe.flags.skip_ap_auto_progress` / `ap_auto_progress_enabled` as the existing suite does to control the cascade.

- **`erpnext.accounts.doctype.ap_invoice_capture.test_ap_invoice_capture`** (extend the existing module):
  - Resolver: AC-05-1..AC-05-11 (Tier-1 exact/glob/regex/bad-regex/ambiguous/inactive; Tier-2 single/boundary-90/multiple/none; exact-still-wins regression).
  - No-auto-create invariant: AC-05-12 — assert `frappe.db.count("Supplier")` unchanged across each Unknown path.
  - Stream branching: AC-05-13 (Stream I BLOCKED), AC-05-14 (Stream R soft, vendor string retained).
  - Tier-3 gate: AC-05-15 (off), AC-05-16 (on+confident→Draft request linked), AC-05-17 (on+not-confident→none).
  - Back-compat: assert `_match_supplier("X")` still returns the `(name, status)` tuple for the legacy callers.
- **`erpnext.accounts.doctype.supplier_master_change_request.test_supplier_master_change_request`** (new):
  - AC-05-18 approve happy path (creates Supplier from `proposed_payload`, sets `created_supplier`, re-runs validation flipping capture to Matched/Validated).
  - AC-05-19 SoD negative (requester==approver raises); AC-05-20 approver-role negative (missing role raises); blank `approver_role` falls back to settings default then `Accounts Manager`.
  - AC-05-21 idempotency (re-approve Posted → no duplicate Supplier).
  - Edge: `reject_supplier_master_change_request` keeps the Stream-I capture BLOCKED and records `decision_reason`.
- **`erpnext.accounts.doctype.ap_supplier_alias.test_ap_supplier_alias`** (new):
  - Each `match_type` resolves its key (exact/glob/regex); precedence exact>glob>regex when several could match.
  - Bad regex stored but skipped at match time (no raise); inactive alias never matches; alias → disabled Supplier is excluded.
- **`erpnext.accounts.doctype.ap_closed_loop_settings.test_ap_closed_loop_settings`** (extend):
  - AC-05-22 `get_supplier_resolution_settings()` returns the five documented defaults.
  - AC-05-23 `unmapped_card_spend_account` validation rejects group/nonexistent account.

Coverage bar per CLAUDE.md: positive + negative (guard/error path) + edge for each public function; for the alias `match_type` "registry", resolution of each registered key **and** the unknown/bad-pattern path.

### 7.2 Clean-room test plan

`test/testplans/specs/05-supplier-resolution-3tier.md` — one-line scope: a fresh-bench operator creates Supplier `Amazon` + an `AP Supplier Alias` glob `AMZN Mktp US*`→Amazon, files a capture with `proposed_supplier="AMZN Mktp US*4Z9"`, and verifies Tier-1 resolves to Amazon (Matched/Alias); then verifies (a) a Stream-I unknown vendor stays **BLOCKED** in review; (b) with `enable_gated_supplier_creation` on + high OCR confidence, a `Supplier Master Change Request` appears in **Draft**, and approving it **as a second user** (SoD) creates the Supplier and re-validates the capture to Matched; (c) a Stream-R unknown vendor is **non-blocking** and the downstream JE memo carries the raw vendor string against the Unmapped Card Spend account. Written to the CLAUDE.md test-plan template (feature-under-test, branch/commit, env setup with the named Anthropic key obtained by the operator, test-data prerequisites, numbered cases with full URL/API payload + expected DB state/text + pass/fail box, cleanup, summary checklist).

### 7.3 UI testing (Playwright MCP)
Browser-driven verification of the desk UI this slice adds, via the **Playwright MCP** server. These are the UI steps of the §7.2 clean-room runbook.
- **Prereq:** Playwright MCP per `test/testplans/BROWSER-TESTING-SETUP.md` (`claude mcp list` must list `playwright`; restart after registering). `.mcp.json` / `.playwright-mcp/` gitignored.
- **Evidence:** screenshots to `test/testplans/screenshots/05-supplier-resolution-3tier/<name>.png` (committed; pass as the screenshot `filename`).
- **Source of truth stays the DB:** after every UI write, verify via `bench --site <site> mariadb` / `bench … execute`, then delete UI-created data.

**Scenarios** (`route → action → expected UI → DB assertion`):
- Open a capture whose extracted vendor is unknown → form shows `supplier_match_status = Unknown` plus a "Create Supplier"/request action; click it → a Draft `Supplier Master Change Request` is created and linked (`supplier_change_request`), capture stays Blocked; screenshot both → DB-assert the request doc + the link.
- As a manager, open the `Supplier Master Change Request` and approve it (its Workflow action) → the Supplier is created and the capture re-validates to Matched; screenshot → DB-assert Supplier exists + capture `supplier_match_status = Matched`.
- Alias path: a capture whose vendor string matches an `AP Supplier Alias` glob resolves to the canonical Supplier (status Matched); screenshot → DB-assert `matched_supplier`.

**Not browser-testable in this slice** (covered by §7.1/§7.2): the rapidfuzz scoring + the three-tier resolution internals (§7.1).

## 8. Open decisions

- **OD-05-1 — distinct `Alias` match status vs fold into `Matched`.** Options: (a) add `"Alias"` to the `supplier_match_status` Literal; (b) reuse `"Matched"` and record the tier only in `supplier_match_tier`. **Recommended:** (a) — distinct value aids audit and the observability dashboard. Owner: AP product lead. Lock: before Tier-1 build (changes the DF Literal at py:192-194 and any report consuming it).
- **OD-05-2 — short/common-name over-scoring on Tier-2.** `token_set_ratio` over-scores short tokens (e.g. `"ABC"`). Options: (a) min-candidate-length floor below which fuzzy is skipped (Unknown); (b) a secondary `partial_ratio`/`WRatio` tie-break; (c) accept and rely on the manager curating aliases. **Recommended:** (a) length floor of 4 chars + (c). Owner: AP product lead. Lock: at Tier-2 build. Expose the floor in settings so it is tunable without code.
- **OD-05-3 — auto-create an alias on approved create.** When a `Create` request posts a Supplier, should the controller also persist an `AP Supplier Alias` from `requested_supplier_name` so the next variant resolves at Tier 1? **Recommended:** yes, store an `exact` alias with `source_capture` set (cheap, audit-friendly, no false positives). Owner: AP product lead. Lock: at Tier-3 build.
- **OD-05-4 — where `proposed_supplier_confidence` lives.** It must be persisted at extract time (currently dropped, §3). Options: (a) [[04-extraction-confidence-line-items]] owns it as part of the full confidence child table and this spec consumes a single derived float; (b) this spec adds the one `proposed_supplier_confidence` field defensively if 04 lands later. **Recommended:** (a), with (b) as the fallback to avoid blocking. Owner: extraction + supplier-resolution leads jointly. Lock: before Tier-3 build (the gate is data-dependent on it).
- **OD-05-5 — Stream-R Ambiguous handling.** Soft (treat like Unknown → Unmapped Card Spend) or pick the top fuzzy candidate? **Recommended:** soft (do not auto-pick; preserve the raw string), because a wrong auto-pick pollutes vendor aging silently. Owner: AP product lead. Lock: at Stream-aware build.
- **OD-05-6 — regex match_type availability.** Regex is a ReDoS/injection surface. Options: (a) allow regex but guard with `try/except re.error` + author-role restriction + optional timeout; (b) disallow regex entirely (exact + glob only). **Recommended:** (a) — keep regex but restrict alias authoring to `Accounts Manager` and guard compilation; revisit a timeout if a slow pattern is observed. Owner: security + AP leads. Lock: at Tier-1 build.
- **OD-05-7 — stream enum ownership/timing.** The `stream` field is net-new. Options: (a) [[02-intake-stream-tagging]] defines it and lands first; (b) this spec introduces it and hands ownership to 02. **Recommended:** (a). Owner: workflow-v2 orchestrator. Lock: before either spec is built (the enum values must be defined once).
- **OD-05-8 — gate vehicle: submittable `Supplier Master Change Request` vs a native `Workflow` placed on `Supplier`.** ERPNext lets you attach a native `Workflow` (states/transitions/allowed-roles) directly to the `Supplier` doctype, which would avoid a bespoke request doctype entirely. Options: (a) the submittable request doctype this spec defines; (b) a native Workflow on `Supplier`. **Recommended:** (a), for three concrete reasons a Supplier-attached Workflow cannot satisfy: (i) **no row to gate yet** — on Stream I the gate must hold an *unresolved vendor string* with **no `Supplier` record in existence** (the create is blocked precisely *because* no Supplier exists), and a Workflow on `Supplier` can only gate transitions of a row that already exists, so it cannot gate creation-from-nothing; (ii) **wrong target doctype for the headline vector** — the bank-change attack/error surface lives on `Bank Account`, not `Supplier` (see §5.1 correction), so a Supplier-only Workflow would leave "Update Bank Details" entirely ungated; (iii) **evidence back-link** — the request carries `evidence_capture`, the link the controller uses to **re-run validation** on the originating capture when the change posts (a native Supplier Workflow has nowhere to anchor that capture linkage). Owner: AP product lead + workflow-v2 orchestrator. Lock: before the Tier-3 / spec-11 Workflow build (it determines whether spec 11 wires a Workflow onto this request doctype or onto `Supplier`).
- **OD-05-9 — gated-creation default: OFF (as-built) vs ON-for-high-confidence (automation-first target).** *(added 2026-06-02)* `enable_gated_supplier_creation` shipped `default 0`, so Tier-3 never auto-files and a confident-but-unknown vendor dead-stops at a human who must notice *and* file the request. Options: (a) keep OFF — operator opts in per site; (b) **default ON, scoped to high OCR confidence** (`proposed_supplier_confidence >= supplier_autocreate_confidence_threshold`) so the system auto-files the Draft request and the human only approves; (c) default ON unconditionally (rejected — would file requests for low-confidence garbage names). **Recommended: (b)** — it closes the [[00-overview]] row-05 automation gap with the SoD control fully intact (Draft-only; a different user still approves; Stream-I capture stays BLOCKED until posted). Implemented via the AC-05-24..26 planned slice; ship behind a one-line settings-default flip plus the confidence-scope guard already present in §5.3 Tier-3. Owner: AP product lead. Lock: before the auto-create-default slice. (Independent of OD-05-3, which makes the *next* variant resolve at Tier 1 with no human at all.)

## 9. Dependencies & sequencing

**Must land first:**
- [[01-foundations-settings-async-idempotency]] — idempotency keys + `AP Posting Ledger` (for the Supplier-insert-on-approval idempotency) and the `enqueue_step` runner.
- [[04-extraction-confidence-line-items]] — persists the Anthropic per-field `supplier` confidence into `proposed_supplier_confidence`; the Tier-3 gate is dead without it (OD-05-4 gives a fallback).
- [[02-intake-stream-tagging]] — defines the `stream` enum this spec branches on (OD-05-7). If 02 slips, introduce the field here and hand it over.
- Already present: `rapidfuzz~=3.14.3` (`pyproject.toml:14`) — do **not** add.

**This unblocks / is a shared vehicle for:**
- [[06-gl-coding-tax-costcenter]] — a resolved/created Supplier is the key for `AP Supplier Coding Profile` lookups; `proposed_payload` should carry coding defaults so an approved create seeds them.
- [[08-validation-gates]] & [[11-approval-sod-workflow]] — `Supplier Master Change Request` is the **single** approval gate reused for bank-detail / payment-term / disable changes (`change_type` variants). The Workflow record (states/transitions/roles) for this doctype is owned by [[11-approval-sod-workflow]]; design `proposed_payload` + the controller dispatch generically so those specs reuse it rather than building a second gate.
- [[07-classification-doctype-branching]] — consumes the Stream-R soft path (raw vendor string → JE memo against `settings.unmapped_card_spend_account`); coordinate the memo-preservation contract (vendor string verbatim).
- [[10-ap-review-observability]] — consumes `supplier_match_tier`/`supplier_match_confidence`/`supplier_change_request` and the `supplier_unmapped` reason code.

**Estimated size:** **L** (per IMPLEMENTATION-PLAN units) — two new DocTypes (one submittable with a workflow seam), a non-trivial 3-tier resolver replacing a 28-line function while preserving an invariant, stream-aware branching that touches the validation core, a settings extension, and three new/extended test modules plus a clean-room runbook. The Workflow record itself is **out of scope** here (spec 11), which keeps this from being XL.
