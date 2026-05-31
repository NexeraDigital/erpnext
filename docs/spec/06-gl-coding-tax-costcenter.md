---
spec: 06-gl-coding-tax-costcenter
title: GL Coding, Cost Center & Tax Assignment
plan_step: Step 5 — GL Coding, Cost Center & Tax Assignment
stream: both
status: Draft
depends_on: [01-foundations-settings-async-idempotency, 04-extraction-confidence-line-items, 05-supplier-resolution]
related: [00-overview, 07-classification-doctype-branching, 08-validation-gates, 09-confidence-routing, 10-ap-review-observability]
---

# 06 — GL Coding, Cost Center & Tax Assignment
> _Revised 2026-05-31: applied native-vs-custom review findings; added Playwright UI test plan (§7.3)._

## 1. Summary
This spec builds the **auto-coding layer** for routine vendors: a new per-supplier master `AP Supplier Coding Profile` that layers default expense account, cost center, purchase-tax template, payment terms, and accounting dimensions on top of native Party Account, plus a re-runnable `apply_coding_profile_for(capture)` entry point that merges three default layers and writes them onto the **draft** Purchase Invoice. It implements **workflow-v2-plan.md Step 5** for **both streams** — Stream I (full coding before approval) and Stream R (catch-all "Unmapped Card Spend" expense when no profile resolves). Current-state delta: today the promote path does a two-layer merge (`_coalesce_defaults`, ap_invoice_capture.py:1116) with **no supplier tier, no cost-center inference, no tax, and no submitted-PI guard** — this spec adds all four and exposes `is_fully_coded(capture)` as the gate [[08-validation-gates]] / [[09-confidence-routing]] consult before anything auto-posts.

## 2. Plan alignment

**workflow-v2-plan.md Step 5 (quoted):**

> "The expense account, cost center, and tax treatment are applied. ERPNext's Supplier doctype natively carries a per-Company default payable account via its Party Account child table; default cost center and default expense account are layered on through Custom Fields or a supplier-to-coding mapping table, which drives auto-coding for routine vendors. For organizations with multiple locations or departments, the cost center can be inferred from the location on the receipt, the card last-4 used to pay, or the supplier's assigned cost center; ambiguous signals send the document to the review queue rather than defaulting silently. Tax fields (sales tax, use tax accrual) are populated from the extracted tax line and validated against the supplier's tax profile. Without coding at this step, nothing can auto-post and every document falls to manual review."

**Control-Summary row (quoted):**

> | Auto-coding from supplier defaults | Step 5 | Enables straight-through processing |

**Stream R vs Stream I divergence here:**

- **Stream I (unpaid payable):** Full coding is a hard prerequisite for the approval gate. A matched supplier MUST exist (it is a blocking step per plan Step 4); the profile supplies expense/cost-center/tax/terms, cost-center ambiguity routes to review, and `is_fully_coded` must be True before [[07-classification-doctype-branching]]'s PI branch hands off to [[11-approval-sod-workflow]].
- **Stream R (already-paid card/cash):** Supplier resolution is a **soft** flag, not a block (plan Step 4). When `matched_supplier` is None / no profile resolves, coding does **not** fail — the line's expense account falls back to the new `unmapped_card_spend_account` (Settings) with the raw vendor string preserved, ties to [[05-supplier-resolution]]'s soft-flag path, and the document still proceeds toward the Journal-Entry / bank-feed reconciliation path. There is no approval to gate, so `is_fully_coded` gates only the auto-**post** of the Journal Entry / PI, not an approval.

Cost-center inference and tax population/validation are **stream-agnostic in mechanism** but only fire when the upstream signals exist on the capture (see §3 / [[04-extraction-confidence-line-items]] dependency).

## 3. Current state

What ships today that this builds on or replaces (verified against the code, not memory):

- **Two-layer defaults merge — NO supplier tier.** `_coalesce_defaults(defaults)` at `erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.py:1116-1145` merges **only** `AP Closed Loop Settings` (lowest, via `get_promote_defaults()`) then the caller-supplied `defaults` dict (highest, non-None wins per-field, lines 1140-1143). It filters the result to `_PROMOTE_DEFAULT_KEYS = ("company","item_code","qty","uom","warehouse","expense_account","cost_center")` (lines 1105-1113). The per-supplier middle tier this spec adds **does not exist**.
- **Promote writes coding verbatim, no inference, no tax.** `promote_to_purchase_invoice(capture, actor, defaults, save)` at `ap_invoice_capture.py:1148-1235` builds **one** PI item row and sets `item_row["expense_account"]` (1213-1214) and `item_row["cost_center"]` (1215-1216) **only if present in the coalesced defaults**, taken verbatim — there is **no** cost-center inference from location / card-last4 / supplier, **no** ambiguity→review branch, and **no** tax handling at all (no `pi.taxes_and_charges`, no `pi.taxes` rows, no Party Account / payable logic).
- **No re-run / submitted-PI guard.** Re-promotion is blocked once `promotion_status == PROMOTED` and `purchase_invoice` is set (1181-1186); the function always `new_doc("Purchase Invoice")` (1190) and `insert()`s a fresh **draft** (1222), so it never edits an existing PI and therefore never needed a docstatus guard. The re-runnable coding step this spec adds **introduces** the draft-only rule.
- **Supplier match is the keying input.** `_match_supplier(supplier_name)` at `ap_invoice_capture.py:975-1003` (matches by `name` or `supplier_name`, ambiguous when >1, never auto-creates) feeds `validate_for_purchase_invoice` (1020-1102), which sets `capture.matched_supplier`. `apply_coding_profile_for` keys the profile lookup on `matched_supplier`.
- **Settings defaults bag.** `get_promote_defaults()` at `ap_closed_loop_settings.py:85-108` reads via `frappe.db.get_singles_dict` **deliberately not** `frappe.get_single` to dodge `set_missing_values` pulling the session user's default warehouse (docstring footgun note, lines 88-97). Settings JSON has `default_company/item_code/expense_account/cost_center` as Link fields (`ap_closed_loop_settings.json:34-58`). There is **no** `unmapped_card_spend_account`, **no** profile-level or Settings-level tax-template field.
- **Native substrate present — REUSE, do not rebuild.** Supplier `accounts` child Table → `Party Account` (`supplier.json:309-315`, "Mention if non-standard payable account") gives the per-Company payable account natively; `Party Account` child doctype is `istable=1` with `company`(Link Company) / `account`(Link Account) / `advance_account`(Link Account). Supplier already carries `payment_terms` (Link Payment Terms Template, `supplier.json:259-262`) and `tax_category` (Link Tax Category, `supplier.json:122-125`). Accounting dimensions carry through PI → PI Item → GL Entry via `hooks.py accounting_dimension_doctypes` (block starts ~line 539; includes "Purchase Invoice","Purchase Invoice Item","GL Entry").
- **Native Company-level floor (the Layer-0 fallback below this profile, verified against source).** Below the supplier profile and Settings sits ERPNext's own per-Company default. The native **expense** floor is **`Company.default_expense_account`** (Link → Account, label *"Default Cost of Goods Sold Account"*, `erpnext/setup/doctype/company/company.json:404`); the native **payable** floor is `Company.default_payable_account` (`:393`); the native **cost-center** floor is **`Company.cost_center`** (Link → Cost Center, label *"Default Cost Center"*, `:440`). **Source-verification note / correction to the review brief:** the brief asserted `Company.cost_center` *does not exist* and should be replaced — that is **wrong**; `Company.cost_center` **is** present (`:440`) and is the correct native cost-center default, so it is **retained**. What the brief got right is that **`Company.round_off_cost_center`** (`:355`) is a *different* field — the cost center used for rounding write-offs — and must **not** be mistaken for the default-coding cost center. The takeaway the brief intended still holds: cite **`Company.default_expense_account`** as the native expense floor (not any `round_off_*` field) and `Company.cost_center` as the native cost-center floor.
- **Native Item-axis coding already exists — `Item Default` (REUSE on the item axis; the profile is ADDITIVE on the supplier axis).** ERPNext already resolves per-item, per-company coding via the `item_defaults` child Table on `Item` → child doctype **`Item Default`** (`erpnext/stock/doctype/item_default/item_default.json`), which carries `expense_account` (`:92`) and `buying_cost_center` (`:73`) keyed by `company` (`:37`). On PI creation ERPNext fetches these onto the PI item natively — so this spec does **not** reinvent item-level coding. The new supplier-keyed `AP Supplier Coding Profile` is **additive, on a different axis**: it codes by **vendor**, which `Item Default` cannot do. It is specifically needed because the fork's promote path builds the PI from a **single default item** (`AP Closed Loop Settings.default_item_code`), so `Item Default` alone would code *every* vendor's line identically off that one item — it can never vendor-differentiate. The profile supplies the vendor-axis defaults `Item Default` structurally cannot.
- **Cascade is a pure state machine.** `_determine_next_step` (`ap_invoice_capture.py:321-366`) returns `(method, reason)` and currently has **no coding hop** — validation (Step 2) flows straight to the manual promote seam, then promotion → approval (Step 3). This spec inserts the coding step (§5.4).

**Correction to the brief:** the brief's data-model note proposes a profile field `default_purchase_tax_template` and says to set "the PI's `purchase_taxes_and_charges_template`." Verified against the local v16 app: the **Purchase Invoice header field that holds the template is `taxes_and_charges`** (Link → `Purchase Taxes and Charges Template`), at `purchase_invoice.json:748-753` — there is **no** field named `purchase_taxes_and_charges_template` on Purchase Invoice. The profile field name (`default_purchase_tax_template`) is a fork-local choice and is fine; the **write target on the PI must be `pi.taxes_and_charges`**, and applying it should trigger the native taxes-table fetch (see §5.3 step 7). PI Item `cost_center` (`purchase_invoice_item.json:525`) and `expense_account` (`:491`) field names are confirmed correct.

## 4. Upstream grounding

All four citations below were verified during research (the cost-center page was re-fetched while authoring and the quoted definition matched). Per the CLAUDE.md grounding rule, each framework surface this spec touches is anchored here and inline in §5 where a specific signature is asserted.

| # | URL | What it confirms | Quoted signature/section |
|---|---|---|---|
| C1 | https://docs.frappe.io/erpnext/user/manual/en/cost-center | Cost Center is an org unit costs/income are charged to; settable at **Company / Item / Order-Invoice** levels — grounds the per-supplier `default_cost_center` and the PI-item `cost_center` the promote path writes. The page does **not** name the PI Item field or GL mechanics — for those the in-repo code (`ap_invoice_capture.py:1215-1216`, `purchase_invoice_item.json:525`) and the `accounting_dimension_doctypes` hook are source of truth. | "A Cost Center is a part of an organization where costs or income can be charged." Levels listed: "Company," "Item," "Order/Invoice." |
| C2 | https://docs.frappe.io/erpnext/user/manual/en/purchase-taxes-and-charges-template | Purchase Taxes and Charges Template fields (Title, **Is Default**, taxes child table with **Account Head**, Type, Rate, Cost Center, Description). Grounds `default_purchase_tax_template` as the auto-select target and the `is_default` fallback when no profile tax is set. | Is Default: "Selecting default will apply this template by default for new Purchase transactions"; Account Head: "The Account ledger under which this tax will be booked"; Rate: "The Tax rate, eg: 14 = 14% tax" |
| C3 | https://docs.frappe.io/erpnext/user/manual/en/accounting-dimensions | Creating an Accounting Dimension auto-generates the transaction custom fields **via a background job**, which then appear on transactions and GL Entries (with company-specific Default Dimensions and Mandatory toggles). Grounds the `default_accounting_dimensions` child table AND explains why carry-through onto the PI is native (no rebuild) — and why a fresh site may not yet have the column (risk R6). | "As you create the dimension, custom fields will be created using a background job for that specific dimension." |
| C4 | https://github.com/frappe/erpnext/blob/develop/erpnext/buying/doctype/supplier/supplier.json | Native Supplier carries the per-Company payable account via `accounts` (Table → "Party Account", "Mention if non-standard payable account"), plus `payment_terms` (Link → "Payment Terms Template") and `tax_category` (Link → "Tax Category"). Confirms the payable-account / terms / tax-category layers must be **reused, not rebuilt**; matches local `supplier.json:122,259,311`. | `{"fieldname":"accounts","fieldtype":"Table","options":"Party Account"}`; `{"fieldname":"payment_terms","fieldtype":"Link","options":"Payment Terms Template"}`; `{"fieldname":"tax_category","fieldtype":"Link","options":"Tax Category"}` |

Framework-surface citations reused from sibling specs (cited where the mechanism is theirs, not re-grounded here): whitelisted-method convention and `frappe.enqueue` cascade → [[01-foundations-settings-async-idempotency]]; per-field confidence + line-item / tax extraction fields → [[04-extraction-confidence-line-items]]; `AP Review Event` emission → [[10-ap-review-observability]].

## 5. Design

### 5.1 Data model

#### 5.1.1 New master DocType: `AP Supplier Coding Profile` (non-Single, one row per Supplier)

`autoname`: `field:supplier` (docname == supplier name → lookup is a single `frappe.db.exists`/`get_doc` by supplier). `track_changes: 1`. Module: Accounts.

| fieldname | fieldtype | options / default | purpose |
|---|---|---|---|
| `supplier` | Link | options `Supplier`; `reqd:1`; **`unique:1`** | The vendor this profile codes. UNIQUE enforced in field JSON (not just naming) so a duplicate insert raises. |
| `default_expense_account` | Link | options `Account` | Layer-1 expense account written onto the PI item row (`expense_account`). |
| `default_cost_center` | Link | options `Cost Center` | The supplier's assigned cost center — the **lowest-priority** cost-center inference signal (§5.3 step 5). |
| `default_purchase_tax_template` | Link | options `Purchase Taxes and Charges Template` | Layer-1 tax template; written to PI header `taxes_and_charges` (§3 correction). |
| `default_payment_terms_template` | Link | options `Payment Terms Template` | Profile-level override of `Supplier.payment_terms` (native remains the base). |
| `coding_notes` | Small Text | — | Free-text operator notes (why this vendor codes the way it does). |
| `default_accounting_dimensions` | Table | options `AP Supplier Coding Dimension` | Thin (dimension, value) pairs applied to the PI item row when the dimension's column exists. |

**Per-Company scope (OPEN DECISION D1):** Account / Cost Center / Payable are Company-scoped in ERPNext, but this profile keys UNIQUE on `supplier` only. Recommended default for the pilot: **single-company profile** — carry company from `AP Closed Loop Settings.default_company`, resolve the payable account from native `Supplier.accounts` per target company, and do **not** add a `company` field. The multi-company alternative (add `company`, switch to UNIQUE(supplier, company)) is deferred (§8). Do **NOT** add a `payable_account` field — payable stays native (`supplier.json:309-315`).

**Permissions:** `Accounts Manager` and `AP Clerk` (NEW role, [[00-overview]]) read+write; `Accounts User` read; `Auditor (Read Only)` (NEW role) read. System Manager full.

#### 5.1.2 New child DocType: `AP Supplier Coding Dimension` (`istable: 1`)

| fieldname | fieldtype | options / default | purpose |
|---|---|---|---|
| `dimension` | Link | options `Accounting Dimension` | Ties to the configured dimension master (its `document_type` names the reference doctype). Link, not Select, so it tracks installed dimensions. |
| `dimension_value` | Dynamic Link | options `dimension_doctype` | The value, typed against the dimension's reference doctype (mirrors how native dimension custom fields are typed). |
| `dimension_doctype` | Data / read-only | fetched from `dimension.document_type` | Holds the target doctype name so `dimension_value`'s Dynamic Link can resolve it. |

> **Decision D5:** Dynamic Link vs a plain Select of fieldnames for `dimension_value`. Recommended: **Dynamic Link** keyed off the dimension's `document_type` — most faithful to native dimension fields. Requires the `Accounting Dimension` master exposes the reference doctype (it does, via `document_type`). Locked at build (§8).

#### 5.1.3 Changed DocType: `AP Closed Loop Settings` (Single) — new fields

Append to the existing OCR/promote Single (`ap_closed_loop_settings.json`). New section `coding_section` ("GL Coding Defaults").

| fieldname | fieldtype | options / default | purpose |
|---|---|---|---|
| `unmapped_card_spend_account` | Link | options `Account` | **Stream-R catch-all** expense account used when no profile/supplier resolves (ties to [[05-supplier-resolution]] soft-flag). Lowest-priority expense fallback. |
| `default_purchase_tax_template` | Link | options `Purchase Taxes and Charges Template` | Lowest tax layer (below the profile). If unset, the company's `is_default` template applies natively (C2). |

`get_promote_defaults()` (`ap_closed_loop_settings.py:85-108`) is **extended** to also surface these two keys (`unmapped_card_spend_account`, `purchase_tax_template`) using the **same `get_singles_dict` raw-read discipline** (risk R4) and the same "omit empties" filter — it MUST NOT switch to `get_single`.

#### 5.1.4 Changed DocType: `AP Invoice Capture` — new fields

These are the capture-side inputs coding/inference needs that **do not exist today** (the capture JSON has zero tax/card/location fields). Adding them is partly a [[04-extraction-confidence-line-items]] obligation (extraction must populate `extracted_tax_amount`); this spec owns the coding-status/review fields.

| fieldname | fieldtype | options / default | purpose | owner |
|---|---|---|---|---|
| `extracted_tax_amount` | Currency | — | Tax line surfaced by extraction; validated against the resolved template (§5.3 step 7). | [[04-extraction-confidence-line-items]] surfaces; this spec consumes |
| `extracted_tax_rate` | Percent | — | Optional extracted rate for rate-level validation. | [[04-extraction-confidence-line-items]] surfaces; this spec consumes |
| `card_last4` | Data | length 4 | Cost-center inference signal (card → CC). | this spec |
| `receipt_location` | Link | options `Location` | Cost-center inference signal (location → CC). Fallback to Data if `Location` doctype absent (D4). | this spec |
| `coding_status` | Select | `Pending`\n`Coded`\n`Ambiguous`\n`Flagged`; default `Pending` | Coding lifecycle marker distinct from `validation_status`. | this spec |
| `coding_review_reason` | Small Text | — | Which signals conflicted / why coding is flagged, surfaced to the review queue. | this spec |
| `applied_cost_center` | Link | options `Cost Center` | The cost center actually written (audit of which signal won). | this spec |
| `applied_expense_account` | Link | options `Account` | The expense account actually written. | this spec |
| `coding_source` | Data | default `ap-coding-v1` | Provenance tag (mirrors `validation_source`, `ap_invoice_capture.py:1081`). | this spec |

The existing `action_required` / `action_required_reason` pair (used by `validate_for_purchase_invoice`, `ap_invoice_capture.py:1086-1089`) is **reused** to route ambiguous/flagged coding to review — `coding_status` is the structured signal, `action_required` the queue trigger.

### 5.2 Endpoints

All whitelisted methods are co-located in `ap_invoice_capture.py`, mirror the existing `*_for` wrapper convention (e.g. `promote_to_purchase_invoice_for`, `ap_invoice_capture.py:1687`; `validate_for_purchase_invoice_for`, `:1678`), accept a capture **name (str) OR doc** like every sibling, normalize a `defaults` arg from JSON-string-or-dict exactly as `promote_to_purchase_invoice_for` does (`:1692-1696`), and call `doc._kick_next_step()` before returning the name to resume the cascade.

```python
# Pure callable (importable, used by tests + cascade) — NOT whitelisted
def apply_coding_profile_for(
    capture: "APInvoiceCapture | str",
    defaults: dict | None = None,
    save: bool = True,
) -> "APInvoiceCapture":
    """Three-layer coding merge + cost-center inference + tax population.
    Re-runnable; refuses to mutate a submitted Purchase Invoice."""

def is_fully_coded(capture: "APInvoiceCapture | str") -> bool:
    """Gate for Step 8 auto-post: expense_account AND cost_center resolved
    unambiguously AND tax validated (or no tax line present)."""

# Internal helpers (module-level, importable for unit tests)
def _resolve_supplier_coding(matched_supplier: str | None) -> dict: ...
def _infer_cost_center(
    capture: "APInvoiceCapture",
    supplier_profile: dict,
) -> "tuple[str | None, str | None]":  # (cost_center, ambiguity_reason)
    ...

# Whitelisted wrapper — UI / API entry point
@frappe.whitelist()
def apply_coding_profile_for_ui(capture: str, defaults: str | dict | None = None) -> str:
    """Normalize `defaults` (JSON str or dict), apply coding, resume cascade."""
    parsed = json.loads(defaults) if isinstance(defaults, str) and defaults else (defaults or None)
    doc = apply_coding_profile_for(capture, defaults=parsed)
    doc._kick_next_step()
    return doc.name

# Whitelisted read for the coding-review queue dashboard (mirrors get_manager_approval_queue_for, :1758)
@frappe.whitelist()
def get_coding_review_queue_for() -> list[dict]:
    """Captures with coding_status in ('Ambiguous','Flagged') and action_required==1."""
```

`get_promote_defaults_for_ui()` (`ap_closed_loop_settings.py:151-158`) is extended to return the two new Settings keys so the Promote dialog can prefill them.

### 5.3 Logic

`apply_coding_profile_for(capture, defaults=None, save=True)` — numbered:

1. **Normalize input.** If `capture` is a str, `frappe.get_doc("AP Invoice Capture", capture)` (mirrors `:1038`).
2. **Submitted-PI guard (highest-severity, risk R3).** If `capture.purchase_invoice` is set, read `frappe.db.get_value("Purchase Invoice", capture.purchase_invoice, "docstatus")`. If `== 1`, **raise `CapturePromotionError`** ("Cannot re-code a submitted Purchase Invoice {0}") and write **nothing**. Coding only ever mutates a `docstatus == 0` draft. (The current promote path has no such guard because it always news a fresh draft, `:1190`.)
3. **Resolve the three default layers** (lowest → highest), extending `_coalesce_defaults`:
   - **Layer 0** — `get_promote_defaults()` (`ap_closed_loop_settings.py:85-108`), reused verbatim (now also yields `unmapped_card_spend_account`, `purchase_tax_template`).
   - **Layer 1** — `_resolve_supplier_coding(capture.matched_supplier)`: returns `{}` if `matched_supplier` is falsy or `not frappe.db.exists("AP Supplier Coding Profile", matched_supplier)`; else `frappe.get_doc(...)` and emit `{expense_account, cost_center, purchase_tax_template, payment_terms_template, accounting_dimensions:[...]}` (omit empty fields). Use raw reads, no `set_missing_values` (risk R4).
   - **Layer 2** — caller `defaults` dict (non-None wins per-field), preserved exactly as `_coalesce_defaults` lines 1140-1143 so existing `_PROMOTION_DEFAULTS` tests keep passing.
   - Merge non-None top-down; filter to an **extended `_PROMOTE_DEFAULT_KEYS`** that now also includes `purchase_tax_template`, `payment_terms_template`, and an `accounting_dimensions` payload. Keep `company`/`item_code`/`qty`/`uom`/`warehouse` flowing through unchanged.
4. **Expense account resolution (stream-aware).** Effective expense = merged `expense_account` if present (Layer-2 caller > Layer-1 profile > Layer-0 Settings `default_expense_account`). **If absent AND `matched_supplier` is None/unknown AND no profile** → set effective expense to `unmapped_card_spend_account` (Stream-R catch-all) and `coding_status = "Flagged"`, `action_required = 1`, `coding_review_reason = "No supplier/profile — using Unmapped Card Spend"` (soft-flag, [[05-supplier-resolution]]). If even `unmapped_card_spend_account` is unset → leave expense empty, `coding_status="Flagged"` → `is_fully_coded` will be False (no auto-post). (Below all of the above sits ERPNext's own native floor `Company.default_expense_account`, `company.json:404` — the PI's native validation will apply it if every fork layer is empty, but the fork does **not** treat that native floor as "coded enough" to auto-post: a fork-resolved expense is required for straight-through. See §3 native-floor note.)
5. **Cost-center inference** via `_infer_cost_center(capture, supplier_profile)` → `(cost_center, ambiguity_reason)`. Resolution **priority order from the plan**: (a) `receipt_location` → mapped CC, (b) `card_last4` → mapped CC, (c) `supplier_profile.default_cost_center`. Rules:
   - Collect every signal that resolves to a concrete CC.
   - **Exactly one distinct CC across resolving signals** → write it (highest-priority signal wins ordering, but they agree) → `applied_cost_center = CC`.
   - **Two+ signals resolve to *different* CCs** → **AMBIGUOUS**: set `coding_status="Ambiguous"`, `coding_review_reason="Cost-center conflict: location={..} vs card={..}"`, `action_required=1`, and **DO NOT write any cost center** (assert it stays empty in tests — risk R5: must NOT fall back to `default_cost_center` on conflict).
   - **No signal resolves AND no default** → leave CC empty, `coding_status` at least `Flagged`, `action_required=1`. (ERPNext's native `Company.cost_center` floor, `company.json:440`, may still be applied by the PI itself, but as with expense the fork does not count the bare native floor as a *resolved* inference signal for auto-post.)
   - Location→CC and card-last4→CC mapping sources: D2 (recommended — read from the location's / a card-registry's CC; pilot may map via a thin lookup or the profile only). Until [[04-extraction-confidence-line-items]] lands `receipt_location`/`card_last4`, signals (a)/(b) are simply absent and (c) governs (graceful degrade).
   - **HRMS-conditional signal — Department-based cost center (NOT in the pilot signal set).** The plan's "inferred from … the department" phrasing maps to `Department.payroll_cost_center`, which is provided by the **separate HRMS app** and is **absent from this erpnext checkout** (verified: the `erpnext` `Department` doctype has no `payroll_cost_center` field; HRMS is not installed in this bench — apps present are `frappe`, `erpnext`, `payments`). A Department→CC signal is therefore **HRMS-CONDITIONAL**: it must be guarded with an app/field-presence check (`frappe.db.has_column("Department", "payroll_cost_center")`) and is **dropped from the pilot signal set** unless HRMS is installed. The three signals above (location, card-last4, profile) do not depend on HRMS.
6. **Payment terms.** If merged `payment_terms_template` present, stage it for the PI header `payment_terms_template`; else native `Supplier.payment_terms` applies downstream (no action). Do not overwrite a non-empty PI value the caller set.
7. **Tax population + validation (C2).** If merged `purchase_tax_template` present, stage `pi.taxes_and_charges = <template>` (§3 correction — field is `taxes_and_charges`, NOT `purchase_taxes_and_charges_template`) and let the native template→`pi.taxes` fetch populate the taxes rows (the same mechanism the PI form uses on template change). **Validate** `capture.extracted_tax_amount` (and `extracted_tax_rate` if present) against the template's computed tax / the supplier's native `tax_category` (`supplier.json:122`): on mismatch beyond tolerance (D3) → `coding_status="Flagged"`, `coding_review_reason="Extracted tax {x} != template tax {y}"`, `action_required=1`, and the doc is **not** eligible to auto-post. If no profile/Settings tax template → the company `is_default` template applies natively (C2) and no template is staged here.
8. **Accounting dimensions (C3, risk R6).** For each `default_accounting_dimensions` row, before writing the value onto the PI item, **guard** with `frappe.db.has_column("Purchase Invoice Item", <fieldname>)` / `pi_item.meta.has_field(...)` — the dimension custom field is created by a background job and may not exist on a fresh site. Skip silently (no error) when the column is absent or the row's value is empty. Present-but-empty child rows set nothing and raise nothing.
9. **Apply to the draft PI (if one exists).** If `capture.purchase_invoice` is a `docstatus==0` draft, load it and write: `item_row.expense_account`, `item_row.cost_center` (only if unambiguous), `item_row` dimension fields (guarded), `pi.taxes_and_charges`, `pi.payment_terms_template`; `pi.save()`. If no PI exists yet, persist the resolved values onto the capture (`applied_expense_account`, `applied_cost_center`, staged tax/terms) so a subsequent `promote_to_purchase_invoice` consumes them via the merge — this makes coding a re-runnable, PI-independent step.
10. **Set coding_status / provenance.** If no ambiguity/flag was set: `coding_status="Coded"`, and **only clear** `action_required` if validation also has no outstanding action (do not stomp validation's `action_required`). Always set `coding_source` and the `applied_*` audit fields.
11. **Idempotency.** Coding is naturally idempotent (re-deriving the same merge yields the same writes). Where a posting operation is involved downstream, the idempotency key is owned by [[01-foundations-settings-async-idempotency]]; coding itself writes only draft fields and is safe to repeat.
12. **Persist.** `if save: capture.save()`; return the capture.

`is_fully_coded(capture)` → True **iff** effective `expense_account` resolved (non-empty) AND `cost_center` resolved unambiguously (`coding_status != "Ambiguous"` and `applied_cost_center` set) AND tax validated (no tax-mismatch flag; absence of an extracted tax line is "validated"). This is the gate [[08-validation-gates]] / [[09-confidence-routing]] / the Step-8 auto-post call site consult — **"without coding, nothing auto-posts."** Today `promote_to_purchase_invoice` would happily create a PI with empty expense/cost-center; this gate closes that hole.

### 5.4 Cascade & stream-awareness

- **New hop in `_determine_next_step`** (`ap_invoice_capture.py:321-366`), inserted **between** the validation step (current Step 2, line 339) and the manual promote seam:

  ```text
  if (validation_status == VALIDATED
      and coding_status in (None, "Pending")
      and matched_supplier  # Stream I: required; Stream R catch-all handled inside the step
  ):
      return ("apply_coding_profile_for_ui", "auto: post-validation GL coding")
  ```

  For **Stream R** with no `matched_supplier`, the gate still fires (the catch-all path needs to run) — the condition is relaxed to allow a null supplier when `stream == "R"` (the `stream` field is owned by [[02-intake-stream-tagging]]).
- **Pause vs auto-advance:** if coding lands `coding_status in ("Ambiguous","Flagged")` with `action_required==1`, `_determine_next_step` returns None at the coding state → the capture **parks in the coding-review queue** (a new pause point alongside OCR-review and manual-promote). Only `coding_status == "Coded"` lets the cascade advance to the promote seam.
- **Re-entry after correction:** when a clerk fixes the supplier match or supplies a cost center via [[10-ap-review-observability]]'s reject/reopen, re-calling `apply_coding_profile_for_ui` re-runs the merge on the still-draft PI (edge case in §7) and, if now `Coded`, `_kick_next_step` resumes the cascade.
- **Stream divergence summary:** Stream I requires `is_fully_coded` True before [[07-classification-doctype-branching]] hands the PI to [[11-approval-sod-workflow]]; Stream R uses `is_fully_coded` only to gate the auto-post of the JE/PI, never an approval, and tolerates the `unmapped_card_spend_account` fallback as "coded enough to post."

### 5.5 Cross-cutting

- **Permissions / SoD:** profile authoring is `Accounts Manager` / `AP Clerk`; coding itself runs under the cascade's job user. SoD enforcement is [[11-approval-sod-workflow]]'s concern — coding does not approve.
- **Idempotency:** via [[01-foundations-settings-async-idempotency]]'s key on any downstream posting; coding writes only draft fields (§5.3 step 11).
- **Async / enqueue:** the coding hop routes through the existing `_enqueue_next` / `_run_cascade_step` wrapper (`ap_invoice_capture.py:368-403`) — `enqueue_after_commit=True`, `deduplicate=True`, per-capture-per-step job; under `in_test` it runs `now=True`. No new queue plumbing.
- **Observability:** every coding ambiguity/flag SHOULD emit an `AP Review Event` (root-cause vocabulary owned by [[10-ap-review-observability]]) — relevant tags: `supplier_unmapped` (catch-all path), and a coding-specific reason for cost-center conflict / tax mismatch. The stream-tag-vs-classifier and coding-flag rates feed the Step-9 dashboard.
- **Fork docs:** adding the new doctypes + capture fields is inside the AP closed-loop scope → `docs/architecture/FORK-CHANGES.md` AND `FORK-CHANGES-PLAIN.md` must be updated in the **same commit** (paired), per CLAUDE.md.

## 6. Acceptance criteria

- **AC-06-1 (profile uniqueness):** Inserting a second `AP Supplier Coding Profile` for a supplier that already has one **raises** (DuplicateEntryError from `unique:1`). *(negative)*
- **AC-06-2 (layer-1 beats layer-0):** With a profile present and Settings holding different values and no caller override, `apply_coding_profile_for` writes the **profile's** `expense_account`/`cost_center` onto the draft PI item, not the Settings values. *(positive)*
- **AC-06-3 (three-layer precedence):** For a key all three layers set, the **caller** value wins; for a key only Settings has, the Settings value still flows through. *(positive)*
- **AC-06-4 (cost-center single signal):** With only `supplier_profile.default_cost_center` resolving, that CC is written, `coding_status=="Coded"`, `action_required==0`, `applied_cost_center` set. *(positive)*
- **AC-06-5 (cost-center ambiguity):** Two signals resolving to **different** CCs → `coding_status=="Ambiguous"`, `coding_review_reason` populated, `action_required==1`, and **no** cost center written (`applied_cost_center` empty, PI item `cost_center` empty). *(edge)*
- **AC-06-6 (tax match):** `extracted_tax_amount` matching the template's computed tax → `pi.taxes_and_charges` set, taxes rows populated, no flag, `coding_status` not Flagged. *(positive)*
- **AC-06-7 (tax mismatch):** `extracted_tax_amount` disagreeing beyond tolerance → `coding_status=="Flagged"`, `action_required==1`, `is_fully_coded` False, PI not eligible to auto-post. *(negative)*
- **AC-06-8 (submitted-PI guard):** Calling `apply_coding_profile_for` when `capture.purchase_invoice` is `docstatus==1` **raises `CapturePromotionError`** and leaves the PI byte-for-byte unchanged. *(negative)*
- **AC-06-9 (Stream-R catch-all):** No profile and None/unknown `matched_supplier` → effective expense = `unmapped_card_spend_account`, capture soft-flagged (`action_required==1`); if `unmapped_card_spend_account` is itself unset → coding blocked, `is_fully_coded` False, no auto-post. *(negative/edge)*
- **AC-06-10 (gate):** `is_fully_coded` returns True **only** when expense + cost_center (unambiguous) + tax (validated/absent) are all resolved; False if any is missing or flagged. *(positive + negative)*
- **AC-06-11 (re-run after corrected supplier):** Code with supplier A's profile on a draft PI, change `matched_supplier` to B, re-call `apply_coding_profile_for` → draft PI now carries B's profile values (draft mutation allowed). *(edge)*
- **AC-06-12 (Settings footgun regression):** After the profile layer is added, `get_promote_defaults()` still **omits** empty Link fields (no session-default leakage, `ap_closed_loop_settings.py:88-97` discipline preserved). *(regression)*
- **AC-06-13 (additive regression):** Existing `promote_to_purchase_invoice` tests passing explicit `_PROMOTION_DEFAULTS` pass **unchanged** (the new middle layer is additive). *(regression)*
- **AC-06-14 (empty dimensions):** Profile present but `default_accounting_dimensions` empty → no dimension fields set, no error; a dimension whose column does not exist on the site is skipped silently (R6 guard). *(edge)*

## 7. Tests

### 7.1 Automated
Base class `from frappe.tests import IntegrationTestCase`; roll back all DB writes in `tearDown` (reentrant). Run with `bench --site <site> run-tests --module <dotted.path>`.

- **`erpnext.accounts.doctype.ap_supplier_coding_profile.test_ap_supplier_coding_profile`** (new, beside the new doctype):
  - *positive:* create a profile for `_Test Supplier` and assert each field round-trips; `_resolve_supplier_coding("_Test Supplier")` returns the expected dict; unknown supplier → `{}`.
  - *negative:* duplicate-insert for the same supplier raises (AC-06-1); `_resolve_supplier_coding(None)` → `{}`.
  - *edge:* profile with empty `default_accounting_dimensions` → resolver returns no dimensions, no error (AC-06-14).
- **`erpnext.accounts.doctype.ap_invoice_capture.test_ap_invoice_capture`** (extend existing, `test_ap_invoice_capture.py`):
  - *positive:* AC-06-2, AC-06-3, AC-06-4, AC-06-6, AC-06-10 (True branch), AC-06-11.
  - *negative:* AC-06-7, AC-06-8 (assert PI unchanged), AC-06-9 (both sub-cases), AC-06-10 (False branch), AC-06-12.
  - *edge:* AC-06-5 (ambiguity — assert CC stays empty), AC-06-13 (existing promote tests green), AC-06-14 (missing dimension column skipped via `has_column` monkeypatch/guard).
  - *helper resolution:* `_infer_cost_center` matrix — single-signal each (location-only, card-only, profile-only) → write; two-conflicting → ambiguous/no-write; none → empty. (This is the registry-style "resolution of each key + the conflict error path" coverage the house style requires.)

### 7.2 Clean-room test plan
- **`test/testplans/ap-supplier-coding-profile.md`** — runbook (kebab-case, matching `ocr-phase3-settings.md` convention): from a clean bench, create `Supplier` + `Account` (expense) + `Cost Center` + `Purchase Taxes and Charges Template` fixtures, create an `AP Supplier Coding Profile`, drive a capture through validate → `apply_coding_profile_for` → promote, and assert the **draft** PI carries the profile's expense account, cost center, `taxes_and_charges` (with populated taxes rows), and any dimension; plus the **ambiguous-cost-center review-queue** case and the **`unmapped_card_spend_account` catch-all** case (Stream R). Scope line: "Verifies per-supplier auto-coding, cost-center inference + ambiguity routing, tax population, and the Stream-R catch-all on a clean ERPNext bench."
- *(Optional second slug)* **`test/testplans/ap-coding-cost-center-inference.md`** — split out only if the inference matrix grows (location/card/profile permutations). Scope line: "Cost-center inference precedence and conflict-routing matrix."

### 7.3 UI testing (Playwright MCP)
Browser-driven verification of the desk UI this slice adds, via the **Playwright MCP** server. These are the UI steps of the §7.2 clean-room runbook.
- **Prereq:** Playwright MCP per `test/testplans/BROWSER-TESTING-SETUP.md` (`claude mcp list` must list `playwright`; restart after registering). `.mcp.json` / `.playwright-mcp/` gitignored.
- **Evidence:** screenshots to `test/testplans/screenshots/ap-supplier-coding-profile/<name>.png` (committed; pass as the screenshot `filename`).
- **Source of truth stays the DB:** after every UI write, verify via `bench --site <site> mariadb` / `bench … execute`, then delete UI-created data.

**Scenarios** (`route → action → expected UI → DB assertion`):
- A capture for a supplier WITH an `AP Supplier Coding Profile` → trigger the Promote/coding action; the PI line auto-fills expense account / cost center / tax with no manual entry; screenshot the prefilled Promote dialog or the resulting PI → DB-assert the PI item coding == the profile.
- A capture with ambiguous cost-center signals → lands in the Coding Review queue (the `get_coding_review_queue_for` list/report) with the reason and NO cost center silently set; screenshot the queue → DB-assert the capture is flagged + `cost_center` empty.

**Not browser-testable in this slice** (covered by §7.1/§7.2): the three-layer merge resolution + dimension `has_column` guard (§7.1).

## 8. Open decisions

| # | Decision | Options | Recommended default | Owner | Must lock |
|---|---|---|---|---|---|
| D1 | Profile company scope | (a) single-company (company from `Settings.default_company`, payable from native Party Account) / (b) add `company` + UNIQUE(supplier, company) | **(a) single-company** for the pilot — honors "don't rebuild Party Account" | Russ + Bryan | Before building the profile JSON (blocks the `unique` constraint shape) |
| D2 | Cost-center inference signal sources | (a) profile `default_cost_center` only (pilot) / (b) + receipt-location→CC map / (c) + card-last4→CC registry | **(c) full** as the design target, **(a) shipped first** — degrade gracefully until [[04-extraction-confidence-line-items]] lands the fields | Russ | When [[04-extraction-confidence-line-items]] fields land |
| D3 | Tax-validation tolerance | exact match / ±currency-rounding / ±% band | **±currency-rounding (smallest unit)** to absorb extractor rounding without hiding real mismatches | Bryan | At build, before AC-06-6/7 tests |
| D4 | `receipt_location` fieldtype | Link → `Location` / plain `Data` | **Link → `Location`** if the doctype is installed; fall back to `Data` if not | Russ | At build (depends on installed app set) |
| D5 | `dimension_value` typing | Dynamic Link (off dimension `document_type`) / Select of fieldnames | **Dynamic Link** — faithful to native dimension fields | Russ | When building `AP Supplier Coding Dimension` |
| D6 | Catch-all account naming | reuse an existing GL account / require a dedicated "Unmapped Card Spend" account in CoA | **Dedicated account** so Stream-R catch-all spend is isolated for later remapping | Bryan | Before Stream-R go-live (with [[05-supplier-resolution]]) |
| D7 | Where the coding hop pauses | new "Coding Review" pause point / fold into existing OCR-review queue | **New pause point** (`coding_status` Ambiguous/Flagged) so root-cause is distinct in [[10-ap-review-observability]] | Russ | At build (affects `_determine_next_step`) |
| D8 | Vendor-coding storage: separate `AP Supplier Coding Profile` doctype vs **Custom Fields on `Supplier`** | (a) separate profile doctype (this spec) / (b) four fork Custom Fields on `Supplier` — `default_expense_account` / `default_cost_center` / `default_purchase_tax_template` / `default_payment_terms_template` | **(a) separate doctype.** Trade-off recorded honestly: option (b) would **avoid a second doctype and the supplier→profile join**, and the fields would sit **beside the native `Supplier.payment_terms` (`supplier.json:259`) and `Supplier.tax_category` (`:122`)** that already encode vendor-axis defaults — genuinely simpler for the four scalar fields. **The deciding factor for (a)** is the **`default_accounting_dimensions` child table**: a child Table is awkward and intrusive as a Custom Field bolted onto the upstream `Supplier` master, whereas it is first-class on a fork-owned doctype. Secondary factor: **fork-isolation hygiene** — keeping fork fields off the upstream `Supplier` master reduces merge friction with `develop` and keeps the fork delta legible (CLAUDE.md FORK-CHANGES discipline). Net: the scalar-only case favors (b), but the child-table requirement tips it to (a). | Russ + Bryan | Before building the profile JSON (it is the doctype-shape decision; pairs with D1) |

## 9. Dependencies & sequencing

**Must land first:**
- [[04-extraction-confidence-line-items]] — surfaces `extracted_tax_amount` (and ideally `card_last4`, `receipt_location`). **Hard blocker** for tax population/validation and two of three cost-center signals; the third (`profile.default_cost_center`) works without it, so coding can ship in a degraded "profile-only" mode and light up the rest when 04 lands.
- [[05-supplier-resolution]] — provides the matched-supplier primitive this keys on (already partly present via `_match_supplier`/`validate_for_purchase_invoice`) and owns the soft-flag path the `unmapped_card_spend_account` catch-all ties into.
- [[01-foundations-settings-async-idempotency]] — idempotency keys + async runner conventions this reuses.

**Reuses (does not rebuild):** native Party Account / `Supplier.accounts` (per-Company payable), `Supplier.payment_terms` + `tax_category`, `hooks.py accounting_dimension_doctypes` wiring, the existing `_enqueue_next`/`_run_cascade_step` cascade.

**This unblocks:**
- **Step 8 auto-post gate** ([[08-validation-gates]] / [[09-confidence-routing]]): `is_fully_coded(capture)` is the gate they must call — "without coding, nothing auto-posts."
- [[07-classification-doctype-branching]]: the PI/JE branch consumes the coded draft (expense/cost-center/tax already on it).

**Estimated size:** **L** (per IMPLEMENTATION-PLAN units). Two new doctypes (master + child) + Settings + capture field additions + the three-layer merge refactor + cost-center inference + tax population/validation + the cascade hop + automated tests + clean-room plan + paired fork-docs. The inference matrix and tax-validation tolerance are the fiddly bits; the submitted-PI guard (R3) is small but highest-severity.
