# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""Defaults installer for the AP Closed Loop foundation settings.

Wired into ``after_migrate`` (erpnext/hooks.py). Backfills the new
``AP Closed Loop Settings`` fields on existing sites — but ONLY when blank, so
an operator's edits are never clobbered. Idempotent: safe to run on every
migrate. See docs/spec/01-foundations-settings-async-idempotency.md §5.3-F.
"""

from __future__ import annotations

import frappe

SETTINGS_DOCTYPE = "AP Closed Loop Settings"

# (fieldname -> default) for the foundation fields that need a value on a fresh
# or upgraded site. Section breaks, the field_thresholds JSON, and the
# account-link fields are intentionally left blank (no sensible site-wide
# default), so they are omitted here.
AP_SETTINGS_DEFAULTS = {
	"auto_post_amount_threshold": 1000.0,
	"dedupe_window_days": 90,
	"enforce_sod": 1,
	"sod_threshold_amount": 0,
}


def install_ap_defaults() -> None:
	"""Backfill blank foundation settings with their documented defaults.

	Only writes a field when its current stored value is blank (``None``/``""``)
	so re-running is a no-op and an operator-edited value is never overwritten.
	"""

	# A very fresh site may not have the doctype yet (first-install ordering);
	# guard so after_migrate never errors before the schema exists.
	if not frappe.db.exists("DocType", SETTINGS_DOCTYPE):
		return

	# Read RAW stored text via get_singles_dict, NOT get_single_value: the latter
	# coerces an unset Float/Int to 0, which we could not distinguish from an
	# operator's deliberate 0. A field is "blank" (and gets backfilled) only when
	# its tabSingles value is absent / NULL / empty — a freshly-migrated field has
	# no row yet, so it reads as missing here.
	stored = frappe.db.get_singles_dict(SETTINGS_DOCTYPE) or {}
	for field, default in AP_SETTINGS_DEFAULTS.items():
		raw = stored.get(field)
		if raw is None or str(raw).strip() == "":
			frappe.db.set_single_value(SETTINGS_DOCTYPE, field, default)
