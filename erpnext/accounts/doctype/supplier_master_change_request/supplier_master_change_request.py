# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""Supplier Master Change Request — Tier-3 gated supplier-master mutation (spec 05).

The single approval gate for supplier-master changes. ``change_type="Create"`` is
the one this slice implements end-to-end: it holds an unresolved vendor string
(no ``Supplier`` exists yet — that is precisely what the gate blocks on Stream I),
and on approval creates the ``Supplier`` from an allow-listed ``proposed_payload``.
The other variants (Update Bank Details / Payment Terms / Disable) are dispatched
here but their bodies are owned by specs 08/11; they raise a clear NotImplemented
until those specs land. The native Workflow record (states/transitions/roles) is
owned by spec 11 — here the lifecycle is controller-driven via ``workflow_state``.

Approval is doubly gated: ``frappe.only_for(approver_role)`` (mirrors
``document_capture.record_manager_decision``) AND a requester≠approver
segregation-of-duties backstop in the controller, independent of the spec-11
Workflow transition Allowed Role.

Grounding (local v16 source — what ships):
* Supplier create payload keys — ``erpnext/buying/doctype/supplier/supplier.json``
  (``supplier_name`` Data reqd; ``supplier_type`` Select reqd Company/Individual/
  Partnership; ``supplier_group`` Link; ``autoname:"naming_series:"``).
* Bank Account fields for the Update Bank Details variant —
  ``erpnext/accounts/doctype/bank_account/bank_account.json`` (iban/bank_account_no/
  branch_code/bank, keyed by ``party_type``+``party``); the bank fields are NOT on
  the Supplier master, only ``default_bank_account`` is.
* Idempotent create — ``erpnext.accounts.ap_closed_loop.idempotency.with_idempotency``
  (spec 01); ``created_supplier`` is also checked first so a retried approval can
  never create a duplicate Supplier.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

CHANGE_TYPE_CREATE = "Create"
CHANGE_TYPE_UPDATE_BANK = "Update Bank Details"
CHANGE_TYPE_UPDATE_TERMS = "Update Payment Terms"
CHANGE_TYPE_DISABLE = "Disable"

STATE_DRAFT = "Draft"
STATE_PENDING = "Pending Approval"
STATE_APPROVED = "Approved"
STATE_POSTED = "Posted"
STATE_REJECTED = "Rejected"

_OPEN_STATES = (STATE_DRAFT, STATE_PENDING, STATE_APPROVED)

# Allow-listed Supplier fieldnames the controller may write on a Create approval.
# Bounds the blast radius: a requester cannot smuggle arbitrary fields into the
# Supplier master. Keys verified against supplier.json (local v16 source).
ALLOWED_CREATE_KEYS = (
	"supplier_name",
	"supplier_group",
	"supplier_type",
	"country",
	"default_currency",
	"tax_id",
)

# Allow-listed Bank Account fieldnames for the Update Bank Details variant
# (verified against bank_account.json). party_type/party are NOT in the payload —
# the controller sets them from target_supplier so the requester cannot retarget.
ALLOWED_BANK_ACCOUNT_KEYS = (
	"account_name",
	"bank",
	"iban",
	"bank_account_no",
	"branch_code",
	"account",
	"is_company_account",
	"is_default",
)

DEFAULT_APPROVER_ROLE = "Accounts Manager"


class SupplierMasterChangeRequest(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		amended_from: DF.Link | None
		approver_role: DF.Link | None
		change_type: DF.Literal["Create", "Update Bank Details", "Update Payment Terms", "Disable"]
		created_supplier: DF.Link | None
		decision_at: DF.Datetime | None
		decision_by: DF.Link | None
		decision_reason: DF.SmallText | None
		evidence_capture: DF.Link | None
		naming_series: DF.Literal["SMCR-.YYYY.-.#####"]
		proposed_payload: DF.Code | None
		requested_by: DF.Link | None
		requested_supplier_name: DF.Data | None
		target_supplier: DF.Link | None
		workflow_state: DF.Literal["Draft", "Pending Approval", "Approved", "Posted", "Rejected"]
	# end: auto-generated types

	def before_insert(self) -> None:
		# Anchor the SoD check: the requester is whoever raised the request.
		if not self.requested_by:
			self.requested_by = frappe.session.user
		if not self.workflow_state:
			self.workflow_state = STATE_DRAFT
		if not self.approver_role:
			self.approver_role = _default_approver_role()


def _default_approver_role() -> str:
	try:
		from erpnext.accounts.doctype.ap_closed_loop_settings.ap_closed_loop_settings import (
			get_supplier_resolution_settings,
		)

		role = get_supplier_resolution_settings().get("supplier_change_approver_role")
		return role or DEFAULT_APPROVER_ROLE
	except Exception:
		return DEFAULT_APPROVER_ROLE


def _allowlisted(payload: dict | str | None, keys: tuple[str, ...]) -> dict:
	"""Parse the payload (JSON string or dict) and keep only allow-listed keys."""

	if isinstance(payload, str) and payload.strip():
		try:
			payload = json.loads(payload)
		except (TypeError, ValueError):
			payload = {}
	if not isinstance(payload, dict):
		return {}
	return {k: v for k, v in payload.items() if k in keys and v not in (None, "")}


@frappe.whitelist()
def approve_supplier_master_change_request(request: str, actor: str | None = None) -> str:
	"""Approve a Draft/Pending request and post the supplier-master mutation.

	Enforces ``approver_role`` (``frappe.only_for``) + a requester≠approver SoD
	backstop, then for ``change_type=Create`` creates the Supplier idempotently from
	the allow-listed ``proposed_payload``, sets ``created_supplier``, moves the
	request to ``Posted``, and re-runs ``validate_for_purchase_invoice`` on the
	``evidence_capture`` so a blocked Stream-I capture flips to Validated. Returns
	the request name. Never creates a duplicate Supplier (``created_supplier`` +
	idempotency-ledger guard).
	"""

	from erpnext.accounts.doctype.document_capture.document_capture import (
		CaptureApprovalError,
		validate_for_purchase_invoice,
	)

	req = frappe.get_doc("Supplier Master Change Request", request)
	actor_user = actor or frappe.session.user

	# Idempotency: an already-posted request is a no-op (AC-05-21).
	if req.workflow_state == STATE_POSTED:
		return req.name

	if req.workflow_state not in _OPEN_STATES:
		raise CaptureApprovalError(
			_("Supplier Master Change Request {0} is already decided (state {1}).").format(
				req.name, req.workflow_state
			)
		)

	# Role gate (mirrors record_manager_decision, py:1992). Raises PermissionError.
	frappe.only_for(req.approver_role or _default_approver_role() or DEFAULT_APPROVER_ROLE)

	# Segregation of duties: the requester may not approve their own request.
	if actor_user == req.requested_by:
		raise CaptureApprovalError(
			_("Segregation of duties: the requester may not approve their own supplier change request.")
		)

	if req.change_type == CHANGE_TYPE_CREATE:
		supplier_name = _post_create(req)
		req.created_supplier = supplier_name
	else:
		# Dispatch + SoD live here; the bodies for these variants are owned by
		# specs 08/11 (Update Bank Details targets a Bank Account row, not the
		# Supplier — see §5.1). Fail loudly rather than silently no-op.
		raise CaptureApprovalError(
			_("change_type '{0}' is not yet implemented (owned by specs 08/11).").format(
				req.change_type
			)
		)

	req.decision_by = actor_user
	req.decision_at = now_datetime()
	req.workflow_state = STATE_POSTED
	req.save(ignore_permissions=True)

	# OD-05-3: persist an exact alias so the next variant of this vendor string
	# resolves at Tier 1. Non-fatal — a failure here must not undo the approval.
	_maybe_seed_alias(req)

	# Re-validate the originating capture so Tier-1/2 now find the new Supplier and
	# a blocked Stream-I capture flips BLOCKED -> VALIDATED, then resume the cascade.
	if req.evidence_capture and frappe.db.exists("Document Capture", req.evidence_capture):
		capture = validate_for_purchase_invoice(req.evidence_capture)
		capture._kick_next_step()

	return req.name


def _post_create(req: "SupplierMasterChangeRequest") -> str:
	"""Create the Supplier from the allow-listed payload (idempotent). Returns name."""

	# Primary idempotency guard: never create a second Supplier for a posted request.
	if req.created_supplier and frappe.db.exists("Supplier", req.created_supplier):
		return req.created_supplier

	payload = _allowlisted(req.proposed_payload, ALLOWED_CREATE_KEYS)
	if not payload.get("supplier_name"):
		# Fall back to the requested vendor string if the payload omitted the name.
		payload["supplier_name"] = (req.requested_supplier_name or "").strip()
	if not payload.get("supplier_name"):
		from erpnext.accounts.doctype.document_capture.document_capture import (
			CaptureApprovalError,
		)

		raise CaptureApprovalError(_("Cannot create a Supplier without a supplier_name."))

	def _create() -> dict:
		doc = frappe.get_doc({"doctype": "Supplier", **payload})
		# The frappe.only_for role gate above is the authorization boundary, mirroring
		# issue_mock_payment's PE insert — AP-flow approvals shouldn't require per-user
		# Supplier create rights beyond the gated role.
		doc.insert(ignore_permissions=True)
		return {"doctype": "Supplier", "name": doc.name}

	# Belt-and-suspenders against retried background jobs (spec 01): when the request
	# carries a capture, route the insert through the AP Posting Ledger idempotency
	# guard. Without a capture, the created_supplier short-circuit above is the guard.
	if req.evidence_capture:
		from erpnext.accounts.ap_closed_loop.idempotency import generate_key, with_idempotency

		key = generate_key(req.evidence_capture, f"smcr_create:{req.name}")
		result = with_idempotency(key, _create, capture=req.evidence_capture, step=f"smcr_create:{req.name}")
		return result["name"]

	return _create()["name"]


def _maybe_seed_alias(req: "SupplierMasterChangeRequest") -> None:
	"""OD-05-3: store an exact AP Supplier Alias from the requested vendor string."""

	try:
		pattern = (req.requested_supplier_name or "").strip()
		if not pattern or not req.created_supplier:
			return
		exists = frappe.db.exists(
			"AP Supplier Alias", {"alias_pattern": pattern, "match_type": "exact"}
		)
		if exists:
			return
		frappe.get_doc(
			{
				"doctype": "AP Supplier Alias",
				"canonical_supplier": req.created_supplier,
				"alias_pattern": pattern,
				"match_type": "exact",
				"is_active": 1,
				"source_capture": req.evidence_capture,
				"notes": _("Auto-created from approved Supplier Master Change Request {0}.").format(
					req.name
				),
			}
		).insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(
			title="SMCR alias auto-seed failed",
			message=frappe.get_traceback(),
		)


@frappe.whitelist()
def reject_supplier_master_change_request(
	request: str, reason: str, actor: str | None = None
) -> str:
	"""Reject a request with a reason. Drives -> Rejected, records decision_by/at/reason.

	On Stream I the linked capture stays BLOCKED (no payable). Returns the request name.
	"""

	from erpnext.accounts.doctype.document_capture.document_capture import (
		CaptureApprovalError,
	)

	reason = (reason or "").strip()
	if not reason:
		raise CaptureApprovalError(_("A rejection reason is required."))

	req = frappe.get_doc("Supplier Master Change Request", request)
	if req.workflow_state not in _OPEN_STATES:
		raise CaptureApprovalError(
			_("Supplier Master Change Request {0} is already decided (state {1}).").format(
				req.name, req.workflow_state
			)
		)

	frappe.only_for(req.approver_role or _default_approver_role() or DEFAULT_APPROVER_ROLE)

	req.decision_by = actor or frappe.session.user
	req.decision_at = now_datetime()
	req.decision_reason = reason
	req.workflow_state = STATE_REJECTED
	req.save(ignore_permissions=True)
	# The capture stays BLOCKED on Stream I — no re-validation, no Supplier created.
	return req.name
