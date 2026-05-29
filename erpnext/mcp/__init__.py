"""ERPNext MCP (Model Context Protocol) server.

A secure, audit-logged, permission-respecting MCP tool surface over AP data.
See ``docs/planning/mcp-server-plan.md`` and ``docs/changes/ADR-MCP-5-vendor-frappe-mcp-transport.md``.

The JSON-RPC + Streamable-HTTP transport is a vendored copy of ``frappe/mcp``
(MIT) under ``_vendor/`` (see ``_vendor/PROVENANCE.md``). The vendored package
keeps its absolute ``frappe_mcp.*`` imports, so we put ``_vendor/`` on ``sys.path``
here to make ``import frappe_mcp`` resolve to the vendored copy without editing it.
"""

import os
import sys

_VENDOR_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_vendor")
if _VENDOR_DIR not in sys.path:
	# Prepend so the vendored, pinned copy wins even if the real ``frappe/mcp``
	# app is ever installed alongside this fork.
	sys.path.insert(0, _VENDOR_DIR)
