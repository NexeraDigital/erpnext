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

---

## Guiding principle — the north star (governs every spec)

**Automate the AP workflow as much as possible to relieve humans of routine duties, and escalate to a human only when the system genuinely can't decide confidently — or shouldn't decide alone for control reasons.**

Every design choice in these specs is settled against that goal. Concretely:

- **Automate the common case end-to-end.** A clean, confident, in-policy document should flow intake → dedupe → OCR → classify → validate → code → post → (Stream I) approve → pay → close **with no human touch**. Throughput is the point; a human in the loop is a cost, not a default.
- **Escalation is a safety valve, not friction.** Human touchpoints — OCR review, Coding Review, Needs-Review routing (spec 09), reject/reopen (spec 10), approval/SoD (spec 11) — exist to catch only what automation *shouldn't* own: low confidence, ambiguity, failed controls, or genuine authorization needs. They must never gate the happy path.
- **On any heavier-vs-lighter trade-off, prefer the path that keeps documents auto-advancing** and reserves human attention for true exceptions. Add a control or a manual step only when it removes a real risk or a real decision a human must make — not for completeness.
- **Measure success by how little reaches a human.** The spec-10 `AP Review Event` root-cause report quantifies *avoidable* escalations; a rising auto-rate and a shrinking exception tail are the scorecard, and they drive the tuning loop (loosen a threshold, add an alias, fix an upstream miss).
- **Escalate, don't dead-end.** When a human is pulled in, the item must carry the specific reason, be resolvable in one step, and re-enter automation once cleared (reject→reopen, route-to-review→re-route). Exceptions loop; they don't fall out of the system.

When two specs (or two options within a spec) appear to conflict, resolve toward **more automation with a clean escalation seam** over **more process**.

### Automation-first doctrine — per-spec levers, escalation seams, and gaps to close

Each spec is re-anchored so the **automation lever** is the default path and the **escalation seam** fires only on a genuine exception. The right-hand column is the *unrealized* automation each spec should grow into (the build backlog that closes the gap between "a human touches everything once" and "only the doubtful ones").

| # | Automates with no human | Escalates only when… | Automation to close (the gap) |
|---|---|---|---|
| 01 | idempotent retries, background jobs | — (pure plumbing) | — |
| 02 | auto-tags Receipt/Invoice; email/photo intake | truly unclassifiable (→ handled downstream) | — |
| 03 | auto-blocks exact dups before any OCR cost | a near-dup look-alike (flagged, **still proceeds**) | — |
| 04 | per-field confidence + line items | — (it *produces* the decision signal) | **feed the confidence into auto-confirm (see 09)** |
| 05 | 3-tier auto-resolve (alias→exact→fuzzy); alias table *learns* | an unknown vendor on an **invoice** | **default the gated auto-create request ON for high-confidence names** (approval still required) |
| 06 | profile-driven auto-coding of expense/cost-center/tax | cost-center or tax genuinely ambiguous | **bootstrap coding from the vendor's prior posted PIs** so no human pre-builds a profile |
| 07 | auto-classifies + routes to the right posting doctype | the content itself is ambiguous | **trust content over the intake guess** — stop sending *every* stream disagreement to Manual Review |
| 08 | auto 3-way-match / anomaly / bank-change checks | a control actually **fails** (Stream I) | per-line 3WM (today PO-level only) |
| 09 | auto-advances clean + confident + in-policy | low confidence **or** an open flag | **apply the same gate one step earlier → auto-confirm the OCR proposal (the #1 lever)** |
| 10 | auto-emits root-cause telemetry | a human acts (by definition) | — (it's the scorecard that shrinks the rest) |
| 11 | auto-approves in-policy invoices | above-threshold **or** enterer = approver | keep the engine + app-code SoD guard; native Workflow **deferred** |
| 12 | auto-pays **opt-in** trusted vendors hands-free | new / untrusted / unusual amount (→ one human click) | grow the trusted auto-pay set over time |
| 13 | native auto-match of bank lines | a line is unmatched past SLA, or amount mismatches | — |
| 14 | derived auto-close when `settled` + `bank_cleared` agree | trial-balance drift to investigate | — |

**The single highest-leverage gap is #9/#4: confidence-gated auto-confirm.** Today every capture pauses for a human to confirm the OCR proposal *regardless of confidence*; the per-field signal to skip that on clean extractions already exists (spec 04) and is only used later (spec 09 approval). Closing it is the difference between "every document needs a human once" and "only the doubtful ones do" — the clearest expression of the north star.

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
| 11 | [[11-approval-sod-workflow]] | Auto-approve in-policy invoices (under threshold, checks passed) and **escalate only what needs a human**: above-threshold sign-off, "enterer ≠ approver" (the real control), and a separate approver for bank-detail changes. Pilot keeps the existing engine + an app-code SoD guard; the company-wide native Workflow is a deferred, opt-in upgrade. | Roles (fixtures); `AP Approval Matrix` (deferred); Workflows (deferred) |
| 12 | [[12-payment-execution]] | Pay approved bills (invoices only); auto-pay opt-in per vendor so trusted vendors flow hands-free, others stay human-triggered; receipts skip this. | — |
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
3. **Approval scope — automate-first pilot vs company-wide native Workflow** *(spec 11)* — the real control is
   **"enterer ≠ approver,"** and it's delivered by an **app-code SoD guard** that never depends on one native
   setting. **Recommended (north-star aligned): the pilot keeps the existing approval engine** (which already
   auto-approves in-policy invoices) **and adds the app-code SoD guard + approver roles**, escalating only the
   above-threshold / failed-control cases. The **company-wide native `Workflow` on `Purchase Invoice`** (which
   would govern *every* PI in the company, not just AP-capture ones) is a **deferred, opt-in upgrade** gated on
   pilot-scope sign-off — not the pilot default. If adopted, still verify the `allow_self_approval` lever on the
   running v16 instance; the app-code guard remains the authority regardless.
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
  positive + negative + edge, rolled back in `tearDown`), a clean-room **test plan** under
  `test/testplans/<slug>.md`, and — for specs with a desk-UI surface (02–14) — a **Playwright MCP UI test
  plan** (§7.3) per `test/testplans/BROWSER-TESTING-SETUP.md`, with committed screenshots under
  `test/testplans/screenshots/<slug>/` and the DB as the source of truth. All are named in each spec's §7.
  (Spec 01 is backend-only — UI testing N/A.)
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

**Revised 2026-06-02** — the whole spec set was **re-visioned automation-first** against the north star
("Guiding principle" above): each spec now leads with what flows *without a human* and reserves its
escalation seam for genuine exceptions, and each carries the specific automation it should grow into (the
"Automation-first doctrine" table). Nothing is deployed, so this re-vision changes the *target design*
freely — built specs (01–10) keep their shipped behavior documented and add the automation-first target as
**planned** extensions (new ACs marked planned; status unchanged until built); unbuilt specs (11–14) are
re-anchored directly. The headline build item is the **confidence-gated auto-confirm** gap (#9/#4).

Build-status snapshot at re-vision time: specs **01–10 implemented** (`status: Done`), **11–14 Draft**.
Recommended next steps: (a) close the auto-confirm gap (#9/#4) as the first automation-first slice;
(b) build 11 the automation-first way (auto-approve in-policy + app-code SoD, native Workflow deferred);
(c) lock the remaining customer decisions (#1, vendor-approval, threshold). When a spec's automation-first
extension is built, tick its planned ACs in `STATUS.md` per the verify-before-tick rule.
