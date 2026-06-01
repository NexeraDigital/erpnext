# Test Plan — GL Coding, Cost Center & Tax Assignment (spec 06)

> Clean-room runbook for **spec 06** (`docs/spec/06-gl-coding-tax-costcenter.md`). Executable by a fresh Claude instance with no prior context on a clean bench. No external API keys needed — pin the deterministic Fake OCR provider throughout.

## 1. Feature under test

Per-supplier GL **auto-coding**: an `AP Supplier Coding Profile` supplies the default expense account, cost center, purchase-tax template, payment terms, and accounting dimensions for a vendor, layered on top of native ERPNext vendor settings. `apply_coding_profile_for(capture)` merges three default layers (Settings → profile → caller), **infers a cost center** (routing conflicting signals to a Coding-Review queue instead of guessing), **validates tax** against the resolved template, and stages the coding onto the draft Purchase Invoice. `is_fully_coded(capture)` gates auto-posting. Stream-R receipts with no vendor fall back to an "Unmapped Card Spend" account. User-visible change: a new `AP Supplier Coding Profile` master, a GL-coding section on `AP Invoice Capture`, and a `default_purchase_tax_template` on `AP Closed Loop Settings`.

## 2. Branch / commit

- **Branch:** `russ/migrateToV16` · working tree. Sanity: `erpnext/accounts/doctype/ap_supplier_coding_profile/` exists; `apply_coding_profile_for` / `is_fully_coded` are defined in `ap_invoice_capture.py`; `get_coding_settings` in `ap_closed_loop_settings.py`.

## 3. Environment setup

```bash
bench --site <test-site> migrate   # installs AP Supplier Coding Profile + Dimension,
                                    # the capture coding fields, and default_purchase_tax_template
```
- frappe v16 + this erpnext fork. **Pin Fake OCR:** AP Closed Loop Settings → OCR Provider = Fake (Deterministic) (record + restore the prior value). No external keys.

## 4. Test data prerequisites

- A System Manager / Accounts Manager login.
- A `Supplier` (e.g. `Acme Coding Co`), an expense **Account** (e.g. `_Test Account Cost for Goods Sold - _TC`), a **Cost Center**, and a **Purchase Taxes and Charges Template** for the company with one "On Net Total" row at a known rate (e.g. 10%).
- An `AP Supplier Coding Profile` for that supplier with the expense account, cost center, and tax template set.

## 5. Numbered test cases

### TC-1 — Automated suites (pin Fake first)
- **Action:**
  ```bash
  bench --site <test-site> run-tests --module erpnext.accounts.doctype.ap_supplier_coding_profile.test_ap_supplier_coding_profile
  bench --site <test-site> run-tests --module erpnext.accounts.doctype.ap_invoice_capture.test_ap_invoice_capture
  ```
- **Expected:** `5 OK` and `Ran 120 tests … OK (skipped=1)`.
- **Pass/fail:** PASS iff both green.

### TC-2 — Profile auto-codes a capture (works)
- **Action:** drive a capture for `Acme Coding Co` through OCR → Confirm → validate. With the cascade configured, the coding step runs; otherwise call `apply_coding_profile_for` (the form/coding action). 
- **Expected (form, GL Coding section):** `Coding Status = Coded`, `Applied Expense Account` = the profile's account, `Applied Cost Center` = the profile's cost center, `Applied Tax Template` = the profile's template, no review reason.
- **DB check:** `bench --site <site> mariadb -e "SELECT coding_status, applied_expense_account, applied_cost_center, applied_tax_template FROM \`tabAP Invoice Capture\` WHERE name='<APIC>'\\G"`
- **Pass/fail:** PASS iff the profile's coding is applied and status is Coded.

### TC-3 — Cost-center conflict routes to review (guard)
- **Precondition:** a scenario where two cost-center signals resolve differently (in the automated suite this is exercised by monkeypatching the location/card resolvers; in a live bench, set a profile cost center and a conflicting location/card map if configured).
- **Expected:** `Coding Status = Ambiguous`, `Coding Review Reason` names the conflict, `Action Required = 1`, and **no** cost center is written (`Applied Cost Center` empty). The capture appears in `get_coding_review_queue_for`.
- **Pass/fail:** PASS iff ambiguous coding does not silently pick a cost center and the capture is flagged.

### TC-4 — Tax mismatch flags the capture (guard)
- **Action:** set the capture's extracted `tax_amount` to a value that disagrees with the template-computed tax (e.g. template 10% on subtotal 300 = 30, but extracted tax = 25), then run coding.
- **Expected:** `Coding Status = Flagged`, review reason "Extracted tax 25 != template-computed tax 30", `is_fully_coded` False (the capture is not eligible to auto-post).
- **Pass/fail:** PASS iff a tax mismatch flags and blocks auto-post.

### TC-5 — Line-aware promote carries the coding to the PI (works)
- **Action:** after coding (Coded), promote the capture to a Purchase Invoice.
- **Expected:** the draft PI's item rows carry the applied expense account + cost center; the PI header `taxes_and_charges` = the resolved template with its taxes rows populated.
- **DB check:** `SELECT expense_account, cost_center FROM \`tabPurchase Invoice Item\` WHERE parent='<PI>'` and the PI's `taxes_and_charges`.
- **Pass/fail:** PASS iff the PI reflects the coding.

### TC-6 — Stream-R catch-all (edge)
- **Action:** a Stream-R (Receipt) capture with no matched supplier and no profile, with `AP Closed Loop Settings → Unmapped Card Spend Account` set; run coding.
- **Expected:** `Applied Expense Account` = the Unmapped Card Spend account, `Coding Status = Flagged`, `Action Required = 1` (soft-flag — still proceeds, not blocked). With the account unset → no expense, `is_fully_coded` False.
- **Pass/fail:** PASS iff the catch-all account is used and the capture is soft-flagged.

### TC-7 — Submitted-PI guard (negative)
- **Action:** promote a capture, **submit** the resulting Purchase Invoice, then call `apply_coding_profile_for` again.
- **Expected:** raises `CapturePromotionError` ("Cannot re-code a submitted Purchase Invoice …"); the PI is unchanged (docstatus still 1).
- **Pass/fail:** PASS iff re-coding a submitted PI is refused.

## 6. Cleanup / rollback

- Delete test `AP Supplier Coding Profile`, `AP Invoice Capture`, any `Purchase Invoice`/`Payment Entry`, `Purchase Taxes and Charges Template`, and Suppliers created.
- Restore `AP Closed Loop Settings → OCR Provider` and clear any test `Unmapped Card Spend Account` / `Default Purchase Tax Template`.

## 7. Pass/fail summary template

| Test | Description | Result |
|---|---|---|
| TC-1 | Automated suites (5 / 120 OK) | [ ] |
| TC-2 | Profile auto-codes → Coded | [ ] |
| TC-3 | Cost-center conflict → Ambiguous, no CC, review queue | [ ] |
| TC-4 | Tax mismatch → Flagged, not fully coded | [ ] |
| TC-5 | Promote carries coding to the PI | [ ] |
| TC-6 | Stream-R catch-all account used + soft-flagged | [ ] |
| TC-7 | Submitted-PI re-code refused | [ ] |

**Overall:** [ ] PASS / [ ] FAIL — notes:
