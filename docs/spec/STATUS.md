# AP Closed-Loop Workflow v2 — Build Status

> Source-of-truth tracker for implementing `docs/spec/01`–`14`. Companion to [[00-overview]].
> **Update on every merged slice PR.** This file — plus each spec's frontmatter `status:` — is what survives across sessions; the in-session task list does not.
>
> **Last updated:** 2026-06-01 · **Specs:** 14 · **Acceptance criteria:** 221 · **Overall:** 🟡 9/14 done — **specs 01–09 ✅** (149/221 ACs green; no regressions). Behavioral browser-smoke screenshots committed per spec under `test/testplans/screenshots/<NN-slug>/`.

## How to use this file

- **Verify before you tick.** A spec/AC is marked ✅ only **after** its automated tests are **run green in the current session** (cite the `Ran N tests … OK`) — never because the code is written. ✅ **Done** = all ACs green this session + `FORK-CHANGES`(+PLAIN) updated + `test/testplans/<slug>.md` written. The §7.2 clean-room + §7.3 Playwright runbooks are a **separate downstream gate**: record their execution as a note (e.g. *clean-room/UI: pending*) and don't claim them run when they weren't. Use 👀 for code landed but automated ACs not yet all green. (Rule: `CLAUDE.md` → "Spec build-status tracking — verify before you tick".)
- On each merged slice PR: (1) tick the AC boxes in the per-spec checklist below, (2) update the spec's **Status / ACs / PR** in the dashboard, (3) flip the spec's frontmatter `status:` (`Draft → In Progress → Done`).
- Build in **phase order** and respect `depends_on`. **Lock each gating decision before the spec(s) it gates** (next section).
- Per CLAUDE.md: every slice also updates `docs/architecture/FORK-CHANGES.md` + `FORK-CHANGES-PLAIN.md` in the same PR, and ships its `test/testplans/<slug>.md`.

## Status legend

🔲 Not started · 🔒 Decisions locked · 🟡 In progress · 👀 In review · ✅ Done · ⛔ Blocked

---

## Decisions to lock first (these gate the specs)

Lock these before starting the specs they gate. See each spec's §8 and [[00-overview]] for full options.

- [~] **#1 — Stream-R posting model** → **PROVISIONALLY LOCKED = Option C: PI `is_paid=1`** (2026-06-01) for spec-07 build — least custom code, keeps the supplier visible in AP/spend-by-supplier. **Reversible** via the single `_build_already_paid_voucher()` seam (swap to direct JE / PI+Clearing is a one-function change). **Customer sign-off still pending** (see TODO T-010); also informs #2 for 13/14. *Gates 07, 13, 14.* — owner: accounting lead
- [ ] **#2 — Retire the "no Bank Transaction" guardrail** (+ write the ADR; dual closure `settled`+`bank_cleared`). *Gates 13, 14.*
- [ ] **#3 — `allow_self_approval` semantics** — verify on the running **v16** instance; app-code SoD backstop regardless. *Gates 11.*
- [x] **#4 — Confidence-threshold field reconciliation** — **LOCKED (spec 01):** keep `ocr_confidence_threshold` canonical + a `get_confidence_threshold(field)` getter; no second scalar. *Gates 04, 09.*
- [x] **#5 — `poppler` system binary** installed on every worker host (for `pdf2image`). **Handled (spec 03):** code ships **graceful degradation** — `_compute_phash` returns `None` and dedupe runs **exact-hash-only** when poppler/imagehash is absent (AC-03-8), so the install is a **deploy task, not a code blocker**. NOT currently installed on the dev bench (`which pdftoppm` empty); install (`apt-get install poppler-utils` + `pip install imagehash pdf2image`) before the perceptual pass can be **live-verified** (§7.2 clean-room). *Gated 03 (now exact-only until installed).*
- [x] **#6 — Retry-delay realization** — **LOCKED (spec 01, phase-1):** native `RetryBackgroundJobError` for immediate transients + immediate re-enqueue for delayed backoff; scheduled sweep deferred to phase-2.
- [ ] **#7 — Native `Authorization Rule` vs custom `AP Approval Matrix`** (use native for amount gate). *Gates 11.*
- [ ] **#8 — SimpleFIN vs native Plaid** (default Plaid unless a business reason). *Gates 13 at pre-cutover only — mock build does not block.*
- [ ] **#9 — Enable native `check_supplier_invoice_uniqueness`** (config, off by default). *Supports 03.*

---

## Dashboard

| # | Spec | Phase | Status | ACs | Size | Depends on | Gating decision / blocked-on | PR |
|---|------|-------|--------|-----|------|-----------|------------------------------|----|
| 01 | [[01-foundations-settings-async-idempotency]] | 0 Foundation | ✅ | 20/20 | L | — | #4, #6 locked | committed ✓ |
| 02 | [[02-intake-stream-tagging]] | 1 Intake | ✅ | 15/15 | L | 01 | — | committed ✓ |
| 03 | [[03-deduplication]] | 1 Intake | ✅ | 13/13 | M | 01, 02 | #5 (poppler), #9 | committed ✓ |
| 04 | [[04-extraction-confidence-line-items]] | 1 Intake | ✅ | 15/15 | L | 01 | #4 locked | committed ✓ |
| 05 | [[05-supplier-resolution]] | 2 Resolve | ✅ | 23/23 | L | 01, 04 | bank-detail→`Bank Account` (fixed) | working tree |
| 06 | [[06-gl-coding-tax-costcenter]] | 2 Resolve | ✅ | 14/14 | L | 01, 04, 05 | D8 → separate profile doctype | working tree |
| 07 | [[07-classification-doctype-branching]] | 2 Resolve | ✅ | 14/14 | L | 01, 02, 05, 06 | #1 → Option C (PI is_paid), provisional | working tree |
| 08 | [[08-validation-gates]] | 3 Gate | ✅ | 21/21 | L | 01, 04, 05, 06, **11※** | 3WM PO-level (pilot); bank-lift full rule → 11※ | working tree |
| 09 | [[09-confidence-routing]] | 3 Gate | ✅ | 14/14 | S | 04, 08 | threshold single-source → 11 (D-9/T-013) | working tree |
| 10 | [[10-ap-review-observability]] | 3 Gate | 🔲 | 0/17 | — | 01 | `AP Review Event` seam freeze | — |
| 11 | [[11-approval-sod-workflow]] | 4 Approve | 🔲 | 0/12 | L | 02, 05, 08 | **#3, #7** | — |
| 12 | [[12-payment-execution]] | 4 Approve | 🔲 | 0/14 | M | 01, 02, 07 | auto-pay gate default | — |
| 13 | [[13-bank-feed-reconciliation]] | 5 Close | 🔲 | 0/13 | L | 01, 02, 07 | **#2, #8** | — |
| 14 | [[14-closure-audit-retention]] | 5 Close | 🔲 | 0/16 | L | 01, 07, 13 | #1, #2 (consumes) | — |

*Size for 10 not stated in-spec (estimate M). **08※:** 08 and 11 are mutually dependent — land 08 with an interim `has_approved_bank_change()` **stub**, then 11, then wire 08's real check (08 §8 D10).*

> **Verification state (09):** ✅ all 14 ACs green this session (Fake OCR). New class `TestAPInvoiceCaptureConfidenceRouting` **15 tests** run programmatically (bench-runner summary swallowed by the harness on this WSL bench): **`Ran=15 failures=0 errors=0 skipped=0 → OK`**. **Blast-radius / regression:** `request_approval` is the cascade's Step-3 hot path, so the full module was re-run the same way: **`Ran=171 failures=0 errors=0 skipped=1 → OK`** (was 156; +15 routing tests, no false reroutes — existing approval tests extract via the fake provider so their confidence rows stay above threshold). **Reconciliations (spec predates 05–08):** (1) **Stream-R no-approval is owned by spec 07** — Already-Paid posts via `promote_already_paid` (PI `is_paid`, not a JE) and the cascade *skips* approval, so it never reaches `request_approval`; this spec adds **no** JE auto-post and the evaluator is **stream-agnostic** (AC-09-2 reconciled = the cascade's Step-3 excludes Already-Paid). (2) The `auto_post_amount_threshold` field + `get_auto_post_threshold()` **already existed** (spec 01/04); AC-09-10 was already met. (3) **`AP Review Event` (spec 10) is not built** — emission is a `frappe.db.exists`-guarded seam; AC-09-4/5's "event row exists" sub-assertion **defers to spec 10**, while the routing behaviour + graceful-absent path (AC-09-14) are green now. **Decisions adopted** = spec recommendations D-1(b)/D-2/D-3(a)/D-4(a)/D-6(a)/D-7(a)/D-8(a). **Carve-out (honest):** confidence axis fails closed on a *populated* table with a missing/low mandatory row, but an **empty** table degrades to pass (graceful, matching specs 06/08). **Deferral:** D-9 (spec 11's Workflow gate must read the same `auto_post_amount_threshold`) → **TODO T-013**. §7.2 clean-room runbook **written**; §7.3 behavioral browser-smoke screenshots **committed** under `screenshots/09-confidence-routing/`.
>
> **Verification state (08):** ✅ all 21 ACs green this session (Fake OCR). New class `TestAPInvoiceCaptureValidationGates` **22 tests** (21 ACs + one AC-08-16 re-check: promotion re-runs bank detection so a change *after* a clean validation still blocks) run programmatically via `unittest.TextTestRunner` (the bench-runner summary line is swallowed by the harness on this WSL bench, so the suite was loaded + run in `bench console`): **`Ran=22 failures=0 errors=0 skipped=0 → OK`**. **Blast-radius / regression (AC-08-21):** the three gates run inside `validate_for_purchase_invoice` (fires for every AP capture) and the bank gate re-runs inside `promote_to_purchase_invoice`, so the full module was re-run the same way: **`Ran=156 failures=0 errors=0 skipped=1 → OK`** (was 134; +22 gate tests, no false blocks on the existing happy paths). **Decisions adopted** = spec recommendations: D1 PO-cumulative 3WM, D2 `respect_over_billing_allowance` off (independent/stricter AP tolerance), D3 dedicated `AP Supplier Anomaly Baseline` cache, D4 daily-refresh + lazy-recompute (no per-PI `on_submit`), D5 pre-promotion custom 3WM only, D6 dedicated 3WM-override fields, D7 absent stream ⇒ Stream I, D8 soft-skip when no prior PE, D10 conservative `has_approved_bank_change` (Posted + decided-by-≠-requester). **Pilot simplification (honest):** 3WM is **PO-level** (sum of PO-item `received_qty` + ordered amount), not per-line PO-item matching — OCR emits no `po_detail` mapping yet. **Deferral (honest):** the full **non-AP / Treasury-Approver** bank-change-lift role rule is owned by **spec 11** (TODO **T-012**); the current lift is the spec-05 SoD backstop. §7.2 clean-room runbook **written** (`test/testplans/specs/08-validation-gates.md`); §7.3 behavioral browser-smoke screenshots **committed** under `screenshots/08-validation-gates/`.
>
> **Verification state (07):** ✅ all 14 ACs green this session (Fake OCR). Built on the **provisionally-locked Option C (PI `is_paid=1`)** for Stream-R already-paid posting, behind the `_build_already_paid_voucher()` swap seam (reversible per TODO T-010). `test_ap_invoice_capture` **Ran 134 tests … OK (skipped=1)** (was 120; +14 `TestAPInvoiceCaptureDocumentTypeBranching`: classify Already-Paid/Employee/Unpaid, override-wins, stream-disagreement→Manual Review, ambiguous→Manual Review, already-paid→is_paid PI with the bank-leg GL verified on submit, wrong-doctype/idempotency/missing-config guards, PI-guard-rejects-Already-Paid, cascade routing decisions at each fork, `get_already_paid_config`, migrate-safety schema). No-regression this session: `ap_closed_loop_settings` 20, `ap_supplier_coding_profile` 5, `ap_supplier_alias` 8, `supplier_master_change_request` 6, `async_runner` 6, `idempotency` 7, `stream_tagging` 17, `extractors` 19, `walking_skeleton` 4 — all OK (the auto-progress cascade test is inside the 134 and passed with the new classify hop). **Decisions adopted** = spec recommendations: D-07-1 Option C (locked provisionally, swappable), D-07-3 `expense_claim` as `Data` (hrms absent), D-07-4 sibling `get_already_paid_config()`, D-07-5 unmatched-when-employee-check-needed → Manual Review, D-07-6 leave the PI draft. **Reconciliations:** derived the provisional stream from spec-02's existing `stream` field (no duplicate `provisional_stream` field); reused `purchase_invoice` (Option C makes the Stream-R voucher a PI, so no `journal_entry` field); reused spec-01's `credit_card_clearing_account` as the paid-from account. **Deferrals (honest):** the `AP Review Event` emission on stream-disagreement is **deferred to spec 10** (that doctype isn't built) — the signal is persisted on the capture (`stream_tag_agreement='Disagree'` + reason) instead; the Employee→Expense Claim path is Manual Review (hrms absent); the Option-A JE builder is specified behind the seam but not built (C is locked). §7.2 clean-room runbook **written**; §7.3 behavioral browser-smoke screenshots **committed** under `screenshots/07-classification-doctype-branching/`.
>
> **Verification state (06):** ✅ all 14 ACs green this session (Fake OCR; coding needs no live provider). New suite `test_ap_supplier_coding_profile` **5 OK**; `test_ap_invoice_capture` **Ran 120 tests … OK (skipped=1)** (was 107; +13 `TestAPCodingProfile`: 3-layer precedence, cost-center single-signal + conflict→Ambiguous, tax match/mismatch, submitted-PI guard, Stream-R catch-all ×2, the `is_fully_coded` gate, re-code-on-supplier-change mutating the draft PI, settings-footgun regression, missing-dimension-column skip). AC-06-13 (additive regression) = the existing promote tests still green in the 120. No-regression this session: `ap_closed_loop_settings` 20, `ap_supplier_alias` 8, `supplier_master_change_request` 6, `async_runner` 6, `idempotency` 7, `stream_tagging` 17, `extractors` 19, `walking_skeleton` 4 — all OK. **Decisions adopted** = spec recommendations: D1 single-company profile (no `company` field; payable stays native), D2 profile-only cost-center shipped with monkeypatchable location/card stubs that degrade to the profile signal, D3 ±0.01 tax tolerance, D4 `receipt_location` as `Data` (the Location doctype is **absent** on this bench), D5 Dynamic-Link dimension value, D7 new Coding-Review pause point (cascade hop gated on profile-existence so unconfigured sites flow unchanged), D8 separate `AP Supplier Coding Profile` doctype. Reconciliations: reused spec-04's `tax_amount`/`subtotal_amount` (no duplicate `extracted_tax_amount`); `unmapped_card_spend_account` already existed (spec 01/05); added `get_coding_settings()` accessor rather than overloading `get_promote_defaults`. §7.2 clean-room runbook **written**; §7.3 behavioral browser-smoke screenshots **committed** under `screenshots/06-gl-coding-tax-costcenter/`.
>
> **Verification state (05):** ✅ all 23 ACs green this session (Fake OCR pinned per the spec-01 test-env note, then the site's `Anthropic Claude` provider restored). New suites: `test_ap_supplier_alias` **8 OK**, `test_supplier_master_change_request` **6 OK**; extended: `test_ap_invoice_capture` **Ran 107 tests … OK (skipped=1: PDF/poppler)** (was 88; +19 spec-05 resolver/stream/Tier-3 tests, incl. the existing ambiguous-supplier test rewritten to drive the real 3-tier resolver via two aliases since this site names Suppliers by `supplier_name` so duplicate-name ambiguity is impossible), `test_ap_closed_loop_settings` **20 OK** (was 17; +3). No-regression proof this session: `test_extractors` 19, `test_anthropic` 26, `test_audit` 11, `test_hardening` 16, `test_benchmark` 9, `test_idempotency` 7, `test_async_runner` 6, `test_install` 3, `test_stream_tagging` 17, `test_portal_pull` 2 — all OK. **Open-decisions adopted** = the spec's recommendations (OD-05-1 distinct `Alias` status; OD-05-2 fuzzy min-length floor=4, exposed in settings; OD-05-3 auto-seed exact alias on approved create; OD-05-5 Stream-R Ambiguous treated soft; OD-05-6 regex kept, manager-authored + guarded; OD-05-7 consumes spec-02 `stream` — values `Receipt (R)`/`Invoice (I)`; OD-05-8 submittable `Supplier Master Change Request`). The Workflow record (states/transitions/roles) + `Treasury Approver`/`Auditor (Read Only)` roles + the non-Create `change_type` bodies are **deferred to spec 11/08** (approval is controller-driven via `approve_supplier_master_change_request` for now). §7.2 clean-room runbook **written**; §7.3 Playwright pass **pending**.
>
> **Verification state (04):** ✅ all 15 ACs green this session — `test_ap_invoice_capture` **Ran 88 tests … OK**, `test_extractors` **19 OK**, `test_anthropic` **26 OK**, `test_ap_closed_loop_settings` **17 OK**; no-regression proof: `test_hardening`/`test_audit`/`test_integration` (16/11/5) + spec-01/02/03 suites unchanged. A **real-Anthropic e2e** on `invoice_01.pdf` was executed (live API call) — header + 5 header-confidence rows + 2 line items + subtotal/tax all extracted correctly — and it **surfaced a tax-reconciliation bug** (pre-tax lines vs tax-inclusive total) now **fixed** (tax-aware reconciliation + 2 regression tests → capture suite 88 OK; spec §5.3.5 corrected; commit `6b95426fe5`). A second UI fix bound the header `subtotal_amount`/`tax_amount` to `proposed_currency` so they display in the extracted currency like the line items (was `final_currency`, empty pre-review → default-currency symbol; commit `c529feb0a5`), re-validated by a real GBP extraction (`APIC-2026-00006`). The §7.2 clean-room runbooks + §7.3 Playwright pass remain pending. The per-field threshold reused spec-01's `field_thresholds` + canonical scalar (no second scalar — locked decision #4).
>
> **Verification state (01–03):** ✅ reflects **automated ACs run green this session** (the per-spec test modules + the now-81-test capture regression). Their §7.2 clean-room and §7.3 Playwright runbooks are **written but not yet executed** (01's §7.3 is N/A — backend-only; 02's email-inbound runbook needs a live mailbox). **Spec-03 perceptual path:** `imagehash`+`pdf2image` are now installed in the bench venv, and the **image (PNG/JPG) branch is live-verified** — `test_real_phash_image_branch_flags_near_duplicate` runs the **real** `imagehash` pipeline (no monkeypatch) and flags a re-scan as a suspect. The **PDF-rasterization branch still needs the `poppler` system binary** (`test_real_phash_pdf_branch` **skips** until `poppler-utils` is installed); for PDF inputs dedupe currently degrades to exact-only on this bench. The fuzzy-distance decision logic is additionally covered by mocked tests (AC-03-6/7) + pure-Python Hamming distance. **Spec-03 verified this session:** `test_ap_invoice_capture` **Ran 81 tests … OK (skipped=1: PDF/poppler)**, `test_ap_closed_loop_settings` **Ran 16 tests … OK**, plus AC-03-13 schema (`content_hash`/`perceptual_hash` `varchar(140)`, indexed, non-unique) via `information_schema`.

---

## Build order

```
Phase 0  Foundation        01
Phase 1  Intake/Extraction  02 · 03 · 04        (03 before any billable OCR; 04 unblocks routing)
Phase 2  Resolve/Code/Fork  05 · 06 · 07
Phase 3  Gate/Route/Review  08 · 09 · 10        (10 is cross-cutting — can land alongside 02–09)
Phase 4  Approve/Pay        11 · 12             (Stream I only)
Phase 5  Close              13 · 14
```

- **Critical path:** `01 → 04 → 05 → 06 → 07 → 08 → 09 → 11 → 12 → 13 → 14`.
- **Cycle to break:** **08 (stub) → 11 → 08 (wire real bank-change check)**.
- **Parallelizable once 01 lands:** 02/03 (intake), 04 (extraction), and 10 (observability) proceed independently.

---

## Per-spec acceptance-criteria checklists

Tick each AC when its automated test is green. Descriptions live in each spec's §6 (kept DRY here — IDs only).

<details><summary><b>01 — Foundations · 20/20 ✅</b></summary>

- [x] AC-01-1
- [x] AC-01-2
- [x] AC-01-3
- [x] AC-01-4
- [x] AC-01-5
- [x] AC-01-6
- [x] AC-01-7
- [x] AC-01-8
- [x] AC-01-9
- [x] AC-01-10
- [x] AC-01-10a
- [x] AC-01-10b
- [x] AC-01-10c
- [x] AC-01-11
- [x] AC-01-12
- [x] AC-01-13
- [x] AC-01-14
- [x] AC-01-15
- [x] AC-01-16
- [x] AC-01-17
</details>

<details><summary><b>02 — Intake & Stream Tagging · 15/15 ✅</b></summary>

- [x] AC-02-1
- [x] AC-02-2
- [x] AC-02-3
- [x] AC-02-4
- [x] AC-02-5
- [x] AC-02-6
- [x] AC-02-7
- [x] AC-02-8
- [x] AC-02-9
- [x] AC-02-10
- [x] AC-02-11
- [x] AC-02-12
- [x] AC-02-13
- [x] AC-02-14
- [x] AC-02-15
</details>

<details><summary><b>03 — Deduplication · 13/13 ✅</b></summary>

- [x] AC-03-1
- [x] AC-03-2
- [x] AC-03-3
- [x] AC-03-4
- [x] AC-03-5
- [x] AC-03-6
- [x] AC-03-7
- [x] AC-03-8
- [x] AC-03-9
- [x] AC-03-10
- [x] AC-03-11
- [x] AC-03-12
- [x] AC-03-13
</details>

<details><summary><b>04 — Extraction (confidence + line items) · 15/15 ✅</b></summary>

- [x] AC-04-1
- [x] AC-04-2
- [x] AC-04-3
- [x] AC-04-4
- [x] AC-04-5
- [x] AC-04-6
- [x] AC-04-7
- [x] AC-04-8
- [x] AC-04-9
- [x] AC-04-10
- [x] AC-04-11
- [x] AC-04-12
- [x] AC-04-13
- [x] AC-04-14
- [x] AC-04-15
</details>

<details><summary><b>05 — Supplier Resolution · 23/23</b></summary>

- [x] AC-05-1
- [x] AC-05-2
- [x] AC-05-3
- [x] AC-05-4
- [x] AC-05-5
- [x] AC-05-6
- [x] AC-05-7
- [x] AC-05-8
- [x] AC-05-9
- [x] AC-05-10
- [x] AC-05-11
- [x] AC-05-12
- [x] AC-05-13
- [x] AC-05-14
- [x] AC-05-15
- [x] AC-05-16
- [x] AC-05-17
- [x] AC-05-18
- [x] AC-05-19
- [x] AC-05-20
- [x] AC-05-21
- [x] AC-05-22
- [x] AC-05-23
</details>

<details><summary><b>06 — GL Coding / Tax / Cost Center · 14/14</b></summary>

- [x] AC-06-1
- [x] AC-06-2
- [x] AC-06-3
- [x] AC-06-4
- [x] AC-06-5
- [x] AC-06-6
- [x] AC-06-7
- [x] AC-06-8
- [x] AC-06-9
- [x] AC-06-10
- [x] AC-06-11
- [x] AC-06-12
- [x] AC-06-13
- [x] AC-06-14
</details>

<details><summary><b>07 — Classification & Branching · 14/14</b></summary>

- [x] AC-07-1
- [x] AC-07-2
- [x] AC-07-3
- [x] AC-07-4
- [x] AC-07-5
- [x] AC-07-6
- [x] AC-07-7
- [x] AC-07-8
- [x] AC-07-9
- [x] AC-07-10
- [x] AC-07-11
- [x] AC-07-12
- [x] AC-07-13
- [x] AC-07-14
</details>

<details><summary><b>08 — Validation Gates · 21/21</b></summary>

- [x] AC-08-1
- [x] AC-08-2
- [x] AC-08-3
- [x] AC-08-4
- [x] AC-08-5
- [x] AC-08-6
- [x] AC-08-7
- [x] AC-08-8
- [x] AC-08-9
- [x] AC-08-10
- [x] AC-08-11
- [x] AC-08-12
- [x] AC-08-13
- [x] AC-08-14
- [x] AC-08-15
- [x] AC-08-16
- [x] AC-08-17
- [x] AC-08-18
- [x] AC-08-19
- [x] AC-08-20
- [x] AC-08-21
</details>

<details><summary><b>09 — Confidence Routing · 14/14</b></summary>

- [x] AC-09-1
- [x] AC-09-2
- [x] AC-09-3
- [x] AC-09-4
- [x] AC-09-5
- [x] AC-09-6
- [x] AC-09-7
- [x] AC-09-8
- [x] AC-09-9
- [x] AC-09-10
- [x] AC-09-11
- [x] AC-09-12
- [x] AC-09-13
- [x] AC-09-14
</details>

<details><summary><b>10 — AP Review & Observability · 0/17</b></summary>

- [ ] AC-10-1
- [ ] AC-10-2
- [ ] AC-10-3
- [ ] AC-10-4
- [ ] AC-10-5
- [ ] AC-10-6
- [ ] AC-10-7
- [ ] AC-10-8
- [ ] AC-10-9
- [ ] AC-10-10
- [ ] AC-10-11
- [ ] AC-10-12
- [ ] AC-10-13
- [ ] AC-10-14
- [ ] AC-10-15
- [ ] AC-10-16
- [ ] AC-10-17
</details>

<details><summary><b>11 — Approval & SoD (native Workflow) · 0/12</b></summary>

- [ ] AC-11-1
- [ ] AC-11-2
- [ ] AC-11-3
- [ ] AC-11-4
- [ ] AC-11-5
- [ ] AC-11-6
- [ ] AC-11-7
- [ ] AC-11-8
- [ ] AC-11-9
- [ ] AC-11-10
- [ ] AC-11-11
- [ ] AC-11-12
</details>

<details><summary><b>12 — Payment Execution · 0/14</b></summary>

- [ ] AC-12-1
- [ ] AC-12-2
- [ ] AC-12-3
- [ ] AC-12-4
- [ ] AC-12-5
- [ ] AC-12-6
- [ ] AC-12-7
- [ ] AC-12-8
- [ ] AC-12-9
- [ ] AC-12-10
- [ ] AC-12-11
- [ ] AC-12-12
- [ ] AC-12-13
- [ ] AC-12-14
</details>

<details><summary><b>13 — Bank-Feed Reconciliation · 0/13</b></summary>

- [ ] AC-13-1
- [ ] AC-13-2
- [ ] AC-13-3
- [ ] AC-13-4
- [ ] AC-13-5
- [ ] AC-13-6
- [ ] AC-13-7
- [ ] AC-13-8
- [ ] AC-13-9
- [ ] AC-13-10
- [ ] AC-13-11
- [ ] AC-13-12
- [ ] AC-13-13
</details>

<details><summary><b>14 — Closure & Audit / Retention · 0/16</b></summary>

- [ ] AC-14-1
- [ ] AC-14-2
- [ ] AC-14-3
- [ ] AC-14-4
- [ ] AC-14-5
- [ ] AC-14-6
- [ ] AC-14-7
- [ ] AC-14-8
- [ ] AC-14-9
- [ ] AC-14-10
- [ ] AC-14-11
- [ ] AC-14-12
- [ ] AC-14-13
- [ ] AC-14-14
- [ ] AC-14-15
- [ ] AC-14-16
</details>
