# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""Tests for the document-level idempotency layer (spec 01 §5.3-A/B)."""

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from erpnext.accounts.ap_closed_loop import idempotency

LEDGER = "AP Posting Ledger"


class TestIdempotency(IntegrationTestCase):
    def setUp(self):
        frappe.flags.skip_ap_auto_progress = True
        self.capture = frappe.get_doc(
            {
                "doctype": "Document Capture",
                "source_file_url": "http://example.test/idemp.pdf",
                "source_filename": "idemp.pdf",
            }
        ).insert(ignore_permissions=True)

    def tearDown(self):
        frappe.flags.skip_ap_auto_progress = False
        frappe.db.rollback()

    def _winner_row(self, key):
        return frappe.get_doc(
            {
                "doctype": LEDGER,
                "idempotency_key": key,
                "capture": self.capture.name,
                "step": "promote",
                "result_doctype": "Purchase Invoice",
                "result_name": "PINV-WINNER",
                "posted_at": now_datetime(),
            }
        ).insert(ignore_permissions=True)

    # AC-01-1 — deterministic, pure, sensitive only to (capture, step)
    def test_generate_key_is_deterministic_and_pure(self):
        k1 = idempotency.generate_key("APIC-2026-00001", "promote")
        k2 = idempotency.generate_key("APIC-2026-00001", "promote")
        self.assertEqual(k1, k2)
        self.assertEqual(len(k1), 64)
        int(k1, 16)  # valid hex, raises if not
        self.assertNotEqual(k1, idempotency.generate_key("APIC-2026-00001", "approve"))
        self.assertNotEqual(k1, idempotency.generate_key("APIC-2026-00002", "promote"))

    # AC-01-2 — STABLE across a settings save (the double-post guard / D9)
    def test_generate_key_stable_across_settings_save(self):
        k_before = idempotency.generate_key(self.capture.name, "promote")
        # Bump AP Closed Loop Settings.modified via an unrelated field edit.
        frappe.db.set_single_value(
            "AP Closed Loop Settings", "ocr_model", "claude-sonnet-4-6"
        )
        k_after = idempotency.generate_key(self.capture.name, "promote")
        self.assertEqual(
            k_before, k_after, "generate_key must not depend on settings.modified"
        )

    # AC-01-3 — first call runs fn once and records the ledger row
    def test_with_idempotency_first_call_runs_fn_and_records(self):
        calls = []

        def fn():
            calls.append(1)
            return {"doctype": "Purchase Invoice", "name": "PINV-IDEMP-1"}

        key = idempotency.generate_key(self.capture.name, "promote")
        result = idempotency.with_idempotency(key, fn, self.capture.name, "promote")

        self.assertEqual(len(calls), 1)
        self.assertEqual(result["doctype"], "Purchase Invoice")
        self.assertEqual(result["name"], "PINV-IDEMP-1")
        self.assertFalse(result["reused"])

        row = frappe.db.get_value(
            LEDGER,
            {"idempotency_key": key},
            ["capture", "step", "result_doctype", "result_name", "posted_at"],
            as_dict=True,
        )
        self.assertTrue(row)
        self.assertEqual(row.capture, self.capture.name)
        self.assertEqual(row.step, "promote")
        self.assertEqual(row.result_doctype, "Purchase Invoice")
        self.assertEqual(row.result_name, "PINV-IDEMP-1")
        self.assertTrue(row.posted_at)

    # AC-01-4 — second call with same key does NOT re-run fn or duplicate the row
    def test_with_idempotency_second_call_does_not_rerun(self):
        calls = []

        def fn():
            calls.append(1)
            return {"doctype": "Purchase Invoice", "name": "PINV-IDEMP-2"}

        key = idempotency.generate_key(self.capture.name, "promote")
        idempotency.with_idempotency(key, fn, self.capture.name, "promote")
        result2 = idempotency.with_idempotency(key, fn, self.capture.name, "promote")

        self.assertEqual(len(calls), 1)  # fn NOT called the second time
        self.assertTrue(result2["reused"])
        self.assertEqual(result2["name"], "PINV-IDEMP-2")
        self.assertEqual(frappe.db.count(LEDGER, {"idempotency_key": key}), 1)

    # AC-01-5 — pre-inserted row wins; fn never runs, no duplicate
    def test_with_idempotency_existing_row_wins(self):
        key = idempotency.generate_key(self.capture.name, "promote")
        self._winner_row(key)

        calls = []

        def fn():
            calls.append(1)
            return {"doctype": "Purchase Invoice", "name": "PINV-LOSER"}

        result = idempotency.with_idempotency(key, fn, self.capture.name, "promote")
        self.assertEqual(len(calls), 0)  # fast path: fn never called
        self.assertTrue(result["reused"])
        self.assertEqual(result["name"], "PINV-WINNER")
        self.assertEqual(frappe.db.count(LEDGER, {"idempotency_key": key}), 1)

    # AC-01-5 (concurrency branch) — exists-check misses, insert collides, re-resolves
    def test_with_idempotency_reresolves_on_unique_violation(self):
        key = idempotency.generate_key(self.capture.name, "promote")
        self._winner_row(key)

        # Force the fast-path exists-check to MISS so we reach the insert+except.
        orig_resolve = idempotency._resolve_existing
        state = {"n": 0}

        def flaky_resolve(k):
            state["n"] += 1
            if state["n"] == 1:
                return None  # pretend not present yet (the race)
            return orig_resolve(k)

        idempotency._resolve_existing = flaky_resolve
        try:
            result = idempotency.with_idempotency(
                key,
                lambda: {"doctype": "Purchase Invoice", "name": "PINV-LOSER"},
                self.capture.name,
                "promote",
            )
        finally:
            idempotency._resolve_existing = orig_resolve

        self.assertTrue(result["reused"])
        self.assertEqual(result["name"], "PINV-WINNER")
        self.assertEqual(frappe.db.count(LEDGER, {"idempotency_key": key}), 1)

    # AC-01-6 — the UNIQUE index rejects a duplicate idempotency_key insert
    def test_duplicate_ledger_insert_raises(self):
        key = idempotency.generate_key(self.capture.name, "promote")
        self._winner_row(key)
        with self.assertRaises((frappe.UniqueValidationError, frappe.DuplicateEntryError)):
            self._winner_row(key)
