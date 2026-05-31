# ERPNext AP Closed-Loop Workflow — v2

> **Subtitle:** From receipt image to fully closed AP transaction — with industry-standard controls
> **Changes from v1:** Adds duplicate detection, supplier resolution, doctype branching, confidence-based routing, GL/tax/cost-center coding, segregation of duties, vendor-master change controls, exception loopback, and bank-feed closure.
> **Changes since Bryan's 2026-05-26 review:** Receipts and invoices are now framed as **two streams from intake**, not one stream that branches at step 6. Step 9 adds an explicit **observability** instrumentation requirement so we can measure whether the system is automating everything that can be automated. A new upstream-control note (PO → estimate/quote/SOW → invoice reconciliation) is called out as the strongest lever for shrinking step 9. Step 10 includes a concrete ERPNext-build sketch. Step 11 is constrained to **invoices only** and explicitly marked secondary.

---

## Two streams from intake (receipt vs. invoice)

Receipts and invoices look similar arriving in the inbox, but the downstream logic differs from the moment they land. The workflow forks at step 1, not step 6 — and the two streams have different SLAs, different control sets, and different downstream doctypes.

**Stream R — Receipts (already paid).** The money has already moved on a card or out of cash. The job is reconciliation, not authorization. Target SLA: **matched against the SimpleFIN bank feed within 72 hours** of intake (worst case — most card receipts post to the feed within 24 hours). No approval routing, no payment execution; just dedupe → extract → code → post as Journal Entry (or PI + Credit-Card-Clearing if vendor-aging visibility is wanted) → bank-feed match.

**Stream I — Invoices (unpaid payable).** The money has not moved yet. The job is *match to a known vendor, create a payable, route for approval, and pay*. If the vendor is unknown, **vendor creation is an in-process step** (gated by reviewer approval — see step 4) before the payable can be created. Steps 9, 10, and 11 are load-bearing on this stream; steps 11–12 (payment + bank-feed closure) close the loop.

Document-type classification (step 6) still exists, but it now serves to **confirm and refine** the stream assignment made at step 1 (e.g., "this `.pdf` from `vendor@stripe.com` is actually a card receipt, not a bill — move it to Stream R") rather than to make the decision from scratch. The benefit of framing the fork at step 1 is that downstream controls only need to fire for the stream that needs them — invoices get the approval + payment + observability load, receipts get the lightweight reconciliation path.

---

## Step-by-Step Walkthrough

**1. Receipt / Invoice Intake (with stream tag)**
The process begins when an invoice or receipt arrives — emailed PDF, scanned paper document, phone-camera photo, or vendor portal pull. The document is logged into ERPNext immediately and attached to a new AP record so the artifact is timestamped and retrievable from the moment it enters the organization. No structured data is required from the vendor at this stage; the system accepts whatever format arrives.

At intake the document is tagged with a **provisional stream** — Stream R (Receipt, already-paid) or Stream I (Invoice, unpaid payable) — using the cheapest signals available: sender domain heuristics, attachment filename (`receipt_*.pdf` vs `invoice_*.pdf`), folder/label routing from the email channel, and the presence of card-receipt patterns in the body (e.g., "PAID", last-4 digits, authorization codes). The provisional tag drives queue priority and the downstream SLA clock: Stream R items start a **72-hour SimpleFIN match countdown** immediately. Step 6 can revise the stream tag if extraction reveals the heuristic was wrong; the revision is logged for tuning.

**2. Pre-Extraction Deduplication**
Before any extraction runs, the document is checked against the last 90 days of intake for duplicates. Two checks run in parallel: an exact file-hash check (catches re-uploads of the same image) and a fuzzy near-duplicate check (catches re-scans of the same receipt). Any hit short-circuits the workflow and surfaces the original record to the operator rather than starting a second extraction. This is the firewall against the most common AP error — paying or booking the same invoice twice.

**3. AI Extraction with Per-Field Confidence**
A narrow AI layer reads the document and extracts structured fields: vendor name, invoice or receipt number, date, line items, subtotal, tax, total, and any visible PO or account reference. The extractor returns a confidence score **per field**, not just per document — extraction systems routinely produce a confident total while hallucinating the vendor, so a single document-level score is not safe to route on. The AI is scoped to extraction only; humans remain in control of validation and decisioning.

**4. Supplier Resolution**
The extracted vendor string is resolved to an ERPNext Supplier record through a three-tier match. First, a deterministic alias table catches known variants (`AMZN Mktp US*4Z9` → `Amazon`). Second, fuzzy matching against existing suppliers handles new variants of known vendors. Third, if no match is found and confidence is high enough, the system queues a "create new supplier" request for reviewer approval — auto-creating suppliers without a gate is a known data-quality hazard and a fraud vector.

**ERPNext reality check:** ERPNext ships the Supplier doctype natively (form UI, quick-add from any linked field, naming series), but it does **not** ship an approval gate on Supplier creation — by default, any user with `Purchase User` permission can create a Supplier directly. The "reviewer approval" gate described above is a control we build on top, not a native feature we enable. Candidate build mechanisms are listed in implementation guide §6.0a; the choice is deferred to the build phase.

For **Stream I** specifically, an unresolved supplier is **a blocking in-process step**, not a post-hoc cleanup: a payable cannot be created against an unknown vendor, so the gated supplier-creation request short-circuits step 5 onward and the invoice waits in the review queue until the supplier is either approved or the document is rejected back to the sender. For **Stream R** (already-paid card receipts), an unresolved supplier is a softer flag — the GL impact already happened on the card, so the JE can post against a generic "Unmapped Card Spend" expense account with the original vendor string preserved as a memo, and supplier mapping happens out-of-band without blocking reconciliation.

**5. GL Coding, Cost Center & Tax Assignment**
The expense account, cost center, and tax treatment are applied. ERPNext's Supplier doctype natively carries a per-Company default payable account via its Party Account child table; default cost center and default expense account are layered on through Custom Fields or a supplier-to-coding mapping table, which drives auto-coding for routine vendors. For organizations with multiple locations or departments, the cost center can be inferred from the location on the receipt, the card last-4 used to pay, or the supplier's assigned cost center; ambiguous signals send the document to the review queue rather than defaulting silently. Tax fields (sales tax, use tax accrual) are populated from the extracted tax line and validated against the supplier's tax profile. Without coding at this step, nothing can auto-post and every document falls to manual review.

**6. Document-Type Classification & Doctype Selection**
The document is classified and routed to the appropriate ERPNext doctype based on the nature of the transaction. This step **confirms or revises** the provisional stream tag from step 1 using the structured extraction (the body said "PAID" but the structured total + due-date pattern says "invoice" — escalate to step 9):

- **Unpaid vendor bill (Stream I)** → `Purchase Invoice` (later paid via `Payment Entry`)
- **Already-paid card or cash receipt (Stream R)** → `Journal Entry` (DR expense, CR card/cash liability)
- **Employee out-of-pocket expense (Stream R-employee)** → `Expense Claim` (later paid via `Payment Entry`)
- **Other / stream-tag conflict** → routed to review for manual classification

Routing everything to a single doctype causes double-counting of liabilities and breaks trial-balance reconciliation. This branch is the heart of correct ERPNext AP automation. The stream-tag-vs-classifier disagreement rate is a tuning signal — high disagreement means the step-1 intake heuristics need improvement (more domain rules, better label routing).

**7. Validation, Anomaly Detection & Three-Way Match (where applicable)**
The system runs the full validation suite: required fields present, totals consistent with line items, vendor active, expense account valid, entity assigned, duplicate check confirmed, vendor bank details unchanged since last payment. An **amount-anomaly check** flags any invoice where the total significantly exceeds this supplier's recent history (default rule: > 3x the rolling 6-month average for the same supplier, or > 2 standard deviations if there's enough history). This catches typo'd amounts, double-billing, and fraudulent invoices that a small AP team would otherwise miss — small AP teams have fewer second-pair-of-eyes, so the rule is more valuable, not less. For unpaid vendor bills with a referenced PO, a three-way match is run against the Purchase Order and Goods Receipt — invoices that don't match the PO within tolerance are flagged. PO-less / two-way matching is acceptable for small environments but is an explicit policy choice, not a default.

**8. Confidence-Based Routing (Auto-Post vs. Review Queue)**
Documents fork based on a combined signal of per-field confidence and validation flags:
- **All fields above the confidence threshold and no validation flags** → auto-submitted as a draft to the appropriate doctype, queued for approval if over threshold.
- **Any field below threshold or any validation flag raised** → routed to the AP review queue with the exception reason surfaced (low vendor confidence, total mismatch, duplicate suspect, unrecognized supplier, etc.).

This routing is what makes the workflow scalable. Without it, every document needs a human, and the throughput benefit of OCR is lost.

**9. AP Review (Exception Handling) — instrumented as a feedback gate**
For items in the review queue, an AP clerk addresses the surfaced exception: correcting a misread field, resolving a supplier ambiguity, completing GL coding, or rejecting the document back to the vendor with a reason. Rejected items are not dead-ends — they re-enter the workflow when corrected, and the rejection trail is preserved for audit. This step is also where vendor-pushback conversations live (missing PO, wrong amount, unclear billing entity).

**Observability requirement.** Step 9 is not just an exception handler — it is the **gate that tells us whether we are automating everything we can automate**. Every clerk action is instrumented and emitted as a structured `AP Review Event` so we can answer two questions on a recurring cadence:

1. *What percentage of step-9 work is the system creating that it shouldn't be?* (i.e., what fraction of exceptions had a fixable upstream root cause — a missing supplier alias, a confidence threshold that was too tight, a misclassified stream tag at step 1?)
2. *What input change would have eliminated this exception?* (added supplier alias, expanded amount-anomaly baseline, opened up the confidence threshold for that supplier, a new email-routing rule, a PO created upstream — see below.)

Each `AP Review Event` captures: original exception reason code, action taken (field corrected / supplier created / rejected / classified-other), field(s) changed, time-to-resolve, the clerk's chosen **root-cause tag** from a fixed vocabulary (`extraction_miss`, `supplier_unmapped`, `confidence_threshold_too_tight`, `stream_mistag`, `policy_violation`, `vendor_error`, `missing_po`, `other`), and any free-text note. A weekly "Top step-9 root causes" report drives the auto-rate dashboard and surfaces the highest-leverage tuning changes.

**Upstream control — the PO loop (theory, not phase-1 scope by default).** The strongest lever for shrinking step 9 is upstream: a **Purchase Order pre-approves the receipt of a future invoice**, with an attached estimate, quote, or scope of work to anchor the agreed amount and scope. When the work is approved, the PO is created; when the invoice arrives, the three-way match (step 7) reconciles invoice against PO and goods receipt *before* the outbound payment is made, and most of the questions a step-9 reviewer would otherwise have to chase are already answered by the PO record. PO-first AP shifts authorization from the back end (clerk-after-the-fact) to the front end (approver-before-the-fact) and is the design Bryan called out as "in theory." Whether to make the PO loop in-scope for v1 is an explicit policy decision per client — for environments where the PO loop is not yet operational, the step-9 instrumentation is what tells us how much friction we would save by adopting it.

**10. Approval Routing with Segregation of Duties — Stream I only**
**Applies only to Stream I (unpaid invoices and employee expense claims).** Stream R receipts skip this step — the money already moved, so there is nothing to authorize. Items in scope are routed to the appropriate approver(s) based on policy — typically driven by amount thresholds, department, cost center, or supplier risk profile. Segregation of duties is enforced: the role that extracted/coded the document cannot also approve it above a defined threshold, and vendor master changes (especially bank-detail changes) follow a separate approval path from invoice approvals. This is the formal authorization gate.

**ERPNext build sketch (full detail in the implementation guide).** Approval is built on ERPNext's native `Workflow` doctype, not custom code. One Workflow record (`AP Document Approval`) applies to `Purchase Invoice` and `Expense Claim` with states `Draft → Pending Review → Pending Approval → Approved → Submitted`. Each transition is a `Workflow Transition` row with an `Allowed Role` and a Python `Condition` (e.g., `doc.grand_total > 5000`). The `Workflow Transition` doctype also exposes an **`allow_self_approval`** field that, by name, should prevent the submitter from also approving — **this is the SoD lever, but the runtime behavior must be verified on our target ERPNext version**, because official documentation does not state the exact rule and there is some history of similar Workflow-layer settings behaving differently across versions. The plan is to verify on the cloned instance and **backstop SoD with a Server Script `validate` hook** that explicitly throws if the approving user equals the submitter on above-threshold transitions, so the control doesn't depend on a single setting. A second Workflow record (`Supplier Bank Change Approval`) routes any change to vendor bank fields through a separate approver. The shape of the answer to "how do you build this in ERPNext?" is unchanged — native `Workflow` doctype + role-based permissions + a thin Server Script for SoD enforcement, not a new app.

**11. Payment Execution — Stream I only, automation is secondary**
**Applies only to Stream I (unpaid invoices and employee expense claims).** For Stream R receipts this step is a no-op (the money already moved on the card; advance directly to step 12).

For invoices, the approved Purchase Invoice triggers a Payment Entry — either via the configured payment rail (ACH, check, card) or a controlled mock execution in pilot environments. Automation of the disbursement leg is **explicitly a phase-2 goal, not phase 1**: whether it is worth automating at all depends on the vendor's accepted payment method and the downstream wiring (does the bank support ACH origination from a Mercury/SimpleFIN-connected account? is there a check-printer integration? does the vendor accept card and is that the cheapest rail?). The phase-1 default is **"approved Purchase Invoice → human triggers Payment Entry → Payment Entry recorded in ERPNext"**, with full automation behind a per-supplier `auto_pay_eligible` flag set off by default. The bank-feed match in step 12 still confirms closure regardless of whether the Payment Entry was triggered automatically or manually.

For employee reimbursements, the Expense Claim is paid out via Payment Entry on the configured cadence — same human-trigger default in phase 1.

**12. Bank-Feed Match & Reconciliation** *(mocked during development)*
The actual money movement is reconciled against the bank feed: card transactions match Journal Entries for already-paid receipts; ACH/check disbursements match Payment Entries for vendor bills and reimbursements. Exact-amount + date-window matching is used as the primary signal; fuzzy auto-matching by party name is known to be unreliable when similar vendor names exist and is treated as a hint, not a clearance. Bank-feed match is the **external** signal that closes the loop — until it lands, the transaction is not truly closed.

**During development this step is mocked** using fixture bank transactions that mirror the shape of real feed data. The matching logic, exception paths, and reconciliation reports are all exercised end-to-end against the mock; only the live feed connection is deferred until pre-cutover, at which point the mock is swapped for the real bank-feed integration with no other workflow changes.

**13. Closure & Audit Trail**
The invoice, payment, GL entries, and bank-transaction match are linked and the transaction is closed. Trial-balance reconciliation runs against the prior period to detect any drift. Frappe's built-in Version doctype captures field-level history across the entire lifecycle, and attachments are retained for 7 years per IRS requirements. From this point the full audit chain — image, extraction, validation, approval, payment, bank-match, posting — is retrievable from a single record.

---

## Key Design Principles

**Two streams from intake.** Receipts (already paid) and invoices (unpaid payable) are tagged separately at step 1 and run different downstream control sets. Receipts target a 72-hour SimpleFIN reconciliation SLA and skip approval + payment execution; invoices carry the approval + payment + observability load. Steps 6, 10, and 11 are stream-aware.

**Branching, not linear.** A single linear flow cannot handle the doctype branch (Purchase Invoice / Journal Entry / Expense Claim) or the confidence-routed branch (auto-post / review queue). The workflow has to fork in at least three places to be correct (stream tag, doctype, confidence).

**Step 9 is a feedback gate, not just an exception handler.** Every clerk action is instrumented so we can measure what percentage of step-9 work is avoidable and what input changes (supplier aliases, threshold tuning, upstream POs) would shrink it. Without this instrumentation the system can't tell us where to invest tuning effort.

**Authorization belongs upstream where possible.** A PO created from an approved estimate/quote/SOW pre-authorizes the invoice, moves three-way matching to step 7, and removes most of the questions step 9 would otherwise have to chase. Whether the PO loop is in scope for v1 is a per-client policy choice; the step-9 instrumentation quantifies the savings if it is adopted.

**Closure comes from outside.** "Mock payment issued" or "payment entry submitted" is internal confirmation. The transaction is not closed until the bank feed confirms the money moved.

**Per-field confidence, not document-level.** LLM extractors are poorly calibrated at document level; per-field scores routed against independent thresholds is the published best practice.

**Human checkpoints with teeth.** Segregation of duties between extractor/poster and approver, separate workflow for vendor-master changes, and explicit reviewer approval before auto-creating suppliers — all guard against the largest AP fraud vectors.

**Exceptions loop, they don't dead-end.** Rejected items, vendor pushbacks, and re-scans must have a path back into the workflow with the original audit trail preserved.

**Async by default, idempotent everywhere.** AI extraction and bank-feed sync are queue-backed (`frappe.enqueue`) — the UI never blocks on an external call. Every operation that creates an ERPNext document (Supplier, Purchase Invoice, Payment Entry, Journal Entry) uses an idempotency key so a retried job cannot double-post and break the trial-balance reconciliation.

---

## Control Summary

| Control | Where it lives | Why it matters |
|---|---|---|
| Stream tag at intake (Receipt vs Invoice) | Step 1 | Routes the two flows correctly from t=0; drives the 72h SimpleFIN SLA on Stream R |
| File-hash + fuzzy dedupe | Step 2 | Prevents double-booking |
| Per-field confidence scoring | Step 3 | Routes safely; catches hallucinations |
| Gated supplier creation (blocking on Stream I) | Step 4 | Prevents master-data pollution and fraud; payable cannot be created without a known vendor |
| Auto-coding from supplier defaults | Step 5 | Enables straight-through processing |
| Doctype branching (stream-aware) | Step 6 | Prevents double-counted liabilities; revises step-1 stream tag if needed |
| Three-way match (where PO exists) | Step 7 | Prevents overpayment and duplicate billing |
| Amount-anomaly check (per-supplier rolling avg) | Step 7 | Catches typo'd amounts, double-billing, fraudulent invoices |
| Vendor bank-detail change workflow | Step 7 | Defends against social-engineering fraud |
| Idempotency keys on all posting operations | Throughout | Prevents duplicate Suppliers / PIs / Payment Entries from retried jobs |
| Async background queue (`frappe.enqueue`) | Steps 3, 12 | Keeps UI responsive during AI extraction and bank-feed sync |
| Confidence-based routing | Step 8 | Scales throughput; isolates exceptions |
| **AP Review Event instrumentation** | Step 9 | Measures avoidable-exception rate and drives the auto-rate tuning loop |
| **PO-as-upstream-control (optional, per-client policy)** | Step 7 + upstream | Pre-authorizes payables; collapses most step-9 questions |
| Segregation of duties via Workflow + `allow_self_approval` off | Step 10 | Internal-control standard; native ERPNext config |
| Bank-feed match for closure | Step 12 | External confirmation of money movement |
| 7-year audit retention | Step 13 | IRS requirement |

---

## Inputs, Control Points, and Outcomes

**Core Inputs:** Invoice/receipt image • Supplier master data • Chart of accounts with per-supplier defaults • PO and goods-receipt records (where applicable) • Bank transaction feed

**Control Points:** Stream tagging at intake (Receipt vs Invoice) • Deduplication • Supplier resolution gate (blocking for Stream I) • Validation rules • Three-way match (where applicable) • Confidence thresholds • Human review with SLA + root-cause instrumentation • Approval routing with SoD (Stream I) • Vendor-master change approval • Bank-feed reconciliation (72h SLA on Stream R) • Optional PO-as-upstream-control

**Final Outcomes:** Correctly classified posting to the right ERPNext doctype • Payment executed and confirmed via bank feed • Trial-balance reconciled • Field-level audit history retained 7 years

---

## Business Value

- **Reduced manual data entry** through OCR + auto-coding for routine vendors
- **Faster AP cycle times** via confidence-based straight-through processing
- **Lower error rate** from deduplication, validation, and three-way matching
- **Stronger fraud controls** via SoD, gated supplier creation, and vendor-master change approval
- **Audit-ready by construction** with field-level version history and 7-year retention
- **Closed-loop traceability** anchored on external bank-feed confirmation, not internal status flags
