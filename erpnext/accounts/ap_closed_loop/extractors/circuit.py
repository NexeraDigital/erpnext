# Copyright (c) 2026, Nexera and Contributors
# License: GNU General Public License v3. See license.txt

"""A tiny process-local circuit breaker for the OCR provider.

When the provider is unhealthy (repeated rate-limit / 5xx / timeout failures),
hammering it just piles up slow-failing captures. After N consecutive failures
the breaker "opens" for a cooldown window and new calls fail fast with a clear
error; the first call after the cooldown is allowed (half-open) and a success
resets it.

Process-local only — no shared/distributed state. That's deliberate: it's a
courtesy backstop against a flapping provider within one worker, not a
cluster-wide guarantee. The clock is injectable so tests are deterministic.
"""

from __future__ import annotations

import time

import frappe

DEFAULT_FAILURE_THRESHOLD = 5
DEFAULT_COOLDOWN_SECONDS = 60.0


class CircuitOpenError(frappe.ValidationError):
	"""Raised when the breaker is open (provider considered temporarily down)."""


class CircuitBreaker:
	def __init__(self, failure_threshold=DEFAULT_FAILURE_THRESHOLD,
	             cooldown_seconds=DEFAULT_COOLDOWN_SECONDS, clock=time.monotonic):
		self.failure_threshold = failure_threshold
		self.cooldown_seconds = cooldown_seconds
		self._clock = clock
		self._failures = 0
		self._opened_at = None

	def check(self) -> None:
		"""Raise CircuitOpenError if the breaker is open and still cooling down.
		Transitions to half-open (allows one trial call) once cooldown elapses."""
		if self._opened_at is None:
			return
		elapsed = self._clock() - self._opened_at
		if elapsed < self.cooldown_seconds:
			raise CircuitOpenError(
				frappe._(
					"OCR provider temporarily unavailable (circuit open after "
					"repeated failures). Retry in ~{0}s."
				).format(int(self.cooldown_seconds - elapsed))
			)
		# cooldown elapsed -> half-open: let the next call through as a trial.
		self._opened_at = None

	def record_success(self) -> None:
		self._failures = 0
		self._opened_at = None

	def record_failure(self) -> None:
		self._failures += 1
		if self._failures >= self.failure_threshold:
			self._opened_at = self._clock()

	@property
	def is_open(self) -> bool:
		return self._opened_at is not None


# Shared breaker for the live AnthropicExtractor (one per worker process).
_SHARED_BREAKER = CircuitBreaker()


def shared_breaker() -> CircuitBreaker:
	return _SHARED_BREAKER
