# Vendored: `frappe/mcp`

This directory contains a **vendored copy** of the transport layer of
[`frappe/mcp`](https://github.com/frappe/mcp), per `docs/changes/ADR-MCP-5-vendor-frappe-mcp-transport.md`.

- **Upstream:** https://github.com/frappe/mcp
- **License:** MIT (see `LICENSE` in this directory — `Copyright (c) 2025 Alan <me@18alan.space>`)
- **Pinned commit:** `0ea7d0ebfb4ff7244a1ee1b3d6b37ffdfa0f2611` (2025-11-06)
- **Vendored on:** 2026-05-28

## What was copied

The JSON-RPC dispatch + Werkzeug transport bridge only:

```
frappe_mcp/__init__.py
frappe_mcp/server/__init__.py
frappe_mcp/server/server.py          # MCP class: dispatch + handle()
frappe_mcp/server/handlers.py        # initialize/ping (+ NotImplementedError stubs)
frappe_mcp/server/types.py           # JSON-RPC + MCP pydantic types
frappe_mcp/server/tools/__init__.py  # Tool TypedDict, get_tool, run_tool
frappe_mcp/server/tools/handlers.py  # handle_call_tool / handle_list_tools
frappe_mcp/server/tools/tool_schema.py
```

## What was NOT copied

- `frappe_mcp/cli/**` — the dev CLI; not needed at runtime.
- `frappe_mcp/server/tests/**`, `frappe_mcp/server/tools/test_*.py` — upstream's own tests.

## Modifications to vendored code

**One minimal patch**, marked inline with `# VENDOR PATCH` comments:

- `frappe_mcp/server/tools/__init__.py` — the `from jsonschema import validate`
  import is made **lazy** (moved into `run_tool`). Upstream imports it at module
  top, but `run_tool` is the only consumer and the ERPNext MCP server never calls
  it (our `handle_call_tool` path validates arguments with Pydantic instead).
  `jsonschema` is not in the bench environment, so a top-level import would break
  `import frappe_mcp`. No behavioral change for any code path we use.

Everything else is byte-for-byte identical to upstream at the pinned commit. The
package keeps its absolute `frappe_mcp.*` imports; `erpnext/mcp/__init__.py`
inserts this `_vendor/` directory onto `sys.path` so `import frappe_mcp` resolves
to this copy. All other adaptation (Pydantic schema injection, auth, L1 transport
checks, audit) lives in our own `erpnext/mcp/*.py` modules that wrap the vendored
`MCP` class.

## Seams we patch in our own code (NOT here)

See ADR-MCP-5 §"Three seams". Briefly: (1) we inject Pydantic-generated
`input_schema`/`output_schema` via `MCP.add_tool` instead of its
signature-inferred schema; (2) tool-execution errors are returned as MCP
`isError` content by the vendored `handle_call_tool` (spec-correct) — our
`endpoint.py` owns the protocol-level JSON-RPC error mapping, which the vendored
`MCP._handle_request` already does correctly (`-32601/-32602/-32700`); (3) we add
Origin + `MCP-Protocol-Version` validation in `endpoint.py`.

## Re-syncing

To update: re-clone upstream, check out the new commit, copy the same file set,
update the pinned SHA above and in ADR-MCP-5, and re-run the MCP test suite.
