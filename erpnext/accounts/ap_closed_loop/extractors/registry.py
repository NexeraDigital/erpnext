# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""OCR provider registry.

Single lookup point mapping a provider name to an ``OCRProvider`` instance.
Phase 1 ships only the deterministic ``fake`` provider; Phase 2 registers the
Anthropic provider here, and ``run_extraction`` selects between them based on
``AP Closed Loop Settings.ocr_provider``.
"""

from __future__ import annotations

from erpnext.accounts.ap_closed_loop.extractors.anthropic import AnthropicExtractor
from erpnext.accounts.ap_closed_loop.extractors.base import OCRProvider
from erpnext.accounts.ap_closed_loop.extractors.fake import FakeExtractor

# Registry keys are the values stored in AP Closed Loop Settings.ocr_provider's
# select options. "fake" is the default until Phase 3 wires settings-driven
# selection; "anthropic" is the real Claude-backed provider (Phase 2).
_PROVIDERS = {
	"fake": FakeExtractor,
	"anthropic": AnthropicExtractor,
}


def get_extractor(name: str = "fake", **kwargs) -> OCRProvider:
	"""Return an OCRProvider instance for the named provider.

	Extra keyword args (e.g. ``model``, ``confidence_threshold``) are passed
	to the provider constructor; providers that don't use them ignore them.

	Raises ValueError for an unknown provider so a misconfigured setting
	fails loudly rather than silently skipping extraction.
	"""

	provider_cls = _PROVIDERS.get(name)
	if provider_cls is None:
		raise ValueError(
			f"Unknown OCR provider {name!r}. Registered: {', '.join(sorted(_PROVIDERS))}."
		)
	return provider_cls(**kwargs)
