---
spec: 07-classification-doctype-branching
title: Document-Type Classification & Doctype Branching (stream-aware)
plan_step: Step 6 — Document-Type Classification & Doctype Selection (confirms/revises the Step 1 provisional stream tag)
stream: both
status: Done
depends_on: [01-foundations-settings-async-idempotency, 02-intake-stream-tagging, 05-supplier-resolution, 06-gl-coding-tax-costcenter]
related: [00-overview, 04-extraction-confidence-line-items, 08-validation-gates, 10-ap-review-observability, 14-closure-audit-retention]
---

# 07 — Document-Type Classification & Doctype Branching (stream-aware)
> _Revised 2026-05-31: applied native-vs-custom review findings; added Playwright UI test plan (§7.3)._

## 1. Summary
This spec adds the Step-6 fork that classifies a confirmed capture into an ERPNext document type and routes it to the correct posting doctype: **Unpaid Bill → Purchase Invoice** (Stream I, existing path), **Already Paid → Purchase Invoice with `is_paid=1`** (Stream R, NEW path — recommended native posting: ONE submitted PI books both the expense and its offsetting payment — the invoice legs (DR expense / CR supplier) plus the Is-Paid payment legs (DR supplier / CR bank) — netting the supplier to zero yet keeping it visible in spend-by-supplier/AP reports; alternative postings are a direct Journal Entry or PI + clearing account — see D-07-1), **Employee Reimbursement → Expense Claim** (Stream R-employee, DEFERRED — hrms absent, routed to Manual Review), **Other / stream conflict → Manual Review**. It is the heart of correct ERPNext AP automation: routing every document to one doctype double-counts liabilities and breaks trial-balance reconciliation. Current-state delta: today the pipeline is hardwired to a single doctype (Purchase Invoice) with no `document_type` field, no stream tag, and no already-paid posting path; this spec inserts a classification hop into the auto-progression cascade and forks on the result. The strongest native already-paid posting is `Purchase Invoice.is_paid=1` (recommended — it reuses the existing `promote_to_purchase_invoice` field-mapping path, adding only `is_paid` / `cash_bank_account` / `paid_amount`, and keeps the Supplier visible in spend-by-supplier/AP reports); the posting mechanism stays config-swappable behind a single seam (D-07-1).

## 2. Plan alignment

`docs/planning/workflow-v2-plan.md` **Step 6** (lines 44–52):

> The document is classified and routed to the appropriate ERPNext doctype based on the nature of the transaction. This step **confirms or revises** the provisional stream tag from step 1 using the structured extraction (the body said "PAID" but the structured total + due-date pattern says "invoice" — escalate to step 9):
> - **Unpaid vendor bill (Stream I)** → `Purchase Invoice` (later paid via `Payment Entry`)
> - **Already-paid card or cash receipt (Stream R)** → `Journal Entry` (DR expense, CR card/cash liability)
> - **Employee out-of-pocket expense (Stream R-employee)** → `Expense Claim` (later paid via `Payment Entry`)
> - **Other / stream-tag conflict** → routed to review for manual classification
>
> Routing everything to a single doctype causes double-counting of liabilities and breaks trial-balance reconciliation. This branch is the heart of correct ERPNext AP automation. The stream-tag-vs-classifier disagreement rate is a tuning signal — high disagreement means the step-1 intake heuristics need improvement.

Control-Summary row (line 129):

> | Doctype branching (stream-aware) | Step 6 | Prevents double-counted liabilities; revises step-1 stream tag if needed |

**Stream R vs Stream I divergence here:**
- **Stream I (Unpaid Bill):** continues through the existing `validate_for_purchase_invoice` → `promote_to_purchase_invoice` path. A new guard asserts `document_type == 'Unpaid Bill'` at the promotion precondition block.
- **Stream R (Already Paid):** routes to a NEW already-paid promotion that posts DR expense / CR bank-or-card-liability. The **recommended native mechanism (D-07-1 option C)** is a single `Purchase Invoice` with `is_paid=1` + `cash_bank_account` + `paid_amount`: within ONE submitted PI, ERPNext adds the Is-Paid payment legs **on top of** the normal invoice booking: the invoice posts DR expense / CR supplier (Creditors), and `make_payment_gl_entries` (`erpnext/accounts/doctype/purchase_invoice/purchase_invoice.py:1546-1590`) posts the Is-Paid legs DR supplier / CR bank — so the supplier is credited then debited and **nets to zero**, while the vendor STILL appears in spend-by-supplier/AP reports — and it REUSES the existing `promote_to_purchase_invoice` field-mapping path (only adds 3 fields). The alternative (option A) is a direct **Journal Entry** (DR expense / CR card-or-cash liability with `voucher_type='Credit Card Entry'`/`'Cash Entry'`), which is the most custom code (a new hand-balanced JE builder, a new `journal_entry` link field, and teaching closure-evidence a third voucher type). Whichever mechanism is chosen, this branch does **NOT** pass through the PI-specific supplier-matching/PO-classification logic the same way Stream I does (the already-paid PI skips PO/PR classification): no approval routing, no separate payment execution (the money already moved); closure is reconciliation-only (extends in [[14-closure-audit-retention]]). See D-07-1 for the recommended default and the swap-friendly seam.
- **Stream R-employee (Employee Reimbursement):** DEFERRED. Expense Claim ships in the separate `hrms` app, which is **absent on this bench** — routed to Manual Review with an hrms-dependency reason and a reserved (non-linkable) `expense_claim` field.
- **Other / conflict:** Manual Review state halts the cascade and holds for a clerk; the disagreement is persisted as a tuning signal for [[10-ap-review-observability]].

## 3. Current state

**SPEC 07 IS GREENFIELD.** A grep across `erpnext/accounts/ap_closed_loop/**` and the `ap_invoice_capture` doctype returns zero hits for `stream`, `document_type`, `already_paid`, `journal_entry`, or `expense_claim`. The entire pipeline assumes one doctype (Purchase Invoice).

Anchors this spec builds on (verified by reading the files):

- **The branch point — `APInvoiceCapture._determine_next_step()`** at `ap_invoice_capture.py:321-366`. It is a single linear state machine. After OCR `Confirmed` (Step 2, lines 339-344) it returns `("validate_for_purchase_invoice_for", ...)`, then a manual Promote seam, then `request_approval_for` / `issue_mock_payment_for`. **There is no document-type fork.** This is exactly where the Step-6 classification hop is inserted, before validation/promotion.
- **`promote_to_purchase_invoice(capture, actor, defaults, save)`** at `ap_invoice_capture.py:1148-1235` — the existing Stream-I target. Preconditions enforced: `validation_status == Validated` (line 1170), `matched_supplier` set (line 1177), and the not-already-promoted **soft guard** at lines 1181-1186 (`if capture.promotion_status == PROMOTION_STATUS_PROMOTED and capture.purchase_invoice: raise CapturePromotionError`). It builds a draft PI via `frappe.new_doc("Purchase Invoice")`, maps `supplier`/`bill_no`/`bill_date`/`posting_date`/`currency`, appends one item row from `_coalesce_defaults()`, then `pi.insert(ignore_permissions=True)` (line 1222) and leaves the PI **draft**. The `assert document_type=='Unpaid Bill'` guard from the brief maps onto adding a check alongside the precondition block at ~line 1170.
- **Whitelisted wrappers** each call `doc._kick_next_step()` to resume the cascade: `validate_for_purchase_invoice_for` (1677), `promote_to_purchase_invoice_for` (1686-1702), `issue_mock_payment_for` (1734). A NEW `promote_to_journal_entry_for` follows the exact `promote_to_purchase_invoice_for` shape (parse `defaults` str/dict, call the pure function, reload capture, `_kick_next_step`, return the voucher name).
- **`_match_supplier()`** at `ap_invoice_capture.py:975-1002` resolves `final_supplier` → Supplier by `name`/`supplier_name`, never auto-creates. The employee-reimbursement classifier reads `Supplier.supplier_group` off the matched supplier.
- **Status enum** — `DF.Literal` at `ap_invoice_capture.py:182-189` is **6 values** (Pending Review / Unsupported / Rejected / Proposed / Needs Correction / Confirmed). There is **NO `Manual Review` state**. `action_required` (Check, declared line 153) + `action_required_reason` (Data, line 154) are the existing review-escalation seam — orthogonal to a status value; adding `Manual Review` to the `DF.Literal` AND the JSON `options` is a migrate-affecting schema change.
- **Idempotency available today is the soft capture-flag guard only** (lines 1181-1186) plus enqueue-level `deduplicate=True` + per-capture-per-step `job_name` at `_enqueue_next` (~line 400; commented at 372). There is **NO DB natural-key uniqueness guard** on the inserted voucher — `_hash_bytes()` (579) only seeds fake OCR. A stronger natural-key/content-hash guard is a [[01-foundations-settings-async-idempotency]] deliverable not yet present; this spec consumes whatever 01 provides and must not assume more.
- **`AP Closed Loop Settings`** (`ap_closed_loop_settings.py`) has `default_company`/`default_item_code`/`default_expense_account`/`default_cost_center`/`default_warehouse`/`default_uom` + OCR config. It has **NO card/cash liability account** and **NO employee_supplier_group**; both are ADDED here. `get_promote_defaults()` at `ap_closed_loop_settings.py:85` reads via `get_singles_dict` (deliberately not `get_single`, to avoid session-default auto-population — line 88-97 explains the footgun).
- **`walking_skeleton.py`** is a parallel reference-only flow (PI → PE → closure evidence); it does not touch `document_type` and creates PIs directly. `derive_closure_evidence` (278-339) derives closure from native state (no custom closed flag) and currently understands only PI+PE — [[14-closure-audit-retention]] must learn the JE voucher the same way.
- **`hrms` / Expense Claim — confirmed ABSENT** on this bench: `ls apps/ | grep -i hrms` → `NO_HRMS_APP`; no `expense_claim` doctype directory found. The deferral is real on this environment.

**Correction to the brief:** the brief's `data_model_notes` says `purchase_invoice` is a Link at "DF line 208" — confirmed: `purchase_invoice: DF.Link | None` is at line 208, `promotion_status: DF.Literal["Not Promoted", "Promoted"]` at line 209. The new `journal_entry` field parallels it exactly. No other corrections — current state matches the brief.

## 4. Upstream grounding

| URL | Verified | What it confirms | Quoted signature/section |
|---|---|---|---|
| https://docs.frappe.io/erpnext/user/manual/en/journal-entry | ✅ | Journal Entry is the Stream-R target. `voucher_type` natively includes the entries needed; the `accounts` child table carries the columns we need; debits must equal credits. So `promote_to_journal_entry` can post DR expense / CR card-or-cash liability and tag `voucher_type='Credit Card Entry'` (or `'Cash Entry'`) with **no custom field**. | "**Bank Entry** - Use this type when making or receiving a payment using a Bank Account … **Cash Entry** - This is the same as 'Bank Entry' but the payment is made via Cash Account … **Credit Card Entry** - This is a type of entry to easily identify all credit card entries." / "the sum of debits is equal to the sum of credits." |
| https://docs.frappe.io/erpnext/user/manual/en/purchase-invoice | ✅ | The existing Stream-I target. Standard GL = Debit Expense/Asset (+ Taxes), Credit Supplier (AP). **Critical for the locked decision (§8 D-07-1):** PI natively supports an `Is Paid` flag that adds Debit Supplier / Credit Bank-or-Cash — a THIRD option (B) between "direct JE" (A) and "PI + clearing account" (C). `Supplier Invoice No` / `Supplier Invoice Date` are the `bill_no`/`bill_date` fields already mapped by `promote_to_purchase_invoice`. | "Debits: Expense or Asset (net totals, excluding taxes), Taxes. Credits: Supplier." / "You can tick 'Is Paid' if the amount has already been paid … Debits: Supplier. Credits: Bank/Cash Account." |
| https://github.com/frappe/erpnext/blob/version-16/erpnext/patches/v14_0/remove_hr_and_payroll_modules.py | ✅ | Grounds the Employee-Reimbursement deferral. The patch early-returns if `hrms` is installed; otherwise it deletes the HR/Payroll Module Defs (which cascades away the HR doctypes including Expense Claim). Expense Claim therefore lives in the separate `hrms` app, not ERPNext core. Confirmed locally: no `apps/hrms`, no `expense_claim` doctype. So the Employee branch MUST route to Manual Review and the `expense_claim` field MUST NOT be a live `Link` (see §8 D-07-3). | `if "hrms" in frappe.get_installed_apps():` → `return` (early-return guard at top); then `frappe.delete_doc("Module Def", "HR", ignore_missing=True, force=True)` / `... "Payroll" ...`. |
| https://docs.frappe.io/framework/v15/user/en/basics/doctypes/docfield | ✅ | Canonical DocType field-types reference (the `/select_field` path from the brief 404s — this is the verified fallback). Confirms how to declare the new `document_type` **Select** field (option list in the `options` property) and the `journal_entry` **Link** field (`options` = target DocType name), mirroring how `status`/`ocr_status` are declared as `DF.Literal` and `purchase_invoice` as `DF.Link` in this doctype. | Select example: `"fieldtype": "Select", "options": ["Low", "Medium", "High"]`. Link example: `"fieldtype": "Link", "options": "User"` (Options = target DocType). "Frappe comes with more than 30 different fieldtypes." |

Local source-of-truth confirmations (re-verified on this `russ/migrateToV16` checkout per risk #5):
- `erpnext/accounts/doctype/journal_entry/journal_entry.json` → `is_submittable: 1`; `voucher_type` Select options include `Credit Card Entry`, `Cash Entry`, `Bank Entry`; fields `bill_no` (Data), `bill_date` (Date), `user_remark` (Small Text), `posting_date` (Date), `accounts` (Table → Journal Entry Account), `company` (Link).
- `erpnext/accounts/doctype/journal_entry_account/journal_entry_account.json` → `account` (Link Account), `debit_in_account_currency` (Currency), `credit_in_account_currency` (Currency), `party_type` (Link DocType), `party` (Dynamic Link), `cost_center` (Link Cost Center), `reference_type` (Select — its option list includes `Expense Claim`), `reference_name` (Dynamic Link), `user_remark` (Small Text).

## 5. Design

**Stream-R posting framing (read before §5.1–§5.4).** The strongest **native** already-paid path is `Purchase Invoice.is_paid=1` (D-07-1 option C, **recommended default**): one submitted PI books both the invoice legs (DR expense / CR supplier) and the Is-Paid payment legs (DR supplier / CR bank) via `make_payment_gl_entries` (`purchase_invoice.py:1546-1590`), so the supplier nets to zero yet stays visible in spend-by-supplier/AP reports, and it REUSES the existing `promote_to_purchase_invoice` field-mapping path — adding only `is_paid` / `cash_bank_account` / `paid_amount`. The detailed Stream-R design that follows (the `journal_entry` field, `promote_to_journal_entry`, the `Journal Entry`-shaped data model) documents **option A** (direct JE) as the *default implementation behind the `_build_already_paid_voucher()` seam* — it is fully specified so the seam has a concrete fallback, but the **recommended** build is option C (`is_paid`). Because the choice is isolated to the single `_build_already_paid_voucher()` helper (§5.2), choosing C means: the Stream-R voucher is a **Purchase Invoice** (the `journal_entry` Link field is unnecessary — reuse `purchase_invoice`), `promote_to_journal_entry` collapses into the existing `promote_to_purchase_invoice` path plus the 3 paid-fields, and closure-evidence needs **no third voucher type** (flag this downstream simplification for specs [[13-bank-feed-reconciliation]] and [[14-closure-audit-retention]] — see §5.5). Sections 5.1–5.4 below describe option A concretely; substitute the PI-`is_paid` mapping where they say "Journal Entry" if C is locked.

### 5.1 Data model

#### DocType `AP Invoice Capture` — ADD fields

Declared in `ap_invoice_capture.json`; mirrored in the `DF.Literal`/`DF.Link` auto-types block (`ap_invoice_capture.py:150-235`) to match existing convention. Add a module-level constant block alongside `STATUS_*` / `VALIDATION_STATUS_*` (lines 36-90).

| fieldname | fieldtype | options / default | purpose |
|---|---|---|---|
| `document_type` | Select | `Unpaid Bill`\n`Already Paid`\n`Employee Reimbursement`\n`Manual Review`; default empty | The Step-6 classification. Drives the cascade fork. Declared `DF.Literal[...]` to match `status` (182) / `ocr_status` (166). |
| `provisional_stream` | Select | `I`\n`R`\n`R-employee`\n`Unknown`; default empty | The Step-1 provisional tag (owned by [[02-intake-stream-tagging]]). **If spec 02 has not landed it, spec 07 defines it here** and flags the dependency (§8 D-07-2). |
| `classified_stream` | Select | `I`\n`R`\n`R-employee`; default empty | The stream this step resolves to, derived from `document_type`. |
| `stream_tag_agreement` | Select | `Agree`\n`Disagree`\n`Unconfirmed`; default `Unconfirmed` | Queryable tuning signal feeding [[10-ap-review-observability]]. `Disagree` forces `document_type='Manual Review'`. |
| `journal_entry` | Link | `Journal Entry` | The Stream-R promotion target handle. Parallels `purchase_invoice` (208). |
| `expense_claim` | Data | placeholder, default empty | RESERVED for the Employee branch. **NOT a live `Link`** because the target doctype is absent (would break migrate/link-validation). Converts to `Link → Expense Claim` in the hrms-enabled follow-up (§8 D-07-3). |
| `classification_override` | Select | same 4 options as `document_type`; default empty | The clerk override that **always wins**. `classify_document_type` reads this. |
| `classified_at` | Datetime | — | Audit parity with `validated_at` (206). |
| `classified_by` | Link | `User` | Audit parity with `validated_by` (205). |
| `classification_source` | Data | default `ap-classify-v1` (constant `CLASSIFICATION_SOURCE_DEFAULT`) | Audit parity with `validation_source` (207). |
| `card_charge_marker` | Data | — | The OCR evidence string ("paid by Visa \*\*\*\*1234" / "PAID") that drove the Already-Paid call — for audit + the disagreement log. |
| `detected_last4` | Data | — | The last-4 digits matched, if any. |

**Status enum extension** — add `Manual Review` to the `status` `DF.Literal` (182-189) **and** the JSON `status` `options`. Migrate-affecting; risk #4 — confirm no report/permission/list-view assumes the old 6-value set.

**New module-level constants** (alongside lines 36-90):
```
DOCUMENT_TYPE_UNPAID_BILL = "Unpaid Bill"
DOCUMENT_TYPE_ALREADY_PAID = "Already Paid"
DOCUMENT_TYPE_EMPLOYEE_REIMBURSEMENT = "Employee Reimbursement"
DOCUMENT_TYPE_MANUAL_REVIEW = "Manual Review"
STREAM_I = "I"; STREAM_R = "R"; STREAM_R_EMPLOYEE = "R-employee"; STREAM_UNKNOWN = "Unknown"
STREAM_AGREEMENT_AGREE = "Agree"; STREAM_AGREEMENT_DISAGREE = "Disagree"; STREAM_AGREEMENT_UNCONFIRMED = "Unconfirmed"
STATUS_MANUAL_REVIEW = "Manual Review"
CLASSIFICATION_SOURCE_DEFAULT = "ap-classify-v1"
JE_VOUCHER_TYPE_CREDIT_CARD = "Credit Card Entry"
JE_VOUCHER_TYPE_CASH = "Cash Entry"
```

**Permissions:** no new permission rule on `AP Invoice Capture` itself — `document_type`/`classification_override` are writable by the roles that already write the capture (`Accounts User` / `Accounts Manager`, and the new `AP Clerk` from the bible when [[11-approval-sod-workflow]] lands). The whitelisted classify/promote wrappers gate with `frappe.only_for(...)` matching the existing convention (see §5.2).

#### DocType `AP Closed Loop Settings` — ADD fields

| fieldname | fieldtype | options / default | purpose |
|---|---|---|---|
| `default_card_clearing_account` | Link | `Account`; default empty | CR side of the Stream-R JE when paid by **card** (`voucher_type='Credit Card Entry'`). |
| `default_paid_liability_account` | Link | `Account`; default empty | CR side when paid by **cash** (`voucher_type='Cash Entry'`). Optional; if unset, `default_card_clearing_account` is used. |
| `employee_supplier_group` | Link | `Supplier Group`; default empty | Drives the employee-reimbursement classifier. **No native is_internal/employee flag exists** on Supplier Group (only `is_group`/`payment_terms`/`default_payable_account`), and `Supplier.is_internal_supplier` is inter-company, not employees — so the classifier MUST match a configured Supplier Group **name**, not a native boolean (risk #2). |

Extend `get_promote_defaults()` (`ap_closed_loop_settings.py:85`) **or** add a sibling `get_je_defaults()` returning `{company, expense_account, cost_center, card_clearing_account, paid_liability_account}` from `get_singles_dict` (same empty-omitting convention, lines 99-108). Recommend a **sibling `get_je_defaults()`** so the PI promote path stays untouched (§8 D-07-4). Add `employee_supplier_group` to whichever helper the classifier reads.

#### Child tables

**None new.** Journal Entry's native `accounts` child (`Journal Entry Account`) already carries `account` / `debit_in_account_currency` / `credit_in_account_currency` / `party_type` / `party` / `cost_center` / `reference_type` / `reference_name` / `user_remark` (verified in JSON, §4).

### 5.2 Endpoints

All whitelisted wrappers normalize a `defaults` arg that may arrive as a JSON **string** (from the JS form) or a **dict** (from server/test code) — the existing convention at `promote_to_purchase_invoice_for:1692-1696`. Each calls `_kick_next_step()` to resume the cascade.

```python
# NEW — classification entrypoint (mirrors confirm_extracted_fields_for at ~960)
@frappe.whitelist()
def classify_document_type_for(capture: str, override: str | None = None) -> str:
    """Run/refresh Step-6 classification. `override` (clerk) always wins.
    Returns capture.document_type. Resumes the cascade via _kick_next_step."""

# NEW — Stream-R promotion entrypoint (mirrors promote_to_purchase_invoice_for:1686-1702)
@frappe.whitelist()
def promote_to_journal_entry_for(capture: str, defaults: str | dict | None = None) -> str:
    """Promote an 'Already Paid' capture into a Journal Entry. Returns je.name.
    Parses defaults str|dict, reloads capture, calls _kick_next_step."""
```

Pure functions (save-optional like the existing ones):

```python
def classify_document_type(
    capture: "APInvoiceCapture | str",
    override: str | None = None,
    actor: str | None = None,
    save: bool = True,
) -> str: ...

def promote_to_journal_entry(
    capture: "APInvoiceCapture | str",
    actor: str | None = None,
    defaults: dict | None = None,
    save: bool = True,
) -> "Document": ...   # returns the Journal Entry doc
```

Both wrappers call `frappe.only_for(("Accounts User", "Accounts Manager"))` (or the new `AP Clerk` role once [[11-approval-sod-workflow]] introduces it), matching the role-gating convention already used by the other action wrappers.

The Already-Paid posting is built inside a **single swap-friendly helper** so the §8 D-07-1 A↔B↔C decision is one function change. **Recommended default: option C (PI `is_paid=1`)** — least custom code, keeps Supplier visibility, reuses the existing PI field-mapping path:

```python
def _build_already_paid_voucher(capture, defaults) -> "Document":
    """Single decision point for the already-paid posting. Keep this the ONLY
    place the A/B/C choice lives so the mechanism stays config-swappable.
    RECOMMENDED impl (option C): build a Purchase Invoice with is_paid=1 +
    cash_bank_account + paid_amount — one submitted PI posts DR expense / CR bank
    via make_payment_gl_entries (purchase_invoice.py:1546-1590); supplier nets to
    zero but stays visible in spend-by-supplier/AP reports; reuses the existing
    promote_to_purchase_invoice mapping (adds only the 3 paid fields).
    Fallback impl (option A): build a balanced Journal Entry (most custom code).
    Swappable to either without touching the promote-path callers."""
```

### 5.3 Logic

#### `classify_document_type(capture, override=None, actor=None, save=True) -> str`
New pure function, co-located near `_classify_purchase_reference` (`ap_invoice_capture.py:1005`).

1. **Resolve capture** (str → doc) as the other pure functions do.
2. **Precondition:** capture must be OCR `Confirmed` (`status == STATUS_CONFIRMED`) so structured fields are reliable; else raise `CaptureValidationError` (reuse the existing exception, subclasses `frappe.ValidationError`).
3. **Override wins:** if `override` (or persisted `capture.classification_override`) is set, set `document_type = override`, `classification_source = "clerk-override"`, skip heuristics, jump to step 7.
4. **Heuristic resolution order:**
   - (a) **Card-charge marker present** → `document_type = 'Already Paid'`, `classified_stream = 'R'`. Detection: OCR text (from `final_*` fields / `ocr_raw_response`) matches a last-4 regex `(?:\*{2,}|x{2,}|ending\s+in\s+)(\d{4})` or a literal `PAID` / `paid by <brand> ****dddd` marker. Persist the matched string to `card_charge_marker` and the digits to `detected_last4`.
   - (b) **Employee supplier group** → if `matched_supplier` is set and `Supplier.supplier_group == settings.employee_supplier_group` (configured group must exist; if the configured group is missing, treat as not-employee and continue) → `document_type = 'Employee Reimbursement'`, `classified_stream = 'R-employee'`.
   - (c) **Else** → `document_type = 'Unpaid Bill'`, `classified_stream = 'I'`.
   - (d) **Ambiguous / unresolvable** (e.g. employee-group check needed but supplier unmatched, per the locked §8 D-07-5 default) → `document_type = 'Manual Review'`.
5. **CONFIRM/REVISE the provisional tag:** compare `classified_stream` against `provisional_stream` (from [[02-intake-stream-tagging]]).
   - Map `Unpaid Bill→I`, `Already Paid→R`, `Employee Reimbursement→R-employee`.
   - If `provisional_stream` is empty/`Unknown` → `stream_tag_agreement = 'Unconfirmed'` (no conflict to resolve).
   - If they match → `stream_tag_agreement = 'Agree'`.
   - If they **disagree** (e.g. body said PAID but `provisional_stream='I'` from a structured total + due-date) → **override to review:** `document_type = 'Manual Review'`, `stream_tag_agreement = 'Disagree'`, `action_required = 1`, `action_required_reason` names the conflict (e.g. *"Stream conflict: intake tagged I, classifier read Already-Paid card marker {marker} — manual classification required"*). **Persist this record** (it is the [[10-ap-review-observability]] tuning signal — emit an `AP Review Event` with root-cause `stream_mistag`; do NOT just log to console).
6. **If `document_type == 'Manual Review'`** for any reason: set `status = STATUS_MANUAL_REVIEW`, `action_required = 1`, leave `action_required_reason` set.
7. **Audit + persist:** set `classified_at = now_datetime()`, `classified_by = actor or frappe.session.user`, `classification_source` (default `ap-classify-v1`). `if save: capture.save()`. Return `document_type`.

**Idempotency:** classification is naturally re-runnable — a clerk override re-runs it and supersedes the prior result. No DB voucher is created here, so no natural-key concern.

#### `promote_to_journal_entry(capture, actor=None, defaults=None, save=True) -> Document`
New pure function mirroring `promote_to_purchase_invoice` (`ap_invoice_capture.py:1148-1235`).

1. **Resolve capture** (str → doc).
2. **Preconditions** (raise `CapturePromotionError` on each):
   - `document_type == 'Already Paid'` (wrong-doctype guard — symmetric to the new PI guard).
   - `matched_supplier` set **OR** a configured suspense party (per [[06-gl-coding-tax-costcenter]] "Unmapped Card Spend"; Stream R supplier is a soft flag per plan Step 4, line 39 — so an unmatched supplier does NOT block here, it falls back to the configured Unmapped account).
   - **Soft idempotency guard** (parallel to 1181-1186): `if capture.promotion_status == PROMOTION_STATUS_PROMOTED and capture.journal_entry: raise CapturePromotionError("...already promoted to Journal Entry {0}")`.
   - **Config guard:** `settings.default_card_clearing_account` (or `default_paid_liability_account` for cash) MUST be set; else raise `CapturePromotionError` with a clear message — never build an unbalanced JE.
3. **Build via `_build_already_paid_voucher(capture, defaults)`** (default option A):
   - `je = frappe.new_doc("Journal Entry")`.
   - `je.voucher_type = 'Cash Entry'` if the marker indicates cash else `'Credit Card Entry'` (default).
   - `je.company = defaults.company or get_je_defaults().company`.
   - `je.posting_date = capture.final_invoice_date.isoformat() if set else today()`.
   - `je.bill_no = capture.final_supplier_invoice_no`; `je.bill_date = capture.final_invoice_date` (isoformat).
   - `je.user_remark` = audit string (capture name + provider + "Stream R already-paid; not bank reconciled — closure pending bank-feed match per spec 13").
   - **Row 1 — DR expense:** `account = defaults.expense_account or get_je_defaults().expense_account`, `cost_center = ...cost_center`, `debit_in_account_currency = flt(capture.final_total_amount)`. Optionally `party_type='Supplier'` + `party = matched_supplier` for spend-by-supplier visibility (recommended when supplier is matched).
   - **Row 2 — CR liability:** `account = default_card_clearing_account` (or `default_paid_liability_account` for cash), `credit_in_account_currency = flt(capture.final_total_amount)`.
   - **Balance assertion:** DR total == CR total == `final_total_amount` (Journal Entry's own validate also enforces this — §4).
4. `je.insert(ignore_permissions=True)`. **Leave the JE draft** (parity with `promote_to_purchase_invoice` which leaves the PI draft) — see §8 D-07-6.
5. **Persist on capture** (parallel to 1224-1229): `capture.journal_entry = je.name`, `capture.promotion_status = PROMOTION_STATUS_PROMOTED`, `capture.action_required = 0`, `capture.action_required_reason = None`, `if actor: capture.classified_by = actor`. `if save: capture.save()`. Return `je`.

**Idempotency:** reuse the soft guard (step 2) exactly as PI does. A stronger DB natural-key/content-hash guard (dedupe on `supplier + bill_no + total`) is a [[01-foundations-settings-async-idempotency]] deliverable **not yet present** — this spec calls it out (risk #8) rather than assuming it; in the interim, enqueue `deduplicate=True` + the `promotion_status` check inside a single transaction is the guard. Note the residual race window.

#### Add the wrong-doctype guard to `promote_to_purchase_invoice`
Insert at the precondition block (~line 1170), **before** the existing `validation_status` check:
```
if capture.document_type and capture.document_type != DOCUMENT_TYPE_UNPAID_BILL:
    raise CapturePromotionError("Capture document_type is {0}; only 'Unpaid Bill' promotes to Purchase Invoice.")
```
(Guard only fires when `document_type` is set — preserves back-compat for captures created before this field exists, which classify defaults to `Unpaid Bill`.)

### 5.4 Cascade & stream-awareness

Insert a **classification hop** into `_determine_next_step()` (`ap_invoice_capture.py:321-366`), **after** Step 2's OCR-Confirmed check and **before** validation/promotion:

```
# Step 2b (NEW): Confirmed OCR, not yet classified → classify
if (self.ocr_status == OCR_STATUS_CONFIRMED
        and not self.document_type):
    return ("classify_document_type_for", "auto: post-confirm Step-6 classification")
```

Then **fork on `document_type`** for the existing Step 2/3 logic:

| document_type | Stream | Next hop | Notes |
|---|---|---|---|
| `Unpaid Bill` | I | `validate_for_purchase_invoice_for` → (manual Promote seam) → `promote_to_purchase_invoice` | Existing path, unchanged except the new wrong-doctype guard. |
| `Already Paid` | R | `promote_to_journal_entry_for` | **Bypasses** `validate_for_purchase_invoice` (PI-specific). A thin `validate_for_journal_entry` (checks expense + liability account + amount present) MAY gate it; recommend gating (§8 D-07-7). NO approval, NO payment hop — closure is reconciliation-only ([[14-closure-audit-retention]]). |
| `Employee Reimbursement` | R-employee | **none** — set `status='Manual Review'`, `action_required_reason` names the hrms dependency, leave `expense_claim` unset, **return None** (halt). | Becomes a live Expense Claim branch only when hrms is installed (§8 D-07-3). |
| `Manual Review` | — | **return None** (halt; hold for clerk). | Clerk sets `classification_override` and re-runs `classify_document_type_for`, which supersedes and resumes. |

Concretely, the existing Step 2 line (339-343) becomes guarded by `self.document_type == DOCUMENT_TYPE_UNPAID_BILL`, and a new Already-Paid branch returns `("promote_to_journal_entry_for", "auto: Stream-R already-paid posting")` when `document_type == DOCUMENT_TYPE_ALREADY_PAID and not self.journal_entry`.

**Pause vs auto-advance:** `Unpaid Bill` still pauses at the manual Promote seam (defaults required, per the comment at 345-348). `Already Paid` can auto-advance to JE promotion **only if** `get_je_defaults()` supplies company + expense + clearing accounts; if any is missing, `promote_to_journal_entry` raises and `_run_cascade_step` parks the capture with `action_required` (the existing failure-wrapper behavior described at 380-386) — recommend treating Already-Paid as a manual-promote seam too until config is verified (§8 D-07-6). `Manual Review` and `Employee Reimbursement` halt.

Test flags are unchanged: `frappe.flags.ap_auto_progress_enabled` opts the cascade in under `in_test`; `skip_ap_auto_progress` short-circuits (lines 308-313).

### 5.5 Cross-cutting

- **Permissions / SoD:** classify + JE-promote wrappers gate with `frappe.only_for(...)` (existing convention). Stream R has **no** approval/SoD ([[11-approval-sod-workflow]] is Stream I only) — the JE posts and reconciles; the only control is the optional `validate_for_journal_entry`.
- **Idempotency ([[01-foundations-settings-async-idempotency]]):** consumes the job-level `deduplicate=True`/`job_name` + the soft capture-flag guard. The natural-key voucher guard is a 01 deliverable not yet present (risk #8) — named, not assumed.
- **Async / enqueue:** both new hops route through `_enqueue_next` → `_run_cascade_step` exactly like the existing steps (no new enqueue machinery).
- **Observability ([[10-ap-review-observability]]):** the stream-tag disagreement (`stream_tag_agreement='Disagree'`) is persisted on the capture AND emitted as an `AP Review Event` with root-cause tag `stream_mistag`. The classifier-vs-tag agreement rate is the Step-9 tuning signal the plan calls out (lines 52, 67-72).
- **Closure ([[14-closure-audit-retention]]):** under **option A (JE)** the `journal_entry` link + `voucher_type` is the NEW Stream-R closure anchor — `derive_closure_evidence` (walking_skeleton.py:278-339) must learn to recognise a submitted JE (and its bank-feed match from [[13-bank-feed-reconciliation]]) the way it currently recognises PI+PE.
- **Downstream simplification IF option C (`is_paid`) is chosen (flag for specs [[13-bank-feed-reconciliation]] and [[14-closure-audit-retention]]):** the Stream-R voucher is a **Purchase Invoice** (the already-paid PI), so there is **no separate `journal_entry` link to track** (reuse the existing `purchase_invoice` field) and **closure-evidence needs no third voucher type** — `derive_closure_evidence` already understands PI; the Stream-R closure anchor is just a *submitted, `is_paid` Purchase Invoice* whose bank-side payment GL is posted in-line, and spec 13's bank-feed match reconciles against that PI's bank leg rather than a distinct JE. Specs 13 and 14 should treat the JE-recognition work as **conditional on D-07-1 landing on option A**, not unconditional.

## 6. Acceptance criteria

- **AC-07-1 (positive, classify Already Paid):** A confirmed capture whose OCR text contains `"paid by Visa ****1234"` classifies to `document_type='Already Paid'`, `classified_stream='R'`, with `card_charge_marker` and `detected_last4='1234'` persisted.
- **AC-07-2 (positive, classify Employee):** A confirmed capture whose `matched_supplier` belongs to the configured `employee_supplier_group` classifies to `document_type='Employee Reimbursement'`, `classified_stream='R-employee'`.
- **AC-07-3 (positive, classify Unpaid Bill):** A confirmed capture with no card marker and a normal (non-employee-group) supplier classifies to `document_type='Unpaid Bill'`, `classified_stream='I'`.
- **AC-07-4 (override wins):** With `classification_override='Unpaid Bill'`, a capture that DOES carry a card-charge marker still classifies to `Unpaid Bill` (`classification_source='clerk-override'`).
- **AC-07-5 (disagreement → Manual Review + signal):** `provisional_stream='I'` but a PAID marker present → `document_type='Manual Review'`, `status='Manual Review'`, `stream_tag_agreement='Disagree'`, `action_required=1` with a conflict reason, and an `AP Review Event` (root-cause `stream_mistag`) is created.
- **AC-07-6 (negative, ambiguous → Manual Review):** A capture with no marker and an **unmatched** supplier (employee check needed but supplier unresolved) classifies to `Manual Review` per the locked default (§8 D-07-5).
- **AC-07-7 (positive, JE promotion):** Promoting an `Already Paid` capture produces a `Journal Entry` with `voucher_type='Credit Card Entry'`, two **balanced** accounts rows (DR `default_expense_account` == CR `default_card_clearing_account` == `final_total_amount`); `capture.journal_entry` set, `promotion_status='Promoted'`, `action_required` cleared. Verified via the JE `accounts` child rows, not a screenshot.
- **AC-07-8 (negative, wrong document_type):** `promote_to_journal_entry` on a capture whose `document_type != 'Already Paid'` raises `CapturePromotionError`.
- **AC-07-9 (negative, idempotency guard):** A second `promote_to_journal_entry` on an already-promoted capture raises `CapturePromotionError` (no second JE created).
- **AC-07-10 (negative, missing config):** `promote_to_journal_entry` with no `default_card_clearing_account` configured raises `CapturePromotionError` — and does **not** insert an unbalanced JE.
- **AC-07-11 (negative, PI guard):** `promote_to_purchase_invoice` on an `Already Paid` capture raises `CapturePromotionError` (`document_type` guard).
- **AC-07-12 (cascade routing):** With `ap_auto_progress_enabled`: an Unpaid-Bill capture lands on the PI path; an Already-Paid capture lands on the JE path; an Employee-Reimbursement capture lands in `Manual Review` with an hrms-dependency reason and **no** `expense_claim` link; a Manual-Review capture halts the cascade.
- **AC-07-13 (settings):** `get_je_defaults()` returns `card_clearing_account` + `employee_supplier_group` + expense/cost-center/company; a missing-config call surfaces the gap (empty-key omission) so the promote guard fires.
- **AC-07-14 (migrate-safety):** After `bench migrate`, `document_type` (Select, 4 options) and the extended `status` (7 options incl. `Manual Review`) exist; `expense_claim` is a `Data` field (NOT a broken `Link`); no migrate error from the absent Expense Claim doctype.

## 7. Tests

### 7.1 Automated
Module: `erpnext.accounts.doctype.ap_invoice_capture.test_ap_invoice_capture` — add a new class `TestAPInvoiceCaptureDocumentTypeBranching` (mirror `TestAPInvoiceCaptureValidationAndPromotion` at line 536; idempotency-guard pattern at `test_promote_is_idempotent_guard` line 715; cascade pattern at `TestAPInvoiceCaptureAutoProgress` line 1296). Base `from frappe.tests import IntegrationTestCase` (line 8). Roll back DB writes in `tearDown` (delete any created JE/PI/captures + the `AP Review Event`).

`classify_document_type()` cases:
- **Positive:** card marker → `Already Paid` (AC-07-1); employee-group supplier → `Employee Reimbursement` (AC-07-2); plain bill → `Unpaid Bill` (AC-07-3).
- **Override:** override beats card marker (AC-07-4).
- **Disagreement/edge:** `provisional_stream='I'` + PAID marker → `Manual Review` + `stream_tag_agreement='Disagree'` + `action_required=1` + `AP Review Event` created (AC-07-5).
- **Negative:** ambiguous / unmatched-supplier-when-employee-check-needed → `Manual Review` per locked default (AC-07-6).

`promote_to_journal_entry()` cases:
- **Positive:** balanced JE, `voucher_type='Credit Card Entry'`, capture fields set (AC-07-7) — assert via `frappe.get_doc("Journal Entry", capture.journal_entry).accounts`.
- **Negative/guard:** wrong `document_type` raises (AC-07-8); second call when promoted raises (AC-07-9, mirror line 715); missing `default_card_clearing_account` raises and creates **no** JE (AC-07-10).
- **Wrong-doctype on PI:** `promote_to_purchase_invoice` on Already-Paid raises (AC-07-11).

Cascade-routing cases (`frappe.flags.ap_auto_progress_enabled`): all four landings (AC-07-12).

Settings cases: `get_je_defaults()` positive + missing-config negative (AC-07-13).

Run locally before declaring done (per CLAUDE.md — throwaway console probes are insufficient):
```
bench --site <site> run-tests --module erpnext.accounts.doctype.ap_invoice_capture.test_ap_invoice_capture
```

### 7.2 Clean-room test plan
Ship `test/testplans/document-type-classification-branching.md` (kebab slug). Scope: a fresh-bench operator classifies and promotes two captures (one card-marked → JE, one plain bill → PI) plus an employee-group supplier capture (→ Manual Review because hrms is absent), verifying each via `bench mariadb`/`bench execute` against the DB (JE `voucher_type` + balanced rows + `capture.document_type`/`journal_entry`), not screenshots. Required sections per CLAUDE.md, with the **explicit note** that the Expense Claim path is *expected* to land in Manual Review because hrms is absent on this bench (and that installing hrms makes the reserved `expense_claim` field linkable — a future-state note, not a step). Test-data prereqs: a Supplier in a Supplier Group configured as `employee_supplier_group`; `AP Closed Loop Settings` with `default_company`/`default_expense_account`/`default_cost_center`/`default_card_clearing_account` set; two captures with exact OCR text/markers given inline. Cleanup deletes the test JE/PI/captures.

### 7.3 UI testing (Playwright MCP)
Browser-driven verification of the desk UI this slice adds, via the **Playwright MCP** server. These are the UI steps of the §7.2 clean-room runbook.
- **Prereq:** Playwright MCP per `test/testplans/BROWSER-TESTING-SETUP.md` (`claude mcp list` must list `playwright`; restart after registering). `.mcp.json` / `.playwright-mcp/` gitignored.
- **Evidence:** screenshots to `test/testplans/screenshots/document-type-classification-branching/<name>.png` (committed; pass as `filename`).
- **Source of truth stays the DB:** after every UI write, verify via `bench --site <site> mariadb` / `bench … execute`, then delete UI-created data.

**Scenarios** (`route → action → expected UI → DB assertion`):
- After Confirm, open the capture → `document_type` is classified and shown (e.g. "Already Paid" with the `card_charge_marker` visible); screenshot → DB-assert `document_type`, `classified_stream`, `stream_tag_agreement`.
- A stream-conflict capture (intake said Invoice, classifier reads a PAID card marker) → lands in `Manual Review` with `action_required_reason` naming the conflict; screenshot → DB-assert status `Manual Review` + `stream_tag_agreement='Disagree'`.
- Clerk override: set `classification_override` on the form and re-run classify → classification changes accordingly; screenshot → DB-assert `document_type` == override.

**Not browser-testable in this slice** (covered by §7.1/§7.2): the JE-vs-PI `is_paid` GL posting internals (§7.1); hrms-absent Employee-Reimbursement deferral is asserted via DB.

## 8. Open decisions

- **D-07-1 — Already-Paid posting mechanism.** Options: **(A)** direct **Journal Entry** (DR expense / CR card-or-cash liability) — the original plan default, but the **most custom code**: an entirely new hand-balanced JE builder, a new `journal_entry` link field, and teaching closure-evidence a third voucher type; **(B)** **Purchase Invoice + a 'Credit Card Clearing' account** (more documents and a momentary AP-aging blip — vendor shows in AP aging *and* spend-by-supplier); **(C)** **Purchase Invoice with `is_paid=1`** — the strongest native path. **Recommended default: (C).** *Verified:* with `is_paid=1` + `cash_bank_account` + `paid_amount`, ONE submitted PI carries **two GL layers** — the normal invoice booking (DR expense / CR supplier-Creditors) plus the Is-Paid payment legs added by `make_payment_gl_entries` (`erpnext/accounts/doctype/purchase_invoice/purchase_invoice.py:1546-1590`): DR supplier / CR bank. The supplier is thus credited then debited and nets to zero, the vendor STILL appears in spend-by-supplier/AP reports, AND it REUSES the existing `promote_to_purchase_invoice` field-mapping path (adds only 3 fields: `is_paid`, `cash_bank_account`, `paid_amount`). Recommend (C) on **least-custom-code + keeps-Supplier-visibility** grounds. Implement behind the single `_build_already_paid_voucher()` helper so A↔B↔C stays a one-function, config-swappable change. *(Note: option C was surfaced/strengthened by reading `make_payment_gl_entries` in upstream source — it was NOT the original plan default, which assumed the JE.)* This remains a **decision, not a forced resolution** — the seam keeps it swappable. **Owner:** accounting lead (Bryan). **Lock by:** start of the build for this spec.
- **D-07-2 — `provisional_stream` field ownership.** This step CONFIRMS/REVISES the Step-1 tag. If [[02-intake-stream-tagging]] lands first, it owns `provisional_stream` + the agreement fields; if 07 lands first, 07 defines them. **Recommended default:** define the field set in **whichever spec lands first** and the other references it (no duplicate definition). **Owner:** orchestrator. **Lock by:** before either 02 or 07 starts coding.
- **D-07-3 — `expense_claim` field type pre-hrms.** A live `Link → Expense Claim` breaks migrate/link-validation because the doctype is absent. Options: **(a)** declare `expense_claim` as **`Data` placeholder now**, convert to `Link` in the hrms follow-up; **(b)** gate a `Link` behind hrms presence (conditional field — fragile). **Recommended default: (a).** **Owner:** this spec's builder. **Lock by:** start of build (it's a schema decision).
- **D-07-4 — `get_je_defaults()` vs extending `get_promote_defaults()`.** Options: a **sibling `get_je_defaults()`** (PI path untouched) vs **extending `get_promote_defaults()`** (one helper, but PI promote would carry JE-only keys). **Recommended default: sibling `get_je_defaults()`.** **Owner:** builder. **Lock by:** build start.
- **D-07-5 — Classifier fallback when supplier unmatched (employee check needed).** Options: default to **`Manual Review`** (safe — don't guess), vs default to **`Unpaid Bill`** (Stream I, optimistic). **Recommended default: `Manual Review`** (an unmatched supplier on Stream I already blocks at validation per plan Step 4 line 39, so routing to review is consistent). **Owner:** accounting lead. **Lock by:** before AC-07-6 test is written.
- **D-07-6 — Submit the JE on promote, or leave draft + manual seam.** Options: **leave draft** (parity with `promote_to_purchase_invoice`, clerk submits) vs **`je.submit()`** in the promote call (auto-post). **Recommended default: leave draft** unless [[14-closure-audit-retention]] requires a submitted JE for closure derivation — revisit when 14 is specced. Relatedly, decide whether Already-Paid **auto-advances** to promotion or **pauses** at a manual seam like Unpaid Bill; **recommend pause** until `get_je_defaults()` config is verified non-empty. **Owner:** accounting lead + 14 owner. **Lock by:** before 14 is built.
- **D-07-7 — JE-specific validation gate.** Options: **add `validate_for_journal_entry`** (asserts expense + liability account + amount present before promote) vs **rely on the promote-config guard only**. **Recommended default: add the thin gate** (consistent with the Unpaid-Bill validation seam; keeps the failure message specific). **Owner:** builder. **Lock by:** build start.

## 9. Dependencies & sequencing

**Must land first:**
- [[01-foundations-settings-async-idempotency]] — idempotency. This spec **consumes** the job-level `deduplicate`/`job_name` + soft capture-flag guard; the stronger natural-key/content-hash voucher guard is a 01 deliverable not yet present (risk #8). 07 must not assume more than 01 provides.
- [[02-intake-stream-tagging]] — owns `provisional_stream` (D-07-2). 07 confirms/revises it; if 02 is late, 07 defines the field and flags ownership.
- [[06-gl-coding-tax-costcenter]] — supplies the expense account / cost-center inference and the "Unmapped Card Spend" account that the Stream-R JE's CR/DR sides reference for unmatched suppliers.
- [[05-supplier-resolution]] — `matched_supplier` + `Supplier.supplier_group` feed the employee classifier (soft dependency; current `_match_supplier` suffices for the happy path).
- `AP Closed Loop Settings` field additions (`default_card_clearing_account`, `default_paid_liability_account`, `employee_supplier_group`) + `get_je_defaults()` — in-scope here.

**Unblocks / feeds:**
- [[10-ap-review-observability]] — consumes the `stream_tag_agreement='Disagree'` signal (`AP Review Event`, root-cause `stream_mistag`) this step persists.
- [[14-closure-audit-retention]] — must extend `derive_closure_evidence` to recognise the Journal Entry voucher (+ `voucher_type`) as the Stream-R closure anchor (walking_skeleton.py:278-339 understands only PI+PE today).
- [[13-bank-feed-reconciliation]] — the JE is the artifact the 72h SimpleFIN match reconciles against for Stream R.

**Estimated size: L.** New field set on two DocTypes (migrate-affecting status-enum change), one new pure classifier + one new pure promotion path + one new helper, two new whitelisted wrappers, a cascade fork with four branches, settings extension, and a full test class + clean-room plan. Smaller than XL (no new child tables, reuses the JE native schema), larger than M (touches the shared cascade and two DocTypes' schemas).
