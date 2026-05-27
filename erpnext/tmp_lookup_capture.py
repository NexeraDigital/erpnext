import frappe


def run():
    name = "APIC-2026-00004"
    if not frappe.db.exists("AP Invoice Capture", name):
        print(f"{name} does not exist on this site.")
        return
    d = frappe.get_doc("AP Invoice Capture", name)
    print(f"=== {d.name} ===")
    print(f"Source filename:        {d.source_filename}")
    print(f"Source file URL:        {d.source_file_url or '—'}")
    print(f"Status:                 {d.status}")
    print(f"Action required:        {bool(d.action_required)}  ({d.action_required_reason or '—'})")
    print(f"OCR status:             {d.ocr_status}")
    print(f"Supplier match:         {d.supplier_match_status}  -> {d.matched_supplier or '—'}")
    print(f"Validation status:      {d.validation_status}  ({d.validation_message or '—'})")
    print(f"Promotion status:       {d.promotion_status}  -> {d.purchase_invoice or '—'}")
    print(f"Approval status:        {d.approval_status}  ({d.routing_reason or '—'})")
    print(f"Payment readiness:      {d.payment_readiness}")
    print(f"Payment lifecycle:      {d.payment_lifecycle_status}")
    print(f"Payment entry:          {d.payment_entry or '—'}")
