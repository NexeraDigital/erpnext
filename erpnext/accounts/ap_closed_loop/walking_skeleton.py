# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""AP Closed Loop walking skeleton.

Thinnest repeatable end-to-end flow that exercises the native ERPNext
AP spine before any real OCR / UI / policy work:

    source capture -> deterministic fake extraction -> existing Supplier
    -> native Purchase Invoice (submitted) -> walking-skeleton approval
    -> mock-labeled native Payment Entry (submitted) -> closure evidence.

Guardrails enforced by this module:

* Purchase Invoice is the canonical payable invoice (native doctype).
* Payment Entry is the payment/closure anchor (native doctype).
* No Bank Transaction is created; bank reconciliation is NOT implied.
* No custom "closed" flag is stored. Closure is derived from native
  state: submitted PI + submitted PE + zero outstanding / paid status.
* Provider/payment artifacts are explicitly labeled as MOCK so the
  evidence cannot be mistaken for a real banking integration.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any

import frappe
from frappe.utils import flt, now_datetime, nowdate

MOCK_PROVIDER = "deterministic_fake_extractor"
MOCK_PAYMENT_PROVIDER = "mock_payment_provider"
MOCK_PAYMENT_PREFIX = "MOCK-PAY"
MOCK_PAYMENT_REMARK = (
    "MOCK PAYMENT - AP Closed Loop walking skeleton. "
    "Not bank reconciled. No real banking integration."
)
APPROVAL_SHORTCUT = "walking_skeleton_auto_approve"


@dataclass
class SourceCapture:
    """Stand-in for a real receipt/invoice capture.

    Header-level data only; deliberately not a file upload, since the
    walking skeleton predates real OCR and storage work.
    """

    capture_id: str
    image_uri: str
    captured_at: str
    content_hash: str = ""

    def __post_init__(self) -> None:
        if not self.content_hash:
            seed = f"{self.capture_id}|{self.image_uri}|{self.captured_at}"
            self.content_hash = hashlib.sha256(seed.encode("utf-8")).hexdigest()


@dataclass
class FakeExtraction:
    """Result of deterministic fake header-level extraction."""

    supplier: str
    bill_no: str
    bill_date: str
    item_code: str
    description: str
    qty: float
    rate: float
    currency: str
    provider: str = MOCK_PROVIDER
    is_mock: bool = True

    @property
    def grand_total(self) -> float:
        return flt(self.qty) * flt(self.rate)


@dataclass
class ApprovalOutcome:
    approved: bool
    shortcut: str
    approver: str
    decided_at: str


@dataclass
class MockPaymentInstruction:
    reference: str
    provider: str
    status: str
    amount: float
    issued_at: str
    is_mock: bool = True


@dataclass
class ClosureEvidence:
    source: dict
    extraction: dict
    approval: dict
    mock_payment: dict
    purchase_invoice: str
    payment_entry: str
    pi_status: str
    pi_outstanding_amount: float
    pi_grand_total: float
    pi_docstatus: int
    pe_docstatus: int
    pe_paid_amount: float
    gl_entry_count: int
    gl_entries: list[dict] = field(default_factory=list)
    bank_transaction_count: int = 0
    closed: bool = False
    closure_basis: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def fake_extract(source: SourceCapture, supplier: str) -> FakeExtraction:
    """Deterministic header-level fake extraction.

    The values are derived from the capture's content hash so the same
    source always yields the same extraction, which keeps tests stable
    without needing a real OCR provider.
    """

    seed = int(source.content_hash[:8], 16)
    qty = 1.0
    rate = float(100 + (seed % 50))
    bill_no = f"FAKE-BILL-{source.content_hash[:8].upper()}"
    return FakeExtraction(
        supplier=supplier,
        bill_no=bill_no,
        bill_date=nowdate(),
        item_code="_Test Item",
        description=f"Walking-skeleton line for {source.capture_id}",
        qty=qty,
        rate=rate,
        currency="INR",
    )


def _build_remarks(source: SourceCapture, extraction: FakeExtraction) -> str:
    return (
        "AP Closed Loop walking skeleton.\n"
        f"Source capture_id: {source.capture_id}\n"
        f"Source content_hash: {source.content_hash}\n"
        f"Source uri: {source.image_uri}\n"
        f"Extracted by: {extraction.provider} (MOCK)\n"
        f"Extracted bill_no: {extraction.bill_no}\n"
        f"Mock extraction: {extraction.is_mock}"
    )


def create_purchase_invoice(
    source: SourceCapture,
    extraction: FakeExtraction,
    company: str = "_Test Company",
    cost_center: str = "_Test Cost Center - _TC",
    expense_account: str = "_Test Account Cost for Goods Sold - _TC",
    warehouse: str = "_Test Warehouse - _TC",
) -> Any:
    """Create and submit a native Purchase Invoice for the extraction."""

    pi = frappe.new_doc("Purchase Invoice")
    pi.company = company
    pi.supplier = extraction.supplier
    pi.currency = extraction.currency
    pi.conversion_rate = 1
    pi.posting_date = nowdate()
    pi.bill_no = extraction.bill_no
    pi.bill_date = extraction.bill_date
    pi.remarks = _build_remarks(source, extraction)
    pi.append(
        "items",
        {
            "item_code": extraction.item_code,
            "description": extraction.description,
            "qty": extraction.qty,
            "rate": extraction.rate,
            "warehouse": warehouse,
            "expense_account": expense_account,
            "cost_center": cost_center,
            "conversion_factor": 1.0,
        },
    )
    pi.insert()
    pi.submit()
    return pi


def apply_walking_skeleton_approval(pi: Any, approver: str | None = None) -> ApprovalOutcome:
    """Walking-skeleton approval shortcut.

    No custom approval doctype yet; we record the decision in the PI's
    remarks so it shows up in the canonical document trail and can be
    swapped out for a real workflow later.
    """

    outcome = ApprovalOutcome(
        approved=True,
        shortcut=APPROVAL_SHORTCUT,
        approver=approver or (frappe.session.user if frappe.session else "Administrator"),
        decided_at=str(now_datetime()),
    )
    appended = (
        f"{pi.remarks}\n"
        f"Approval shortcut: {outcome.shortcut} (approved by {outcome.approver} at {outcome.decided_at})"
    )
    frappe.db.set_value("Purchase Invoice", pi.name, "remarks", appended)
    pi.reload()
    return outcome


def create_mock_payment_entry(
    pi: Any,
    paid_from: str = "_Test Bank - _TC",
) -> tuple[Any, MockPaymentInstruction]:
    """Create and submit a mock-labeled Payment Entry for the PI.

    The payment is explicitly labeled MOCK via reference_no and remarks;
    no Bank Transaction is created and no bank reconciliation is implied.
    """

    from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

    pe = get_payment_entry("Purchase Invoice", pi.name, bank_account=paid_from)
    pe.paid_from = paid_from
    pe.reference_no = f"{MOCK_PAYMENT_PREFIX}-{pi.name}"
    pe.reference_date = nowdate()
    pe.custom_remarks = 1
    pe.remarks = MOCK_PAYMENT_REMARK
    pe.insert()
    pe.submit()

    instruction = MockPaymentInstruction(
        reference=pe.reference_no,
        provider=MOCK_PAYMENT_PROVIDER,
        status="settled-mock",
        amount=flt(pe.paid_amount),
        issued_at=str(now_datetime()),
    )
    return pe, instruction


def _gl_entries_for(pi_name: str, pe_name: str) -> list[dict]:
    return frappe.db.get_all(
        "GL Entry",
        filters={
            "voucher_no": ["in", [pi_name, pe_name]],
            "is_cancelled": 0,
        },
        fields=["voucher_type", "voucher_no", "account", "debit", "credit"],
        order_by="voucher_no, account",
    )


def _bank_transaction_count(pi_name: str, pe_name: str) -> int:
    """Confirm no Bank Transaction was created for our voucher pair.

    Returns the count rather than asserting so tests can decide how to
    express the expectation.
    """

    if not frappe.db.exists("DocType", "Bank Transaction"):
        return 0
    return frappe.db.count(
        "Bank Transaction Payments",
        filters={"payment_document": "Payment Entry", "payment_entry": pe_name},
    )


def derive_closure_evidence(
    source: SourceCapture,
    extraction: FakeExtraction,
    approval: ApprovalOutcome,
    instruction: MockPaymentInstruction,
    pi: Any,
    pe: Any,
) -> ClosureEvidence:
    """Build closure evidence purely from native ERPNext state."""

    pi_state = frappe.db.get_value(
        "Purchase Invoice",
        pi.name,
        ["status", "outstanding_amount", "grand_total", "docstatus"],
        as_dict=True,
    )
    pe_state = frappe.db.get_value(
        "Payment Entry",
        pe.name,
        ["docstatus", "paid_amount"],
        as_dict=True,
    )

    gl_entries = _gl_entries_for(pi.name, pe.name)
    bt_count = _bank_transaction_count(pi.name, pe.name)

    closed = (
        pi_state.docstatus == 1
        and pe_state.docstatus == 1
        and flt(pi_state.outstanding_amount) == 0
        and pi_state.status == "Paid"
    )
    closure_basis = (
        "Purchase Invoice submitted (docstatus=1), "
        "Payment Entry submitted (docstatus=1), "
        "PI outstanding_amount=0, PI status='Paid'. "
        "No custom closed flag stored."
    )

    extraction_evidence = asdict(extraction)
    extraction_evidence["grand_total"] = extraction.grand_total
    extraction_evidence["total_amount"] = extraction.grand_total

    return ClosureEvidence(
        source=asdict(source),
        extraction=extraction_evidence,
        approval=asdict(approval),
        mock_payment=asdict(instruction),
        purchase_invoice=pi.name,
        payment_entry=pe.name,
        pi_status=pi_state.status,
        pi_outstanding_amount=flt(pi_state.outstanding_amount),
        pi_grand_total=flt(pi_state.grand_total),
        pi_docstatus=int(pi_state.docstatus),
        pe_docstatus=int(pe_state.docstatus),
        pe_paid_amount=flt(pe_state.paid_amount),
        gl_entry_count=len(gl_entries),
        gl_entries=gl_entries,
        bank_transaction_count=bt_count,
        closed=closed,
        closure_basis=closure_basis,
    )


def run_walking_skeleton(
    source: SourceCapture | None = None,
    supplier: str = "_Test Supplier",
    company: str = "_Test Company",
    paid_from: str = "_Test Bank - _TC",
) -> ClosureEvidence:
    """Run the full deterministic AP closed-loop walking skeleton.

    Returns the structured closure evidence. Intended for use from
    tests and developer-mode shells; not wired to any UI yet.
    """

    if source is None:
        source = SourceCapture(
            capture_id="walking-skeleton-capture-001",
            image_uri="mock://captures/walking-skeleton-001.png",
            captured_at=str(now_datetime()),
        )

    extraction = fake_extract(source, supplier=supplier)
    pi = create_purchase_invoice(source, extraction, company=company)
    approval = apply_walking_skeleton_approval(pi)
    pe, instruction = create_mock_payment_entry(pi, paid_from=paid_from)
    return derive_closure_evidence(source, extraction, approval, instruction, pi, pe)
