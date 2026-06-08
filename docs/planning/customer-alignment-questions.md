# Customer Alignment — Questions to Move Forward

**Date:** 2026-06-05
**Context:** Refined after the Russ ↔ Brandon working session, incorporating the customer's
earlier written feedback (lean, deterministic, receipt-focused; suppliers seeded; payment
external + reconciled via Plaid/SimpleFIN; OCR via BAML/cheap models; "don't over-engineer
the invoice process").

---

## Reframe (decided internally — informs everything below)

- **Definition of done = a clean month-end close / reconciliation.** Success is the ingested
  data — invoice *or* receipt — landing in ERPNext **correctly**, proven by a month-end close.
  We don't care about genre; we care it posts right.
- **System of record = ERPNext.** Settled. Not a customer question.
- **Match logic is ours, not his.** How a receipt matches a bank/card transaction
  (amount / merchant / date window / tolerance) and the receipt↔supplier match key are
  **internal design problems** (the fuzzy part) — do **not** ask the customer.
- **Field needs are framed by cost accounting (internal).** ERPNext follows standard
  cost-accounting paradigms (cost centers, projects, accounts), so we lean on that model for
  which fields a receipt needs rather than asking the customer a field-by-field wishlist.
- **Immediate priority = get OCR through the system, landing correctly.** Receipt *arrival
  channels* (email / Dropbox / OneDrive / photo) are a "tomorrow" concern — capture now,
  not blocking.

**Planning implication:** if "done" is correct GL landing + month-end reconciliation, then
**receipt-vs-invoice classification matters less than correct posting** — keep the
OCR → post → reconcile loop tight and de-emphasize the classifier / approval machinery.

---

## Questions for the customer

### Opening — set the frame (note to self, before the questions)

> **Open with this.** Acknowledge up front that we **probably over-engineered the plan** —
> Bryan's feedback this morning was genuinely helpful, and we've re-scoped around it. The point
> of this call is to **align to the process vision *he* has**, not to defend what we built. Lead
> with that; it sets the tone for everything below.

### Version upgrade — confirm first
1. **Version upgrade:** we **held off upgrading your ERPNext instance pending your
   confirmation** — can we proceed, and when's a good maintenance window? (The pilot work
   targets v16.)

### Blocker — ask first
2. **Ramp's relationship:** Are we *replacing* Ramp, or *ingesting* from it? (Decides whether
   we build capture/OCR, or just match + reconcile Ramp's data.)

### Intake source (capture now)
3. How do receipts **arrive** today (email, Dropbox, OneDrive, phone photo)? — for the later
   automation / monitoring step.
4. Are **all receipts electronic** (email / PDF / digital), or are there **paper** receipts that
   need scanning or photographing? Roughly what share is physical?
5. Could **WellyBox** be the single intake source for receipts *and* invoices? You liked how it
   pulls inline-body receipts → PDF → OCR → vendor straight from the inbox. Caveats to weigh: it
   stops at the **document layer** — no bank feed, and no *native* ERPNext integration that we
   know of (worth confirming), so we'd still need our own webhook/BAML step to land records and
   create the Purchase Invoice. It's also a **proprietary SaaS** that cuts against the
   open-source goal (and routes financial documents through a third party — sharper once PHI is
   in scope). So: standardise intake on WellyBox, or build the open-source equivalent (a
   PrimitiveMail-style email endpoint feeding our own BAML parser)?

### Scope confirmation
6. OK to **turn off** the heavy invoice machinery for now — multi-step approval / segregation
   of duties, 3-way PO match, and in-ERPNext payment execution (payment is external +
   reconciled)?

### PO workflow & pre-approval

> **Surface the contradiction, don't bury it.** Q6 proposes turning *off* 3-way PO matching —
> but on 2026-05-26 Bryan described wanting **POs with an attached estimate / quote / SOW to
> pre-approve invoices**. Those two conflict; resolve it explicitly rather than assuming PO is off.

7. **Is PO creation in scope now, or is no-PO / two-way match acceptable for the pilot?** You
   described PO-based pre-approval — the opposite of turning PO matching off — so we don't want
   to assume. And **what do you do today**: do you raise POs at all, and in what system?
8. **Approval rule:** should an invoice auto-approve when a matching **estimate / quote / SOW**
   exists (and hold for review when none does)? What's the rule — and any amount threshold
   above which a human still signs off regardless?
9. **Where do the estimate / quote / SOW documents live today** (email, a drive folder, a
   tool), and how would we get them into the system to match an invoice against?

### Suppliers
10. Confirm the **supplier list** in the instance you gave us is the seed — is it complete and
    current?
11. For **auto-create + notify**: who gets the notification, and what minimum fields make a
    valid new supplier?

### Deterministic supplier matching (sender-address seed)
12. Can you provide the **sender email address / domain per supplier** (e.g. Amazon always
    emails from the same address)? That lets us seed a deterministic alias table
    (**sender-domain → Supplier**), so routine receipts match with **zero AI / semantic
    parsing** — the determinism you asked for.
13. **Receipts that don't arrive by email** (phone photos, paper, in-app / portal downloads)
    have no sender domain to key on — how common are those, and how should we match them to a
    supplier (read the merchant name off the document, a manual pick, a fallback alias)?

### GL coding & metadata
14. To **post** each invoice/receipt, it needs **GL coding + metadata** beyond what's printed on
    the document — **expense account, cost center, tax treatment**, item/category (and project /
    payment terms where relevant). Where should each come from: a **per-supplier default** we set
    once, a **rule** (by vendor or category), or read off the **document**? And which fields are
    **mandatory** for your books vs. nice-to-have?

### Bank feed
15. **Plaid or SimpleFIN**, and which **accounts / cards** feed in?

### Goal / definition of done
16. Confirm success = a **clean month-end close**. Do you run a formal month-end close today —
    who does it, on what cadence, and what has to tie out for a month to be "closed"?

### AI assistant (chat + MCP)
17. We've added **AI chat + an MCP layer** to ERPNext — today it's **read-only** (the AI can
    *look up* AP data and answer questions, with permissions + an audit trail). Do you want it to
    stay **informational only**, or also **take actions** on your behalf? If actions: which ones —
    e.g. create / code a draft invoice, match a receipt to a transaction, flag or approve, post,
    notify a vendor? (Decides how much write access + guardrails we build.)

### Logistics
18. First **milestone + timeline**; can we get **~20 real sample receipts** and **feed access**
    (Plaid / SimpleFIN sandbox or live)?

---

## Dropped from the customer ask (now internal)

| Item | Why |
|---|---|
| System of record | Decided — it's ERPNext. |
| Cost-accounting *dimensions* wishlist | We don't ask a field-by-field list — but the **GL-coding + metadata source** (and which fields are mandatory) is asked in the GL coding section above. |
| Receipt ↔ supplier match *logic* | Our design (deterministic alias resolver). The seed *data* — sender-domain per supplier — is now asked above. |
| Match tolerance / logic (amount / merchant / date) | Our design — the fuzzy reconciliation problem. |
