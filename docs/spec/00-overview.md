---
spec: 00-overview
title: AP Closed-Loop Workflow v2 — Specification Index & Architecture
plan_step: All (index)
stream: both
status: Draft
related: [01-foundations-settings-async-idempotency, 02-intake-stream-tagging, 03-deduplication, 04-extraction-confidence-line-items, 05-supplier-resolution, 06-gl-coding-tax-costcenter, 07-classification-doctype-branching, 08-validation-gates, 09-confidence-routing, 10-ap-review-observability, 11-approval-sod-workflow, 12-payment-execution, 13-bank-feed-reconciliation, 14-closure-audit-retention]
---

# 00 — AP Closed-Loop Workflow v2: Specification Index & Architecture

## What this folder is

`docs/spec/` is the implementation specification for the **AP Closed-Loop Workflow v2** described in
[`docs/planning/workflow-v2-plan.md`](../planning/workflow-v2-plan.md). The plan describes *what* the
workflow should do (13 steps, two streams, industry-standard controls). These 14 specs (`01`–`14`)
describe *how to build each piece* on top of the current fork: the new DocTypes, fields, endpoints,
controller logic, acceptance criteria, tests, and the decisions that must be locked before coding.

One spec per workflow capability. Read this index first, then the spec for the piece you're building.

### Relationship to older planning docs

These specs **supersede** the v1-era planning in `docs/changes/IMPLEMENTATION-PLAN.md` and
`docs/changes/GAP-ANALYSIS.md` wherever they disagree. Those were written against the v1 `NewUpdates.md`
**before** two things changed:

1. **Real OCR shipped.** The fork now has a working Anthropic Claude extractor (retry, circuit breaker,
   size guard, cost audit, Haiku→Sonnet fallback). The old plan's "integrate Azure Document Intelligence"
   (decision D4) is moot — step 3 is now a *confidence + line-items extension* of a working extractor,
   not a greenfield OCR build.
2. **The v2 reframe.** v2 adds the **two-stream model**, the **AP Review Event** observability gate,
   **native Workflow + Server-Script SoD**, **SimpleFIN** as the named feed, the **PO upstream control**,
   and **payment-as-secondary** — none of which the v1 docs anticipated.

Also: the old plan proposed a new `AP Settings` Single. **Don't.** The fork already ships
`AP Closed Loop Settings` — every new knob extends *that* doctype (see [[01-foundations-settings-async-idempotency]]).

---

## The two streams (the core idea)

A document is sorted into one of two streams the moment it arrives, and the two are handled differently:

| | **Stream R — Receipts** | **Stream I — Invoices** |
|---|---|---|
| Meaning | Already paid (on a card / in cash) | A bill you still owe |
| The job | **Reconcile** it — confirm the money that already moved | **Match → approve → pay** |
| Posts as | Journal Entry *(or PI + Credit-Card-Clearing)* | Purchase Invoice → Payment Entry |
| Approval? | **No** — nothing to authorize, money already moved | **Yes** — formal sign-off with segregation of duties |
| Payment? | **No-op** — already paid | Human-triggered (auto-pay opt-in per vendor) |
| Closes when | Bank feed matches the Journal Entry (72h SLA) | Bank feed matches the Payment Entry |

The fork happens at **intake (step 1 / spec 02)** and is confirmed-or-corrected at
**classification (step 6 / spec 07)**. How often intake's guess disagrees with classification is a tuning
signal fed to the observability gate (spec 10).

---

## Current baseline (what's already built — don't re-build it)

- **`AP Invoice Capture`** DocType: the full pilot spine — intake → OCR proposal → clerk confirm → validate
  → promote to Purchase Invoice → request approval → manager decision → mock payment → derived closure.
  Header-only today (one invoice line at the total).
- **Real OCR**: `extractors/anthropic.py` (Anthropic Claude) with hardening + cost audit. But
  `ExtractionResult` carries only *missing/ambiguous sets* — **no numeric per-field confidence, no line items** yet.
- **`AP Closed Loop Settings`** (Single): promote defaults + OCR config. The home for all new settings.
- **Auto-progression cascade**: advances a capture through every step the system can decide on its own;
  pauses at OCR review, manual promote, and manager approval.
- **Mock payment + derived closure**: `MOCK-PAY-` labelled Payment Entries; closure derived from native
  Purchase Invoice + Payment Entry state (no custom "closed" flag); **no Bank Transaction created** (a
  Phase-1 guardrail that spec 13 deliberately retires).

---

## The 14 specs (plain-language index)

| # | Spec | In one plain sentence | New DocTypes |
|---|------|----------------------|--------------|
| 01 | [[01-foundations-settings-async-idempotency]] | The shared plumbing: one settings home, a safety latch so a retried job can't post twice, and a way to run slow work in the background. | `AP Posting Ledger` |
| 02 | [[02-intake-stream-tagging]] | The front door: tag every arrival as Receipt or Invoice, start the 72h receipt clock, and accept docs by email/photo. | `AP Stream Rule` |
| 03 | [[03-deduplication]] | "Have we seen this before?" — block exact re-uploads and look-alike re-scans before spending money on AI. | — |
| 04 | [[04-extraction-confidence-line-items]] | Upgrade the AI reader to report how sure it is **per field** and to pull out **line items**, not just the total. | `AP Invoice Capture Confidence`, `AP Invoice Capture Item` |
| 05 | [[05-supplier-resolution]] | Identify the vendor (alias table → fuzzy match → human-approved creation for new vendors); unknown blocks invoices, softer for receipts. | `AP Supplier Alias`, `Supplier Master Change Request` |
| 06 | [[06-gl-coding-tax-costcenter]] | Auto-fill the accounting codes (expense account, cost center, tax) for routine vendors; ambiguous ones go to review. | `AP Supplier Coding Profile` |
| 07 | [[07-classification-doctype-branching]] | The fork in the road: unpaid bill → Purchase Invoice; paid receipt → Journal Entry; employee expense → parked. | — |
| 08 | [[08-validation-gates]] | The fraud/error checks: three-way match (PO + receipt), amount anomaly, and vendor bank-detail-change detection. | `AP Supplier Anomaly Baseline` |
| 09 | [[09-confidence-routing]] | The auto-pilot switch: confident + all-checks-pass + under-limit → auto-post; otherwise → review queue. | — |
| 10 | [[10-ap-review-observability]] | The review desk **plus** a feedback loop that tags every fix's root cause so you can see what manual work was avoidable. | `AP Review Event`, `AP Capture Rejection Log` |
| 11 | [[11-approval-sod-workflow]] | Sign-off (invoices only) on ERPNext's native Workflow, enforcing "enterer ≠ approver" and a separate approver for bank-detail changes. | Workflows + Roles (fixtures), `AP Approval Matrix` |
| 12 | [[12-payment-execution]] | Pay approved bills (invoices only); human-triggered by default, auto-pay opt-in per vendor; receipts skip this. | — |
| 13 | [[13-bank-feed-reconciliation]] | Prove the money moved: match postings to the SimpleFIN bank feed; nothing is truly closed until the bank confirms. | — |
| 14 | [[14-closure-audit-retention]] | The finish line: close only when posting **and** bank agree, assemble the full audit trail, drift report, 7-year retention. | Report + Print Format |

---

## New data-model footprint (all new DocTypes, one place)

**Transaction / log:** `AP Posting Ledger` (idempotency), `AP Review Event` (observability),
`Supplier Master Change Request` (gated vendor changes).
**Masters / config:** `AP Stream Rule`, `AP Supplier Alias`, `AP Supplier Coding Profile`,
`AP Supplier Anomaly Baseline`, `AP Approval Matrix`.
**Child tables (on `AP Invoice Capture`):** `AP Invoice Capture Confidence`, `AP Invoice Capture Item`,
`AP Capture Rejection Log`.
**Fixtures (native machinery, not new doctypes):** Workflows `AP Document Approval` +
`Supplier Bank Change Approval`; Roles `AP Clerk`, `Treasury Approver`, `Auditor (Read Only)`.
**Reports/formats:** `Accounts Payable Trial Balance Drift` (report), `AP Audit Trail` (print format).
**Extended throughout:** `AP Closed Loop Settings` (the single settings backbone) and `AP Invoice Capture`.

---

## Build order & dependencies

Dependency-driven phases (anything that gates auto-post lands before auto-post; anything that gates
payment lands before payment; anything that gates closure lands before closure):

```
Phase 0  Foundation        01
Phase 1  Intake/Extraction 02 → 03 → 04           (03 before any billable OCR; 04 unblocks routing)
Phase 2  Resolve/Code/Fork 05 → 06 → 07
Phase 3  Gate/Route/Review 08, 09, 10             (10 is cross-cutting — can land alongside any of 02–09)
Phase 4  Approve/Pay       11 → 12                (Stream I only)
Phase 5  Close             13 → 14
```

**Critical path:** `01 → 04 → 05 → 06 → 07 → 08 → 09 → 11 → 12 → 13 → 14`.

**Parallelizable once 01 lands:** 02/03 (intake), 04 (extraction), and 10 (observability) can all proceed
independently; 05/06 are a short chain; 08's three gates are independent of each other.

**One dependency cycle to break:** 08 (bank-change detector) needs to ask "is there an *approved*
bank-detail change?", which is answered by 11 (the Supplier Bank Change Approval workflow). Resolve by
landing 08 with an interim `has_approved_bank_change()` **stub** (08 open-decision D10), then replacing it
when 11 lands. So the real order is **08 (stub) → 11 → 08 (wire real check)**.

---

## Decisions to lock (headline — full lists live in each spec's §8)

These shape doctype fields or branching and should be decided early:

1. **Stream R posting model** *(spec 07 D-07-1, spec 13)* — how already-paid receipts post. Three options
   behind one swap-friendly helper: **(a) Purchase Invoice with `is_paid=1`** — native one-document
   already-paid posting (DR expense / CR bank, supplier nets to zero, vendor stays in spend reports) that
   **reuses the existing promote path**; **(b) a direct Journal Entry** (most custom code — new builder + a
   `journal_entry` link + a third closure voucher type); **(c) PI + Credit-Card-Clearing** (more documents).
   **Recommended (review-updated): (a) `is_paid`** — least custom code, keeps Supplier visibility. *Single
   highest-leverage decision; if (a) wins, specs 13/14 simplify — no separate `journal_entry` link.*
2. **Retire the "no Bank Transaction" guardrail** *(spec 13 D0)* — required for step 12. Needs a short ADR
   and a same-PR docstring/test update on `walking_skeleton.py` + `ap_invoice_capture.py`. **Recommended:** retire, split closure into `settled` + `bank_cleared`.
3. **`allow_self_approval` semantics** *(spec 11)* — the native Workflow SoD lever must be **verified on the
   running v16 instance**; we back it up with an app-code/Server-Script check regardless so the control
   never depends on one setting. **Action:** verify on the clone before building.
4. **Confidence-threshold field reconciliation** *(spec 01 D1)* — keep the existing `ocr_confidence_threshold`
   as canonical vs add a new `per_field_confidence_threshold`. **Recommended:** keep the existing field, add a getter.
5. **System dependency for perceptual dedupe** *(spec 03)* — pHash needs the `poppler` binary (`pdf2image`).
   Flag for the WSL/pilot install scripts.
6. **Retry-delay realization** *(spec 01 D5)* — `frappe.enqueue` has no delay arg; phase-1 uses immediate
   re-enqueue, phase-2 a scheduled sweep.
7. **Native `Authorization Rule` vs custom `AP Approval Matrix`** *(spec 11 D-8, review-added)* — ERPNext
   ships a native amount/role/company approval-limit rule, enforced on PI submit. **Recommended:** use it for
   the pilot amount gate; reserve the custom matrix for department/cost-center/supplier-risk axes later.
8. **SimpleFIN vs native Plaid** *(spec 13 D8, review-added)* — Plaid is ERPNext's built-in bank feed (zero
   connector code); SimpleFIN is a new external integration. **Recommended:** default to Plaid unless there's
   a concrete business reason for SimpleFIN (record it).
9. **Enable native duplicate-invoice check** *(spec 03, review-added)* — turn on
   `Accounts Settings.check_supplier_invoice_uniqueness` (off by default) as a promote-time second firewall
   alongside the custom image dedupe. *Config action, not a code decision.*

---

## Cross-spec reconciliation notes

- **The stream field** is owned by **spec 02** (`stream`, Select `Receipt (R)`/`Invoice (I)`/`Unclassified`).
  Spec 07's `provisional_stream` references should align to spec 02's name — 02 defines it first.
- **`AP Closed Loop Settings`** is the *single* settings backbone. Spec 01 reserves placeholder sections so
  specs 02/08/13 fill their config blocks without `field_order` churn.
- **The `journal_entry` link field** on `AP Invoice Capture` is owned by **spec 07** — but is **needed only if**
  Stream R posts as a direct Journal Entry (decision #1 option b). If `is_paid` (option a) wins, the Stream-R
  voucher is a Purchase Invoice and no `journal_entry` link is added; specs 13/14 are written to handle either.
- **Idempotency, async, settings getters** are owned by **spec 01**; every document-creating step (05/07/12/13)
  routes its insert through `with_idempotency`.
- **The `AP Review Event` emitter** (spec 10) is an *optional* dependency for other specs — they emit an event
  *if* the helper is installed, never hard-fail without it.
- **The approval threshold** has one canonical source: the `auto_post_amount_threshold` setting (owned by
  **spec 09**). Spec 11's native Workflow condition reads it via `frappe.db.get_single_value`; the hard-coded
  `1000.0` survives only as the empty-settings fallback. *(Distinct from the per-field OCR-confidence threshold in #4.)*
- **Vendor bank details live on the native `Bank Account` doctype** — `Supplier` carries only `default_bank_account`.
  Spec 05's "Update Bank Details" request targets `Bank Account`; spec 08's change-detector watches
  `Bank Account` / `Bank` / `Supplier.default_bank_account`.
- **`payment_lifecycle_status`** adds the single value `Bank Cleared` (specs 13 + 14 agree); the two closure
  signals are carried as derived `settled` + `bank_cleared` fields, not as extra enum values.

---

## Cross-cutting standards (apply to every spec)

- **Grounding (mandatory):** every framework surface cites an upstream Frappe v15 / ERPNext / GitHub source
  (per `CLAUDE.md`). Each spec's §4 carries the verified citations.
- **Tests (mandatory):** every spec ships **automated tests** (`frappe.tests.IntegrationTestCase`,
  positive + negative + edge, rolled back in `tearDown`) **and** a clean-room **test plan** under
  `test/testplans/<slug>.md`. Both are named in each spec's §7.
- **Idempotency & async:** document-creating steps are retry-safe; slow work (OCR, bank sync) is queue-backed.
- **Permissions / roles:** native Role permissions. New roles: `AP Clerk`, `Treasury Approver`,
  `Auditor (Read Only)`.
- **MOCK labelling:** the mock label moves from the Payment Entry to the *mock bank-feed source* in spec 13.
- **Migrations:** schema-affecting changes ship a numbered patch; defaults install via `after_migrate`.

---

## Status

**Revised 2026-05-31** — a native-vs-custom review was applied across all 14 specs, with every native claim
verified against the installed **ERPNext 16.20.0 / Frappe 16.18.3** source. Folded in: lean on native `is_paid`
(#1), `Authorization Rule` (#7), `check_supplier_invoice_uniqueness` (#9) and Plaid (#8); corrected the
bank-details target (→ `Bank Account`), the idempotency-key double-post hole + exception-ordering bug (spec 01),
and a settings field-precedence bug (spec 02); and reconciled the approval-threshold source and the closure
vocabulary across specs. *(One review claim — "`Company.cost_center` doesn't exist" — was itself wrong and was
corrected during editing: the field exists at `company.json:440`.)*

All 14 specs are **Draft**. Recommended next steps: (a) lock the headline decisions above, especially #1
and #3; (b) start the build at [[01-foundations-settings-async-idempotency]]; (c) write each spec's paired
`test/testplans/<slug>.md` skeleton as its slice begins. When a spec is implemented, flip its frontmatter
`status:` to `In Progress` / `Done`.
