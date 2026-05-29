Here's the email-ready version — no commit SHAs, no jargon, scannable. Every bullet is verified-and-defensible (the citation-heavy version lives in `docs/planning/v16-vs-v15-ar-ap-features.md` if anyone challenges a specific item).

---

**For paying your suppliers (Accounts Payable)**

- Ready-to-use print layout for the Accounts Payable report
- Ready-to-use print layout for supplier bills (Purchase Invoices), with an item-image variant
- Ready-to-use print layout for Purchase Orders, with an item-image variant
- Ready-to-use print layout for Request for Quotation with item images
- Per-item sales tax storage on supplier bills was rebuilt — Frappe themselves flagged this as a breaking change. If we build AP automation on v15 today and you upgrade later, parts of it have to be reworked
- New dedicated records for tax withholding (1099-style and foreign-supplier deductions), cleaner than the v15 model
- Improved exchange rate handling on supplier advance payments in foreign currency
- Purchase analytics now roll up across parent and subsidiary companies

**For collecting from your customers (Accounts Receivable)**

- Ready-to-use print layout for the Accounts Receivable report
- Ready-to-use print layout for Sales Orders
- Ready-to-use print layout for Sales Invoices, with an item-image variant
- Ready-to-use print layout for Quotations, with an item-image variant
- Ready-to-use print layout for POS Invoices, with an item-image variant
- Payment Requests can be generated directly from an invoice's payment schedule, with the amount calculated automatically (useful for milestones, deposits, installments)

**For your books in general (both sides)**

- Financial Report Templates — Profit & Loss and Balance Sheet become reusable, formula-driven, and ready for IFRS, US GAAP, or any custom format
- Consolidated Trial Balance Report across all subsidiary companies, with currencies converted automatically
- Ready-to-use print layouts for Trial Balance, Balance Sheet, P&L Statement, Cash Flow Statement, and General Ledger
- "Not applicable" is now a real option for sales tax on a line item (instead of forcing a workaround)
- Journal Entry Templates now support accounting dimensions and party
- Journal Entries can reference Bank Transactions directly for cleaner reconciliation
- Custom financial reports export to Excel with formatting preserved
- A single, consistent remark field across documents (with a custom-remark toggle)
- Deferred revenue / expense report now includes service start and end dates with rolled-up totals

**A one-line closer if you want it:**

> v16 adds 20 ready-to-use print layouts covering AR/AP reports, financial statements, and every standard sales/purchase document — none of which exist on v15.

---

A few notes for tuning before you send:

- The full list is 23 bullets. For an email that's borderline long. If your customer contact is finance-focused, the AP + AR sections (14 bullets) might be enough; you could drop the "books in general" section or move it to an attachment.
- The breaking-change bullet on Purchase Invoice tax (in the AP section) is the one that most directly argues for "don't build on v15 — you'll pay twice." Worth keeping prominent.
- The "1099-style and foreign-supplier deductions" parenthetical assumes a US-context customer. If they're not, swap for whichever withholding regime they actually deal with (TDS in India, etc.) or just drop the parenthetical.

Want me to produce a shorter "executive summary" 5-bullet version that fits in two paragraphs of an email?
