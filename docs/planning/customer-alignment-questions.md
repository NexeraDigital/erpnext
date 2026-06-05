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
- **Field needs are framed by cost accounting.** ERPNext follows standard cost-accounting
  paradigms (cost centers, projects, accounts). Most field questions are answered by that
  model — ask what *dimensions* they track, not a laundry list.
- **Immediate priority = get OCR through the system, landing correctly.** Receipt *arrival
  channels* (email / Dropbox / OneDrive / photo) are a "tomorrow" concern — capture now,
  not blocking.

**Planning implication:** if "done" is correct GL landing + month-end reconciliation, then
**receipt-vs-invoice classification matters less than correct posting** — keep the
OCR → post → reconcile loop tight and de-emphasize the classifier / approval machinery.

---

## Questions for the customer

### 1. Blocker — ask first
1. **Ramp's relationship:** Are we *replacing* Ramp, or *ingesting* from it? (Decides whether
   we build capture/OCR, or just match + reconcile Ramp's data.)

### 2. Goal / definition of done
2. Confirm success = a **clean month-end close**. Do you run a formal month-end close today —
   who does it, on what cadence, and what has to tie out for a month to be "closed"?

### 3. Cost accounting (the reframe)
3. What **cost-accounting dimensions** do you track — cost centers, projects, departments /
   classes? *(That determines which fields we must capture and code on each receipt; the rest
   follows ERPNext's standard cost-accounting model — so no field-by-field wishlist needed.)*

### 4. Suppliers
4. Confirm the **supplier list** in the instance you gave us is the seed — is it complete and
   current?
5. For **auto-create + notify**: who gets the notification, and what minimum fields make a
   valid new supplier?

### 5. Bank feed
6. **Plaid or SimpleFIN**, and which **accounts / cards** feed in?

### 6. Scope confirmation
7. OK to **turn off** the heavy invoice machinery for now — multi-step approval / segregation
   of duties, 3-way PO match, and in-ERPNext payment execution (payment is external +
   reconciled)?

### 7. Lower priority (capture now, not blocking)
8. How do receipts **arrive** today (email, Dropbox, OneDrive, phone photo)? — for the later
   automation / monitoring step.

### 8. Logistics
9. First **milestone + timeline**; can we get **~20 real sample receipts** and **feed access**
   (Plaid / SimpleFIN sandbox or live)?

---

## Dropped from the customer ask (now internal)

| Item | Why |
|---|---|
| System of record | Decided — it's ERPNext. |
| Receipt ↔ supplier match key | Our design (deterministic, seeded). |
| Match tolerance / logic (amount / merchant / date) | Our design — the fuzzy reconciliation problem. |
