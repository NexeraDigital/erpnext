# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""Step-aware async runner for the AP Closed Loop cascade.

Generalises the in-controller ``_enqueue_next`` pattern into a reusable wrapper
over ``frappe.enqueue`` that:

* selects the right RQ queue per step (OCR → ``long``, posting/matching →
  ``short``, else ``default``),
* runs the step inside a dispatcher that classifies a failure into
  immediate-retry (native :class:`frappe.exceptions.RetryBackgroundJobError`),
  delayed-backoff (custom re-enqueue), or permanent (dead-letter onto the
  capture's ``action_required``),
* preserves the existing test-mode behaviour (``now=True``, no after-commit) so
  the cascade stays inside the test rollback boundary.

See docs/spec/01-foundations-settings-async-idempotency.md §5.3-C.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.exceptions import RetryBackgroundJobError

# The controller module that holds the cascade step functions. Phase-1: all
# steps live on the AP Invoice Capture controller. Resolution is centralised in
# ``_resolve_step`` so tests can monkeypatch it and future specs can extend it.
_STEP_MODULE = "erpnext.accounts.doctype.ap_invoice_capture.ap_invoice_capture"

_DISPATCH_PATH = "erpnext.accounts.ap_closed_loop.async_runner._dispatch_step"

MAX_RETRIES = 3

# Queue selection: explicit map first, then a substring fallback, then default.
QUEUE_BY_STEP = {
	"run_dedupe_for": "short",
	"run_fake_extraction_for": "long",
	"run_extraction": "long",
	"run_extraction_for": "long",
	"validate_for_purchase_invoice_for": "short",
	"request_approval_for": "short",
	"issue_mock_payment_for": "short",
	"issue_payment_for": "short",
	"promote_to_purchase_invoice_for": "short",
	"promote_to_journal_entry_for": "short",
	"create_journal_entry": "short",
	"create_bank_transaction": "short",
}

_LONG_SUBSTRINGS = ("extract", "ocr")
_SHORT_SUBSTRINGS = (
	"validate",
	"promote",
	"approval",
	"approve",
	"payment",
	"pay",
	"journal",
	"bank",
)

# Transient errors where an IMMEDIATE native retry is acceptable. Kept narrow;
# extended by the consuming specs (04 OCR, 13 bank feed) as real providers land.
_IMMEDIATE_RETRY_EXCEPTIONS = (ConnectionError, TimeoutError)


class RetryLaterError(Exception):
	"""Raise from a step to request a DELAYED-backoff re-enqueue (NOT the native
	immediate ``RetryBackgroundJobError``). For rate-limited providers that need
	minute-scale spacing. See spec §5.3-C, delayed-backoff bucket."""


def resolve_queue(step_name: str) -> str:
	"""Return the RQ queue for a step name (``long`` / ``short`` / ``default``)."""

	if step_name in QUEUE_BY_STEP:
		return QUEUE_BY_STEP[step_name]
	low = (step_name or "").lower()
	if any(s in low for s in _LONG_SUBSTRINGS):
		return "long"
	if any(s in low for s in _SHORT_SUBSTRINGS):
		return "short"
	return "default"


def enqueue_step(capture: str, step_name: str, **kwargs) -> None:
	"""Enqueue one cascade step on the right queue via the dispatcher.

	Mirrors the original ``ap_invoice_capture._enqueue_next`` test handling: in
	tests (``frappe.flags.in_test``) the job runs synchronously (``now=True``)
	and WITHOUT ``enqueue_after_commit`` so its writes stay inside the test's
	rollback boundary; in production it defers until after commit so a real
	worker sees committed state.
	"""

	in_test = bool(frappe.flags.get("in_test"))
	frappe.enqueue(
		_DISPATCH_PATH,
		capture=capture,
		step_name=step_name,
		queue=resolve_queue(step_name),
		job_id=f"apic::{capture}::{step_name}",
		deduplicate=True,
		enqueue_after_commit=not in_test,
		now=in_test,
		**kwargs,
	)


def _resolve_step(step_name: str):
	"""Resolve a step name to its callable on the step module."""

	import importlib

	module = importlib.import_module(_STEP_MODULE)
	return getattr(module, step_name)


def _classify(exc: Exception) -> str:
	"""Classify a step exception → ``immediate`` | ``delayed`` | ``permanent``.

	Each transient error takes EXACTLY ONE path — never both native immediate
	retry and a custom re-enqueue (that would stack native 5× under custom 3× =
	up to 15 attempts; see spec §5.3-C).
	"""

	if isinstance(exc, RetryLaterError):
		return "delayed"
	if isinstance(exc, frappe.ValidationError):
		return "permanent"
	if isinstance(exc, _IMMEDIATE_RETRY_EXCEPTIONS):
		return "immediate"
	# Unknown error: fail safe — surface to a human rather than retry blindly.
	return "permanent"


def _dispatch_step(capture: str, step_name: str, _attempt: int = 0, **kwargs) -> None:
	"""Worker entry point: run the step, then classify failures.

	The order of the ``except`` clauses is LOAD-BEARING: the concurrency
	re-resolve branch (``UniqueValidationError`` / ``DuplicateEntryError``) MUST
	be caught BEFORE the generic ``ValidationError`` → dead-letter branch,
	because ``UniqueValidationError`` subclasses ``ValidationError`` — otherwise
	a concurrency loss is dead-lettered instead of silently re-resolved.
	"""

	try:
		fn = _resolve_step(step_name)
		fn(capture)
		return
	except (frappe.UniqueValidationError, frappe.DuplicateEntryError):
		# Concurrency: another worker won the idempotency-key insert. The post
		# is deduplicated, not failed — do NOT dead-letter. (with_idempotency
		# normally re-resolves this internally; this is the belt-and-suspenders
		# path if it propagates here.)
		return
	except RetryBackgroundJobError:
		# Already the native retry signal — let it propagate to execute_job.
		raise
	except Exception as exc:  # noqa: BLE001 — the classifier decides the bucket
		bucket = _classify(exc)
		if bucket == "immediate":
			# Hand off to frappe's native worker retry (up to 5×, sleep(retry+1)).
			raise RetryBackgroundJobError(str(exc)) from exc
		if bucket == "delayed" and _attempt < MAX_RETRIES:
			# Delayed-backoff re-enqueue. Phase-1 (D5): immediate re-enqueue
			# without a true delay; phase-2 adds a scheduled sweep.
			enqueue_step(capture, step_name, _attempt=_attempt + 1, **kwargs)
			return
		# Permanent, or delayed retries exhausted → dead-letter onto the capture.
		_dead_letter(capture, step_name, exc, _attempt)


def _dead_letter(capture: str, step_name: str, exc: Exception, attempt: int) -> None:
	"""Surface a permanent failure on the capture (``action_required``) + Error Log.

	Generalises ``ap_invoice_capture._run_cascade_step``'s dead-letter behaviour.
	Deliberately does NOT re-raise (avoids RQ retry loops; ``action_required`` is
	the canonical user-visible signal).
	"""

	frappe.log_error(
		title=f"AP Cascade Step Failed: {step_name} on {capture}",
		message=frappe.get_traceback(),
	)
	try:
		msg = str(exc)[:160] or exc.__class__.__name__
		frappe.db.set_value(
			"AP Invoice Capture",
			capture,
			{
				"action_required": 1,
				"action_required_reason": _("Auto-step '{0}' failed: {1}").format(step_name, msg),
			},
			update_modified=True,
		)
		frappe.db.commit()
	except Exception:
		frappe.log_error(
			title=f"AP Cascade Step Failed AND Surface Failed: {capture}",
			message=frappe.get_traceback(),
		)

	_emit_review_event_if_present(capture, step_name, exc)


def _emit_review_event_if_present(capture: str, step_name: str, exc: Exception) -> None:
	"""Best-effort spec-10 hook (D8). No-op until AP Review Event lands."""

	try:
		from erpnext.accounts.ap_closed_loop import review_events  # type: ignore
	except Exception:
		return
	emit = getattr(review_events, "emit_dead_letter_event", None)
	if not callable(emit):
		return
	try:
		emit(capture=capture, step=step_name, error=str(exc))
	except Exception:
		frappe.log_error(
			title=f"AP Review Event emit failed: {capture}",
			message=frappe.get_traceback(),
		)
