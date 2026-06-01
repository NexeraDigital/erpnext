# AP Invoice Capture — Workflow Sequence (current state)

> Sequence of the **as-implemented** `AP Invoice Capture` cascade on `russ/migrateToV16`.
> Source of truth: `erpnext/accounts/doctype/ap_invoice_capture/ap_invoice_capture.py`
> (`_determine_next_step` is the routing table) + `erpnext/accounts/ap_closed_loop/`.
> Last derived from code: 2026-05-31.
>
> **Keep `AP-CAPTURE-SEQUENCE.png` in sync.** When the cascade changes, edit the
> Mermaid block below, bump the date above, then regenerate the image with
> `<bench>/env/bin/python docs/architecture/render_sequence_diagram.py` and commit
> both files together (the CLAUDE.md "AP capture cascade / workflow" rule).

The cascade auto-advances through the steps below, **pausing at three human-decision
seams** (OCR review, manual Promote, manager approval). Each hop is enqueued on the
async runner (`frappe.enqueue`, after-commit) in production; in tests it runs
synchronously. A step only fires when its precondition holds, so a `Duplicate` /
`Unsupported` / `Rejected` capture simply stops.

```mermaid
sequenceDiagram
    autonumber
    actor Clerk as AP Clerk
    participant Ch as Intake Channel
    participant Cap as AP Invoice Capture
    participant Q as Async Cascade (RQ)
    participant Dd as Dedupe
    participant OCR as OCR Provider
    participant Set as AP Settings
    actor Mgr as Manager
    participant PI as Purchase Invoice
    participant PE as Payment Entry (mock)

    Note over Clerk,Ch: Intake — manual upload / email-in / mobile / portal-pull(base)
    Clerk->>Ch: upload invoice file
    Ch->>Cap: create_capture_from_file()
    activate Cap
    Cap->>Cap: validate(): stream tag (R/I/Unclassified),<br/>copy File.content_hash, supported-format check
    alt unsupported format
        Cap-->>Clerk: status=Unsupported + action_required — CASCADE STOPS
    end
    Cap->>Q: after_insert → _kick_next_step()
    deactivate Cap

    Note over Q,Dd: Step 0 — pre-extraction dedupe (BEFORE any billable OCR)
    Q->>Dd: run_dedupe_for()
    Dd->>Set: get_dedupe_config()
    Dd->>Dd: exact MD5 content_hash + perceptual pHash<br/>vs last 90 days
    alt exact duplicate
        Dd-->>Clerk: status=Duplicate, duplicate_of=oldest original,<br/>action_required — CASCADE STOPS (no OCR cost)
    else near-duplicate (visual)
        Dd-->>Cap: action_required "suspected near-duplicate"<br/>(stays Pending Review → still OCR'd)
    else clean
        Dd-->>Cap: stamp duplicate_detected_at
    end

    Note over Q,OCR: Step 1 — OCR extraction (+ per-field confidence & line items, spec 04)
    Q->>OCR: run_extraction()
    OCR->>Set: get_ocr_config() (provider / model / thresholds)
    OCR-->>Cap: proposed_* + line_items + field_confidences (per-field scores),<br/>subtotal/tax, status=Proposed
    Note over Cap,Clerk: ⏸ PAUSE — human OCR review

    Clerk->>Cap: confirm_extracted_fields() (+ corrections)
    Cap->>Cap: proposed_* → final_*, ocr_status=Confirmed
    Cap->>Q: _kick_next_step()

    Note over Q,Cap: Step 2 — validation
    Q->>Cap: validate_for_purchase_invoice()
    Cap->>Cap: supplier match + PO/PR reference,<br/>validation_status=Validated
    alt unknown supplier / blocked
        Cap-->>Clerk: validation_status=Blocked + action_required — STOPS
    end
    Note over Cap,Clerk: ⏸ PAUSE — manual Promote (needs company / item defaults)

    Clerk->>Cap: promote_to_purchase_invoice(defaults)
    alt line items present (spec 04, line-aware)
        Cap->>Cap: reconcile sum(lines) vs total
        alt mismatch > 0.01
            Cap-->>Clerk: CapturePromotionError + action_required — STOPS (no PI)
        end
        Cap->>PI: create Purchase Invoice (one item per line)
    else no line items (header-line fallback)
        Cap->>PI: create Purchase Invoice (single header line)
    end
    Cap->>Q: _kick_next_step()

    Note over Q,Set: Step 3 — approval routing
    Q->>Cap: request_approval()
    Cap->>Set: get_auto_post_threshold()
    alt total ≤ threshold
        Cap->>Cap: approval_status=Auto Approved → Ready for Payment
    else total > threshold
        Cap-->>Mgr: approval_status=Pending Manager
        Note over Cap,Mgr: ⏸ PAUSE — manager decision
        Mgr->>Cap: record_manager_decision(approve / reject)
        alt rejected
            Cap-->>Clerk: approval_status=Rejected, payment Blocked — STOPS
        end
    end
    Cap->>Q: _kick_next_step()

    Note over Q,PE: Step 4 — payment (MOCK — no real banking)
    Q->>Cap: issue_mock_payment()
    Cap->>PE: create mock Payment Entry
    PE-->>Cap: payment_lifecycle=Closed
    Cap-->>Clerk: Closed (mock paid)
```

## Notes on current state

- **Stream R vs Stream I:** intake tags a provisional stream (spec 02), but the
  cascade above is the **single linear path** — the divergent Stream-R posting
  (PI `is_paid` / clearing) and bank-feed reconciliation (specs 07 / 13) are
  **not yet built**, so today every capture follows the Promote → Approve → Pay
  path regardless of stream.
- **Three pause seams** are deliberate (no silent posting): OCR review, manual
  Promote, manager approval.
- **Payment is mock** — `issue_mock_payment` writes a Payment Entry tagged as a
  pilot mock; there is no real banking integration.
- **Dedupe perceptual branch** needs `poppler` on the worker; absent it, Step 0
  degrades to the exact-hash check only (the rest of the flow is unchanged).
- **Routing table:** the step preconditions live in `_determine_next_step`
  (`ap_invoice_capture.py`); the whitelisted step functions are
  `run_dedupe_for` / `run_fake_extraction_for` / `validate_for_purchase_invoice_for`
  / `request_approval_for` / `issue_mock_payment_for`.
