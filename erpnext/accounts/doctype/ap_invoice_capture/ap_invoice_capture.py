# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""AP Invoice Capture.

Narrow pre-accounting capture record for the AP Closed Loop pilot.

This DocType is the manual intake landing pad for invoice images. It is
explicitly NOT an accounting document and must not progress silently into
Purchase Invoice, Payment Entry, or Bank Transaction. Its job is to:

* preserve the original uploaded artifact (or a traceable reference to it),
* expose source context, received time, lifecycle state, and action-required
  status so an AP clerk can review it,
* reject / flag unsupported or ambiguous formats so they cannot silently
  proceed to payment.

Phase 1 intake channel is Manual ERPNext Upload. Supported formats are PDF,
PNG, JPG, JPEG (case-insensitive).
"""

from __future__ import annotations

import os

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({"pdf", "png", "jpg", "jpeg"})

STATUS_PENDING_REVIEW = "Pending Review"
STATUS_UNSUPPORTED = "Unsupported"
STATUS_REJECTED = "Rejected"

INTAKE_MANUAL_UPLOAD = "Manual ERPNext Upload"


class AmbiguousSourceError(frappe.ValidationError):
	"""Raised when a capture cannot identify its source artifact."""


class APInvoiceCapture(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		action_required: DF.Check
		action_required_reason: DF.Data | None
		file_extension: DF.Data | None
		intake_channel: DF.Literal["Manual ERPNext Upload"]
		is_supported_format: DF.Check
		received_at: DF.Datetime
		source_context: DF.SmallText | None
		source_file: DF.Link | None
		source_file_url: DF.Data | None
		source_filename: DF.Data
		status: DF.Literal["Pending Review", "Unsupported", "Rejected"]
		validation_message: DF.SmallText | None
	# end: auto-generated types

	def validate(self):
		if not self.received_at:
			self.received_at = now_datetime()

		self._hydrate_from_linked_file()
		self._require_source_reference()

		extension = _normalize_extension(self.file_extension or self.source_filename or "")
		self.file_extension = extension or None
		supported = extension in SUPPORTED_EXTENSIONS
		self.is_supported_format = 1 if supported else 0

		if not supported:
			# Unsupported / ambiguous artifacts must be visibly blocked from
			# silently progressing to any accounting object.
			self.status = STATUS_UNSUPPORTED
			self.action_required = 1
			if not self.action_required_reason:
				self.action_required_reason = _("Unsupported source format")
			if not self.validation_message:
				self.validation_message = _(
					"Unsupported source format: {0}. Supported formats are PDF, PNG, JPG, JPEG."
				).format(extension or _("unknown"))
		else:
			if not self.status:
				self.status = STATUS_PENDING_REVIEW
			if self.status == STATUS_PENDING_REVIEW:
				self.action_required = 1
				if not self.action_required_reason:
					self.action_required_reason = _("Pending AP review")

	def _hydrate_from_linked_file(self) -> None:
		"""Pull filename / url off the linked File record when available."""

		if not self.source_file:
			return

		file_row = frappe.db.get_value(
			"File",
			self.source_file,
			["file_name", "file_url"],
			as_dict=True,
		)
		if not file_row:
			return

		if not self.source_filename and file_row.file_name:
			self.source_filename = file_row.file_name
		if not self.source_file_url and file_row.file_url:
			self.source_file_url = file_row.file_url

	def _require_source_reference(self) -> None:
		"""AC-I2: a capture must always carry a traceable source reference."""

		if not (self.source_file or self.source_file_url):
			raise AmbiguousSourceError(
				_("AP Invoice Capture requires a Source File or Source File URL.")
			)
		if not self.source_filename:
			raise AmbiguousSourceError(
				_("AP Invoice Capture requires a Source Filename for traceability.")
			)


def _normalize_extension(value: str) -> str:
	"""Return a lowercase extension without a leading dot.

	Accepts either a bare extension ("PDF", ".pdf") or a path/filename
	("invoice.PDF", "/private/files/invoice.PDF"). Returns "" if no
	extension can be determined.
	"""

	if not value:
		return ""

	candidate = value.strip().lower()
	if "." in candidate:
		# os.path.splitext handles both bare filenames and full paths.
		_, ext = os.path.splitext(candidate)
		candidate = ext

	candidate = candidate.lstrip(".")
	return candidate


def _resolve_filename(file_doc, explicit_filename: str | None) -> str:
	if explicit_filename:
		return explicit_filename
	if file_doc and getattr(file_doc, "file_name", None):
		return file_doc.file_name
	if file_doc and getattr(file_doc, "file_url", None):
		return os.path.basename(file_doc.file_url)
	return ""


def create_capture_from_file(
	file_doc=None,
	file_name: str | None = None,
	file_url: str | None = None,
	source_context: str | None = None,
	intake_channel: str = INTAKE_MANUAL_UPLOAD,
	received_at=None,
):
	"""Deterministic API for creating an AP Invoice Capture.

	Accepts either a Frappe ``File`` document (or its name) via
	``file_doc``, or a raw ``file_url`` / ``file_name`` pair. Always
	creates a capture record; if the source artifact is unsupported the
	capture is created in ``Unsupported`` status with ``action_required``
	set so it cannot silently progress.

	Returns the saved ``AP Invoice Capture`` document.
	"""

	resolved_file = None
	resolved_file_name = None
	if file_doc is not None:
		if isinstance(file_doc, str):
			resolved_file = frappe.get_doc("File", file_doc)
		else:
			resolved_file = file_doc
		resolved_file_name = resolved_file.name

	effective_filename = _resolve_filename(resolved_file, file_name)
	effective_url = file_url or (resolved_file.file_url if resolved_file else None)

	capture = frappe.new_doc("AP Invoice Capture")
	capture.intake_channel = intake_channel or INTAKE_MANUAL_UPLOAD
	capture.received_at = received_at or now_datetime()
	capture.source_filename = effective_filename
	capture.source_file = resolved_file_name
	capture.source_file_url = effective_url
	capture.source_context = source_context
	capture.insert()
	return capture


@frappe.whitelist()
def create_capture_from_uploaded_file(file_name: str, source_context: str | None = None):
	"""Whitelisted entrypoint for the manual ERPNext upload flow.

	``file_name`` is the ``name`` of an existing Frappe ``File`` record
	(the one created when the user uploads through the ERPNext UI).
	"""

	return create_capture_from_file(file_doc=file_name, source_context=source_context).name
