# Project TODO

Single source of truth for **persistent, outstanding work** on the AP Closed Loop pilot.
If a task outlives the current session/PR, it lives here. Ephemeral, within-a-single-task
steps belong in the in-session todo scratchpad (see `CLAUDE.md` → "Todo management"), not here.

> Maintained by humans and by Claude. Keep it greppable: one task per top-level bullet,
> stable IDs, never reuse an ID, never silently delete — completed work moves to **Done**.

---

## How this file works

**ID scheme.** Every task gets a stable, monotonic ID `T-NNN` (zero-padded to 3+ digits).
The next free ID is tracked in the counter below — bump it whenever you add a task.

- **Next ID:** `T-026`

**Priority labels.**

| Label | Meaning |
|---|---|
| `P0` | Drop-everything: blocking the pilot, broken main, data-loss risk |
| `P1` | Important, scheduled for the current milestone |
| `P2` | Should do, not yet scheduled |
| `P3` | Nice-to-have / someday |

**Statuses** are expressed by which section a task sits in: **In Progress**, **Backlog**,
**Blocked**, **Done**. Move the whole bullet between sections as status changes — keep its ID.

**Task line format** (everything after the title is optional but encouraged):

```
- [ ] **T-001** Short imperative title — one-line description.
      _(P1 · added 2026-05-31 · owner @rsmith · ref: docs/spec/04-...md, #123)_
```

- Use the checkbox: `[ ]` open, `[x]` done.
- `ref:` links context — a spec, planning doc, PR/issue number, or `path:line`. Prefer a link over re-explaining.
- On completion: check the box, append `· done YYYY-MM-DD`, and move the bullet to **Done**.

---

## In Progress

_Nothing in progress._

## Backlog

### Content classifier (spec 07 §34) — next phases

- [ ] **T-024** Content classifier Phase 3 — hybrid rule→LLM escalation. Run the free rule scorer first; only call the LLM when the rule verdict is low-confidence/unknown, so the easy majority never costs an API call. Today the dispatcher is all-rule or all-LLM. _(P2 · added 2026-06-04 · ref: docs/architecture/FORK-CHANGES.md §34; erpnext/.../ap_invoice_capture.py classify_document_content)_
- [ ] **T-025** Content classifier Phase 4 — accuracy at scale. (a) Run the **full real-OCR pipeline** (Anthropic OCR on the Track-B scanned images + any Track-A real dataset, then classify) to measure accuracy on real images, not just text. (b) Grow the labeled corpus (`test/receipts/`), especially the adversarial tier (paid invoices, unpaid receipts, statements, credit notes). (c) Wire the LLM call audit (Integration Request) like the OCR extractor. _(P2 · added 2026-06-04 · ref: test/receipts/README.md; docs/architecture/FORK-CHANGES.md §34)_

### Test hygiene

- [ ] **T-023** Isolate the AP test suite from the dev-site `AP Closed Loop Settings` singleton. `bench run-tests` runs on `erpnext.localhost`, so when a developer toggles automation flags in the browser (e.g. `ocr_provider='Anthropic Claude'` with no key, `auto_confirm_enabled=1`, `enable_coding_history_bootstrap=0`), the shared suite inherits them and fails en masse (observed 2026-06-02: 103 failures + a 13-min run, all from singleton drift; suite is `Ran 226 OK` once the three flags are reset to defaults). Each AP test class that depends on a setting should pin it in `setUp` (provider=fake, auto-confirm off, etc.) and roll back, so results don't depend on dev-site state. Same class of bug as the v16 `ignore_version` and Currency Exchange Settings cases. _(P1 · added 2026-06-02 · ref: erpnext/accounts/doctype/ap_invoice_capture/test_ap_invoice_capture.py; [[reference-v16-ignore-version-in-tests]])_

### Spec 14 (Closure & Audit) — deferred ACs beyond the 2026-06-02 pilot

- [ ] **T-019** Spec-14 audit-trail completeness — populate `bank_match` with the rich sub-fields (`date`, `amount`, `reconciled_by`, `reconciled_at` from BT `modified_by`/`modified`, D-14-5), add the blocked-lifecycle assertion (AC-14-7), and the Stream-R JE close stub (AC-14-8). Pilot ships the dual-signal close + minimal `bank_match` only.
      _(P2 · added 2026-06-02 · ref: docs/spec/14-closure-audit-retention.md AC-14-6/7/8; docs/spec/STATUS.md spec-14 block)_
- [ ] **T-020** Spec-14 TB-drift report — upgrade `Accounts Payable Trial Balance Drift` from the pilot AP-control-balance listing to the PCV-snapshot comparison: diff current-period Creditors/Credit-Card-Clearing GL against the prior `Account Closing Balance` via the vendored `get_previous_closing_entries`, emit `drift` + `over_threshold`, no-PCV → prior=0 (AC-14-9/10/11).
      _(P2 · added 2026-06-02 · ref: docs/spec/14-closure-audit-retention.md AC-14-9..11; erpnext/accounts/report/accounts_payable_trial_balance_drift/)_
- [ ] **T-021** Spec-14 retention enrichment — upgrade `enforce_retention_policy` from flag-only-log to setting `archive_pending`/`archived_flagged_at` on the capture, creating an idempotent Notification for `ap_notification_role`, flagging the linked File, and reading a configurable `retention_years` (fallback 7) (AC-14-12/15). No-delete invariant preserved.
      _(P2 · added 2026-06-02 · ref: docs/spec/14-closure-audit-retention.md AC-14-12/14/15)_
- [ ] **T-022** Spec-14 `AP Audit Trail` Print Format — a single-PDF print format for a closed capture rendering image ref, extraction, validation, approval, payment, bank-match, GL/posting, history, and gates sections (AC-14-16), driven by `build_audit_trail_for`.
      _(P3 · added 2026-06-02 · ref: docs/spec/14-closure-audit-retention.md AC-14-16)_

### Automation-first backlog (from the 2026-06-02 spec re-vision)


- [ ] **T-001** Install `poppler-utils` on every worker host — unblocks spec-03 PDF perceptual dedupe (currently degrades to exact-hash-only for PDF inputs; `test_real_phash_pdf_branch` skips). Confirm `imagehash` + `pdf2image` in each worker venv too.
      _(P1 · added 2026-05-31 · ref: docs/spec/STATUS.md decision #5; deploy task, not a code blocker)_
- [ ] **T-002** Bring up the MCP server on a migrated site — `bench migrate`, confirm the 5 `MCP Tool Config` rows seed, run the ~61 integration tests, then a live MCP Inspector OAuth round-trip. This is the top of the MCP critical path (built + committed, not yet verified on a migrated site).
      _(P1 · added 2026-05-31 · ref: docs/planning/mcp-server-NEXT-STEPS.md §2 · state-changing — needs approval)_
- [ ] **T-003** Execute the §7.3 Playwright UI pass for specs 01–04 (clean-room browser verification). Automated ACs are green; the UI gate is still pending.
      _(P2 · added 2026-05-31 · ref: docs/spec/STATUS.md verification-state notes)_
- [ ] **T-004** Triage the MCP pre-production caveats before any non-loopback deploy — negotiated-version echo, malformed-JSON → `-32700`, mandatory `oauth_resource_uri` for RFC 8707, and finalize open decisions O2/O3/O4 → record ADRs.
      _(P2 · added 2026-05-31 · ref: docs/planning/mcp-server-NEXT-STEPS.md §3–§4)_
- [ ] **T-005** Wire the MCP §7.2 canaries + DB-free unit tests into the repo's CI so they run on every PR touching `erpnext/mcp/`.
      _(P2 · added 2026-05-31 · ref: docs/planning/mcp-server-NEXT-STEPS.md §3 item 7)_
- [ ] **T-006** Remove the `.claude/worktrees/mcp-server` gitlink artifact (`git worktree remove`) once the MCP work is merged, so it isn't committed accidentally.
      _(P3 · added 2026-05-31 · ref: docs/planning/mcp-server-NEXT-STEPS.md §3 item 6)_
- [ ] **T-014** Spec 10 fast-follows (non-blocking): (a) introduce the **`Auditor (Read Only)`** role and grant it read on `AP Review Event` + `AP Capture Rejection Log` (the role is referenced across specs / the Bible but not yet created — current read perms are Accounts User/Manager + System Manager); (b) add a **`review_queue_entered_at`** Datetime stamped when a capture first hits Proposed/Pending Review, and use it for `time_to_resolve_seconds` instead of `creation` (v1 conflates queue wait with active handling). _(P3 · added 2026-06-01 · ref: docs/spec/10-ap-review-observability.md §8 D-8 + §5.1 permissions)_
- [ ] **T-013** Spec 11's native Workflow gate must read the **same** `auto_post_amount_threshold` setting that spec 09 owns — not a duplicate literal (spec 09 decision D-9). Concretely: the "over threshold → manager" Workflow transition `condition` must be `doc.grand_total > frappe.db.get_single_value("AP Closed Loop Settings", "auto_post_amount_threshold")` (this call is in the v16 Workflow `safe_eval` whitelist), so the PI-level native gate and the capture-level evaluator (`request_approval`) share one source — change the setting once, both lanes move. **Do NOT hard-code `1000` in the Workflow JSON.** _(P1 · added 2026-06-01 · ref: docs/spec/09-confidence-routing.md §5.5/D-9; docs/spec/11-approval-sod-workflow.md · feeds spec 11)_
- [ ] **T-012** Wire the **full vendor bank-change approval rule** in spec 11. Spec 08 blocks promotion when a watched bank field changed since the last payment, lifted only by a Posted `Supplier Master Change Request` (type *Update Bank Details*) **decided by someone other than the requester** (`has_approved_bank_change`). That's the **conservative interim** rule (D10). Spec 11 owns the real policy: a dedicated **Treasury Approver** / **non-AP-approver** role (an AP clerk must not be able to lift a bank-change block at all), the ERPNext Workflow states/transitions for the Update-Bank-Details request, and any dollar/risk threshold. Until then, anyone who isn't the requester can lift it — acceptable for the pilot, not for go-live. _(P1 · added 2026-06-01 · ref: docs/spec/08-validation-gates.md §D10; docs/spec/11-approval-sod-workflow.md · feeds spec 11; `has_approved_bank_change` in ap_invoice_capture.py)_
- [ ] **T-011** Confirm with the customer **how new-vendor approval should happen** before go-live. Spec 05 ships the gated `Supplier Master Change Request` flow (an Unknown vendor with high OCR confidence queues a Draft request; nothing auto-creates a Supplier) with a **controller-driven** approval: `frappe.only_for(approver_role)` (default **Accounts Manager**, configurable via `AP Closed Loop Settings.supplier_change_approver_role`) **plus** a requester≠approver segregation-of-duties backstop. Open customer questions: (a) **who** approves new vendors (which role/people, single vs multi-step); (b) whether a **dollar/risk threshold** should require a stronger approver; (c) whether to wire a real ERPNext **Workflow** (states/transitions/Allowed Roles — owned by spec 11) and/or the `Treasury Approver` / `Auditor (Read Only)` roles; (d) whether the gate should be **on by default** (currently off via `enable_gated_supplier_creation`). Today's controller gate is a safe default and reversible; lock the policy with the customer, then spec 11 wires the Workflow accordingly.
      _(P1 · added 2026-06-01 · ref: docs/spec/05-supplier-resolution.md §5.5/§8; docs/spec/11-approval-sod-workflow.md · customer decision, feeds spec 11)_
- [ ] **T-010** Confirm the Stream-R (already-paid card receipt) posting model with the customer/accounting lead. We are building spec 07 with the **provisional default = Option 1: Purchase Invoice with `is_paid=1`** (decision D-07-1 / gating #1) — chosen for least-custom-code + keeps supplier visible in AP/spend-by-supplier reports. It is **reversible**: the posting is built behind a single `_build_already_paid_voucher()` seam, so switching to a direct Journal Entry or PI+Clearing later is a one-function config change, not a rewrite. Get sign-off (or a different choice) from the customer before go-live; this also informs #2 (Bank Transaction guardrail) for specs 13/14.
      _(P1 · added 2026-06-01 · ref: docs/spec/07-classification-doctype-branching.md §8 D-07-1; docs/spec/STATUS.md decision #1 · customer decision, not a code blocker)_
- [ ] **T-009** Consider an extra chat-specific scope-limit control for the AI chat panel — a per-tool `chat_enabled` flag (on `MCP Tool Config`) letting ops restrict the AI's tool surface *more tightly than* a user's own role/permissions. Not a security boundary (Frappe RBAC already binds the chat to the calling user's access); add only if a concrete governance/compliance requirement appears. Cheap to add later, no rework of the chat plan.
      _(P3 · added 2026-05-31 · ref: docs/planning/ai-chat-panel-brief.md; deferred from AI-chat-panel security design discussion)_

## Blocked

- [ ] **T-007** Execute spec-04 §7.2 clean-room runbooks — real-Anthropic per-field confidence + line-items-promote. Runbooks are written; not yet run.
      _(P2 · added 2026-05-31 · ref: docs/spec/STATUS.md verification-state (04) · blocked: needs a live Anthropic API key)_
- [ ] **T-008** Lock the open v2 gating decisions — #1 Stream-R posting model, #2 retire no-Bank-Transaction guardrail (+ADR), #3 `allow_self_approval` on v16, #7 native `Authorization Rule` vs custom matrix, #8 SimpleFIN vs Plaid, #9 native uniqueness check. Each gates downstream specs (07/11/13/14).
      _(P1 · added 2026-05-31 · ref: docs/spec/STATUS.md "Decisions to lock first" · blocked: awaiting accounting lead / Brandon)_

## Done

_Completed tasks are archived here newest-first, with their `done YYYY-MM-DD` date. Never delete — this is the audit trail._

- [x] **T-018** **Gated supplier auto-create defaults ON for high-confidence names (spec 05).** Built: `enable_gated_supplier_creation` default flipped OFF→ON (JSON + getter), scoped to high OCR confidence (guard already in `_maybe_queue_supplier_create`). A confident unknown auto-files a Draft create request (human only approves — SoD intact); low-confidence stays blocked. 3 tests (capture suite 202→205 OK), AC-05-24..26 green. Approval policy stays a customer decision (T-011). · done 2026-06-02 _(ref: docs/architecture/FORK-CHANGES.md §25)_
- [x] **T-017** **Classification trusts confident content over the intake stream tag (spec 07 §5.3).** Built: `enable_classification_trust_content` (default OFF) + `is_classification_trust_content_enabled()`; `_content_classification_confident`; classify disagreement branch trusts confident content (records a `stream_mistag` AP Review Event, no halt) instead of unconditional Manual Review. 3 tests (capture suite 199→202 OK), AC-07-15/16 green; screenshots committed. · done 2026-06-02 _(ref: docs/architecture/FORK-CHANGES.md §24)_
- [x] **T-016** **Coding bootstrap from history (spec 06 §5.3.1).** Built: `enable_coding_history_bootstrap` (default ON) + consensus/min_samples/lookback settings + `get_coding_history_config()`; `_derive_coding_from_history` (per-field consensus over the supplier's posted PIs → derived + ambiguous); Layer-1.5 in `apply_coding_profile_for` (below profile+caller, above Settings) + split-history → Coding Review escalation; `_coding_configured` fires the coding hop for a history-codable supplier with no profile. A routine vendor self-codes from its own history; split → Coding Review naming competing values; thin → fall through. 4 tests (capture suite 195→199 OK), AC-06-15..18 green; screenshots committed. · done 2026-06-02 _(ref: docs/architecture/FORK-CHANGES.md §23)_
- [x] **T-015** **Confidence-gated auto-confirm (the #1 automation lever).** Built: `AP Closed Loop Settings.auto_confirm_enabled` (default OFF) + `is_auto_confirm_enabled()`; shared `_confidence_fields_ok` + `_evaluate_confirm_signals`; `_determine_next_step` Step 1a hop → `auto_confirm_extracted_fields_for` (re-checks gate, suppresses AP Review Event); `confirm_extracted_fields` gained `emit_event`. A clean+confident extraction auto-confirms past the human OCR-review pause; any low/missing confidence or open flag falls back to the human pause. 10 tests (capture suite 185→195 OK), AC-04-16..19 + AC-09-15..17 green; sequence diagram + PNG refreshed; screenshots committed. · done 2026-06-02 _(ref: docs/architecture/FORK-CHANGES.md §22)_
