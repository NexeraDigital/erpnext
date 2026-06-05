# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""Deterministic fake OCR provider.

Wraps the existing deterministic proposal logic in ``document_capture.py``
behind the ``OCRProvider`` interface. Produces exactly the same proposal,
missing-field, and ambiguous-field results as the pre-Phase-1 inline code, so
the test suite and cascade behaviour are byte-for-byte unchanged.

The proposal helpers (``_detect_simulation_markers``, ``_propose_for_seed``,
``_seed_for_capture``) still live in ``document_capture.py`` and are imported
lazily inside ``extract`` to avoid a circular import at module-load time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from erpnext.accounts.ap_closed_loop.extractors.base import (
	PROPOSAL_KEYS,
	ExtractionResult,
	OCRProvider,
)

if TYPE_CHECKING:
	from erpnext.accounts.doctype.document_capture.document_capture import (
		DocumentCapture,
	)


class FakeExtractor(OCRProvider):
	"""Deterministic, hash-seeded fake extractor used in tests and dev."""

	def __init__(self, **_kwargs):
		# Accept and ignore provider-config kwargs (model, confidence_threshold,
		# etc.) so the registry can pass a uniform config to any provider.
		pass

	def name(self) -> str:
		# Lazy import keeps module load cycle-free; the constant is the single
		# source of truth for the provider id.
		from erpnext.accounts.doctype.document_capture.document_capture import (
			FAKE_OCR_PROVIDER,
		)

		return FAKE_OCR_PROVIDER

	def extract(
		self,
		capture: "DocumentCapture",
		*,
		simulate_missing: list[str] | tuple[str, ...] | None = None,
		simulate_ambiguous: list[str] | tuple[str, ...] | None = None,
	) -> ExtractionResult:
		from erpnext.accounts.doctype.document_capture.document_capture import (
			FAKE_OCR_PROVIDER,
			_detect_simulation_markers,
			_propose_for_seed,
			_seed_for_capture,
		)

		# Filename-driven simulation markers, then explicit caller overrides —
		# identical merge order to the pre-Phase-1 inline implementation.
		filename_missing, filename_ambiguous = _detect_simulation_markers(
			capture.source_filename or ""
		)
		missing_fields: set[str] = set(filename_missing)
		ambiguous_fields: set[str] = set(filename_ambiguous)
		if simulate_missing:
			missing_fields.update(simulate_missing)
		if simulate_ambiguous:
			ambiguous_fields.update(simulate_ambiguous)

		proposal = _propose_for_seed(_seed_for_capture(capture))
		# Strip values for any field marked missing (mirrors the old behaviour:
		# a missing field is dropped from the proposal, not just flagged).
		for logical_name in missing_fields:
			if logical_name in proposal:
				proposal[logical_name] = None

		# Per-field confidence (spec 04): the fake provider has no model score, so
		# it derives one from clarity — missing -> 0.0, ambiguous -> 0.5, clear ->
		# 0.95 — one entry per logical key, all tagged Derived-Mapping so routing
		# (spec 09) never mistakes a stand-in for a real model score. Deterministic
		# (depends only on the missing/ambiguous sets). lines stays [] by default.
		confidence: dict[str, float] = {}
		score_sources: dict[str, str] = {}
		for logical_name in PROPOSAL_KEYS:
			if logical_name in missing_fields:
				confidence[logical_name] = 0.0
			elif logical_name in ambiguous_fields:
				confidence[logical_name] = 0.5
			else:
				confidence[logical_name] = 0.95
			score_sources[logical_name] = "Derived-Mapping"

		return ExtractionResult(
			proposal=proposal,
			missing_fields=missing_fields,
			ambiguous_fields=ambiguous_fields,
			provider_name=FAKE_OCR_PROVIDER,
			confidence=confidence,
			score_sources=score_sources,
		)
