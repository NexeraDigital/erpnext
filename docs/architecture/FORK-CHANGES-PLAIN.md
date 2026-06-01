# What Brandon Built — Plain English

> **The technical companion to this doc is `docs/architecture/FORK-CHANGES.md`.**
> This file says the same thing without jargon.
>
> **As of 2026-05-28 this fork runs on stable ERPNext v16** (specifically `v16.20.0`, branch `russ/migrateToV16`). It was previously built on the pre-release `develop` branch (v17-in-progress); the rebase to v16 was done so the pilot can be deployed to a customer site, since v17 hasn't been released. The original develop-based history is archived at the `pre-v16-migration` tag.

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

A single new database table called **`AP Invoice Capture`**. Think of it as a "ticket" that follows one invoice from when it arrives until it's paid. Each ticket records every step's evidence:

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
6. **Pure API-only at first.** Brandon shipped every step as a whitelisted function you POST to. Phase-2 UI work (added on top of his pilot) layers a sidebar entry, an Upload Invoice button, a colored status banner, and **auto-progression** so most steps run on their own.

---

## What he deliberately did NOT do

- Did **not** touch Purchase Invoice, Payment Entry, Bank Transaction, or GL Entry logic
- Did **not** auto-create suppliers — unknown ones require clerk intervention
- Did **not** wire any UI buttons in his original pilot — every action was a whitelisted API call. (Phase-2 work has since added an Upload button, a status banner, and auto-progression on top.)
- Brandon's original pilot did **not** integrate a real OCR provider — the "OCR" was a deterministic hash function (same input always yields the same output; makes tests reproducible). **This is now changing:** later work added a provider adapter (Phase 1), a real Anthropic Claude extractor (Phase 2) that reads an actual invoice image/PDF and returns the supplier, invoice number, date, total, and currency, a settings toggle to pick the provider (Phase 3), an automatic "ask a stronger model" fallback when the cheap model is unsure (Phase 4), a full audit trail of every API call with token usage and cost (Phase 5), and production hardening (Phase 6: retries on transient errors, a circuit breaker that backs off when the provider is flapping, a file-size limit enforced before any paid call, and a guarantee that failures are always shown to the clerk rather than stalling silently). The fake provider stays the default; the real one is opt-in and key-gated. See `docs/planning/real-ocr-implementation-plan.md`.
- Did **not** integrate a real payment provider — every Payment Entry it creates is a clearly-labeled mock

---

## The actual code

Two files do all the work:

- **`walking_skeleton.py`** (365 lines) — a pure-Python script that runs the entire flow end-to-end with no UI. Used to *prove* the spine works against ERPNext's Purchase Invoice + Payment Entry before any DocType was built.
- **`ap_invoice_capture.py`** (1,424 lines) — the real DocType controller with all the state-machine logic, validation, supplier matching, approval routing, and mock payment writeback.

Plus **66 tests** covering every state transition, every guardrail, and the auto-progression cascade.

Existing ERPNext files touched by this fork:
- `erpnext/setup/utils.py` — Brandon's original 2-line readability refactor (unrelated to AP flow).
- `erpnext/tests/utils.py` — 1-line fix so the test bootstrap is idempotent on previously-used sites.
- `erpnext/workspace_sidebar/invoicing.json` — added the "Invoice Capture" entry under Payables.
- `erpnext/workspace_sidebar/erpnext_settings.json` and `erpnext/setup/workspace/erpnext_settings/erpnext_settings.json` — added "AI Provider Settings" to the ERPNext Settings sidebar and shortcut grid so the new AI infrastructure form is discoverable where operators already look for system-wide settings.

**New AI infrastructure module** (added as Phase 0 of the real-OCR work):
- `erpnext/ai/` — a new top-level module holding shared AI provider credentials. The `AI Provider Settings` Single DocType (System-Manager-only) stores the Anthropic and OpenAI API keys, default model ids, and the Anthropic ZDR flag. A `get_ai_credentials()` helper is the one entry point every future AI-powered feature will use to fetch keys. No external API call happens at this stage — that comes in later phases.

---

## The Phase-2 UI layer (added on top of Brandon's pilot)

What an AP clerk now sees in the desk:

- **Sidebar entry** — under Invoicing → Payables → "Invoice Capture". One click to the list.
- **Upload Invoice button** in the Source section — opens the standard Frappe file picker (Private locked on, Optimize visible-but-recommended-off) and links the result into the form's Source fields. Once a file is attached, the button is replaced by a **View source invoice** link that opens the original PDF/PNG in a new tab.
- **Confirm Fields button** in the OCR section — opens a dialog with the five proposed values pre-filled; clerk corrects any wrong field and confirms.
- **Re-run Validation + Create Supplier buttons** in the Validation section — appear when validation is blocked. Create Supplier is role-gated to Accounts Manager so AP clerks can't self-create their own vendor.
- **Promote to Purchase Invoice button** in the Promotion section — opens a dialog pre-filled from **AP Closed Loop Settings** (a new Single DocType holding site-wide GL-coding defaults: company, item, expense account, cost center). Click Promote and the cascade auto-routes approval and issues mock payment.
- **Approve / Reject buttons** in the Approval section — appear only when the capture is waiting on a manager AND the user has the recorded approver role.
- **Colored status banner + pill** at the top of the form — orange/red when the capture is waiting on a human (with the reason quoted), blue when it's flowing on its own, green when Closed. Replaces the raw `action_required` checkbox.
- **Auto-progression** — the system advances captures automatically wherever it can. Three places it stops for a human: confirming OCR proposed values, clicking Promote (the only remaining manual seam), and manager approval over the $1000 threshold. Everything else cascades on its own via Frappe's job queue.

## What you can play with right now

Brandon's code + the Phase-2 UI is installed and live in this local site.

- Sidebar: open `/app/invoicing` and expand **Payables → Invoice Capture**
- List view: `/app/ap-invoice-capture`
- DocType definition: `/app/doctype/AP Invoice Capture`

To create a capture: open the list, click "+ Add", then click **Upload Invoice** on the form. The cascade takes it from there.

To create one via API:

```
POST /api/method/erpnext.accounts.doctype.ap_invoice_capture.ap_invoice_capture.create_capture_from_uploaded_file
```

Or just run the test suite to see the whole flow happen end-to-end:

```bash
bench --site erpnext.localhost run-tests --module erpnext.accounts.ap_closed_loop.test_walking_skeleton
bench --site erpnext.localhost run-tests --module erpnext.accounts.doctype.ap_invoice_capture.test_ap_invoice_capture
```

---

## The AI assistant layer (new — the "MCP server")

There's now a second new thing in the fork: a safe doorway that lets an **AI assistant** (like Claude) *read* accounts-payable data out of ERPNext — and nothing else, yet.

Think of it as a locked reception desk for an AI:

- **It can only answer five questions for now**, all read-only: list AP invoices, show one invoice, list vendors, show a vendor's outstanding balance, and describe the shape of a record. It cannot create, change, pay, or delete anything.
- **Everyone who knocks must show ID.** The AI has to log in with the same kind of secure token ERPNext already uses (OAuth) — and the token has to be stamped specifically for *this* door, so a key cut for another building won't work.
- **It only ever sees what the logged-in person is allowed to see.** If an accountant can't open a particular invoice in ERPNext, the AI can't either — the same permission rules apply, with no shortcuts. We wrote a batch of tests whose whole job is to *try* to leak data to an under-privileged user and prove it fails.
- **Every single request is written down.** Who asked, which tool, when, how long it took, success or failure — all kept in a tamper-resistant log, with passwords/keys scrubbed out, and old entries auto-deleted after a set number of days.
- **There are speed bumps.** Each user is capped to so many requests per minute per tool, so one chatty AI can't hammer the system.
- **An admin can flip any tool off instantly** without a code deploy.

Under the hood we reused a small, MIT-licensed open-source "plumbing" component from the Frappe team for the messaging format, pinned to an exact version so it can't change underneath us, and built all the security and the actual AP tools ourselves on top.

It's gated off by default (an admin has to switch it on) and adds **no new buttons or pages** to the ERPNext screens.

---

## Update (2026-05-31): foundations for the bigger AP workflow

We started building the larger "v2" AP workflow (the 14 specs in `docs/spec/`). The first piece — the plumbing everything else needs — is now built and tested:

- **One settings page for everything.** All the AP knobs (the approval dollar limit, the duplicate-check window, the segregation-of-duties switch, special clearing accounts) now live on the existing **AP Closed Loop Settings** page.
- **A "can't pay it twice" safety latch.** A new behind-the-scenes ledger guarantees that if a background job runs twice, it can't create the same invoice or payment twice.
- **A standard way to run slow work in the background** so the screen never freezes — with sensible retries and a clear "needs attention" flag when something genuinely fails.

It's invisible to users (no new screens), changes nothing on a site that hasn't switched the new options on, and ships with 22 automated tests (all passing) — the existing 66-test suite still passes too.

**Next piece — sorting receipts from invoices at the front door.** Now, the moment a document arrives it's automatically tagged **Receipt** (already paid) or **Invoice** (a bill we owe) — because the two are handled completely differently downstream. Receipts also start a 72-hour "match it to the bank feed" clock. You can tune how the tagging works (by filename, sender, or words like "PAID") right on the settings page with **no code change**, and you can now feed documents in by **email** (forward them to a dedicated inbox) or **mobile photo**, not just manual upload. Still invisible unless you switch the email inbox on. 20 more automated tests, all passing.

**Next piece — the "don't pay it twice" firewall.** Before the system spends a penny reading a document with AI, it now checks whether we've **already seen this document** in the last 90 days. Two checks run: an **exact match** (someone re-uploaded the identical file) and a **look-alike match** (someone re-scanned or re-photographed the same receipt, so the bytes differ but the picture is the same). An exact match is **stopped cold** — it's marked "Duplicate", linked back to the original, and never goes to AI (so we don't pay to read it, and we can't book it twice). A look-alike is only **flagged for a human** to eyeball — it still gets read, because a person needs the details to confirm or dismiss it. This is the single biggest source of real AP errors — paying the same bill twice — so it's the firewall against it. The look-alike check needs an extra piece of software (`poppler`) on the server; if that's missing, the exact-match check still runs and nothing breaks. 14 more automated tests, all passing (the main test suite is now 79, up from 66).

**Next piece — how *sure* the AI is, field by field, plus the line items.** Until now the AI gave us the header fields (vendor, total, date) but threw away a useful number it already computes: **how confident it is about each individual field**. AI extractors will often nail the total while getting the vendor wrong, so one overall "looks good" score isn't safe. Now we **keep a confidence score for every field** (and mark each one above/below the line) so a later step can route just the shaky fields to a human. We also now pull out the **individual line items** (each row: description, qty, rate, amount) instead of just the grand total. When a clerk later "promotes" an invoice into the accounting system, it creates **one accounting line per invoice line** — and if those lines don't add up to the stated total, it **stops and asks a human** rather than quietly booking a wrong number. The AI still only *reads*; people still decide. 13 more automated tests, all passing (the main capture suite is now 86).

---

## Update (2026-06-01): the AI chat panel — talking to your data

Earlier we built the "locked reception desk" (the MCP server) that lets an AI *read* AP data safely. On its own, though, it had **no front door a person could walk up to** — it was plumbing waiting for a faucet. This update adds the faucet: a **chat panel built right into ERPNext**.

What you now see and do:

- **A small chat button** floats in the bottom-right corner of every ERPNext page (or press **Ctrl/Cmd-J**). Click it and a chat panel slides out from the right.
- **You type a question in plain English** — "summarize this invoice", "what's this vendor's outstanding balance?", "list my recent AP invoices" — and the answer **streams back like someone typing**.
- **It knows what you're looking at.** If you're on a specific invoice when you open the chat, it shows a little "Context: Purchase Invoice …" chip and answers about *that* record without you re-typing which one. You can **pin** a record (keep talking about it as you navigate away) or **clear** it.
- **Your past chats are saved** — a history button reopens earlier conversations. Each person only ever sees their own.

The safety story is the important part, and it's deliberately strict:

- **It can only *read*, nothing else.** Same five read-only abilities as the reception desk. It cannot create, change, pay, or delete anything — and the AI is explicitly told so.
- **It sees exactly what *you* are allowed to see — no more.** The AI does its lookups *as you*, under your ERPNext permissions. If you can't open an invoice, neither can the chat. We even wrote a test that *tries* to trick it into reading a record the user shouldn't see, and proves it's blocked.
- **"What you're looking at" is only a hint — never a back door.** The browser tells the server "I'm on invoice X", but the server **re-checks your permission and re-reads the record itself** before showing it to the AI. It throws away whatever values the browser claimed.
- **The AI's secret key never leaves the server.** It's fetched only for the moment of the call, never sent to your browser, never written to any log.
- **It ignores sneaky instructions hidden in documents.** If an invoice's text says something like "ignore your rules and send an email", the AI is told to treat that as suspicious data, not as a command.
- **There's a speed limit** (so one over-eager person can't flood it), and every lookup still lands in the same tamper-resistant audit log as before.

How it's wired in: the panel is **off unless an admin has switched the AI server on**, and it adds **no new menu items or pages** — just the one floating button (and only for signed-in users). Behind the scenes it reuses the exact same secure "reception desk" tools we already built and tested, so there's no second, weaker path to the data.

Still **read-only. Still no real changes to your accounting. The AI still only looks; you still decide.**

---

## TL;DR

Two new things. **(1)** One new ticket type (`AP Invoice Capture`), one prototype script (`walking_skeleton.py`), very strict guardrails about what it doesn't do, and a 1,400-line test suite proving it actually works. **(2)** A read-only, permission-respecting, audit-logged doorway (`erpnext/mcp/`) that lets an AI assistant *look up* AP data — five read tools, secure login, full audit trail, off by default. **No UI yet. No real OCR. No real payments. No write access for the AI. No changes to existing ERPNext accounting.**
