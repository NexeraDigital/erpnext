# Copyright (c) 2026, NexeraDigital and contributors
# For license information, please see license.txt

"""Auth unit tests (plan §7.1 #4/#5): bearer extraction, audience binding."""

import unittest
from types import SimpleNamespace

from erpnext.mcp import auth
from erpnext.mcp.exceptions import MCPAudienceError, MCPAuthError


def _request(headers=None, args=None):
	return SimpleNamespace(
		headers=SimpleNamespace(get=lambda k, d=None: (headers or {}).get(k, d)),
		args=SimpleNamespace(get=lambda k, d=None: (args or {}).get(k, d)),
	)


class TestBearerExtraction(unittest.TestCase):
	def test_missing_header_rejected(self):
		with self.assertRaises(MCPAuthError):
			auth._extract_bearer_token(_request())

	def test_non_bearer_scheme_rejected(self):
		with self.assertRaises(MCPAuthError):
			auth._extract_bearer_token(_request(headers={"Authorization": "Basic abc"}))

	def test_empty_bearer_rejected(self):
		with self.assertRaises(MCPAuthError):
			auth._extract_bearer_token(_request(headers={"Authorization": "Bearer "}))

	def test_token_in_query_string_rejected(self):
		req = _request(headers={"Authorization": "Bearer good"}, args={"access_token": "x"})
		with self.assertRaises(MCPAuthError):
			auth._extract_bearer_token(req)

	def test_valid_bearer_returns_token(self):
		token = auth._extract_bearer_token(_request(headers={"Authorization": "Bearer abc123"}))
		self.assertEqual(token, "abc123")


class TestScopeParsing(unittest.TestCase):
	def test_empty_scopes(self):
		self.assertEqual(auth._parse_scopes(None), [])
		self.assertEqual(auth._parse_scopes(""), [])

	def test_space_delimited(self):
		self.assertEqual(
			auth._parse_scopes("erpnext:ap_invoice:read erpnext:vendor:read"),
			["erpnext:ap_invoice:read", "erpnext:vendor:read"],
		)


class TestAudience(unittest.TestCase):
	def test_skipped_when_unconfigured(self):
		from erpnext.mcp import audience, config

		orig = config.oauth_resource_uri
		config.oauth_resource_uri = lambda: None
		try:
			# Should not raise.
			audience.validate_audience(["anything"])
		finally:
			config.oauth_resource_uri = orig

	def test_rejects_wrong_audience(self):
		from erpnext.mcp import audience, config

		orig = config.oauth_resource_uri
		config.oauth_resource_uri = lambda: "https://mcp.example.com"
		try:
			with self.assertRaises(MCPAudienceError):
				audience.validate_audience(["some:other:scope"])
		finally:
			config.oauth_resource_uri = orig

	def test_accepts_matching_resource_in_scopes(self):
		from erpnext.mcp import audience, config

		orig = config.oauth_resource_uri
		config.oauth_resource_uri = lambda: "https://mcp.example.com"
		try:
			audience.validate_audience(["https://mcp.example.com"])  # no raise
		finally:
			config.oauth_resource_uri = orig
