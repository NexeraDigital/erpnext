# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""OCR provider abstraction for Document Capture.

Phase 1 of the real-OCR work (see docs/planning/real-ocr-implementation-plan.md):
introduces a thin seam so the deterministic fake extractor and a future real
provider (Anthropic Claude, etc.) are interchangeable. The state machine,
cascade, field-writing, and human-review flow in ``document_capture.py`` do
NOT change — they consume an ``ExtractionResult`` regardless of which provider
produced it.

A provider's only job is: given a capture, produce a header-level proposal
plus the set of fields that are missing (absent from the proposal) or
ambiguous (present but low-confidence). It does NOT write to the DocType,
change status, or save — that remains the caller's responsibility so the
audit trail and review semantics stay in one place.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from erpnext.accounts.doctype.document_capture.document_capture import (
		DocumentCapture,
	)

# Logical proposal keys, mirroring MANDATORY_HEADER_FIELDS in document_capture.
PROPOSAL_KEYS = (
	"supplier",
	"supplier_invoice_no",
	"invoice_date",
	"total_amount",
	"currency",
)


@dataclass
class ExtractionResult:
	"""Provider-agnostic output of an OCR extraction.

	``proposal`` is a dict keyed by the logical names in ``PROPOSAL_KEYS``.
	A value of ``None`` means the provider could not read that field
	(equivalently, the field name appears in ``missing_fields``).

	``missing_fields`` — mandatory fields the provider could not extract.
	``ambiguous_fields`` — fields the provider extracted but with low
	confidence; still proposed, but flagged for human attention.

	``provider_name`` — stable identifier written to ``ocr_provider`` and
	embedded in ``ocr_raw_response`` (e.g. ``"fake-deterministic-v1"``).

	``raw_response`` — optional provider-specific payload. Phase 1 leaves it
	empty (the caller builds the fake raw response for backward compatibility);
	real providers (Phase 2+) populate it with the model's full response.

	``confidence`` — numeric per-field score in 0..1 (spec 04), keyed by the
	logical proposal name for header fields and ``line_<i>_<field>`` for line
	rows. Empty when a provider emits no scores; the controller then derives a
	mapping stand-in tagged ``Derived-Mapping``.

	``lines`` — extracted line items; each dict carries
	description/qty/rate/amount/tax_amount/expense_account/cost_center/
	po_reference/pr_reference and an optional per-line ``confidence`` dict.
	"""

	proposal: dict
	missing_fields: set[str] = field(default_factory=set)
	ambiguous_fields: set[str] = field(default_factory=set)
	provider_name: str = ""
	raw_response: dict = field(default_factory=dict)
	confidence: dict = field(default_factory=dict)
	lines: list[dict] = field(default_factory=list)
	# Per-field provenance, keyed like ``confidence``: "Model" (a real numeric
	# score from the provider) or "Derived-Mapping" (a clarity-derived stand-in).
	# The controller writes it to Document Capture Confidence.score_source so
	# routing (spec 09) never over-trusts a fallback score.
	score_sources: dict = field(default_factory=dict)


class OCRProvider(ABC):
	"""Interface every OCR extractor implements."""

	@abstractmethod
	def name(self) -> str:
		"""Stable provider identifier written to ``ocr_provider``."""

	@abstractmethod
	def extract(
		self,
		capture: "DocumentCapture",
		*,
		simulate_missing: list[str] | tuple[str, ...] | None = None,
		simulate_ambiguous: list[str] | tuple[str, ...] | None = None,
	) -> ExtractionResult:
		"""Produce a header-level proposal for the given capture.

		``simulate_missing`` / ``simulate_ambiguous`` are test affordances
		honoured by the fake provider; real providers ignore them (their
		missing/ambiguous sets come from the model's own confidence).
		"""
