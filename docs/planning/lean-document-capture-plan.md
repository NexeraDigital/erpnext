# Document Capture — Lean Scope Implementation Plan

**Date:** 2026-06-05
**Driver:** Customer feedback + the Russ/Brandon reframe (see `customer-alignment-questions.md`).
**Goal:** Reshape Document Capture to the lean loop the customer actually needs —
**capture → read → code (cost accounting) → post → reconcile to the bank feed** — and stop
presenting the heavy invoice-approval-and-payment machinery, **without deleting** it.

> **Definition of done (customer):** ingested data — receipt *or* invoice — **lands in
> ERPNext correctly**, proven by a clean **month-end close**. So the plan optimizes the
> *posting + reconciliation* path and de-emphasizes genre classification, gates, approval,
> and in-ERPNext payment.

---

## 1. Guiding principles

1. **Hide, don't delete.** Everything out-of-scope is gated off behind **one switch**, kept as
   a configurable superset for a larger client later. Only **Mock Payment** is a true removal
   (it's a placeholder superseded by real reconciliation).
2. **One switch, two layers.** A single **"Lean Mode"** setting drives both (a) the **form**
   (hide sections/fields) and (b) the **cascade** (skip steps). No half-states.
3. **Reversible + tested.** Default OFF so current behavior is byte-identical until enabled;
   every slice ships with automated tests + a browser smoke.
4. **Cost accounting is the spine.** GL Coding (expense account / cost center / tax) and Bank
   Reconciliation become the elevated, central sections.

---

## 2. The switch: `lean_mode`

- **Setting:** add `lean_mode` (Check, default 0) to `AP Closed Loop Settings` +
  `is_lean_mode_enabled()` getter (mirror the existing `is_*_enabled` flags).
- **Boot exposure:** surface it in `frappe.boot` (extend_bootinfo) so the client script can
  read it without a server round-trip.
- **Why a switch (not static JSON edits):** reversible, single-customer-scopable, and keeps
  the doctype a superset. Static `hidden:1` on section breaks would bake the trim into the
  shared doctype — wrong for a fork that may serve other clients.

---

## 3. Mechanism (grounded in Frappe v16)

**Form (UI) layer — client script on Document Capture:**
- Frappe `depends_on` evaluates against the *current doc's* fields, not a Singles setting, so a
  global toggle needs a **client script**: on `refresh`, if `frappe.boot.lean_mode`, call
  `frm.toggle_display([... section-break + field names ...], false)` to hide the out-of-scope
  sections/fields. (Same pattern Frappe uses for conditional desk UI.)
- Keep it in `document_capture.js` (already the form's client script).

**Cascade (behavior) layer — `document_capture.py`:**
- `_determine_next_step` is the routing table. In lean mode it must **skip** the approval and
  payment hops (after `promote_*`, the capture is "posted, awaiting bank match" — no
  `request_approval_for`, no `issue_mock_payment_for`).
- `validate_for_purchase_invoice` runs the three gates inline → add a `lean_mode` guard that
  **skips the gates** (three-way match / anomaly / vendor-bank-change) and goes straight to
  supplier-match + validated.
- Net lean cascade: `dedupe → OCR → (auto-confirm) → classify(paid/unpaid only) →
  validate(supplier match only) → code → post PI → reconcile`.

> This is a **flow-visible** change → the AP-CAPTURE-SEQUENCE diagram + PNG must be updated
> (a lean-mode branch), per the CLAUDE.md cascade rule.

---

## 4. Work breakdown (slices — one small commit each)

### Slice 1 — `lean_mode` setting + boot flag
- Add the Check + getter + boot exposure. Tests: getter default OFF/ON; boot flag present.
- No behavior change yet (the flag is read by later slices).

### Slice 2 — Form: hide out-of-scope sections
- Client script hides, when lean: **Intake Classification**, **Document-Type Classification
  internals**, **Validation Gates**, **Approval & Routing**, **Mock Payment**, and the
  **PO/PR-reference** fields in Validation & Match.
- Collapse **Deduplication** by default.
- Browser smoke: lean ON → only the lean sections show; lean OFF → full form. Commit screenshots.

### Slice 3 — Cascade: skip out-of-scope steps
- Guard `validate_for_purchase_invoice` to skip the three gates in lean mode.
- Guard `_determine_next_step` to skip `request_approval_for` + `issue_mock_payment_for` in
  lean mode (post → reconcile, no approval/payment hops).
- Tests: lean capture posts a PI and lands at "awaiting bank match" with no approval/payment
  rows; gates not run. Regression: lean OFF unchanged. Update sequence diagram + PNG.

### Slice 4 — Remove Mock Payment (true removal, not hide)
- Replace the mock-payment step/section with the **reconciliation primacy**: a posted capture's
  terminal pre-close state is "posted, awaiting bank-feed match" (spec 13/14 dual-signal).
- Keep `payment_entry`/lifecycle fields only as needed by reconciliation; drop the mock
  provider scaffolding from the lean path. (Behind lean mode; mock path stays for non-lean.)

### Slice 5 — Elevate the spine
- Rename **"Purchase Invoice Promotion" → "Posting"** (label only; keep fieldnames).
- Make **GL Coding** + **Bank-Feed Reconciliation** the prominent sections (order/labels).
- Keep `document_type` minimal (drives is_paid vs normal PI); hide the
  confidence/rationale/override/marker fields and `expense_claim`.

---

## 5. Per-section change matrix

| Section | Action in lean mode | Layer |
|---|---|---|
| Source | Keep | — |
| Intake Classification | Hide (keep `stream` as quiet field) | form |
| Lifecycle | Keep (already hidden) | — |
| Context | Keep | — |
| Deduplication | Keep, collapsed | form |
| OCR / AI Proposal | Keep — central | — |
| Extraction Detail (lines/tax) | Keep — central | — |
| AP Review | Keep, streamline (auto-confirm default) | cascade |
| Validation & Match | Keep supplier match; **hide PO/PR refs** | form |
| GL Coding | Keep & **elevate**; simplify engine (follow-on) | form |
| Document-Type Classification | Hide internals; keep minimal `document_type` | form |
| Validation Gates | **Hide + skip** (no 3-way/anomaly/fraud) | form + cascade |
| Purchase Invoice Promotion | Keep — central; rename → "Posting" | form |
| Approval & Routing | **Hide + skip** | form + cascade |
| Mock Payment | **Remove** | form + cascade |
| Bank-Feed Reconciliation | Keep & **elevate** (build-out is follow-on) | form |
| Rejection | Keep | — |

---

## 6. Testing (every slice)

- **Automated:** `lean_mode` getter; cascade-in-lean (posts PI, no approval/payment, gates
  skipped); regression suite green with lean OFF (byte-identical) — force test-default
  settings to avoid the dev-singleton drift (T-023).
- **Browser smoke:** lean ON vs OFF form; a receipt driven capture → read → code → post →
  "awaiting bank match." Commit screenshots under `test/testplans/screenshots/<slug>/`.
- **Clean-room runbook:** `test/testplans/specs/NN-lean-document-capture.md`.

## 7. Docs (same-commit set)

- `FORK-CHANGES.md` (+ `-PLAIN`): the lean-mode switch + what it hides/skips.
- **AP-CAPTURE-SEQUENCE.md + .png:** the lean-mode cascade branch (flow-visible).
- `STATUS.md` note; `TODO.md` for the follow-on big builds; `UI-SITEMAP` if labels change.

## 8. Risks & decisions

- **Config-gated vs static:** recommended **config-gated** (lean_mode) — reversible, keeps the
  superset. (Decision for the customer/Russ.)
- **`document_type` minimal-keep:** still needed (paid receipt → PI `is_paid`; unpaid → normal
  PI), so we keep the *decision* but hide the classifier UI.
- **Client-script hiding** isn't enforced server-side — fine for UI tidiness; the *behavior*
  guarantees come from the cascade guards (slice 3), not the form.
- **Data:** no migration; existing captures unaffected (lean mode is presentational + routing).

## 9. Out of scope for THIS plan (follow-on builds, separate)

These are implied by the lean scope but are real projects, not hide/trim work:
1. **Real Plaid/SimpleFIN reconciliation** — build out spec 13/14 from fixtures to a live feed
   match (the actual "done = month-end close" engine). *Largest follow-on.*
2. **Cost-accounting coding simplification** — replace the heavy profile/history coding engine
   with a lean per-supplier default aligned to the customer's cost-accounting dimensions
   (answer to alignment Q3).
3. **BAML as default OCR (Phase C)** — consolidate read+classify on the cheap model; retire
   the standalone Anthropic extractor + content classifier.

## 10. Sequencing & rough effort

| Slice | Effort (AI time) |
|---|---|
| 1 — switch + boot | small |
| 2 — form hides | small–medium |
| 3 — cascade skips + diagram | medium |
| 4 — remove mock payment | small |
| 5 — elevate spine + labels | small |

The five slices are the **lean reshape** (a focused effort). The three follow-on builds in §9
are the substantive engineering that delivers the customer's end goal (correct posting +
month-end reconciliation) and should be planned/estimated separately once the alignment
questions are answered.
