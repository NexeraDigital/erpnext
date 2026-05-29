# Copyright (c) 2026, NexeraDigital and contributors
# For license information, please see license.txt

"""Rate-limit + concurrency integration tests (plan §7.1 #6, L12).

Exercise the real ``frappe.cache`` counters in ``audit.safe_execute``. Tool/user
names are randomized per test so cache windows never collide across runs.
"""

import uuid
from types import SimpleNamespace

from frappe.tests import IntegrationTestCase

from erpnext.mcp import audit
from erpnext.mcp.exceptions import MCPRateLimitError


def _ctx(user):
	return SimpleNamespace(
		user=user, client_id=None, session_id=None, protocol_version=None, ip_address=None
	)


def _ok():
	return {"ok": 1}


class TestRateLimit(IntegrationTestCase):
	def _names(self):
		token = uuid.uuid4().hex[:8]
		return f"u-{token}@example.com", f"tool-{token}"

	def test_under_limit_allowed(self):
		user, tool = self._names()
		cfg = {"rate_limit_per_minute": 3}
		for _ in range(3):
			self.assertEqual(audit.safe_execute(tool, _ctx(user), cfg, _ok, {}), {"ok": 1})

	def test_over_limit_rejected(self):
		user, tool = self._names()
		cfg = {"rate_limit_per_minute": 2}
		audit.safe_execute(tool, _ctx(user), cfg, _ok, {})
		audit.safe_execute(tool, _ctx(user), cfg, _ok, {})
		with self.assertRaises(MCPRateLimitError):
			audit.safe_execute(tool, _ctx(user), cfg, _ok, {})

	def test_zero_disables_rate_limit(self):
		user, tool = self._names()
		cfg = {"rate_limit_per_minute": 0}
		for _ in range(20):
			audit.safe_execute(tool, _ctx(user), cfg, _ok, {})  # no raise

	def test_concurrency_cap_enforced(self):
		import frappe

		user, tool = self._names()
		cfg = {"concurrency_cap": 2}
		key = audit._cc_key(user, tool)
		# Pre-seed the in-flight counter to the cap so the next entry trips it.
		frappe.cache.incrby(key, 2)
		frappe.cache.expire(key, 60)
		with self.assertRaises(MCPRateLimitError):
			audit.safe_execute(tool, _ctx(user), cfg, _ok, {})

	def test_concurrency_slot_released_after_call(self):
		import frappe
		from frappe.utils import cint

		user, tool = self._names()
		cfg = {"concurrency_cap": 1}
		# Two sequential calls both succeed because each releases its slot.
		audit.safe_execute(tool, _ctx(user), cfg, _ok, {})
		audit.safe_execute(tool, _ctx(user), cfg, _ok, {})
		self.assertEqual(cint(frappe.cache.get(audit._cc_key(user, tool))), 0)
