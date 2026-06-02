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

## Update (2026-06-01): sorting each document into the right "bucket" so the books stay correct

Not every AP document is the same kind of thing, and they must be booked **differently**:
- a **bill you haven't paid yet** (you owe a vendor) →  recorded as a normal **Purchase Invoice**, paid later;
- a **receipt for something already paid on a card** (the money's gone) → recorded as a Purchase Invoice **stamped "paid"**, so it books the expense *and* its payment in one go;
- an **employee out-of-pocket expense** → a different kind of record (an Expense Claim).

If you booked all of these the same way, you'd **double-count what you owe** and your books wouldn't balance. So this update adds the step that **looks at each document and routes it to the right bucket** — and, when it can't tell, sends it to a human review queue instead of guessing.

How it decides:
- **Sees a card-payment marker** (like "paid by Visa ****1234" or "PAID") → it's an **already-paid receipt**.
- **The vendor is flagged as an employee** (a group you configure) → it's an **employee reimbursement** → review queue (the employee-expense feature needs an add-on that isn't installed yet, so for now it's handled manually).
- **Otherwise** → a normal **unpaid bill**.
- **A clerk can always override** the decision, and the override wins.

A nice safety check: step 1 of the pipeline already made a quick guess about whether something was a bill or a receipt. This step **double-checks that guess** against the actual contents. If they **disagree** (the quick guess said "bill" but the document clearly shows a card payment), it doesn't just pick one — it **flags it for a human** and records the disagreement, so you can see how often the early guess is wrong and improve it.

For the already-paid receipts, we went with the **simplest, safest accounting method** (recording them as a paid Purchase Invoice) so the vendor still shows up in your "spend by supplier" reports. This is a **provisional** choice we'll confirm with you/the accountant, and it's built so we can switch the method later with a one-line change — nothing is locked in.

As always: **invisible until used** (documents with no markers just behave like before), **no employee-expense automation yet** (routed to manual review), and the already-paid invoices are left as **drafts** for a person to submit. 14 more automated tests, all passing (the main capture suite is now 134).

---

## Update (2026-06-01): auto-filling the accounting codes for routine vendors

Every bill has to be tagged with *where the money comes from* before it can be booked: which **expense account**, which **cost center** (department/project), and what **tax** applies. Doing that by hand for every invoice is the slow part. This update teaches the system to fill those in automatically for vendors you've set up — and, crucially, to **stop and ask a human** when it isn't sure rather than guess.

What it adds:
- **A per-vendor "coding profile."** For a routine vendor you set once: "bills from Acme always go to *Office Supplies expense*, *Marketing cost center*, with *10% VAT*." From then on, the system applies that automatically to each new Acme bill. (It sits *on top of* ERPNext's built-in vendor settings — it doesn't replace them.)
- **Three layers, most-specific wins.** A value you type for this one bill beats the vendor's profile, which beats the company-wide default. So you get sensible defaults but can always override.
- **Cost-center inference that refuses to guess.** The cost center can come from several hints (the vendor's profile, and later the receipt's location or the card used). If the hints **agree**, it's applied. If two hints **disagree**, the system does **not** pick one — it flags the bill to a **Coding Review** queue with the reason ("location says X but card says Y"), so a person decides. No silent wrong-coding.
- **Tax sanity-check.** It compares the tax the AI read off the invoice against what the chosen tax template would compute. If they don't match (beyond rounding), the bill is **flagged** instead of booked with a bad tax number.
- **A catch-all for card receipts.** For an already-paid card receipt with no known vendor, the expense lands in a dedicated "Unmapped Card Spend" account (flagged for later tidy-up) so reconciliation isn't held up.
- **A hard safety rule:** the system will **refuse to re-code an invoice that's already been finalized (submitted)** — coding only ever edits a *draft*.

The headline principle from the plan holds: **"without coding, nothing auto-posts."** There's now a single gate (`is_fully_coded`) that later steps must pass before anything books automatically — it's only green when the expense, the cost center, and the tax are all resolved and unambiguous.

It's **invisible and inert until you use it**: with no vendor profiles set up, bills flow exactly as before. Two new behind-the-scenes record types (the vendor coding profile + its dimensions) and a few settings knobs. 18 more automated tests, all passing (the main capture suite is now 120).

---

## Update (2026-06-01): matching invoices to the right vendor — without polluting the vendor list

When an invoice arrives, the system reads a vendor *name* off it — but that text rarely matches your vendor list exactly. A card statement says `AMZN Mktp US*4Z9`; your books say `Amazon`. Until now the system did one simple check (exact name match) and, failing that, just stopped and asked a human. This update makes that matching far smarter — and adds a **safety gate** so the system can never quietly create junk vendors.

**Three tries to find the right vendor, in order:**
1. **A nickname table.** You teach it once — "anything starting with `AMZN Mktp US` is Amazon" — and from then on it matches automatically. (Patterns can be exact text, wildcards, or, for power users, regular expressions; a typo'd pattern is safely ignored, never crashes anything.)
2. **Fuzzy matching.** If no nickname fits, it compares the invoice's vendor text to your existing vendors and accepts a close-enough match (you set how close). Two equally-close matches? It refuses to guess and flags it.
3. **A gated "create new vendor" request.** Only if the first two fail *and* you've switched this on *and* the AI is confident about the name, it files a **request** to create the vendor — it does **not** create one. A manager reviews and approves it, and — crucially — **the person who raised the request cannot approve their own** (a basic anti-fraud separation-of-duties rule). Approving it creates the vendor, remembers the nickname for next time, and automatically un-blocks the waiting invoice.

   > Creating vendors with no review is a well-known way for bad or duplicate vendor records (and outright fraud) to creep in, so this gate is deliberate. The system **never** auto-creates a vendor on its own — proven by tests that count vendor records before and after every "unknown vendor" path and confirm the count never moves.

**Bills vs. card receipts are treated differently.** For a normal **bill (Invoice)** you haven't paid yet, an unknown vendor is a hard stop — you should never set up a payable to a vendor you can't identify. For an already-paid **card receipt**, the money's already gone, so an unknown vendor is just a soft note: the receipt still goes through, posting to an "Unmapped Card Spend" account with the original vendor text kept as a memo, and someone tidies up the vendor mapping later — it never holds up the bank-reconciliation clock.

There are **two new behind-the-scenes record types** (a vendor-nickname table and the vendor-change-request) and a handful of new knobs on the settings page (how fuzzy is "close enough", whether the create-vendor gate is on, who approves). It's **invisible and inert unless used** — with the gate off (the default) and no nicknames, it behaves exactly like before, just with the smarter fuzzy match added. The actual approval *workflow screen* and a couple of related request types (changing a vendor's bank details, etc.) come in a later step. 36 more automated tests, all passing (the main capture suite is now 107).

---

## Update (2026-06-01): three fraud-and-error catches before a bill gets booked

Before an invoice is allowed through to be paid, this update runs it past **three independent safety checks** — the same three a careful accounts-payable clerk does by hand. If a check fails on a real **bill** (one you'll pay later), the invoice is **held in a review queue** instead of flowing on. On an already-paid **card receipt** (the money's already gone) the checks still run and get **recorded**, but they never hold anything up.

The three checks:

1. **Does it match the purchase order?** ("Three-way match.") If the bill points at a PO, the system compares what was **ordered**, what was actually **received**, and what's being **billed**. Bill for more than you received, or at a higher price than the PO? → flagged. You set how much wiggle-room to allow (default: none — must match exactly). A supervisor can **override** a flag with a typed reason, which is recorded separately so the audit trail stays clean.
2. **Is the amount weird for this vendor?** ("Anomaly check.") The system quietly learns each vendor's recent invoice sizes. A bill that's wildly bigger than normal — say a vendor who's always ~$5,000 suddenly sends $18,400 — gets flagged for a look. If there isn't enough history yet (fewer than 5 past invoices), it just says "not enough history" and never blocks.
3. **Did the vendor's bank details just change?** ("Bank-change check" — an anti-fraud catch.) A classic scam is an email saying "we've changed our bank account, please pay here instead." If a vendor's bank details changed **since the last time you paid them**, the system **blocks the payment** until someone who isn't the requester approves the change. This one even re-checks at the moment of payment, so it can't be slipped past.

How it stays safe and unobtrusive: it **only blocks real bills, never card receipts**; an invoice with no PO simply skips the match (unless you turn on a "PO required" policy); the bank check **does nothing** for a brand-new vendor you've never paid. The vendor "normal size" history is kept in a small behind-the-scenes table that refreshes automatically each night.

One honest limitation: the PO match currently works at the **whole-PO level** (totals), not line-by-line, because the AI doesn't yet tell us exactly which PO line each invoice line maps to — that finer matching comes later. And the bank-change "who's allowed to approve" rule is the **basic** version for now (just "not the same person who asked"); the full treasury-approver rule arrives with the approval-workflow step.

It's **invisible until used** (a bill with no PO, normal amount, and unchanged bank details flows exactly as before) and ships with **22 more automated tests, all passing** (the main capture suite is now 156).

---

## Update (2026-06-01): letting the confident, routine invoices flow through — and stopping only the doubtful ones

The whole point of reading invoices with AI is **throughput**: if every invoice still needs a human, you've gained nothing. This update adds the decision that makes the pipeline scale — it looks at each invoice and asks *"am I confident enough to let this move on by itself?"* If yes, it flows. If anything looks shaky, it stops **that one** invoice (and only that one) in a review queue, with a note saying exactly what was wrong.

It weighs three things together:
1. **Amount** — is it at or under the auto-approve limit you set? (Bigger bills still go to a manager, same as before.)
2. **Confidence** — did the AI read **every** key field (vendor, invoice number, date, total, currency) clearly enough? If even one field was a blurry guess, that's a stop.
3. **Clean checks** — did it pass all the safety checks from the previous update (PO match, amount sanity, bank details)? Any open flag is a stop.

Only when **all three** are good does the invoice move on automatically. Otherwise it lands in a **"Needs Review"** queue, and — this is the useful part — the note names the *specific* problem: *"low confidence on the invoice date"* or *"open flag: three-way match exception."* The clerk fixes that one thing and clicks a button to send it back through; no guessing what was wrong.

A few honest notes:
- **Already-paid card receipts skip all of this** — they were posted and "paid" in one step by an earlier update, so there's nothing to approve; this decision only applies to unpaid bills.
- The amount limit is a **single setting** shared across the whole system, so there's never two different "magic numbers" to keep in sync.
- It **degrades gracefully**: an invoice that never went through AI reading (no confidence scores at all) isn't penalized — it routes on amount and the safety checks, exactly as before.
- The "review queue" feed that records *why* things got stopped (so you can measure how often the AI's first read needs fixing) is wired in as a **hook** here; the actual reporting screen comes in the next update.

**Invisible until it matters**: a clean, confident, under-limit invoice behaves exactly as it always did (auto-approved); only the doubtful ones now stop with a clear reason instead of silently stalling. Ships with **15 more automated tests, all passing** (the main capture suite is now 171).

---

## Update (2026-06-01): a reject button, a paper trail, and measuring *why* invoices need a human

When an invoice can't be auto-processed, a person handles it — but until now there was no clean way to **bounce a bad one back to the vendor**, and no record of **why** invoices keep needing human attention. This update adds both, and turns the review step into a feedback loop that tells you what to fix upstream.

What it adds:
- **A real "reject" action.** A clerk can send a non-finalized invoice back to the vendor with a reason (bad scan, wrong amount, junk). It's marked **Rejected** and drops off the work queue — but it's **not a dead end**: a "reopen" button brings it right back to exactly the stage it was at, with the full reject/reopen history kept for audit. (A rejected invoice can never accidentally slip forward into the books.)
- **A "why" log behind every review action.** Each time someone fixes a field, maps a vendor, or rejects something, the system quietly records one entry tagged with a **root cause** from a fixed list — *extraction miss, unmapped vendor, threshold too tight, wrong stream tag, policy violation, vendor error, missing PO, other*. This is the part that makes the whole pipeline self-improving.
- **A weekly "Top reasons invoices needed a human" report** and a chart, grouped by those root-cause tags. If "threshold too tight" tops the list, you loosen the confidence threshold; if "missing PO" is high, that quantifies whether requiring POs is worth it. It turns gut-feel tuning into a measured decision.

Honest notes:
- **Already-paid card receipts get lighter tracking** — there's no payment to reject, so the approval/rejection reasons don't apply to them.
- The reject here is for invoices **before** they become an official Purchase Invoice; rejecting an invoice that's already been promoted is a separate, later step.
- It records **why** and **how long** a fix took — complementing the existing field-by-field change history (which only records *what* changed).

This is the measurement backbone for "are we automating everything we can?" Ships with **18 more automated tests, all passing** (the main capture suite is now 185, plus a new 4-test module for the event log).

---

## Update (2026-06-02): the person who enters an invoice can't also approve it

A basic anti-fraud rule (segregation of duties): whoever prepared/coded an invoice shouldn't be the one who signs off on paying it. The system *looked* like it enforced this — it checked job title — but it never checked the actual **person**, so a manager could approve an invoice they themselves entered. This update closes that hole: an above-limit approval by the same person who prepared the document is **blocked**, and they're told a different approver is needed. (Rejecting your own is still fine — the risk is self-*approval*.) It also adds the **roles** the workflow needs (AP Clerk, Treasury Approver, Auditor) and tightens the **bank-change** safety check so that lifting a "vendor changed their bank details" block now requires a dedicated **Treasury Approver** — an ordinary AP clerk can't wave it through.

Two honest notes: an admin account is deliberately exempt (the break-glass override, logged), and the *bigger* version of this — putting ERPNext's full built-in approval workflow on every purchase invoice company-wide — is intentionally **deferred** until someone signs off on that company-wide impact. Routine, in-limit invoices still flow through automatically; only the bigger ones and the genuine exceptions stop for a human. Ships with **6 more automated tests** (the main capture suite is now 211).

---

## Update (2026-06-02): pay trusted vendors automatically, everyone else with one click

Paying a bill moves real money, so it's the one place where "stop and let a human press the button" is the *safe* default — but that doesn't mean every payment needs a human forever. This update adds a per-vendor **"Auto-Pay Eligible"** switch: flip it on for a vendor you trust (a utility, a regular SaaS bill), and once their invoice is approved it gets paid **automatically**, no clicks. Every other vendor still pauses after approval for a person to click **Pay**. The idea is to grow the trusted list over time so the routine, in-policy payments flow on their own and a human only touches the new, unusual, or large ones. (Already-paid card receipts skip this entirely — the money already moved.) Payment is still a safe **mock** in this pilot — no real bank rail yet; that's a deliberate later step. Ships with **2 more automated tests** (the main capture suite is now 213).

---

## TL;DR

Two new things. **(1)** One new ticket type (`AP Invoice Capture`), one prototype script (`walking_skeleton.py`), very strict guardrails about what it doesn't do, and a 1,400-line test suite proving it actually works. **(2)** A read-only, permission-respecting, audit-logged doorway (`erpnext/mcp/`) that lets an AI assistant *look up* AP data — five read tools, secure login, full audit trail, off by default. **No UI yet. No real OCR. No real payments. No write access for the AI. No changes to existing ERPNext accounting.**
