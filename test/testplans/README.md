# Test Plans — index

Clean-room runbooks for independent, external verification of this fork's features (see `CLAUDE.md` → "Test plans"). Each is self-contained: a fresh Claude instance with no prior context executes it on a clean bench. Local `bench run-tests` is the automated regression guard; these plans are the human/UI end-to-end gate.

## Layout (kept in subfolders — never a flat dump)

| Folder | What lives here | Naming |
|---|---|---|
| `specs/` | v2 AP-workflow spec runbooks (`docs/spec/01`–`14`) | `NN-<slug>.md`, `NN` = spec number (sorts in build order) |
| `ocr/` | Real-OCR build phases (the OCR provider work, phases 0–6) | `phaseN-<slug>.md` |
| `platform/` | Non-AP-workflow features | `<slug>.md` |
| `screenshots/` | Committed browser-smoke evidence | one subfolder per plan, named after the plan **basename** (`screenshots/05-supplier-resolution-3tier/…`) |
| *(root)* | Infra/setup runbooks + this index | `BROWSER-TESTING-SETUP.md`, `README.md` |

**Screenshots carry the number.** A plan's screenshot folder is named exactly after the plan's basename, so `specs/05-supplier-resolution-3tier.md` → `screenshots/05-supplier-resolution-3tier/`. Never mix two features' shots in one folder.

## Index

### `specs/` — v2 AP workflow (`docs/spec/STATUS.md` tracks build status)
| Plan | Spec | Screenshots |
|---|---|---|
| `specs/01-foundations-settings-async-idempotency.md` | 01 — Foundations (settings, idempotency, async runner) | `screenshots/01-foundations-settings-async-idempotency/` |
| `specs/02-intake-stream-tagging.md` | 02 — Intake & stream tagging | — |
| `specs/02-intake-email-inbound.md` | 02 — Email intake adapter | — |
| `specs/03-deduplication.md` | 03 — Pre-extraction dedup (exact + perceptual) | — |
| `specs/04-extraction-per-field-confidence.md` | 04 — Per-field confidence | — |
| `specs/04-extraction-line-items-promote.md` | 04 — Line items + line-aware promote | — |
| `specs/05-supplier-resolution-3tier.md` | 05 — Supplier resolution (3-tier) + gated creation | `screenshots/05-supplier-resolution-3tier/` |
| `specs/06-gl-coding-tax-costcenter.md` | 06 — GL coding, cost center & tax assignment | `screenshots/06-gl-coding-tax-costcenter/` |
| `specs/07-classification-doctype-branching.md` | 07 — Document-type classification & doctype branching | `screenshots/07-classification-doctype-branching/` |
| `specs/08-validation-gates.md` | 08 — Validation gates: 3-way match, anomaly, vendor bank-change | `screenshots/08-validation-gates/` |
| `specs/09-confidence-routing.md` | 09 — Confidence-based routing (auto-advance vs Needs-Review) | `screenshots/09-confidence-routing/` |
| `specs/10-ap-review-observability.md` | 10 — AP review: reject/reopen + AP Review Event + root-cause report | `screenshots/10-ap-review-observability/` |
| `specs/11-approval-sod-workflow.md` | 11 — Approval & SoD (pilot: app-code SoD guard + roles + bank-change Treasury) | `screenshots/11-approval-sod-workflow/` |

### `ocr/` — real-OCR build phases
| Plan | Phase |
|---|---|
| `ocr/phase0-ai-provider-settings.md` | 0 — AI Provider Settings (shared credentials) |
| `ocr/phase1-adapter.md` | 1 — provider adapter seam |
| `ocr/phase2-real-ocr-anthropic.md` | 2 — Anthropic Claude extractor |
| `ocr/phase3-settings.md` | 3 — settings-driven provider selection |
| `ocr/phase4-fallback.md` | 4 — low-confidence Haiku→Sonnet fallback |
| `ocr/phase5-audit.md` | 5 — audit logging & cost tracking |
| `ocr/phase6-hardening.md` | 6 — retry / circuit breaker / size guard |

### `platform/` — non-AP-workflow features
| Plan | Feature |
|---|---|
| `platform/ai-chat-panel.md` | Context-aware desk AI chat panel (read-only v1) |

### Root
| File | Purpose |
|---|---|
| `BROWSER-TESTING-SETUP.md` | One-time Playwright MCP setup (machine-specific; `.mcp.json` gitignored) |

> **Adding a plan:** create it in the right subfolder with the numbered name, add its row here, and put its browser-smoke screenshots under `screenshots/<plan-basename>/`. Future specs (06–14) get `specs/NN-<slug>.md` when they land.
