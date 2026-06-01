# Test Plan — Intake & Stream Tagging (Receipt vs Invoice)

> Clean-room runbook for **spec 02** (`docs/spec/02-intake-stream-tagging.md`), the primary stream-tagging path. The email-in path has its own companion runbook (`intake-email-inbound.md`). Executable by a fresh instance with no prior context.

## 1. Feature under test

Every `AP Invoice Capture` is tagged at intake with a provisional **stream** — `Receipt (R)` (already paid) / `Invoice (I)` (unpaid bill) / `Unclassified` — from data-driven rules (filename / sender domain / body text / channel). `Receipt (R)` captures get a 72-hour `sla_due_at` deadline (`received_at + 72h`); Invoice/Unclassified leave it NULL. Rules live in **AP Closed Loop Settings → Stream Tagging Rules** so they're tunable with no code change. New intake channels (Email Inbound, Mobile Upload, Vendor Portal Pull base) are added.

## 2. Branch / commit

- **Branch:** `russ/migrateToV16`
- **Commit:** working tree (apply the spec-02 changes if not present). Verify `erpnext/accounts/doctype/ap_stream_rule/` and `ap_closed_loop/portal_pull.py` exist.

## 3. Environment setup

```bash
bench --site <test-site> migrate   # creates AP Stream Rule + the new capture/settings fields,
                                    # and after_migrate seeds 4 default stream rules
```
- frappe v16 + this erpnext fork. No external API keys for this plan.
- **For TC-1's regression line only:** the capture suite needs the deterministic provider — set `AP Closed Loop Settings.ocr_provider = "Fake (Deterministic)"` first (record + restore the prior value).

## 4. Test data prerequisites

- The 4 seed rules are auto-installed by migrate: `filename receipt_* → Receipt (R)` (pri 10), `filename invoice_* → Invoice (I)` (pri 20), `sender_domain stripe.com → Receipt (R)` (pri 30), `body PAID → Receipt (R)` (pri 40). Confirm at `/app/ap-closed-loop-settings` → **Stream Tagging Rules**.
- A System Manager / Accounts Manager login for the UI cases.

## 5. Numbered test cases

### TC-1 — Automated suites
- **Action:**
  ```bash
  bench --site <test-site> run-tests --module erpnext.accounts.ap_closed_loop.tests.test_stream_tagging
  bench --site <test-site> run-tests --module erpnext.accounts.ap_closed_loop.tests.test_portal_pull
  bench --site <test-site> run-tests --module erpnext.accounts.doctype.ap_closed_loop_settings.test_ap_closed_loop_settings
  # regression (set Fake provider first):
  bench --site <test-site> run-tests --module erpnext.accounts.doctype.ap_invoice_capture.test_ap_invoice_capture
  ```
- **Expected:** `17 OK`, `2 OK`, `15 OK`, `66 OK` respectively.
- **Pass/fail:** PASS iff all green.

### TC-2 — Manual upload of a receipt classifies Stream R + sets the 72h SLA
- **Action:** `/app/ap-invoice-capture/new` (or the list **Upload**), attach a PDF named `receipt_demo.pdf`, **Save**.
- **Expected (form):** `Stream = Receipt (R)`, `Stream Provisional Source = filename:receipt_*`, `SLA Due At` populated.
- **DB check:**
  ```bash
  bench --site <test-site> mariadb -e "SELECT stream, stream_provisional_source, received_at, sla_due_at FROM \`tabAP Invoice Capture\` WHERE source_filename='receipt_demo.pdf'\\G"
  ```
  `stream='Receipt (R)'`; `sla_due_at` = `received_at` + 72h.
- **Pass/fail:** PASS iff the row shows Receipt (R) and the 72h deadline.

### TC-3 — Invoice filename → Stream I, no SLA
- **Action:** upload `invoice_demo.pdf`, Save.
- **Expected:** `stream='Invoice (I)'`, `sla_due_at` NULL.
- **Pass/fail:** PASS iff Invoice (I) with NULL `sla_due_at`.

### TC-4 — No signal → Unclassified
- **Action:** upload `statement_q1.pdf`, Save.
- **Expected:** `stream='Unclassified'`, `stream_provisional_source='default'`, `sla_due_at` NULL.
- **Pass/fail:** PASS iff Unclassified.

### TC-5 — Data-driven tuning (no code change)
- **Action:** at `/app/ap-closed-loop-settings` add a Stream Rule row `sender_domain | square.com | Receipt (R)`, Save. Then create a capture whose sender domain is `square.com` (use the console: `from erpnext.accounts.doctype.ap_invoice_capture.ap_invoice_capture import create_capture_from_file; c=create_capture_from_file(file_url="/x/d.pdf", file_name="d.pdf", sender_domain="payments.square.com"); print(c.stream); frappe.db.rollback()`).
- **Expected:** `Receipt (R)` — classification changed purely from the new rule.
- **Pass/fail:** PASS iff the capture classifies Receipt (R) with no code edit.

### TC-6 — Mobile channel
- **Action:** console — upload a File, then `create_capture_from_uploaded_file(file_name, intake_channel="Mobile Upload")`.
- **Expected:** the capture's `intake_channel == "Mobile Upload"`.
- **Pass/fail:** PASS iff persisted.

## 6. Cleanup / rollback

- Automated suites roll back per test. Delete the UI-created captures from TC-2/3/4 (`/app/ap-invoice-capture`). Remove the TC-5 rule row. Restore `ocr_provider` if changed for TC-1.

## 7. Pass/fail summary template

| Case | What | Result |
|---|---|---|
| TC-1 | Automated (17 / 2 / 15 / 66) | [ ] |
| TC-2 | Receipt upload → Stream R + 72h SLA | [ ] |
| TC-3 | Invoice upload → Stream I, no SLA | [ ] |
| TC-4 | Unmatched → Unclassified | [ ] |
| TC-5 | Add rule → reclassifies (no code) | [ ] |
| TC-6 | Mobile channel persists | [ ] |

**Overall:** [ ] PASS  [ ] FAIL — notes: ______
