# Business Case — Upgrading the Customer's ERPNext Install to v16

> **Status:** Recommendation (pending customer agreement to a one-time maintenance window).
>
> **Date drafted:** 2026-05-28.
>
> **Audience:** NexeraDigital pilot stakeholders, customer-side IT/finance leads making the v15-vs-v16 decision.
>
> **Inputs:** Live state of the customer UAT box (`erpnext-nexera-prod-1.tail670355.ts.net`), local fork state on `russ/bryanwork`, upstream `version-15` / `version-16` / `develop` branches of `frappe/frappe` and `frappe/erpnext`, official v16 release announcement (Jan 2026).
>
> **Grounding rule (per `CLAUDE.md`):** every factual claim cites either an upstream URL, a tag/branch in the Frappe or ERPNext source tree, or a file/path on the customer's host.

---

## 0. TL;DR

**Recommendation:** Upgrade the customer's UAT box from ERPNext **v15.108.3** to **v16 (current: v16.20.0)** before the AP closed-loop pilot accumulates production data. The bigger the box gets, the more expensive this upgrade becomes — today it's a half-day; in six months it's a multi-day project with downtime risk.

**The single strongest argument is timing, not features:**

> "You'll have to upgrade to v16 eventually because v15 is in maintenance-only mode. Doing it now while your install is essentially empty costs us half a day. Doing it in six months after the pilot is in production costs us several days and a downtime window — and you'd be running a year-old codebase in the meantime."

---

## 1. Context

| Where | Version | Branch / State |
|---|---|---|
| Customer UAT (`erpnext-nexera-prod-1.tail670355.ts.net`) | **erpnext 15.108.3 / frappe 15.108.0** | Stock upstream, no custom apps |
| NexeraDigital fork (`russ/bryanwork`) | **erpnext 17.0.0-dev / frappe 16.18.3** | Based on `develop` (= future v17, unreleased) |
| Upstream v16 GA | **2026-01-12** | Branch `version-16`, current tip `v16.20.0` (2026-05-27) |

The mismatch:
- Customer is on **stable v15**.
- The pilot fork is built on **pre-release v17** (`develop`).
- **v17 has not been released and cannot be deployed to a customer site.**

So the pilot has to land on either v15 or v16 before it can ship. The question is which.

---

## 2. Why v16 (not v15) for the rebase target

A separate analysis (this document's parent investigation) compared rebasing the fork to `version-15` vs `version-16`. v16 wins on engineering grounds for three reasons:

1. **Workspace model:** `erpnext/workspace_sidebar/invoicing.json` (which the fork edits) exists on `version-16` and is byte-identical to `develop`; it **does not exist on `version-15`** (v15 uses a different workspace structure under `erpnext/accounts/workspace/`).
2. **Test class:** the fork's test files import `from frappe.tests import IntegrationTestCase`. This class exists on `frappe/version-16` (`frappe/tests/classes/integration_test_case.py`) but **not on `frappe/version-15`** (v15 uses `FrappeTestCase` from `frappe/tests/utils.py`).
3. **Local toolchain:** the developer bench is already on `frappe 16.18.3` and `version-16`. A v15 rebase would also require downgrading the framework.

**Rebase effort:** ~2–3 hours for v16, vs ~half-day to a day for v15 — and the v15 work creates a permanent backport-maintenance burden every time the fork pulls upstream changes.

But the engineering argument alone is not enough to justify asking the customer to upgrade their box. The business argument below is.

---

## 3. Business reasons that justify upgrading to v16

### 3.1 Reasons specific to the AP closed-loop pilot

| v16 feature | Why it materially helps the pilot |
|---|---|
| **Standard print formats for Accounts Payable, Accounts Receivable, Trial Balance, and Financial Statements** (commits `1c6dc80b70`, `4e7f2eeaa0`, `1d08448d1a`, `3283c461f1` on `upstream/version-16`) | The AP pilot generates and reviews AP-side documents. On v15, every AP register / aging / payment confirmation print format would have to be custom-built. v16 ships them. Direct labor savings on the pilot, and one fewer surface to maintain in the fork. |
| **Item Wise Tax Details Table** (`feat!: #48692`, commit `91f3c82bdf` — flagged as `feat!` = breaking change) | Restructures how Purchase Invoice stores per-item tax detail. Every PI the pilot creates is affected. On v15 the AP automation would be written against the deprecated structure and would have to be reworked when the customer eventually moves to v16. |
| **Tax withholding entry** (`feat: Introduce tax withholding entry`, commit `c66f78c784`) and **multi-currency in expense claim / advance payment ledger** (commit `78da4c38fa`) | Material if any supplier flow involves withholding tax or non-USD invoicing. Both are absent from v15. |
| **Frappe Caffeine — ~2× faster page loads** (Frappe v16 performance upgrade, [release announcement](https://discuss.frappe.io/t/frappe-erpnext-and-frappe-hr-version-16-release/159053)) | The pilot UI is what the customer demonstrates to stakeholders. Page-load latency is the most visible difference between "this feels modern" and "this feels old." |
| **Espresso UI refresh — persistent sidebar, revamped navigation, refreshed list/form views** (Frappe v16 release announcement) | Direct perception win in stakeholder demos. v15's UI looks visibly dated next to v16. |

### 3.2 Reasons that matter for the customer as an ERPNext user over time

| Argument | Substance |
|---|---|
| **v15 is in maintenance-only mode.** | v16 was released **2026-01-12** after ~2 years of v15. From this point forward, v15 receives only security and critical bug fixes; new features ship on v16+. Staying on v15 is a commitment to a dead-end branch. |
| **The upgrade is inevitable.** | The customer will move to v16 (or v17) eventually. The cheapest possible moment is **before** they accumulate transactional data, custom workflows, or integrations. Their site currently has a 706 MB database, a 49 MB site directory, no custom apps, and 6 days of uptime since install. Migration patches will run in minutes. |
| **Multi-entity financial reporting.** | v16 introduces **Financial Report Templates** (formula-driven, customizable P&L and Balance Sheet, supports IFRS) and a **Consolidated Trial Balance Report** with automatic currency conversion. If the customer ever needs multi-company reporting, these are genuine new capabilities not available in v15. |
| **Quality / community signal.** | The v16 release is described by Frappe as "the most stable major release yet," backed by 600+ contributors and accumulating thousands of bug fixes. The v15 branch will not receive most of those fixes. |

### 3.3 Reasons that do NOT apply here (avoid using as justification)

To keep the argument honest, these v16 highlights from the release announcement are **not relevant** to this customer:

- **Material Requirements Planning (MRP) workflow** — customer is doing AP, not manufacturing
- **Inward Subcontracting** — same
- **Advanced stock reservation in Production Plans** — same
- **HR & Payroll improvements** — unless the customer plans to use those modules
- **No headline AI / LLM feature** could be substantiated from the official v16 announcement; do not claim one

Using irrelevant features in the customer pitch undermines credibility for the features that genuinely matter.

---

## 4. Cost / risk of the upgrade

### 4.1 What's already in place on the customer box (favorable)

| Component | Customer current | v16 requirement | OK? |
|---|---|---|---|
| OS | Ubuntu 24.04 LTS | any modern Linux | Yes |
| MariaDB | 10.11 | >=10.6 | Yes |
| Redis | 7.0 | >=6 | Yes |
| Disk free | 138 GB | ~5 GB | Yes |
| Custom apps | **none** | n/a | Yes (massive risk reducer) |
| Site data | 706 MB DB, 49 MB site dir | n/a | Yes (migration runs in minutes) |

### 4.2 What needs to change (the actual cost)

| Component | Customer current | v16 requirement | Difficulty |
|---|---|---|---|
| **Python** | 3.12.3 | **>=3.14, <3.15** (per `frappe/pyproject.toml` on `version-16` HEAD) | **Medium** — Python 3.14 isn't in Ubuntu 24.04's default repos; install via the deadsnakes PPA (`ppa:deadsnakes/ppa`) or pyenv, then rebuild the bench's Python venv. |
| **Node** | 18.20.8 | **>=24** (per `frappe/package.json` `engines.node` on `version-16` HEAD) | **Low** — install via NodeSource (`setup_24.x`). |
| **wkhtmltopdf** | 0.12.6 | same | No change |

### 4.3 Effort estimate

For a competent operator working on this specific box: **approximately half a day end-to-end**, broken down:

- 60 min — install Python 3.14 + Node 24, verify
- 30 min — rebuild bench venv on 3.14 + `bench setup requirements`
- 30 min — `bench switch-to-branch version-16 frappe erpnext --upgrade` + `bench build`
- 15 min — `bench --site … migrate` (fast — minimal data)
- 60 min — smoke-test the site, verify supervisor + nginx + asset serving
- Buffer for one likely wheel-compatibility hiccup (e.g. a Python C-extension that doesn't yet ship a 3.14 wheel)

### 4.4 Rollback

- If a VM snapshot is taken before starting: rollback is ~5 minutes
- If only `bench backup` is taken: rollback is ~10 minutes (restore SQL dump + site files)

Risk of an irrecoverable failure is low. The customer has no production data to lose.

---

## 5. Decision framing for the customer

If the customer is willing to authorize a **one-hour maintenance window** on the UAT box, the recommendation is unambiguous: **upgrade to v16 now**.

If they are not — or if the answer needs more than a week to arrive — the fallback is to rebase the fork to v15 and accept a permanent backport-maintenance burden. That path is workable but strictly more expensive long-term.

---

## 6. Recommended next steps (sequence)

1. **Confirm customer availability** for a one-hour maintenance window on the UAT box.
2. **Spin up a throwaway VM** that mirrors the customer config (Ubuntu 24.04, MariaDB 10.11, fresh v15.108.3 install) and dry-run the v16 install procedure end-to-end. Surfaces any Python 3.14 wheel-compatibility issues before touching the customer's box.
3. **Take a VM snapshot** of the customer's UAT box (preferred) or a `bench backup --with-files` (minimum).
4. **Execute the documented upgrade procedure** during the maintenance window — see § 4 of the v15→v16 upgrade research, or the upcoming `v16-upgrade-runbook.md`.
5. **Rebase `russ/bryanwork` onto `upstream/version-16`** — net-new files cherry-pick cleanly; only three small upstream-file edits need reapplying.
6. **Deploy the rebased fork** to the freshly-upgraded UAT box.

---

## 7. Sources

### Official Frappe / ERPNext

- [Frappe Forum — ERPNext, HRMS & Frappe Framework v16 Release Dates announcement](https://discuss.frappe.io/t/erpnext-hrms-frappe-framework-v16-release-dates/156349)
- [Frappe Forum — Frappe, ERPNext and Frappe HR Version 16 release announcement](https://discuss.frappe.io/t/frappe-erpnext-and-frappe-hr-version-16-release/159053)
- [Frappe — ERPNext Version 16 — Features & Updates](https://frappe.io/erpnext/version-16)
- [Frappe Blog — Product Updates for November 2025](https://frappe.io/blog/product-updates/product-updates-for-november-2025)
- [GitHub — frappe/erpnext releases](https://github.com/frappe/erpnext/releases)
- [GitHub — frappe/erpnext `version-16` branch](https://github.com/frappe/erpnext/tree/version-16)
- [GitHub — frappe/frappe `version-16` branch](https://github.com/frappe/frappe/tree/version-16)

### Third-party analyses (corroborating, not authoritative)

- [Indictrans — Frappe Framework v16 Release: Key Features & Impact](https://www.indictranstech.com/frappe-framework-v16-whats-new-in-2026/)
- [Indictrans — Frappe v16 Beta: What's New for ERPNext in 2026](https://www.indictranstech.com/frappe-v16-beta-whats-new-for-erpnext-in-2026/)
- [Kainotomo — ERPNext Latest News: What's New in Version 16 (2026 Update)](https://kainotomo.com/blogs/erpnext-v16)
- [Ksolves — ERPNext v16: Features, Release Date, and What to Expect](https://www.ksolves.com/blog/erpnext/erpnext-v16-check-expected-features-date-release-note-and-more)

### Customer-side facts (verified live on 2026-05-28 via SSH inspection)

- Customer host: `erpnext-nexera-prod-1.tail670355.ts.net`
- Bench location: `/home/frappe/frappe-bench`
- Installed apps and versions: `erpnext 15.108.3`, `frappe 15.108.0`
- OS: Ubuntu 24.04.4 LTS
- Python: 3.12.3 (system)
- Node: v18.20.8
- MariaDB: 10.11.14
- Redis: 7.0.15
- Database size: 706 MB total (`/var/lib/mysql/`)
- Site directory size: 49 MB
- Custom apps: none
- Bench installed: 2026-05-22 (6 days before this document)

### Repo-internal facts

- Fork branch: `russ/bryanwork`, currently at `67ede6bc77`
- Local frappe version: `16.18.3 version-16` at `69be97c`
- Local erpnext version string: `17.0.0-dev` (from `erpnext/__init__.py`)
- Fork ahead of `upstream/develop`: 36 commits, 69 files changed, 10,440 insertions, 4 deletions
- Drift `develop` ↔ `version-16`: 1,799 commits (v16 ahead) + 2,131 commits (develop ahead), common ancestor 2026-01-12
- Drift `develop` ↔ `version-15`: 8,409 commits (v15 ahead) + 11,365 commits (develop ahead), common ancestor 2023-10-19
