# Test Plan — Email-Inbound Intake (companion to intake-stream-tagging)

> Clean-room runbook for the **email-in adapter** of spec 02 (`docs/spec/02-intake-stream-tagging.md` §5.3.3). Requires a real inbound mailbox, so it is split out from the primary `intake-stream-tagging.md`. The adapter logic itself is also covered DB-side by the `test_stream_tagging` automated suite (TC-0); this plan verifies the **live** `Communication.after_insert` → capture flow.

## 1. Feature under test

A dedicated inbound **Email Account** receives invoices/receipts; the `Communication.after_insert` hook (`handle_inbound_ap_communication`) turns each inbound mail's supported attachments into `Document Capture` records (one per supported attachment), tagged by stream, with `intake_channel = Email Inbound` and `received_at = the email's date`. The feature is **OFF by default** — it activates only when `AP Closed Loop Settings.ap_intake_email_account` names the inbound account.

## 2. Branch / commit

- **Branch:** `russ/migrateToV16` · working tree (apply spec-02 if absent).

## 3. Environment setup

```bash
bench --site <test-site> migrate
```
- **Inbound Email Account:** create an `Email Account` (`/app/email-account/new`) with **Enable Incoming** = checked, IMAP host/port, and login credentials. **The human operator supplies the mailbox credentials** — never commit them; they are entered in the Email Account form only. A throwaway IMAP mailbox (e.g. a dedicated Gmail/Mailcow account) is sufficient.
- **Activate the feature:** set `AP Closed Loop Settings → AP Intake Email Account` to that account, Save.

## 4. Test data prerequisites

- The inbound Email Account above, named (e.g.) `AP Intake`.
- A sender mailbox to email from.
- A test PDF named `receipt_test.pdf` and an unsupported `note.txt`.

## 5. Numbered test cases

### TC-0 — Adapter logic (automated, no mailbox)
- **Action:** `bench --site <test-site> run-tests --module erpnext.accounts.ap_closed_loop.tests.test_stream_tagging`
- **Expected:** `17 OK` — includes `test_email_in_one_capture_per_supported_attachment` (one capture per supported attachment), `test_email_in_no_supported_attachments` (`[]`), and `test_handle_inbound_guard_skips` (no-op unless inbound on the configured account).
- **Pass/fail:** PASS iff green.

### TC-1 — Live: email a receipt → capture auto-created as Stream R
- **Precondition:** feature activated (§3).
- **Action:** email `receipt_test.pdf` (+ `note.txt`) to the inbound mailbox. Wait for the email-sync scheduler (or run `bench --site <test-site> execute frappe.email.doctype.email_account.email_account.pull`).
- **Expected:** exactly **one** new `Document Capture` (from the PDF, not the `.txt`), with `intake_channel = Email Inbound`, `received_at` = the email's sent time, `stream = Receipt (R)` (filename `receipt_*`), and a 72h `sla_due_at`.
- **DB check:**
  ```bash
  bench --site <test-site> mariadb -e "SELECT name, intake_channel, stream, sla_due_at FROM \`tabDocument Capture\` WHERE source_filename='receipt_test.pdf'\\G"
  ```
- **Pass/fail:** PASS iff one capture, Email Inbound, Receipt (R), 72h SLA, and the `.txt` produced no capture.

### TC-2 — No-op guard (mail not on the AP account)
- **Action:** with the feature still on, send/receive an email on a **different** Email Account (not the configured AP intake one).
- **Expected:** **no** `Document Capture` is created from it.
- **Pass/fail:** PASS iff no capture is created.

### TC-3 — Feature off
- **Action:** clear `AP Closed Loop Settings → AP Intake Email Account`, Save. Receive a new inbound email on the (now-unconfigured) mailbox.
- **Expected:** no capture created (hook is a no-op when the setting is empty).
- **Pass/fail:** PASS iff no capture is created.

## 6. Cleanup / rollback

- Delete captures created by TC-1. Clear `ap_intake_email_account` (or leave configured if you want email intake live). Optionally disable/delete the test Email Account. Never leave real mailbox credentials in a shared site.

## 7. Pass/fail summary template

| Case | What | Result |
|---|---|---|
| TC-0 | Adapter logic automated (17 OK) | [ ] |
| TC-1 | Live email → 1 capture, Email Inbound, Stream R, 72h SLA | [ ] |
| TC-2 | Mail on a non-AP account → no capture | [ ] |
| TC-3 | Feature off (setting empty) → no capture | [ ] |

**Overall:** [ ] PASS  [ ] FAIL — notes: ______
