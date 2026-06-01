# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""Tests for the portal-pull adapter registry (spec 02 §5.3.5)."""

import frappe
from frappe.tests import IntegrationTestCase

from erpnext.accounts.ap_closed_loop import portal_pull
from erpnext.accounts.ap_closed_loop.portal_pull import (
    PortalPullAdapter,
    PulledDocument,
    get_portal_adapter,
    register_portal_adapter,
)


class TestPortalPullRegistry(IntegrationTestCase):
    def tearDown(self):
        portal_pull._ADAPTERS.pop("unit-test-x", None)
        frappe.db.rollback()

    # AC-02-14 (register + resolve)
    def test_register_and_resolve(self):
        @register_portal_adapter("unit-test-x")
        class _StubAdapter(PortalPullAdapter):
            def name(self):
                return "unit-test-x"

            def pull(self):
                return [PulledDocument(file_name="a.pdf", content=b"x")]

        adapter = get_portal_adapter("unit-test-x")
        self.assertIsInstance(adapter, PortalPullAdapter)
        self.assertEqual(adapter.name(), "unit-test-x")
        docs = adapter.pull()
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0].file_name, "a.pdf")

    # AC-02-14 (unknown key raises — same loud-failure contract as the OCR registry)
    def test_unknown_adapter_raises(self):
        with self.assertRaises(ValueError):
            get_portal_adapter("does-not-exist")
