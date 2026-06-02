# Test plan — Spec 11: Approval & Segregation of Duties (automation-first pilot)

## 1. Feature under test

The pilot closes the real control gap: **the person who prepared an invoice may not also
approve it** above threshold. Built (keeping the existing approval engine — the company-wide
native Workflow is a deferred opt-in upgrade, §5.6 / D-2/D-8):
- **App-code SoD identity guard** in `record_manager_decision`: an above-threshold approve by
  the recorded preparer (`reviewed_by` / `validated_by`) raises `CaptureApprovalError`.
  Self-**reject** is allowed; **Administrator** is the audited break-glass exception.
- **Three roles** (`AP Clerk`, `Treasury Approver`, `Auditor (Read Only)`) seeded on migrate.
- **Bank-change → Treasury Approver** (T-012): `has_approved_bank_change` now requires the
  lifting decision to be by a non-requester who holds the **Treasury Approver** role.
- `resolve_approver_role` (pilot returns `Accounts Manager`; matrix deferred).

In-policy invoices still auto-approve (spec 09) — only above-threshold / failed-control cases
escalate. Planning doc: `docs/spec/11-approval-sod-workflow.md`.

## 2. Branch / commit

- **Branch:** `russ/migrateToV16`; commit adding the SoD guard + `_seed_ap_roles` (`git log -1`).

## 3. Environment setup

```bash
bench --site <site> migrate     # seeds the three roles (after_migrate → install_ap_defaults)
bench --site <site> set-config -g ocr_provider "Fake (Deterministic)"
bench start
```
Apps: frappe v16, erpnext (this fork), payments. No hrms (Expense Claim deferred, D-5).

## 4. Test data prerequisites

A promoted capture routed to `Pending Manager` (total over `auto_post_amount_threshold`), with a
known preparer recorded in `reviewed_by`/`validated_by`. Two desk users: one preparer, one clean
approver, both holding `Accounts Manager`.

## 5. Numbered test cases

### A. Automated (authoritative)
- **A-1.** `bench … run-tests --module …test_ap_invoice_capture --test TestAPApprovalSoD` →
  `Ran 6 … OK` (AC-11-4 self-approval blocked, AC-11-5 clean approver passes, self-reject allowed,
  Administrator exempt, AC-11-8 resolver default, AC-11-9 roles installed).
- **A-2.** The updated `TestAPInvoiceCaptureValidationGates.test_ac_08_18…` proves the bank-change
  lift now requires a non-requester **Treasury Approver** (T-012) → OK.
- **A-3.** Full module → `Ran 211 … OK` (zero regressions).

### B. Manual UI
- **B-1 (roles).** Open `/app/role/Treasury Approver` (and `AP Clerk`, `Auditor (Read Only)`) →
  the role exists.
- **B-2 (SoD block).** Log in as the **preparer** (who confirmed/promoted the capture, holding
  Accounts Manager), open the Pending-Manager capture, click **Approve** → blocked with the SoD
  error; `approval_status` stays `Pending Manager`. (Cannot be shown as Administrator — Administrator
  is the break-glass exemption.)
- **B-3 (clean approve).** Log in as a **different** Accounts Manager → Approve succeeds
  (`Manager Approved`).

## 6. Cleanup / rollback

Automated suite rolls back. For manual cases delete the capture/PI and the test users; the roles
are idempotent fixtures (leave them).

## 7. Pass/fail summary template

| # | Case | Result |
|---|---|---|
| A-1 | `TestAPApprovalSoD` — `Ran 6 … OK` | [ ] |
| A-2 | bank-change requires Treasury Approver | [ ] |
| A-3 | Full module — `Ran 211 … OK` | [ ] |
| B-1 | Roles exist in desk | [ ] |
| B-2 | Preparer blocked from self-approval | [ ] |
| B-3 | Different approver succeeds | [ ] |
