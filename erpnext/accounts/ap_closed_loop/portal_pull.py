# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""Vendor portal-pull intake adapter base (spec 02 §5.3.5).

Phase-3 SEAM ONLY — this module ships the abstract base + a registry and NO
concrete vendor adapter. It mirrors the OCR extractors' registry contract
(``erpnext.accounts.ap_closed_loop.extractors.registry``): an unknown adapter
key raises ``ValueError`` so a misconfiguration fails loudly rather than
silently skipping intake.

A concrete adapter would ``pull()`` a list of ``PulledDocument``s from a vendor
portal and feed each through
``ap_invoice_capture.create_capture_from_file(..., intake_channel="Vendor Portal Pull",
received_at=<portal timestamp>)``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime


@dataclass
class PulledDocument:
	"""One artifact pulled from a vendor portal."""

	file_name: str
	content: bytes
	received_at: datetime | None = None
	source_context: str | None = None


class PortalPullAdapter(ABC):
	"""Interface every vendor portal-pull adapter implements."""

	@abstractmethod
	def name(self) -> str:
		"""Stable adapter identifier."""

	@abstractmethod
	def pull(self) -> list[PulledDocument]:
		"""Return the documents currently available from the portal."""


# Registry of adapter name -> class. Empty in Phase 3 (no concrete adapter).
_ADAPTERS: dict[str, type[PortalPullAdapter]] = {}


def register_portal_adapter(
	name: str,
) -> Callable[[type[PortalPullAdapter]], type[PortalPullAdapter]]:
	"""Class decorator that registers a PortalPullAdapter under ``name``."""

	def _decorator(cls: type[PortalPullAdapter]) -> type[PortalPullAdapter]:
		_ADAPTERS[name] = cls
		return cls

	return _decorator


def get_portal_adapter(name: str, **kwargs) -> PortalPullAdapter:
	"""Return an adapter instance for ``name``; raise ValueError if unknown."""

	adapter_cls = _ADAPTERS.get(name)
	if adapter_cls is None:
		registered = ", ".join(sorted(_ADAPTERS)) or "(none)"
		raise ValueError(f"Unknown portal adapter {name!r}. Registered: {registered}.")
	return adapter_cls(**kwargs)
