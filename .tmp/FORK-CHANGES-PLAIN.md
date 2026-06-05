# What Brandon Built — Plain English

> **The technical companion to this doc is `docs/architecture/FORK-CHANGES.md`.**
> This file says the same thing without jargon.

---

## The one-line summary

Brandon (with Codex doing the actual typing) built a **prototype for processing supplier invoices automatically**. It's a *pilot* — narrow, deliberately incomplete, demonstrating the spine of the workflow without touching any existing ERPNext functionality.

The name "AP Closed Loop" means the loop goes: **invoice comes in → gets approved → gets paid → marked closed**, all in one tracked flow.

---

## What problem it solves

Today in stock ERPNext, when a supplier invoice arrives, an AP clerk has to:

1. Read the PDF
2. Manually type the supplier, amount, date into a Purchase Invoice
3. Manually match it to a Purchase Order
4. Get a manager to approve
5. Create a Payment Entry
6. Track that it actually closed

That's six+ manual steps per invoice. Brandon's pilot turns it into a tracked, semi-automated pipeline where the system *suggests* answers and the clerk just confirms.

---

## What he actually built — one new "thing"

A single new database table called **`Document Capture`**. Think of it as a "ticket" that follows one invoice from when it arrives until it's paid. Each ticket records every step's evidence:

| Stage | What happens | What gets recorded |
|---|---|---|
| **Upload** | PDF/PNG/JPG gets uploaded | filename, file extension, "is this a format we can handle?" |
| **OCR proposal** | A fake OCR reads the invoice | "I *think* the supplier is X, the total is Y, the date is Z" — proposals only, never authoritative |
| **Review** | AP clerk confirms or corrects | final supplier, total, date, etc. + who reviewed it |
| **Validation** | System checks against existing data | Does this supplier exist in ERPNext? Is there a matching PO/PR? |
| **Promotion** | Creates a real Purchase Invoice | links the capture ticket to the actual PI |
| **Approval** | Auto-approves under $1000, routes to manager above | who decided, when, why |
| **Mock payment** | Creates a fake Payment Entry | clearly labeled `MOCK-PAY-…` so nobody confuses it for a real bank transfer |
| **Closure** | Derived, not set | once the PI is paid in native ERPNext, the ticket reads "closed" |

Every stage can fail gracefully — if a supplier is unknown, the ticket pauses and shows "needs human attention" rather than guessing.

---

## How he built it — six guardrails

Baked into the code AND enforced by tests:

1. **Doesn't reinvent the wheel.** Uses ERPNext's existing **Purchase Invoice** and **Payment Entry**. Doesn't create parallel invoice doctypes.
2. **Doesn't fake bank reconciliation.** Closure means "this invoice was paid via Payment Entry" — *not* "the bank confirmed it." Those are different signals, and Brandon refuses to conflate them.
3. **Doesn't store a custom `closed` flag.** It *derives* closure by looking at the native ERPNext data (`outstanding_amount == 0` + `status == "Paid"`). No new column.
4. **Everything fake is loudly labeled MOCK.** The mock OCR provider is `deterministic_fake_extractor`. The mock payment reference starts with `MOCK-PAY-`. The remarks literally say "Not bank reconciled. No real banking integration." This prevents the prototype from being mistaken for production.
5. **Nothing happens silently.** Bad data, missing fields, ambiguous suppliers → the ticket pauses with a human-readable reason. No guessing, no quiet auto-completion.
6. **Pure API-only.** No buttons in the desk UI yet. Every step is a function you POST to. The desk UI is Phase 2.

---

## What he deliberately did NOT do

- Did **not** touch Purchase Invoice, Payment Entry, Bank Transaction, or GL Entry logic
- Did **not** auto-create suppliers — unknown ones require clerk intervention
- Did **not** wire any UI buttons — every action is a whitelisted API call
- Did **not** integrate a real OCR provider — the "OCR" is a deterministic hash function (same input always yields the same output; makes tests reproducible)
- Did **not** integrate a real payment provider — every Payment Entry it creates is a clearly-labeled mock

---

## The actual code

Two files do all the work:

- **`walking_skeleton.py`** (365 lines) — a pure-Python script that runs the entire flow end-to-end with no UI. Used to *prove* the spine works against ERPNext's Purchase Invoice + Payment Entry before any DocType was built.
- **`document_capture.py`** (1,424 lines) — the real DocType controller with all the state-machine logic, validation, supplier matching, approval routing, and mock payment writeback.

Plus **1,402 lines of tests** covering every state transition and every guardrail.

The only existing ERPNext file Brandon touched was `erpnext/setup/utils.py` — a 2-line readability refactor unrelated to the AP flow.

---

## What you can play with right now

Brandon's code is installed and live in this local site.

- DocType list view (currently empty): `/desk/ap-invoice-capture/view/list`
- DocType definition (the schema): `/desk/doctype/Document Capture`

There's no UI button yet, so you'd create a capture by calling the API directly:

```
POST /api/method/erpnext.accounts.doctype.document_capture.document_capture.create_capture_from_uploaded_file
```

Or just run the test suite to see the whole flow happen end-to-end:

```bash
bench --site erpnext.localhost run-tests --module erpnext.accounts.ap_closed_loop.test_walking_skeleton
bench --site erpnext.localhost run-tests --module erpnext.accounts.doctype.document_capture.test_document_capture
```

---

## TL;DR

One new ticket type (`Document Capture`), one prototype script (`walking_skeleton.py`), very strict guardrails about what it doesn't do, and a 1,400-line test suite proving it actually works. **No UI yet. No real OCR. No real payments. No changes to existing ERPNext accounting.**
