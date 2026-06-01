# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""Tests for spec 02 — intake stream tagging + email/mobile adapters.

Kept as a dedicated module (rather than extending the capture suite) so the
stream tests stay isolated from that suite's live-OCR-provider coupling; every
test here sets ``skip_ap_auto_progress`` so no cascade / OCR fires.
"""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, get_datetime, now_datetime

from erpnext.accounts.doctype.ap_invoice_capture.ap_invoice_capture import (
    INTAKE_EMAIL_INBOUND,
    INTAKE_MOBILE_UPLOAD,
    STREAM_INVOICE,
    STREAM_RECEIPT,
    STREAM_UNCLASSIFIED,
    classify_stream_at_intake,
    create_capture_from_email,
    create_capture_from_file,
    create_capture_from_uploaded_file,
    handle_inbound_ap_communication,
)

SETTINGS = "AP Closed Loop Settings"

# Priority-ordered injected rules (mirror the seed set) for pure classifier tests.
RULES = [
    {"priority": 10, "signal": "filename", "pattern": "receipt_*", "assign_stream": "Receipt (R)"},
    {"priority": 20, "signal": "filename", "pattern": "invoice_*", "assign_stream": "Invoice (I)"},
    {"priority": 30, "signal": "sender_domain", "pattern": "stripe.com", "assign_stream": "Receipt (R)"},
    {"priority": 40, "signal": "body", "pattern": "PAID", "assign_stream": "Receipt (R)"},
]


def _make_pdf_bytes() -> bytes:
    """A real (valid) minimal one-page PDF — frappe parses PDF File content on
    insert, so fake bytes raise pypdf errors."""

    from io import BytesIO

    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


_PDF_BYTES = _make_pdf_bytes()


class TestStreamClassifier(IntegrationTestCase):
    """The pure classifier — rules injected, no DB."""

    def tearDown(self):
        frappe.db.rollback()

    # AC-02-1
    def test_filename_receipt(self):
        self.assertEqual(
            classify_stream_at_intake("receipt_2026.pdf", None, None, None, rules=RULES),
            ("Receipt (R)", "filename:receipt_*"),
        )

    def test_filename_invoice(self):
        self.assertEqual(
            classify_stream_at_intake("invoice_88.pdf", None, None, None, rules=RULES),
            ("Invoice (I)", "filename:invoice_*"),
        )

    # AC-02-2 (body)
    def test_body_paid(self):
        stream, source = classify_stream_at_intake(
            "scan001.pdf", None, None, "Payment PAID. Card ending 4242. Auth 99X.", rules=RULES
        )
        self.assertEqual(stream, "Receipt (R)")
        self.assertEqual(source, "body:PAID")

    # AC-02-3 (sender)
    def test_sender_domain(self):
        stream, source = classify_stream_at_intake(
            "scan.pdf", "receipts.stripe.com", None, None, rules=RULES
        )
        self.assertEqual(stream, "Receipt (R)")
        self.assertEqual(source, "sender_domain")

    # AC-02-4 (fallthrough)
    def test_no_match_unclassified(self):
        self.assertEqual(
            classify_stream_at_intake("statement.pdf", "acme.com", None, "regular bill", rules=RULES),
            ("Unclassified", "default"),
        )

    # AC-02-6 (no inputs — must not raise)
    def test_none_inputs_do_not_raise(self):
        self.assertEqual(
            classify_stream_at_intake(None, None, None, None, rules=RULES),
            ("Unclassified", "default"),
        )

    # AC-02-5 (precedence — lower priority number wins; deterministic)
    def test_precedence_filename_beats_body(self):
        stream, source = classify_stream_at_intake(
            "invoice_88.pdf", None, None, "now PAID thanks", rules=RULES
        )
        self.assertEqual(stream, "Invoice (I)")
        self.assertEqual(source, "filename:invoice_*")

    def test_unknown_signal_is_skipped_not_raised(self):
        bad = [{"priority": 1, "signal": "nonsense", "pattern": "x", "assign_stream": "Receipt (R)"}]
        self.assertEqual(
            classify_stream_at_intake("x", None, None, None, rules=bad),
            ("Unclassified", "default"),
        )


class TestStreamTaggingCapture(IntegrationTestCase):
    def setUp(self):
        frappe.flags.skip_ap_auto_progress = True
        frappe.db.set_single_value(SETTINGS, "ap_intake_email_account", None)  # email intake OFF
        self._make_rules(RULES)

    def tearDown(self):
        frappe.flags.skip_ap_auto_progress = False
        frappe.db.rollback()

    def _make_rules(self, rules):
        frappe.db.delete("AP Stream Rule", {"parent": SETTINGS})
        for i, r in enumerate(rules, start=1):
            frappe.get_doc(
                {
                    "doctype": "AP Stream Rule",
                    "parent": SETTINGS,
                    "parenttype": SETTINGS,
                    "parentfield": "stream_rules",
                    "idx": i,
                    "enabled": 1,
                    **r,
                }
            ).insert(ignore_permissions=True)

    def _capture(self, filename, **kw):
        return create_capture_from_file(
            file_url=f"/private/files/{filename}", file_name=filename, **kw
        )

    def _make_comm(self, subject="Receipt", content="PAID", sender="receipts@stripe.com",
                   sent_or_received="Received", communication_date=None):
        return frappe.get_doc(
            {
                "doctype": "Communication",
                "communication_type": "Communication",
                "communication_medium": "Email",
                "sent_or_received": sent_or_received,
                "subject": subject,
                "content": content,
                "sender": sender,
                "communication_date": communication_date or get_datetime("2026-03-01 10:00:00"),
            }
        ).insert(ignore_permissions=True)

    def _attach(self, comm, file_name, content=None):
        return frappe.get_doc(
            {
                "doctype": "File",
                "file_name": file_name,
                "content": content if content is not None else _PDF_BYTES,
                "attached_to_doctype": "Communication",
                "attached_to_name": comm.name,
                "is_private": 1,
            }
        ).insert(ignore_permissions=True)

    # AC-02-1 (full insert: stream + source + sla)
    def test_receipt_capture_sets_stream_and_sla(self):
        cap = self._capture("receipt_jan.pdf")
        self.assertEqual(cap.stream, STREAM_RECEIPT)
        self.assertEqual(cap.stream_provisional_source, "filename:receipt_*")
        self.assertIsNotNone(cap.sla_due_at)
        self.assertEqual(
            get_datetime(cap.sla_due_at), get_datetime(add_to_date(cap.received_at, hours=72))
        )

    # AC-02-7 (SLA gating)
    def test_sla_null_for_invoice_and_unclassified(self):
        inv = self._capture("invoice_99.pdf")
        self.assertEqual(inv.stream, STREAM_INVOICE)
        self.assertIsNone(inv.sla_due_at)
        unc = self._capture("statement_q1.pdf")
        self.assertEqual(unc.stream, STREAM_UNCLASSIFIED)
        self.assertIsNone(unc.sla_due_at)

    # AC-02-8 (tag idempotency + sla clears on revision)
    def test_tag_idempotent_and_sla_clears_on_revision(self):
        cap = self._capture("receipt_feb.pdf")
        self.assertEqual(cap.stream, STREAM_RECEIPT)
        self.assertIsNotNone(cap.sla_due_at)
        cap.stream = STREAM_INVOICE  # simulate a Step-6 revision R -> I
        cap.stream_revised_from = STREAM_RECEIPT
        cap.save(ignore_permissions=True)
        cap.reload()
        self.assertEqual(cap.stream, STREAM_INVOICE)  # NOT re-derived back to R
        self.assertIsNone(cap.sla_due_at)  # cleared by the recompute

    # AC-02-9 (channel + explicit received_at persist)
    def test_channel_and_received_at_persist(self):
        when = get_datetime("2026-03-01 09:30:00")
        cap = self._capture("invoice_x.pdf", intake_channel=INTAKE_EMAIL_INBOUND, received_at=when)
        self.assertEqual(cap.intake_channel, INTAKE_EMAIL_INBOUND)
        self.assertEqual(get_datetime(cap.received_at), when)

    # AC-02-10 (mobile param)
    def test_mobile_channel_via_uploaded_file(self):
        f = frappe.get_doc(
            {"doctype": "File", "file_name": "invoice_mobile.pdf", "content": _PDF_BYTES, "is_private": 1}
        ).insert(ignore_permissions=True)
        name = create_capture_from_uploaded_file(f.name, intake_channel=INTAKE_MOBILE_UPLOAD)
        self.assertEqual(frappe.db.get_value("AP Invoice Capture", name, "intake_channel"), INTAKE_MOBILE_UPLOAD)

    # AC-02-11 (email-in: one capture per supported attachment)
    def test_email_in_one_capture_per_supported_attachment(self):
        comm = self._make_comm()
        pdf = self._attach(comm, "receipt_jan.pdf")
        self._attach(comm, "signature.txt", content=b"sig")
        created = create_capture_from_email(comm.name)
        self.assertEqual(len(created), 1)
        cap = frappe.get_doc("AP Invoice Capture", created[0])
        self.assertEqual(cap.source_file, pdf.name)
        self.assertEqual(cap.intake_channel, INTAKE_EMAIL_INBOUND)
        self.assertEqual(get_datetime(cap.received_at), get_datetime(comm.communication_date))
        self.assertEqual(cap.stream, STREAM_RECEIPT)  # receipt_* (pri 10)

    # AC-02-12 (email-in: no supported attachments)
    def test_email_in_no_supported_attachments(self):
        comm = self._make_comm()
        self._attach(comm, "logo.txt", content=b"x")
        self.assertEqual(create_capture_from_email(comm.name), [])

    # AC-02-13 (handler guard — no-op unless inbound on the configured account)
    def test_handle_inbound_guard_skips(self):
        frappe.db.set_single_value(SETTINGS, "ap_intake_email_account", "AP Acct")
        before = frappe.db.count("AP Invoice Capture")
        handle_inbound_ap_communication(
            frappe._dict(communication_type="Communication", sent_or_received="Sent",
                         email_account="AP Acct", name="nope"))  # not Received
        handle_inbound_ap_communication(
            frappe._dict(communication_type="Communication", sent_or_received="Received",
                         email_account="Other", name="nope"))  # wrong account
        frappe.db.set_single_value(SETTINGS, "ap_intake_email_account", None)
        handle_inbound_ap_communication(
            frappe._dict(communication_type="Communication", sent_or_received="Received",
                         email_account="AP Acct", name="nope"))  # feature off
        self.assertEqual(frappe.db.count("AP Invoice Capture"), before)

    # AC-02-15 (data-driven — adding a rule changes classification, no code change)
    def test_data_driven_new_rule(self):
        self._make_rules(
            RULES + [{"priority": 25, "signal": "sender_domain", "pattern": "square.com", "assign_stream": "Receipt (R)"}]
        )
        cap = self._capture("doc.pdf", sender_domain="payments.square.com")
        self.assertEqual(cap.stream, STREAM_RECEIPT)
        self.assertEqual(cap.stream_provisional_source, "sender_domain")
