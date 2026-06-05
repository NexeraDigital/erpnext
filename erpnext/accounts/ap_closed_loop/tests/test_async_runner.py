# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""Tests for the step-aware async runner (spec 01 §5.3-C)."""

import frappe
from frappe.exceptions import RetryBackgroundJobError
from frappe.tests import IntegrationTestCase

from erpnext.accounts.ap_closed_loop import async_runner
from erpnext.accounts.ap_closed_loop.async_runner import RetryLaterError


class TestAsyncRunner(IntegrationTestCase):
    def tearDown(self):
        frappe.db.rollback()

    def _patch(self, obj, attr, value):
        orig = getattr(obj, attr)
        setattr(obj, attr, value)
        self.addCleanup(setattr, obj, attr, orig)

    @staticmethod
    def _raiser(exc):
        def fn(capture):
            raise exc

        return fn

    # AC-01-7 + unknown-key fallback
    def test_resolve_queue(self):
        self.assertEqual(async_runner.resolve_queue("run_fake_extraction_for"), "long")
        self.assertEqual(async_runner.resolve_queue("run_extraction"), "long")
        self.assertEqual(
            async_runner.resolve_queue("validate_for_purchase_invoice_for"), "short"
        )
        self.assertEqual(async_runner.resolve_queue("issue_mock_payment_for"), "short")
        self.assertEqual(async_runner.resolve_queue("create_journal_entry"), "short")
        # substring fallback
        self.assertEqual(async_runner.resolve_queue("some_ocr_thing"), "long")
        self.assertEqual(async_runner.resolve_queue("do_payment_now"), "short")
        # unknown → default
        self.assertEqual(async_runner.resolve_queue("totally_unknown_step"), "default")

    # AC-01-8 — enqueue kwargs (production + test paths)
    def test_enqueue_step_kwargs(self):
        captured = {}

        def fake_enqueue(path, **kwargs):
            captured["path"] = path
            captured.update(kwargs)

        self._patch(frappe, "enqueue", fake_enqueue)

        orig_in_test = frappe.flags.get("in_test")
        # Production path: simulate non-test.
        frappe.flags.in_test = False
        try:
            async_runner.enqueue_step("APIC-X", "run_fake_extraction_for")
        finally:
            frappe.flags.in_test = orig_in_test

        self.assertEqual(captured["path"], async_runner._DISPATCH_PATH)
        self.assertEqual(captured["capture"], "APIC-X")
        self.assertEqual(captured["step_name"], "run_fake_extraction_for")
        self.assertEqual(captured["queue"], "long")
        self.assertEqual(captured["job_id"], "apic::APIC-X::run_fake_extraction_for")
        self.assertTrue(captured["deduplicate"])
        self.assertTrue(captured["enqueue_after_commit"])  # non-test → True
        self.assertFalse(captured["now"])

        # Test path: now=True, enqueue_after_commit=False
        captured.clear()
        frappe.flags.in_test = True
        async_runner.enqueue_step("APIC-Y", "validate_for_purchase_invoice_for")
        self.assertTrue(captured["now"])
        self.assertFalse(captured["enqueue_after_commit"])
        self.assertEqual(captured["queue"], "short")

    # AC-01-9 — delayed-backoff re-enqueues up to MAX_RETRIES then dead-letters
    def test_delayed_backoff_reenqueues_up_to_max(self):
        self._patch(
            async_runner,
            "_resolve_step",
            lambda step: self._raiser(RetryLaterError("rate limited")),
        )
        enqueue_calls = []
        self._patch(
            async_runner,
            "enqueue_step",
            lambda capture, step_name, **kw: enqueue_calls.append(kw),
        )
        dead = []
        self._patch(async_runner, "_dead_letter", lambda *a, **k: dead.append(a))

        async_runner._dispatch_step("APIC-Z", "issue_payment_for", _attempt=0)
        self.assertEqual(len(enqueue_calls), 1)
        self.assertEqual(enqueue_calls[0]["_attempt"], 1)
        self.assertEqual(len(dead), 0)

        # At the cap, no more re-enqueue → dead-letter.
        async_runner._dispatch_step(
            "APIC-Z", "issue_payment_for", _attempt=async_runner.MAX_RETRIES
        )
        self.assertEqual(len(enqueue_calls), 1)  # unchanged
        self.assertEqual(len(dead), 1)

    # AC-01-10 — permanent ValidationError → dead-letter (action_required), no re-raise
    def test_permanent_error_dead_letters(self):
        self._patch(
            async_runner,
            "_resolve_step",
            lambda step: self._raiser(frappe.ValidationError("bad data")),
        )
        set_calls = []
        self._patch(frappe.db, "set_value", lambda *a, **k: set_calls.append((a, k)))
        self._patch(frappe.db, "commit", lambda: None)
        self._patch(frappe, "log_error", lambda **k: None)

        # Must NOT raise.
        async_runner._dispatch_step("APIC-D", "promote_to_purchase_invoice_for")

        self.assertEqual(len(set_calls), 1)
        args, _kwargs = set_calls[0]
        self.assertEqual(args[0], "Document Capture")
        self.assertEqual(args[1], "APIC-D")
        payload = args[2]
        self.assertEqual(payload["action_required"], 1)
        self.assertIn("Auto-step", payload["action_required_reason"])

    # AC-01-10a + AC-01-10b — immediate transient → native RetryBackgroundJobError,
    # NOT dead-lettered, NOT custom-re-enqueued (no double-retry)
    def test_immediate_transient_raises_native_retry(self):
        self._patch(
            async_runner,
            "_resolve_step",
            lambda step: self._raiser(ConnectionError("conn reset")),
        )
        set_calls = []
        self._patch(frappe.db, "set_value", lambda *a, **k: set_calls.append(1))
        enqueue_calls = []
        self._patch(async_runner, "enqueue_step", lambda *a, **k: enqueue_calls.append(1))

        with self.assertRaises(RetryBackgroundJobError):
            async_runner._dispatch_step("APIC-T", "run_extraction")

        self.assertEqual(len(set_calls), 0)  # AC-01-10a: not dead-lettered
        self.assertEqual(len(enqueue_calls), 0)  # AC-01-10b: no custom re-enqueue

    # AC-01-10c — concurrency loss (UniqueValidationError) is re-resolved, NOT dead-lettered
    def test_unique_violation_is_not_dead_lettered(self):
        self._patch(
            async_runner,
            "_resolve_step",
            lambda step: self._raiser(frappe.UniqueValidationError("dup key")),
        )
        set_calls = []
        self._patch(frappe.db, "set_value", lambda *a, **k: set_calls.append(1))

        result = async_runner._dispatch_step("APIC-U", "promote_to_purchase_invoice_for")

        self.assertIsNone(result)
        self.assertEqual(len(set_calls), 0)  # proves the unique branch precedes ValidationError
