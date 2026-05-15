# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import flt

from erpnext.accounts.ap_closed_loop.walking_skeleton import (
    APPROVAL_SHORTCUT,
    MOCK_PAYMENT_PREFIX,
    MOCK_PAYMENT_PROVIDER,
    MOCK_PAYMENT_REMARK,
    MOCK_PROVIDER,
    SourceCapture,
    fake_extract,
    run_walking_skeleton,
)

EXTRA_TEST_RECORD_DEPENDENCIES = ["Item", "Cost Center"]


class TestAPClosedLoopWalkingSkeleton(IntegrationTestCase):
    def tearDown(self):
        frappe.db.rollback()

    def test_fake_extraction_is_deterministic(self):
        source = SourceCapture(
            capture_id="cap-001",
            image_uri="mock://captures/cap-001.png",
            captured_at="2026-05-13T10:00:00",
        )
        first = fake_extract(source, supplier="_Test Supplier")
        second = fake_extract(source, supplier="_Test Supplier")

        self.assertEqual(first.bill_no, second.bill_no)
        self.assertEqual(first.qty, second.qty)
        self.assertEqual(first.rate, second.rate)
        self.assertTrue(first.is_mock)
        self.assertEqual(first.provider, MOCK_PROVIDER)
        self.assertTrue(first.bill_no.startswith("FAKE-BILL-"))

    def test_walking_skeleton_end_to_end(self):
        bank_transaction_count_before = frappe.db.count("Bank Transaction")

        evidence = run_walking_skeleton(supplier="_Test Supplier")

        # AC-E2E1: full AP happy path is demonstrable.
        self.assertTrue(evidence.purchase_invoice)
        self.assertTrue(evidence.payment_entry)
        self.assertEqual(evidence.pi_docstatus, 1)
        self.assertEqual(evidence.pe_docstatus, 1)

        # AC-R4: ledger / accounting lifecycle is visible via GL entries.
        self.assertGreater(evidence.gl_entry_count, 0)
        voucher_nos = {row["voucher_no"] for row in evidence.gl_entries}
        self.assertIn(evidence.purchase_invoice, voucher_nos)
        self.assertIn(evidence.payment_entry, voucher_nos)

        # AC-R5: no Bank Transaction was created. Bank reconciliation
        # must not be implied by this walking skeleton.
        self.assertEqual(frappe.db.count("Bank Transaction"), bank_transaction_count_before)
        self.assertEqual(evidence.bank_transaction_count, 0)
        bt_rows = frappe.db.get_all(
            "Bank Transaction Payments",
            filters={
                "payment_document": "Payment Entry",
                "payment_entry": evidence.payment_entry,
            },
        )
        self.assertEqual(bt_rows, [])

        # AC-R6 & AC-R3: closure state is unambiguous and derived from
        # native state only -- no custom "closed" flag is stored on the
        # PI or PE doctypes.
        self.assertTrue(evidence.closed)
        self.assertEqual(evidence.pi_status, "Paid")
        self.assertEqual(flt(evidence.pi_outstanding_amount), 0.0)
        self.assertIn("docstatus=1", evidence.closure_basis)
        self.assertIn("No custom closed flag", evidence.closure_basis)

        pi_meta = frappe.get_meta("Purchase Invoice")
        pe_meta = frappe.get_meta("Payment Entry")
        for meta in (pi_meta, pe_meta):
            for df in meta.fields:
                self.assertNotIn(
                    "ap_closed_loop_closed", (df.fieldname or "").lower(),
                    f"Unexpected custom closed flag on {meta.name}: {df.fieldname}",
                )

    def test_walking_skeleton_labels_mock_payment(self):
        evidence = run_walking_skeleton(supplier="_Test Supplier")

        # Mock payment instruction in the evidence must be clearly fake.
        self.assertTrue(evidence.mock_payment["is_mock"])
        self.assertEqual(evidence.mock_payment["provider"], MOCK_PAYMENT_PROVIDER)
        self.assertTrue(
            evidence.mock_payment["reference"].startswith(MOCK_PAYMENT_PREFIX),
            evidence.mock_payment["reference"],
        )

        # The Payment Entry itself carries the mock labeling so that
        # closure evidence can be audited from the canonical doc.
        pe = frappe.get_doc("Payment Entry", evidence.payment_entry)
        self.assertTrue(pe.reference_no.startswith(MOCK_PAYMENT_PREFIX))
        self.assertEqual(pe.remarks, MOCK_PAYMENT_REMARK)
        self.assertIn("MOCK PAYMENT", pe.remarks)

    def test_walking_skeleton_records_source_and_approval_on_pi(self):
        source = SourceCapture(
            capture_id="cap-evidence-001",
            image_uri="mock://captures/cap-evidence-001.png",
            captured_at="2026-05-13T11:00:00",
        )
        evidence = run_walking_skeleton(source=source, supplier="_Test Supplier")

        # Source reference + extraction provider + approval shortcut all
        # show up in the canonical PI remarks, so the evidence is
        # readable from the native document trail, not just the return
        # value of run_walking_skeleton.
        pi = frappe.get_doc("Purchase Invoice", evidence.purchase_invoice)
        self.assertIn(source.capture_id, pi.remarks)
        self.assertIn(source.content_hash, pi.remarks)
        self.assertIn(MOCK_PROVIDER, pi.remarks)
        self.assertIn(APPROVAL_SHORTCUT, pi.remarks)

        # Extraction snapshot is preserved on PI bill_no for traceability.
        self.assertEqual(pi.bill_no, evidence.extraction["bill_no"])
        self.assertEqual(evidence.extraction["total_amount"], evidence.pi_grand_total)
        self.assertEqual(evidence.approval["approved"], True)
        self.assertEqual(evidence.approval["shortcut"], APPROVAL_SHORTCUT)
