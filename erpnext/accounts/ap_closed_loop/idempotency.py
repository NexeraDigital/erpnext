# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""Document-level idempotency for the AP Closed Loop pipeline.

This is the foundation primitive that makes every document-creating step
retry-safe: a step routes its create through :func:`with_idempotency`, keyed by
a stable :func:`generate_key` hash, and the ``AP Posting Ledger`` UNIQUE index
guarantees the ERPNext document is created at most once no matter how many
times the step's code runs (a retried background job, a re-fired cascade, a
concurrent worker).

This is a SEPARATE layer from ``frappe.enqueue``'s job-level dedup
(``deduplicate=True`` + ``job_id``): job-level dedup only prevents the same
queued job from being enqueued twice while one is pending; it says nothing
about document creation once a job has run to completion and is retried later.
See docs/spec/01-foundations-settings-async-idempotency.md §5.1-B.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable

import frappe
from frappe.utils import now_datetime

LEDGER_DOCTYPE = "AP Posting Ledger"


def generate_key(capture_name: str, step_name: str) -> str:
	"""Return a stable sha256 hex fingerprint for a (capture, step) operation.

	The key depends ONLY on ``capture_name`` and ``step_name`` — never on
	settings state or any timestamp. This is a correctness requirement, not an
	optimisation: if the key folded in e.g. ``AP Closed Loop Settings.modified``,
	any settings save would change the key for every capture/step, so a job
	retried after an unrelated settings tweak would compute a new key, miss its
	ledger row, re-run ``fn`` and DOUBLE-POST. Keying on capture+step only makes
	the ledger row a stable fingerprint of the logical operation for the life of
	that capture/step. Pure function: no DB read, no exceptions.
	"""

	material = "\x00".join([capture_name, step_name])
	return hashlib.sha256(material.encode("utf-8")).hexdigest()


def with_idempotency(
	key: str,
	fn: Callable[[], dict],
	capture: str,
	step: str,
) -> dict:
	"""Run ``fn`` at most once for ``key``; record the result in the ledger.

	``fn`` must return ``{"doctype": str, "name": str}`` describing the ERPNext
	document it created. Returns ``{"doctype", "name", "reused": bool}``.

	* Fast path: if a ledger row already exists for ``key``, ``fn`` is NOT
	  called and the prior result is returned (``reused=True``) — this is the
	  double-post prevention.
	* Concurrency: the DB UNIQUE index on ``idempotency_key`` is the real
	  guarantee. If a concurrent winner inserts ``key`` between our
	  exists-check and our insert, we catch the unique/duplicate error and
	  re-resolve to the existing row rather than crashing.
	"""

	existing = _resolve_existing(key)
	if existing is not None:
		return {**existing, "reused": True}

	result = fn()
	try:
		frappe.get_doc(
			{
				"doctype": LEDGER_DOCTYPE,
				"idempotency_key": key,
				"capture": capture,
				"step": step,
				"result_doctype": result["doctype"],
				"result_name": result["name"],
				"posted_at": now_datetime(),
			}
		).insert(ignore_permissions=True)
	except (frappe.UniqueValidationError, frappe.DuplicateEntryError):
		# A concurrent caller inserted the same key first. The winner's row is
		# authoritative; re-resolve to it rather than failing. (fn may have
		# produced a duplicate downstream doc — callers keep fn idempotent via
		# their own status guards; see spec §5.3-B / D6.)
		resolved = _resolve_existing(key)
		if resolved is not None:
			return {**resolved, "reused": True}
		raise

	return {"doctype": result["doctype"], "name": result["name"], "reused": False}


def _resolve_existing(key: str) -> dict | None:
	"""Return ``{"doctype", "name"}`` for an existing ledger row, else None."""

	row = frappe.db.get_value(
		LEDGER_DOCTYPE,
		{"idempotency_key": key},
		["result_doctype", "result_name"],
		as_dict=True,
	)
	if not row:
		return None
	return {"doctype": row.result_doctype, "name": row.result_name}
