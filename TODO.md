# Project TODO

Single source of truth for **persistent, outstanding work** on the AP Closed Loop pilot.
If a task outlives the current session/PR, it lives here. Ephemeral, within-a-single-task
steps belong in the in-session todo scratchpad (see `CLAUDE.md` → "Todo management"), not here.

> Maintained by humans and by Claude. Keep it greppable: one task per top-level bullet,
> stable IDs, never reuse an ID, never silently delete — completed work moves to **Done**.

---

## How this file works

**ID scheme.** Every task gets a stable, monotonic ID `T-NNN` (zero-padded to 3+ digits).
The next free ID is tracked in the counter below — bump it whenever you add a task.

- **Next ID:** `T-010`

**Priority labels.**

| Label | Meaning |
|---|---|
| `P0` | Drop-everything: blocking the pilot, broken main, data-loss risk |
| `P1` | Important, scheduled for the current milestone |
| `P2` | Should do, not yet scheduled |
| `P3` | Nice-to-have / someday |

**Statuses** are expressed by which section a task sits in: **In Progress**, **Backlog**,
**Blocked**, **Done**. Move the whole bullet between sections as status changes — keep its ID.

**Task line format** (everything after the title is optional but encouraged):

```
- [ ] **T-001** Short imperative title — one-line description.
      _(P1 · added 2026-05-31 · owner @rsmith · ref: docs/spec/04-...md, #123)_
```

- Use the checkbox: `[ ]` open, `[x]` done.
- `ref:` links context — a spec, planning doc, PR/issue number, or `path:line`. Prefer a link over re-explaining.
- On completion: check the box, append `· done YYYY-MM-DD`, and move the bullet to **Done**.

---

## In Progress

_Nothing in progress._

## Backlog

- [ ] **T-001** Install `poppler-utils` on every worker host — unblocks spec-03 PDF perceptual dedupe (currently degrades to exact-hash-only for PDF inputs; `test_real_phash_pdf_branch` skips). Confirm `imagehash` + `pdf2image` in each worker venv too.
      _(P1 · added 2026-05-31 · ref: docs/spec/STATUS.md decision #5; deploy task, not a code blocker)_
- [ ] **T-002** Bring up the MCP server on a migrated site — `bench migrate`, confirm the 5 `MCP Tool Config` rows seed, run the ~61 integration tests, then a live MCP Inspector OAuth round-trip. This is the top of the MCP critical path (built + committed, not yet verified on a migrated site).
      _(P1 · added 2026-05-31 · ref: docs/planning/mcp-server-NEXT-STEPS.md §2 · state-changing — needs approval)_
- [ ] **T-003** Execute the §7.3 Playwright UI pass for specs 01–04 (clean-room browser verification). Automated ACs are green; the UI gate is still pending.
      _(P2 · added 2026-05-31 · ref: docs/spec/STATUS.md verification-state notes)_
- [ ] **T-004** Triage the MCP pre-production caveats before any non-loopback deploy — negotiated-version echo, malformed-JSON → `-32700`, mandatory `oauth_resource_uri` for RFC 8707, and finalize open decisions O2/O3/O4 → record ADRs.
      _(P2 · added 2026-05-31 · ref: docs/planning/mcp-server-NEXT-STEPS.md §3–§4)_
- [ ] **T-005** Wire the MCP §7.2 canaries + DB-free unit tests into the repo's CI so they run on every PR touching `erpnext/mcp/`.
      _(P2 · added 2026-05-31 · ref: docs/planning/mcp-server-NEXT-STEPS.md §3 item 7)_
- [ ] **T-006** Remove the `.claude/worktrees/mcp-server` gitlink artifact (`git worktree remove`) once the MCP work is merged, so it isn't committed accidentally.
      _(P3 · added 2026-05-31 · ref: docs/planning/mcp-server-NEXT-STEPS.md §3 item 6)_
- [ ] **T-009** Consider an extra chat-specific scope-limit control for the AI chat panel — a per-tool `chat_enabled` flag (on `MCP Tool Config`) letting ops restrict the AI's tool surface *more tightly than* a user's own role/permissions. Not a security boundary (Frappe RBAC already binds the chat to the calling user's access); add only if a concrete governance/compliance requirement appears. Cheap to add later, no rework of the chat plan.
      _(P3 · added 2026-05-31 · ref: docs/planning/ai-chat-panel-brief.md; deferred from AI-chat-panel security design discussion)_

## Blocked

- [ ] **T-007** Execute spec-04 §7.2 clean-room runbooks — real-Anthropic per-field confidence + line-items-promote. Runbooks are written; not yet run.
      _(P2 · added 2026-05-31 · ref: docs/spec/STATUS.md verification-state (04) · blocked: needs a live Anthropic API key)_
- [ ] **T-008** Lock the open v2 gating decisions — #1 Stream-R posting model, #2 retire no-Bank-Transaction guardrail (+ADR), #3 `allow_self_approval` on v16, #7 native `Authorization Rule` vs custom matrix, #8 SimpleFIN vs Plaid, #9 native uniqueness check. Each gates downstream specs (07/11/13/14).
      _(P1 · added 2026-05-31 · ref: docs/spec/STATUS.md "Decisions to lock first" · blocked: awaiting accounting lead / Brandon)_

## Done

_Completed tasks are archived here newest-first, with their `done YYYY-MM-DD` date. Never delete — this is the audit trail._
