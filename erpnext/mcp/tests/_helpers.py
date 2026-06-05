# Copyright (c) 2026, NexeraDigital and contributors
# For license information, please see license.txt

"""Shared fixtures for MCP integration tests.

These build the things an MCP request needs end-to-end: an OAuth client + bearer
token, a simulated ``frappe.request``, and seeded AP data. Kept out of the test
modules so each suite reads cleanly.
"""

import json
import uuid

import frappe
from frappe.utils import add_to_date, now_datetime

_OAUTH_CLIENT_NAME = "mcp-test-client"


def enable_mcp(resource_uri: str | None = None, origins=None, protocols=None):
	"""Configure MCP Settings for a test (enabled, permissive origins)."""
	s = frappe.get_single("MCP Settings")
	s.enabled = 1
	s.require_tls = 0
	s.allowed_origins = json.dumps(origins or ["http://localhost", "http://testserver"])
	s.allowed_protocol_versions = json.dumps(protocols or ["2025-11-25", "2025-03-26"])
	s.oauth_resource_uri = resource_uri or ""
	s.save(ignore_permissions=True)
	frappe.clear_document_cache("MCP Settings", "MCP Settings")


def ensure_oauth_client() -> str:
	"""Return the name of a reusable test OAuth Client, creating it if needed."""
	existing = frappe.db.exists("OAuth Client", {"app_name": _OAUTH_CLIENT_NAME})
	if existing:
		return existing
	client = frappe.new_doc("OAuth Client")
	client.app_name = _OAUTH_CLIENT_NAME
	client.scopes = "all openid"
	client.redirect_uris = "http://localhost/callback"
	client.default_redirect_uri = "http://localhost/callback"
	client.grant_type = "Authorization Code"
	client.response_type = "Code"
	client.skip_authorization = 1
	client.insert(ignore_permissions=True)
	return client.name


def make_bearer_token(user: str, scopes: list[str]) -> str:
	"""Create an Active OAuth Bearer Token and return its access_token string."""
	access_token = f"mcp-test-{uuid.uuid4().hex}"
	token = frappe.new_doc("OAuth Bearer Token")
	token.client = ensure_oauth_client()
	token.user = user
	token.scopes = " ".join(scopes)
	token.access_token = access_token
	token.refresh_token = f"r-{uuid.uuid4().hex}"
	token.expires_in = 3600
	token.expiration_time = add_to_date(now_datetime(), hours=1)
	token.status = "Active"
	token.insert(ignore_permissions=True)
	return access_token


def set_mcp_request(payload: dict, token: str | None = None, origin: str | None = None,
		protocol_version: str | None = "2025-11-25", method: str = "POST"):
	"""Install a simulated MCP HTTP request as ``frappe.request``."""
	from frappe.utils import set_request

	headers = []
	if token:
		headers.append(("Authorization", f"Bearer {token}"))
	if origin:
		headers.append(("Origin", origin))
	if protocol_version:
		headers.append(("MCP-Protocol-Version", protocol_version))
	set_request(method=method, json=payload, headers=headers)


def body(response) -> dict:
	"""Parse a Werkzeug Response body as JSON."""
	return json.loads(response.get_data(as_text=True))


def cleanup_seeded_docs(records: list[tuple[str, str | None]]) -> None:
	"""Best-effort delete of docs seeded in ``setUpClass``.

	``IntegrationTestCase`` rolls back per-test and at class teardown, but our
	``make_submitted_pi`` path calls ``make_test_records(commit=True)`` mid-setup
	(see ``_ensure_erpnext_test_masters``), and that explicit commit flushes the
	seeded ``_MCP`` Supplier to disk — past the reach of the class rollback. So
	those rows persist across runs unless we delete them ourselves. Submitted
	docs are cancelled first; ``force=True`` bypasses link-existence checks
	(frappe ``delete_doc`` arg) so a Supplier deletes despite its PIs/GL entries.

	``records`` is ``(doctype, name)`` pairs in deletion order (children before
	parents). ``None``/missing names are skipped. A final commit makes the
	deletions durable past the class-cleanup rollback.
	"""
	frappe.set_user("Administrator")
	for doctype, name in records:
		if not name or not frappe.db.exists(doctype, name):
			continue
		try:
			doc = frappe.get_doc(doctype, name)
			if getattr(doc, "docstatus", 0) == 1:
				doc.cancel()
			frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
		except Exception:  # pragma: no cover - best-effort teardown
			pass
	frappe.db.commit()


def make_supplier(name: str) -> str:
	if not frappe.db.exists("Supplier", name):
		doc = frappe.new_doc("Supplier")
		doc.supplier_name = name
		doc.supplier_group = frappe.db.get_value("Supplier Group", {"is_group": 0}) or "All Supplier Groups"
		doc.insert(ignore_permissions=True)
		return doc.name
	return name


def _ensure_erpnext_test_masters():
	"""Provision erpnext's base test records (Customer, Supplier, Item, …).

	Importing erpnext's purchase_invoice test module instantiates
	``BootStrapTestData`` at module load, which assumes the standard ``_Test *``
	masters already exist. On a site where the full erpnext test suite hasn't run,
	create them via Frappe's dependency-resolving ``make_test_records`` so the import
	succeeds. Raises ``unittest.SkipTest`` if the environment cannot provide them.
	"""
	import unittest

	try:
		from frappe.tests.utils.generators import make_test_records

		for dt in ("Customer", "Supplier", "Item"):
			make_test_records(dt, commit=True)
	except Exception as e:  # pragma: no cover - environment-dependent
		raise unittest.SkipTest(f"erpnext test masters unavailable in this environment: {e}")


def make_submitted_pi(supplier: str, rate: float = 100.0, qty: float = 1):
	"""Create + submit a Purchase Invoice via erpnext's test helper."""
	import unittest

	_ensure_erpnext_test_masters()
	from erpnext.accounts.doctype.purchase_invoice.test_purchase_invoice import make_purchase_invoice

	try:
		pi = make_purchase_invoice(supplier=supplier, rate=rate, qty=qty, do_not_save=True)
		pi.insert(ignore_permissions=True)
		pi.submit()
	except Exception as e:  # pragma: no cover - environment-dependent
		raise unittest.SkipTest(f"could not seed a submitted Purchase Invoice: {e}")
	return pi
