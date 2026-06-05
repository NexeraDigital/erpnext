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
from erpnext.accounts.ap_closed_loop.extractors.baml_provider import BamlReceiptProvider
from erpnext.accounts.ap_closed_loop.extractors.fake import FakeExtractor

# Registry keys are the values stored in AP Closed Loop Settings.ocr_provider's
# select options. "fake" is the default; "anthropic" is the hand-rolled Claude
# extractor; "baml" is the BAML cheap-vision reader (extract + classify in one call).
_PROVIDERS = {
	"fake": FakeExtractor,
	"anthropic": AnthropicExtractor,
	"baml": BamlReceiptProvider,
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
