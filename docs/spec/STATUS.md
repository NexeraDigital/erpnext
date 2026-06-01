# AP Closed-Loop Workflow v2 — Build Status

> Source-of-truth tracker for implementing `docs/spec/01`–`14`. Companion to [[00-overview]].
> **Update on every merged slice PR.** This file — plus each spec's frontmatter `status:` — is what survives across sessions; the in-session task list does not.
>
> **Last updated:** 2026-05-31 · **Specs:** 14 · **Acceptance criteria:** 221 · **Overall:** 🟡 4/14 done — **specs 01–04 ✅** (63/221 ACs green; 71 new tests passing; no regressions)

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

- [ ] **#1 — Stream-R posting model** → recommend **PI `is_paid=1`** (vs direct JE vs PI+Clearing). *Gates 07, 13, 14.* — owner: accounting lead
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
| 05 | [[05-supplier-resolution]] | 2 Resolve | 🔲 | 0/23 | L | 01, 04 | bank-detail→`Bank Account` (fixed) | — |
| 06 | [[06-gl-coding-tax-costcenter]] | 2 Resolve | 🔲 | 0/14 | L | 01, 04, 05 | coding-profile vs Custom Fields | — |
| 07 | [[07-classification-doctype-branching]] | 2 Resolve | 🔲 | 0/14 | L | 01, 02, 05, 06 | **#1 (Stream-R posting)** | — |
| 08 | [[08-validation-gates]] | 3 Gate | 🔲 | 0/21 | L | 01, 04, 05, 06, **11※** | 3WM native-vs-custom; 11-stub※ | — |
| 09 | [[09-confidence-routing]] | 3 Gate | 🔲 | 0/14 | S | 04, 08 | threshold single-source (w/ 11) | — |
| 10 | [[10-ap-review-observability]] | 3 Gate | 🔲 | 0/17 | — | 01 | `AP Review Event` seam freeze | — |
| 11 | [[11-approval-sod-workflow]] | 4 Approve | 🔲 | 0/12 | L | 02, 05, 08 | **#3, #7** | — |
| 12 | [[12-payment-execution]] | 4 Approve | 🔲 | 0/14 | M | 01, 02, 07 | auto-pay gate default | — |
| 13 | [[13-bank-feed-reconciliation]] | 5 Close | 🔲 | 0/13 | L | 01, 02, 07 | **#2, #8** | — |
| 14 | [[14-closure-audit-retention]] | 5 Close | 🔲 | 0/16 | L | 01, 07, 13 | #1, #2 (consumes) | — |

*Size for 10 not stated in-spec (estimate M). **08※:** 08 and 11 are mutually dependent — land 08 with an interim `has_approved_bank_change()` **stub**, then 11, then wire 08's real check (08 §8 D10).*

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

<details><summary><b>05 — Supplier Resolution · 0/23</b></summary>

- [ ] AC-05-1
- [ ] AC-05-2
- [ ] AC-05-3
- [ ] AC-05-4
- [ ] AC-05-5
- [ ] AC-05-6
- [ ] AC-05-7
- [ ] AC-05-8
- [ ] AC-05-9
- [ ] AC-05-10
- [ ] AC-05-11
- [ ] AC-05-12
- [ ] AC-05-13
- [ ] AC-05-14
- [ ] AC-05-15
- [ ] AC-05-16
- [ ] AC-05-17
- [ ] AC-05-18
- [ ] AC-05-19
- [ ] AC-05-20
- [ ] AC-05-21
- [ ] AC-05-22
- [ ] AC-05-23
</details>

<details><summary><b>06 — GL Coding / Tax / Cost Center · 0/14</b></summary>

- [ ] AC-06-1
- [ ] AC-06-2
- [ ] AC-06-3
- [ ] AC-06-4
- [ ] AC-06-5
- [ ] AC-06-6
- [ ] AC-06-7
- [ ] AC-06-8
- [ ] AC-06-9
- [ ] AC-06-10
- [ ] AC-06-11
- [ ] AC-06-12
- [ ] AC-06-13
- [ ] AC-06-14
</details>

<details><summary><b>07 — Classification & Branching · 0/14</b></summary>

- [ ] AC-07-1
- [ ] AC-07-2
- [ ] AC-07-3
- [ ] AC-07-4
- [ ] AC-07-5
- [ ] AC-07-6
- [ ] AC-07-7
- [ ] AC-07-8
- [ ] AC-07-9
- [ ] AC-07-10
- [ ] AC-07-11
- [ ] AC-07-12
- [ ] AC-07-13
- [ ] AC-07-14
</details>

<details><summary><b>08 — Validation Gates · 0/21</b></summary>

- [ ] AC-08-1
- [ ] AC-08-2
- [ ] AC-08-3
- [ ] AC-08-4
- [ ] AC-08-5
- [ ] AC-08-6
- [ ] AC-08-7
- [ ] AC-08-8
- [ ] AC-08-9
- [ ] AC-08-10
- [ ] AC-08-11
- [ ] AC-08-12
- [ ] AC-08-13
- [ ] AC-08-14
- [ ] AC-08-15
- [ ] AC-08-16
- [ ] AC-08-17
- [ ] AC-08-18
- [ ] AC-08-19
- [ ] AC-08-20
- [ ] AC-08-21
</details>

<details><summary><b>09 — Confidence Routing · 0/14</b></summary>

- [ ] AC-09-1
- [ ] AC-09-2
- [ ] AC-09-3
- [ ] AC-09-4
- [ ] AC-09-5
- [ ] AC-09-6
- [ ] AC-09-7
- [ ] AC-09-8
- [ ] AC-09-9
- [ ] AC-09-10
- [ ] AC-09-11
- [ ] AC-09-12
- [ ] AC-09-13
- [ ] AC-09-14
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
