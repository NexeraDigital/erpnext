# Test Plan — Supplier Resolution (3-tier) + Gated Creation

> Clean-room runbook for **spec 05** (`docs/spec/05-supplier-resolution.md`). Executable by a fresh Claude instance with **no prior context** on a clean bench. No external API keys are required — pin the deterministic Fake OCR provider for every case below.

## 1. Feature under test

An AP Invoice Capture's reviewed vendor string is resolved to an ERPNext `Supplier` via a **three-tier resolver**: (1) a deterministic **`AP Supplier Alias`** table (exact / glob / regex patterns → a canonical Supplier), (2) **fuzzy** match against existing Suppliers (rapidfuzz, tunable cutoff), (3) a **gated** `Supplier Master Change Request` (off by default) that, when approved by a second user, creates the Supplier — the resolver **never** auto-creates one. Validation is **stream-aware**: on **Stream I (Invoice)** an unresolved supplier **blocks** the capture; on **Stream R (Receipt)** it is a **soft** flag (validation passes, raw vendor string preserved for the Unmapped-Card-Spend posting). User-visible change: a new `AP Supplier Alias` master, a new `Supplier Master Change Request` doctype, four new audit fields on the capture, and a supplier-resolution section on `AP Closed Loop Settings`.

## 2. Branch / commit

- **Branch:** `russ/migrateToV16` · working tree. Sanity: `erpnext/accounts/doctype/ap_supplier_alias/` and `.../supplier_master_change_request/` exist; `_resolve_supplier` / `queue_supplier_create_request` are defined in `ap_invoice_capture.py`; `get_supplier_resolution_settings` in `ap_closed_loop_settings.py`.

## 3. Environment setup

```bash
bench --site <test-site> migrate   # installs AP Supplier Alias + Supplier Master Change Request,
                                    # the capture audit fields, and the supplier_resolution settings
bench --site <test-site> doctor    # redis + workers up (for the cascade/enqueue path)
```

- frappe v16 + this erpnext fork. **No external keys.** **Pin Fake OCR** so the synthetic invoices yield a deterministic proposal: open **AP Closed Loop Settings** (`/app/ap-closed-loop-settings`) → **OCR Provider = Fake (Deterministic)**. Record the prior value and restore it at the end.
- `rapidfuzz` ships with the app (`pyproject.toml`); no install needed.

## 4. Test data prerequisites

- A System Manager login and **two** users with the **Accounts Manager** role (call them **MgrA** and **MgrB**) for the SoD case; one user with only **Accounts User** (call them **Clerk**).
- Supplier **`Amazon`** (`/app/supplier/new` → Supplier Name `Amazon`, any group, type Company).
- An `AP Supplier Alias` (`/app/ap-supplier-alias/new`): Canonical Supplier `Amazon`, Alias Pattern `AMZN Mktp US*`, Match Type `glob`, Is Active ✓.
- You will create captures by uploading any valid PDF via the AP Invoice Capture form; the Fake provider proposes deterministic fields, which you override in the Confirm Fields dialog.

## 5. Numbered test cases

### TC-1 — Automated suites (pin Fake first)
- **Action:**
  ```bash
  bench --site <test-site> run-tests --module erpnext.accounts.doctype.ap_supplier_alias.test_ap_supplier_alias
  bench --site <test-site> run-tests --module erpnext.accounts.doctype.supplier_master_change_request.test_supplier_master_change_request
  bench --site <test-site> run-tests --module erpnext.accounts.doctype.ap_invoice_capture.test_ap_invoice_capture
  bench --site <test-site> run-tests --module erpnext.accounts.doctype.ap_closed_loop_settings.test_ap_closed_loop_settings
  ```
- **Expected:** `8 OK`, `6 OK`, `Ran 107 tests … OK (skipped=1)`, `20 OK`.
- **Pass/fail:** PASS iff all four green.

### TC-2 — Tier-1 alias resolves (glob)
- **Action:** create a capture, run the Fake OCR, and in **Confirm Fields** set the supplier to `AMZN Mktp US*4Z9` (plus any total/currency). Then run validation (the cascade does this automatically once Confirmed, or click the validate action).
- **Expected (form):** `Supplier Match Status = Alias`, `Matched Supplier = Amazon`, `Supplier Match Tier = Alias`, `Supplier Match Confidence = 100`, `Validation Status = Validated`.
- **DB check:** `bench --site <test-site> mariadb -e "SELECT supplier_match_status, matched_supplier, supplier_match_tier FROM \`tabAP Invoice Capture\` WHERE name='<APIC>'\\G"`
- **Pass/fail:** PASS iff resolved to Amazon via the Alias tier.

### TC-3 — Stream-I unknown vendor BLOCKS (no auto-create)
- **Precondition:** gated creation **off** (default).
- **Action:** create a capture, confirm with supplier `Totally Unknown Vendor <random>` (a name with no Supplier and no alias). Ensure its `Stream = Invoice (I)`. Validate.
- **Expected:** `Supplier Match Status = Unknown`, `Validation Status = Blocked`, `Action Required = 1`, **no** Supplier created (`SELECT COUNT(*) FROM tabSupplier` unchanged), `Supplier Change Request` empty.
- **Pass/fail:** PASS iff Blocked and no Supplier appeared.

### TC-4 — Gated creation: request → approve as a second user (SoD) → Supplier + re-validate
- **Precondition:** **AP Closed Loop Settings** → **Enable Gated Supplier Creation ✓**, **Supplier Auto-create Confidence Threshold = 0.85**.
- **Action (a):** as **Clerk** (or any user), create a capture for an unknown vendor with a **high** supplier confidence (the Fake provider's clear proposal scores ≥ 0.85; for a precise test set `proposed_supplier_confidence = 0.95` via `bench … execute`). Validate. A **Draft** `Supplier Master Change Request` (change_type `Create`) should be created and linked on the capture (`supplier_change_request`); the capture stays **Blocked**.
- **Action (b) — SoD negative:** as the **same user that raised it**, attempt to approve (`/api/method/erpnext.accounts.doctype.supplier_master_change_request.supplier_master_change_request.approve_supplier_master_change_request` with `{"request":"<SMCR>"}`). **Expected:** error *"Segregation of duties: the requester may not approve their own…"*, no Supplier created.
- **Action (c) — approve as MgrB:** log in as **MgrB** (Accounts Manager, ≠ requester) and approve the same request.
- **Expected:** a Supplier is created; the request shows `Workflow State = Posted` and `Created Supplier` set; the originating capture re-validates to `Validation Status = Validated` with `Matched Supplier` set.
- **DB check:** `SELECT workflow_state, created_supplier FROM \`tabSupplier Master Change Request\` WHERE name='<SMCR>'\\G` and the capture's `validation_status`/`matched_supplier`.
- **Pass/fail:** PASS iff (a) a Draft request with no Supplier, (b) SoD blocks self-approval, (c) MgrB's approval creates the Supplier and un-blocks the capture.

### TC-5 — Gated creation OFF or low confidence → no request
- **Action:** with the gate **off**, repeat TC-4(a); then with the gate **on** but a **low** `proposed_supplier_confidence` (e.g. 0.5), repeat.
- **Expected:** in both cases **no** `Supplier Master Change Request` is created and the capture stays Blocked.
- **Pass/fail:** PASS iff no request in either case.

### TC-6 — Stream-R unknown vendor is SOFT (non-blocking)
- **Action:** create a capture, confirm with an unknown vendor string, set its `Stream = Receipt (R)`, validate.
- **Expected:** `Validation Status = Validated` (**not** Blocked); `Supplier Match Status = Unknown`; `Final Supplier` still holds the raw vendor string verbatim; `Validation Result` contains *"Unmapped card spend … preserved as memo"*.
- **Pass/fail:** PASS iff validated, not blocked, and the vendor string is preserved.

### TC-7 — Unmapped-account setting is validated at save (AC-05-23)
- **Action:** in **AP Closed Loop Settings**, set **Unmapped Card Spend Account** to a **group** account (or a non-existent one) and Save.
- **Expected:** Save is rejected with a clear error (group account / does-not-exist). Setting a postable ledger account saves fine.
- **Pass/fail:** PASS iff a group/non-existent account is rejected at save.

## 6. Cleanup / rollback

- Delete any test `Supplier Master Change Request`, `AP Supplier Alias`, `AP Invoice Capture`, and Suppliers created via the UI/API.
- Restore **AP Closed Loop Settings → OCR Provider** to its prior value, set **Enable Gated Supplier Creation** back to off, and clear any test **Unmapped Card Spend Account**.
- Remove the MgrA/MgrB/Clerk test users if created for this run.

## 7. Pass/fail summary template

| Test | Description | Result |
|---|---|---|
| TC-1 | Automated suites (8 / 6 / 107 / 20 OK) | [ ] |
| TC-2 | Tier-1 alias glob resolves to Amazon | [ ] |
| TC-3 | Stream-I unknown BLOCKS, no auto-create | [ ] |
| TC-4 | Gated request → SoD block → 2nd-user approve creates Supplier + re-validates | [ ] |
| TC-5 | Gate off / low confidence → no request | [ ] |
| TC-6 | Stream-R unknown is soft, vendor string preserved | [ ] |
| TC-7 | Unmapped account validated at save | [ ] |

**Overall:** [ ] PASS / [ ] FAIL — notes:
