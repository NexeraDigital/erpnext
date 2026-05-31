# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""Tests for the AP Closed Loop foundation defaults installer (spec 01 §5.3-F)."""

import frappe
from frappe.tests import IntegrationTestCase

from erpnext.accounts.ap_closed_loop.install import AP_SETTINGS_DEFAULTS, install_ap_defaults

SETTINGS = "AP Closed Loop Settings"


class TestInstallAPDefaults(IntegrationTestCase):
    def tearDown(self):
        frappe.db.rollback()

    def _clear(self):
        # Delete the tabSingles rows so the fields are genuinely absent —
        # faithfully simulates a freshly-migrated site (column added, no value
        # yet), which reads as missing in get_singles_dict.
        for field in AP_SETTINGS_DEFAULTS:
            frappe.db.delete("Singles", {"doctype": SETTINGS, "field": field})

    def _raw(self):
        # Uncached raw read (text), so assertions are not affected by the
        # get_single_value cache after a set_single_value within the txn.
        return frappe.db.get_singles_dict(SETTINGS) or {}

    # AC-01-16 (backfill blanks)
    def test_backfills_blank_fields(self):
        self._clear()
        install_ap_defaults()
        stored = self._raw()
        for field, default in AP_SETTINGS_DEFAULTS.items():
            self.assertEqual(float(stored.get(field)), float(default), msg=field)

    # AC-01-16 (never overwrites an operator value)
    def test_does_not_overwrite_operator_value(self):
        frappe.db.set_single_value(SETTINGS, "auto_post_amount_threshold", 5000)
        install_ap_defaults()
        self.assertEqual(float(self._raw().get("auto_post_amount_threshold")), 5000.0)

    # AC-01-16 (idempotent re-run)
    def test_rerun_is_noop(self):
        self._clear()
        install_ap_defaults()
        first = {f: self._raw().get(f) for f in AP_SETTINGS_DEFAULTS}
        install_ap_defaults()
        second = {f: self._raw().get(f) for f in AP_SETTINGS_DEFAULTS}
        self.assertEqual(first, second)
