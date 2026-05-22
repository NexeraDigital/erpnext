# Fork Changes — AP Closed Loop Receipt Processing

> **Fork:** NexeraDigital/erpnext (this repo, branch `develop`)
> **Upstream baseline:** `frappe/erpnext` commit `b3526599dd` (`Merge pull request #51343 …`)
> **All fork commits are descendants of that upstream commit.**

This fork adds a single, narrowly-scoped vertical slice on top of upstream ERPNext: an **Accounts Payable Closed Loop Receipt Processing** pilot for NexeraDigital. It does **not** modify any existing accounting, stock, or buying logic. The only edit outside the new files is a 2-line refactor in `erpnext/setup/utils.py`.

---

## 1. Files Added / Modified

```
 AGENTS.md                                                              |   76 ++
 erpnext/accounts/ap_closed_loop/__init__.py                            |    0
 erpnext/accounts/ap_closed_loop/walking_skeleton.py                    |  365 +++++
 erpnext/accounts/ap_closed_loop/test_walking_skeleton.py               |  130 ++
 erpnext/accounts/doctype/ap_invoice_capture/__init__.py                |    0
 erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.json    |  662 +++++++++
 erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.py      | 1424 ++++++++++++++++++++
 erpnext/accounts/doctype/ap_invoice_capture/test_ap_invoice_capture.py | 1272 +++++++++++++++++
 erpnext/setup/utils.py                                                 |    4 +-
 9 files changed, 3931 insertions(+), 2 deletions(-)
```

**Net effect:** one new DocType (`AP Invoice Capture`), one new utility module (`ap_closed_loop/`), three test modules, one operating-notes file (`AGENTS.md`), and a 2-line internal refactor.

---

## 2. Commit Timeline

The fork was built as 8 issue-scoped feature commits + their merges. Each feature is one acceptance-criterion-bounded step in the pilot's vertical slice.

| Commit | Subject | What it landed |
|---|---|---|
| `c95d2d9` | feat: add AP closed loop walking skeleton | `ap_closed_loop/walking_skeleton.py` end-to-end deterministic flow against existing ERPNext PI + PE |
| `78a5a6c` | Merge #2 walking skeleton | merge |
| `10e3a7f` | feat: add AP invoice image intake capture | introduces `AP Invoice Capture` doctype — manual upload, supported-format gating |
| `bce1728` | Merge #3 image intake | merge |
| `4e2fe5a` | feat: add OCR proposal review | deterministic fake OCR + `proposed_*` fields + AP-clerk confirm |
| `af3c7ff` | Merge #4 OCR proposal | merge |
| `1c1c6fa` | feat: add validation promotion | supplier matching + PO/PR classification + promote to Purchase Invoice |
| `e0cfa8e` | Merge #5 validation promotion | merge |
| `2fae4ef` | feat: add approval controls | auto-approval threshold + manager routing + decision |
| `ca37666` | Merge #6 approval controls | merge |
| `04ffeb6` | feat: add mock payment writeback | mock-labeled Payment Entry creation tied to capture |
| `c4ec54e` | Merge #7 mock payment | merge |
| `dbabb28` | feat: add AP invoice capture closure evidence | derives closure from native state, exposes audit payload |
| `69d232d` | Merge #8 closure evidence | merge |
| `ae93cf8` | docs: add AP closed loop agent memory | `AGENTS.md` — Codex/Claude operating notes |
| `f40e4b6` | Merge PR #9 codex/ap-closed-loop | final integration merge into `develop` |

GitHub epic: `NexeraDigital/erpnext#1` (per `AGENTS.md`).

---

## 3. Core Design Principles (encoded in code & tests)

Both `walking_skeleton.py` and `ap_invoice_capture.py` open with the same set of explicit guardrails, and the tests enforce them:

1. **Purchase Invoice is the canonical payable invoice.** The pilot never invents a parallel payable doctype.
2. **Payment Entry is the payment/closure anchor.** Native ERPNext doctype, native lifecycle.
3. **No `Bank Transaction` is created.** Bank reconciliation is *not* implied by closure — they are different signals. Tests assert the Bank Transaction count never increases.
4. **No custom `closed` flag is persisted.** Closure is *derived* from native state: submitted PI + submitted PE + `outstanding_amount == 0` + `status == "Paid"`.
5. **All provider / payment artifacts are visibly labeled MOCK.** `reference_no` carries the `MOCK-PAY-…` prefix; remarks explicitly say "Not bank reconciled. No real banking integration." This prevents the evidence trail from being mistaken for a real banking integration.
6. **Nothing silently progresses.** Unsupported formats, missing mandatory fields, unknown suppliers, ambiguous matches, and unapproved totals all set `action_required = 1` and surface a human-readable `action_required_reason`.

---

## 4. AGENTS.md — Operating Notes (new file)

`AGENTS.md` is a project-memory note for human + AI operators working on this pilot. It pins:

- The canonical project state document in Obsidian (`/Users/brandon/.../00 - Project State.md`).
- Supporting notes (Architecture Decisions, Vertical Slice Plan, Implementation Log, AC Matrix, Open Questions, Claude-Codex Handoff).
- GitHub epic: `https://github.com/NexeraDigital/erpnext/issues/1`.
- Operating model: Codex orchestrates and tracks; Claude is the bounded implementation executor.
- Local commands to open the Obsidian vault and to invoke Claude in read-only or implementation mode.

**This file is documentation only — no runtime effect.**

---

## 5. `erpnext/accounts/ap_closed_loop/walking_skeleton.py`

A pure-Python end-to-end flow that exercises the AP spine *before* any real UI/OCR work. It is intentionally **not** wired into the desk; it's invoked from tests and dev shells.

### 5.1 Dataclasses

| Type | Purpose |
|---|---|
| `SourceCapture` | Stand-in for a real receipt — `capture_id`, `image_uri`, `captured_at`, auto-computed `content_hash` (SHA-256 of the seed string). |
| `FakeExtraction` | Deterministic header-level extraction result — supplier, bill_no, qty, rate, currency. Carries `provider = "deterministic_fake_extractor"` and `is_mock = True`. |
| `ApprovalOutcome` | Records the walking-skeleton approval shortcut. |
| `MockPaymentInstruction` | Mock-only payment request (reference, provider, status, amount, issued_at, `is_mock = True`). |
| `ClosureEvidence` | Audit payload: source, extraction, approval, mock_payment, PI/PE names + native state (status, outstanding_amount, docstatus, paid_amount), GL entry list, **Bank Transaction count**, derived `closed` flag, and `closure_basis` explanation. |

### 5.2 Pipeline functions

```text
SourceCapture
   │
   ▼  fake_extract()           ──► FakeExtraction
   │  (deterministic — same content_hash always yields same bill_no/qty/rate)
   ▼  create_purchase_invoice()──► native Purchase Invoice (inserted + submitted)
   │  (single item row, remarks carry source/content_hash/provider/mock flag)
   ▼  apply_walking_skeleton_approval()
   │  (records APPROVAL_SHORTCUT in PI.remarks via frappe.db.set_value)
   ▼  create_mock_payment_entry()
   │  (get_payment_entry helper, paid_from = "_Test Bank - _TC",
   │   reference_no = "MOCK-PAY-<PI>", remarks state "MOCK PAYMENT … no bank reconciliation")
   ▼  derive_closure_evidence()──► ClosureEvidence
      (re-reads PI/PE state, queries GL Entry & Bank Transaction Payments,
       computes closed = PI.docstatus==1 AND PE.docstatus==1 AND outstanding==0 AND status=="Paid")
```

### 5.3 Constants worth knowing

```python
MOCK_PROVIDER         = "deterministic_fake_extractor"
MOCK_PAYMENT_PROVIDER = "mock_payment_provider"
MOCK_PAYMENT_PREFIX   = "MOCK-PAY"
MOCK_PAYMENT_REMARK   = ("MOCK PAYMENT - AP Closed Loop walking skeleton. "
                        "Not bank reconciled. No real banking integration.")
APPROVAL_SHORTCUT     = "walking_skeleton_auto_approve"
```

### 5.4 Tests (`test_walking_skeleton.py`)

`TestAPClosedLoopWalkingSkeleton(IntegrationTestCase)` with `EXTRA_TEST_RECORD_DEPENDENCIES = ["Item", "Cost Center"]`:

- `test_fake_extraction_is_deterministic` — same `SourceCapture` → same `bill_no`, `qty`, `rate`; provider and `is_mock` correct.
- `test_walking_skeleton_end_to_end` — runs `run_walking_skeleton(supplier="_Test Supplier")` and asserts:
  - PI and PE are both submitted (`docstatus == 1`).
  - `outstanding_amount == 0`, `status == "Paid"`.
  - The mock prefix appears on PE `reference_no`.
  - The Bank Transaction count is unchanged.
  - `evidence.closed is True` and `closure_basis` is the literal explanatory string.

---

## 6. New DocType — `AP Invoice Capture`

This is the *production* shape that succeeds the walking skeleton. The DocType is **not an accounting document**; it is a pre-accounting capture record whose job is to land an invoice image, run a non-authoritative OCR proposal, get AP-clerk confirmation, validate against existing ERPNext records, and then hand off to native Purchase Invoice / Payment Entry.

### 6.1 DocType definition (`ap_invoice_capture.json`)

- Naming: `format:APIC-{YYYY}-{#####}`
- Engine: InnoDB
- Field sections (`Section Break`s) shape the form into sequential clerk steps:
  1. **Source** — `source_filename`, `file_extension`, `intake_channel`, `source_file` (Link → File), `source_file_url`, `received_at`.
  2. **Lifecycle** — `status`, `is_supported_format`, `action_required`, `action_required_reason`.
  3. **Context** — `source_context`, `validation_message`.
  4. **OCR** — `ocr_provider`, `ocr_status`, `ocr_extracted_at`, `proposed_supplier`, `proposed_supplier_invoice_no`, `proposed_invoice_date`, `proposed_total_amount`, `proposed_currency`, `proposed_missing_fields`, `proposed_ambiguous_fields`, `ocr_raw_response`.
  5. **Review** — `final_supplier`, `final_supplier_invoice_no`, `final_invoice_date`, `final_total_amount`, `final_currency`, `reviewed_by`, `reviewed_at`, `review_notes`.
  6. **Validation** — `matched_supplier` (Link → Supplier), `supplier_match_status`, `purchase_order_reference` (Link → PO), `purchase_receipt_reference` (Link → PR), `purchase_reference_status`, `validation_status`, `validation_result`, `validated_by`, `validated_at`, `validation_source`.
  7. **Promotion** — `purchase_invoice` (Link → Purchase Invoice), `promotion_status`.
  8. **Approval** — `approval_status`, `approval_threshold`, `approval_threshold_source`, `routing_reason`, `assigned_approver_role`, `decision_by`, `decision_at`, `decision_notes`, `payment_readiness`.
  9. **Mock Payment** — `payment_entry` (Link → Payment Entry), `payment_lifecycle_status`, `mock_payment_provider`, `mock_payment_reference`, `mock_payment_status`, `mock_payment_amount`, `mock_payment_issued_at`, `mock_payment_response`.

The DocType is intentionally rich — every step's *evidence* is persisted on the record so the audit trail is the document.

### 6.2 Constants & state-machine vocabulary (from `ap_invoice_capture.py`)

```python
SUPPORTED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg"}

# Capture lifecycle
STATUS_PENDING_REVIEW / UNSUPPORTED / REJECTED / PROPOSED / NEEDS_CORRECTION / CONFIRMED

# OCR sub-state
OCR_STATUS_NOT_EXTRACTED / PROPOSED / CONFIRMED / NEEDS_CORRECTION

# Validation
SUPPLIER_MATCH_NOT_VALIDATED / MATCHED / UNKNOWN / AMBIGUOUS
PURCHASE_REF_NOT_VALIDATED / NON_PO / PURCHASE_ORDER / PURCHASE_RECEIPT
VALIDATION_STATUS_NOT_VALIDATED / VALIDATED / BLOCKED

# Promotion
PROMOTION_STATUS_NOT_PROMOTED / PROMOTED

# Approval
APPROVAL_STATUS_NOT_REQUIRED / AUTO_APPROVED / PENDING_MANAGER / MANAGER_APPROVED / REJECTED
PAYMENT_READINESS_NOT_READY / READY / BLOCKED
AUTO_APPROVAL_THRESHOLD_DEFAULT = 1000.0
MANAGER_APPROVAL_ROLE_DEFAULT   = "Accounts Manager"

# Mock payment lifecycle
PAYMENT_LIFECYCLE_NOT_REQUESTED / CONFIRMED / CLOSED / BLOCKED
MOCK_PAYMENT_PROVIDER       = "mock_payment_provider"
MOCK_PAYMENT_PREFIX         = "MOCK-PAY"
MOCK_CLEARING_ACCOUNT_DEFAULT = "_Test Bank - _TC"

INTAKE_MANUAL_UPLOAD = "Manual ERPNext Upload"
FAKE_OCR_PROVIDER    = "fake-deterministic-v1"
```

Mandatory header fields enforced across the pipeline:

```python
MANDATORY_HEADER_FIELDS = (
    ("supplier",            "proposed_supplier",            "final_supplier"),
    ("supplier_invoice_no", "proposed_supplier_invoice_no", "final_supplier_invoice_no"),
    ("invoice_date",        "proposed_invoice_date",        "final_invoice_date"),
    ("total_amount",        "proposed_total_amount",        "final_total_amount"),
    ("currency",            "proposed_currency",            "final_currency"),
)
```

### 6.3 Custom exceptions

All inherit from `frappe.ValidationError` so they surface as 4xx in the desk/API:

- `AmbiguousSourceError` — a capture has no traceable source file/URL.
- `OCRExtractionError` — extraction tried on an unsupported format or pre-extraction.
- `CaptureValidationError` — validation step preconditions not met.
- `CapturePromotionError` — promotion preconditions not met.
- `CaptureApprovalError` — approval routing/decision rules violated.
- `CapturePaymentError` — mock payment issuance rules violated.

### 6.4 End-to-end pipeline

```
File upload (manual ERPNext upload)
   │
   ▼  create_capture_from_uploaded_file(file_name)        @frappe.whitelist
      → create_capture_from_file()
         - hydrates filename + URL from the linked File
         - requires source_file OR source_file_url + filename
         - extension gating ⇒ supported? status=Pending Review; else status=Unsupported, action_required=1
   │
   ▼  run_fake_extraction_for(capture)                    @frappe.whitelist
      → run_fake_extraction()
         - rejects unsupported formats (OCRExtractionError)
         - filename markers `missing_<field>` / `ambiguous_<field>` / bare `ambiguous`
           drive deterministic simulation of partial OCR proposals
         - SHA-256(filename|url|file-name) seeds supplier/currency/invoice_no/amount/date
         - writes proposed_* fields + ocr_raw_response JSON
         - status ⇒ Proposed, ocr_status ⇒ Proposed, action_required=1
   │
   ▼  confirm_extracted_fields_for(capture, corrections=…, notes=…)   @frappe.whitelist
      → confirm_extracted_fields()
         - merges proposed_* → final_*, overridden by corrections{}
         - records reviewed_by + reviewed_at
         - any mandatory final_* still empty ⇒ status=Needs Correction (action_required=1)
         - all present ⇒ status=Confirmed (action_required=0)
   │
   ▼  validate_for_purchase_invoice_for(capture, source=…)            @frappe.whitelist
      → validate_for_purchase_invoice()
         - requires status==Confirmed
         - _match_supplier: exact `name` or unique `supplier_name`
           (Unknown / Ambiguous never auto-creates a Supplier)
         - _classify_purchase_reference: PR > PO > Non-PO/Not Applicable
         - issues = missing finals ∪ supplier match problems
         - validation_status ⇒ Validated | Blocked
         - records validated_by, validated_at, validation_source
   │
   ▼  promote_to_purchase_invoice_for(capture, defaults={…})          @frappe.whitelist
      → promote_to_purchase_invoice()
         - requires validation_status==Validated AND matched_supplier
         - inserts a draft Purchase Invoice with one header-line item
           (rate = final_total_amount, qty default 1)
         - PO/PR refs deliberately stay on the capture (Phase 1 = header-only)
         - capture.purchase_invoice ⇐ pi.name, promotion_status ⇐ Promoted
   │
   ▼  request_approval_for(capture, threshold=…, source=…)            @frappe.whitelist
      → request_approval()
         - requires Validated + Promoted, and no prior approval routing
         - threshold default 1000.0 (overridable); source label tracked
         - amount ≤ threshold ⇒ approval_status=Auto Approved,
           payment_readiness=Ready, decision_by/decision_at recorded
         - amount > threshold ⇒ approval_status=Pending Manager,
           assigned_approver_role default "Accounts Manager",
           payment_readiness=Not Ready, action_required=1
   │
   ▼  record_manager_decision_for(capture, approve=True|False, notes=…)  @frappe.whitelist
      → record_manager_decision()
         - requires approval_status==Pending Manager
         - approve ⇒ Manager Approved, payment_readiness=Ready
         - reject  ⇒ Rejected, payment_readiness=Blocked, action_required=1
   │
   ▼  issue_mock_payment_for(capture, paid_from=…)                    @frappe.whitelist
      → issue_mock_payment()
         - requires is_ready_for_payment(capture)
         - submits PI if still draft
         - get_payment_entry("Purchase Invoice", pi.name, bank_account=…)
         - reference_no = MOCK-PAY-<capture-name>
         - remarks = MOCK_PAYMENT_REMARK
         - inserts + submits PE; writes mock_payment_* fields and JSON response
         - payment_lifecycle_status derived from native state
           (Closed when PI.docstatus=1, PE.docstatus=1, outstanding=0, status=Paid)
   │
   ▼  build_closure_evidence_for(capture)                             @frappe.whitelist
      → build_closure_evidence()
         - assembles {capture, ocr, validation, approval, payment, native} payload
         - native.gl_entries: GL Entry rows for both vouchers
         - native.bank_transaction_count: must be 0 (or "no Bank Transaction doctype")
         - top-level closed: derived from native state (no custom flag)
         - closure_basis: literal explanatory string
```

### 6.5 Read-only helpers (clerk dashboards)

```python
get_ap_lifecycle_rows()       → list view: every capture with action_required, statuses, links to PI/PE
get_manager_approval_queue()  → only captures in approval_status == "Pending Manager"
```

Both are exposed via `@frappe.whitelist`-ed `_for` wrappers (`get_ap_lifecycle_rows_for`, `get_manager_approval_queue_for`).

### 6.6 Whitelisted endpoints

All endpoints are reachable as `/api/method/erpnext.accounts.doctype.ap_invoice_capture.ap_invoice_capture.<fn>`:

```
create_capture_from_uploaded_file(file_name, source_context=None)
run_fake_extraction_for(capture)
confirm_extracted_fields_for(capture, corrections=None, notes=None)
validate_for_purchase_invoice_for(capture, source=None)
promote_to_purchase_invoice_for(capture, defaults=None)
request_approval_for(capture, threshold=None, source=None)
record_manager_decision_for(capture, approve, notes=None)
issue_mock_payment_for(capture, paid_from=None)
build_closure_evidence_for(capture)
get_ap_lifecycle_rows_for()
get_manager_approval_queue_for()
```

The string-vs-dict normalization in each wrapper (parsing JSON `corrections`/`defaults`, coercing `approve` from `"1"|"true"|"yes"|"approve"`) lets the same surface be called from desk client scripts and external clients.

### 6.7 Tests (`test_ap_invoice_capture.py`)

1,272 lines covering every state transition and every guardrail. The test suite uses `EXTRA_TEST_RECORD_DEPENDENCIES = ["Supplier", "Item", "Cost Center"]` and a `_PROMOTION_DEFAULTS` dict that lines up with the ERPNext `_Test …` fixtures. Notable patterns:

- PDF intake uses `pypdf.PdfWriter` to produce a real PDF byte stream → uploaded via Frappe's `File` doctype → fed to `create_capture_from_file`.
- Simulated-failure paths use filename markers (`missing_supplier_…pdf`, `ambiguous_invoice_date_…pdf`, bare `ambiguous_…pdf`).
- Closure assertions check the *native* state: `Purchase Invoice.docstatus == 1`, `outstanding_amount == 0`, `status == "Paid"`, `Bank Transaction Payments` count for the PE is 0.
- Negative tests assert each custom exception fires for the intended precondition violation.

---

## 7. Modified File — `erpnext/setup/utils.py`

The only edit to an upstream file is a 2-line readability refactor inside `_enable_all_roles_for_admin`:

```diff
-    all_roles = set(frappe.db.get_values("Role", pluck="name"))
+    all_roles = set(frappe.get_all("Role", pluck="name"))
     admin_roles = set(
-        frappe.db.get_values("Has Role", {"parent": "Administrator"}, fieldname="role", pluck="role")
+        frappe.get_all("Has Role", filters={"parent": "Administrator"}, pluck="role")
     )
```

Semantically equivalent — `frappe.get_all` is the preferred, higher-level helper and standardizes the call style across the two enumerations. This change is unrelated to AP Closed Loop functionality and is best read as incidental cleanup.

---

## 8. What This Fork Deliberately Does NOT Do

- **Does not** create or modify Purchase Invoice, Payment Entry, Bank Transaction, or GL Entry behavior.
- **Does not** auto-create Suppliers — unknown suppliers must be corrected by AP staff.
- **Does not** attach the capture's PO/PR reference to Purchase Invoice line rows — Phase 1 is header-only; the reference remains auditable on the capture.
- **Does not** wire any UI / desk button — every action is invoked via `@frappe.whitelist` RPC. Desk client scripts and a workspace will be Phase 2.
- **Does not** integrate with any real OCR provider — `FAKE_OCR_PROVIDER = "fake-deterministic-v1"` is hash-based and reproducible.
- **Does not** integrate with any real payment provider — `MOCK_PAYMENT_PROVIDER = "mock_payment_provider"` and every Payment Entry it creates carries the `MOCK-PAY-…` prefix and the explicit "Not bank reconciled. No real banking integration." remark.
- **Does not** record a custom `closed` flag — closure is always derived from the native ERPNext PI + PE state.

---

## 9. How to Run the Fork's Tests

From a `bench` that has this app installed against a test site:

```bash
# Walking skeleton (deterministic end-to-end happy path)
bench --site <test-site> run-tests \
    --module erpnext.accounts.ap_closed_loop.test_walking_skeleton

# Full AP Invoice Capture pipeline + all state-machine guardrails
bench --site <test-site> run-tests \
    --module erpnext.accounts.doctype.ap_invoice_capture.test_ap_invoice_capture
```

Both rely on the upstream `before_tests` bootstrap (`erpnext.setup.utils.before_tests`) for `_Test Company`, `_Test Supplier`, `_Test Item`, `_Test Cost Center - _TC`, `_Test Bank - _TC`, `_Test Warehouse - _TC`, and `_Test Account Cost for Goods Sold - _TC`. Each test rolls back in `tearDown`, so the suite is reentrant.
