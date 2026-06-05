# Plan — Migrate Local Fork from v17 (`develop`) to v16 (`version-16`)

> **Status:** Plan only. **Do not execute without explicit go-ahead.**
>
> **Date drafted:** 2026-05-28.
>
> **Scope:** Rebase the NexeraDigital ERPNext fork (`russ/bryanwork`) from its current base (`upstream/develop`, version string `17.0.0-dev`) onto `upstream/version-16` (current tip `v16.20.0`). Local-only work; does not touch the customer's UAT box.
>
> **Inputs:** `docs/planning/v16-upgrade-business-case.md` (motivation), `docs/architecture/FORK-CHANGES.md` (current fork scope), live inspection of `russ/bryanwork` and `upstream/version-16` on 2026-05-28.
>
> **Grounding rule (per `CLAUDE.md`):** every command and claim cites either an upstream URL, a tag/branch in `frappe/frappe` or `frappe/erpnext`, or a path in the local working tree.

---

## 0. TL;DR

- The local **frappe** app is already on `version-16` (`v16.18.3`). **Only erpnext needs to move.**
- The literal `git rebase upstream/version-16` is not the right approach — the fork sits on top of `upstream/develop`, which is 3,930 commits diverged from `version-16`, and the fork's 36 commits include 10 merge commits that become meaningless on v16.
- The right approach is **branch + selective port**: create a new branch from `upstream/version-16`, copy the fork-only files in unchanged, and reapply the 3 small upstream-file edits.
- All 3 upstream-file edits have been verified to **apply cleanly to v16** (specific lines unchanged or files byte-identical).
- Expected effort: **2–3 hours**, mostly verification rather than porting.

---

## 1. Current state (verified 2026-05-28)

| Component | State |
|---|---|
| Bench root | `/home/rsmith/frappe-bench` |
| Local site | `erpnext.localhost` |
| `apps/frappe` branch | `version-16` at `v16.18.3` (commit `69be97c`) — **no change needed** |
| `apps/erpnext` branch | `russ/bryanwork` at `67ede6bc77`, based on `upstream/develop` |
| `apps/erpnext` version string | `17.0.0-dev` (from `erpnext/__init__.py`) |
| Remotes | `origin` → `NexeraDigital/erpnext.git`, `upstream` → `frappe/erpnext.git` |

### Fork scope (what we are porting)

From `git diff --stat upstream/develop..HEAD` (run 2026-05-28):

- **69 files changed**, 10,440 insertions, **4 deletions**
- ~95% net-new (docs/, .tmp/, AGENTS.md, CLAUDE.md, AP closed-loop python/json/JS)
- Three modified upstream files:
  - `erpnext/setup/utils.py` — 1-line change inside `_enable_all_roles_for_admin`
  - `erpnext/tests/utils.py` — 7-line change (adds `ignore_if_duplicate=True` and a comment)
  - `erpnext/workspace_sidebar/invoicing.json` — adds 2 sidebar links (Invoice Capture, AP Closed Loop Settings)

### Compatibility of fork-touched files with v16 (verified)

| File | v16 vs develop status | Fork edit applies to v16? |
|---|---|---|
| `erpnext/tests/utils.py` | **Byte-identical** (`git diff upstream/version-16..upstream/develop -- erpnext/tests/utils.py` is empty) | Yes, cleanly |
| `erpnext/workspace_sidebar/invoicing.json` | **Byte-identical** | Yes, cleanly |
| `erpnext/setup/utils.py` | Minor divergence (an unrelated import line and a signature change on `get_exchange_rate`). The specific 5 lines the fork patches (`_enable_all_roles_for_admin`'s `frappe.db.get_values("Has Role", ...)` call) are **unchanged on v16** | Yes, cleanly |

### v17-only API risk: no hits

Searched `git log upstream/version-16..upstream/develop --grep="^feat!"` restricted to `erpnext/accounts/`, `erpnext/buying/`, `erpnext/setup/` — **no breaking commits in fork-adjacent paths**. The Frappe APIs the fork uses (`frappe.get_doc`, `frappe.get_all`, `frappe.db.*`, `frappe.enqueue`, `frappe.only_for`, `frappe.flags.*`, `frappe.tests.IntegrationTestCase`) all exist on `frappe/version-16`.

---

## 2. Strategy: branch + selective port (not `git rebase`)

### Why not literal `git rebase upstream/version-16`?

The fork's 36 commits include 10 merge commits from `upstream/develop` (e.g. `8b11c57c83 Merge upstream/develop into russ/bryanwork`). Rebasing replays those as no-op merges into v16, producing noise and conflict cascades for no benefit. The substantive content of the fork is in ~25 non-merge feature commits, and even those reference develop-era state.

### Why selective port works

The fork is 95% additive (net-new files under `erpnext/accounts/ap_closed_loop/`, `erpnext/accounts/doctype/document_capture/`, `erpnext/accounts/doctype/ap_closed_loop_settings/`, `docs/`, `.tmp/`, `AGENTS.md`, `CLAUDE.md`). Those files can be copied across without modification because nothing on v16 has anything with the same names. The 3 modified upstream files are small and patches apply cleanly (verified above).

We will produce one or a small number of clean commits on the new branch rather than preserving the fork's noisy history.

---

## 3. Pre-flight checklist (do BEFORE the migration)

### 3.1 Source control safety

- [ ] **Confirm `russ/bryanwork` is pushed to `origin`.** Verify with: `git log --oneline @{u}..HEAD` returns empty. If not empty, push first; the migration creates new branches but should never lose existing commit reachability.
- [ ] **Tag the current fork tip for easy reference.** Suggested: `git tag pre-v16-migration russ/bryanwork && git push origin pre-v16-migration`. Lets us diff or revert later. Not a state change to working tree.
- [ ] **Verify clean working tree.** `git status` must be clean. Stash or commit any unrelated work first.
- [ ] **Fetch upstream.** `git fetch upstream version-16` so we have the latest v16 tip.

### 3.2 Local environment safety

- [ ] **`bench backup` the local site.** The local `erpnext.localhost` site has whatever pilot data has been built up. `bench --site erpnext.localhost backup --with-files` writes to `sites/erpnext.localhost/private/backups/`. Quick, cheap, recoverable.
- [ ] **Note current `bench version` output** for before/after comparison. Save the output to a scratch file.
- [ ] **Confirm `apps/frappe` is on `version-16`** (already verified — `v16.18.3` on `version-16` branch). No frappe-side work needed.

### 3.3 Decisions to confirm before starting

- **History style on the new branch:** one squashed commit vs. preserving the ~10 logical feature groupings vs. cherry-picking individual commits. **Recommendation: one squashed commit titled `feat: rebase AP closed-loop pilot onto upstream/version-16` with the original commit summaries listed in the body.** Cleaner history; the original `russ/bryanwork` stays as the pre-migration tag for archaeology.
- **Branch name:** propose `russ/bryanwork-v16`. Keep the old branch alive (do not delete) until the new one is verified.
- **Whether to also update the customer-deployment doc paths:** `docs/planning/v16-upgrade-business-case.md` already references this migration as step 5; no change needed.

---

## 4. Migration steps

> Each step lists the **command(s)**, **what they do**, and a **verification** to run before proceeding to the next step. Commands are written for the bench root unless noted.

### Step 1 — Snapshot the existing fork

```
cd /home/rsmith/frappe-bench/apps/erpnext
git tag pre-v16-migration russ/bryanwork
git push origin pre-v16-migration
git fetch upstream version-16
```

**Verify:** `git tag | grep pre-v16-migration` returns the tag. `git log -1 upstream/version-16 --format="%cs %h %s"` shows a recent v16 commit (currently `2026-05-27 ff46d20b25 chore(release): Bumped to Version 16.20.0`).

### Step 2 — Create the migration branch off v16

```
cd /home/rsmith/frappe-bench/apps/erpnext
git checkout -b russ/bryanwork-v16 upstream/version-16
```

**Verify:** `git branch --show-current` → `russ/bryanwork-v16`. `git log -1 --format="%h %s"` should match v16's tip.

### Step 3 — Copy net-new fork files in unchanged

These paths exist only on the fork. They can be checked out wholesale.

```
cd /home/rsmith/frappe-bench/apps/erpnext

# AP closed-loop scope (the actual pilot code)
git checkout pre-v16-migration -- \
  erpnext/accounts/ap_closed_loop/ \
  erpnext/accounts/doctype/document_capture/ \
  erpnext/accounts/doctype/ap_closed_loop_settings/

# Documentation and project meta
git checkout pre-v16-migration -- \
  docs/ \
  AGENTS.md \
  CLAUDE.md

# Local dev scratch (optional — these are mostly .tmp/ helpers)
git checkout pre-v16-migration -- .tmp/ .claude/settings.json
```

**Verify:** `git status` shows the expected file additions as staged. `git diff --stat --staged | tail -1` should show roughly the same line-count ballpark as the original fork (allowing for the 3 upstream files which aren't yet ported).

### Step 4 — Reapply the 3 upstream-file edits

Each edit must be reapplied **against v16's version of the file**, not blindly copied from the fork (since `setup/utils.py` differs slightly on v16).

#### 4a. `erpnext/tests/utils.py`

The file is byte-identical on v16 vs develop, so the fork's diff applies as a straight patch.

```
git diff pre-v16-migration~36..pre-v16-migration -- erpnext/tests/utils.py | git apply
```

**Verify:** `git diff --staged erpnext/tests/utils.py` shows the +5/-1 lines around the `ignore_if_duplicate=True` change.

#### 4b. `erpnext/workspace_sidebar/invoicing.json`

Same — byte-identical between v16 and develop. Patch applies directly.

```
git diff pre-v16-migration~36..pre-v16-migration -- erpnext/workspace_sidebar/invoicing.json | git apply
```

**Verify:** `git diff --staged erpnext/workspace_sidebar/invoicing.json` shows the two added Link entries (Invoice Capture, AP Closed Loop Settings).

#### 4c. `erpnext/setup/utils.py`

The file has small unrelated changes on v16 vs develop. The fork's edit is in the `_enable_all_roles_for_admin` function, lines verified unchanged on v16. Apply by editing v16's file directly (1-line swap):

- **Find** (in v16's file, around line 179):
  ```python
  admin_roles = set(
      frappe.db.get_values("Has Role", {"parent": "Administrator"}, fieldname="role", pluck="role")
  )
  ```
- **Replace with:**
  ```python
  admin_roles = set(
      frappe.get_all("Has Role", filters={"parent": "Administrator"}, pluck="role")
  )
  ```

**Verify:** `git diff erpnext/setup/utils.py` shows only the 1-line API swap.

### Step 5 — Stage and commit

```
cd /home/rsmith/frappe-bench/apps/erpnext
git add -A
git status   # eyeball-check before committing
git commit -m "$(cat <<'EOF'
feat: rebase AP closed-loop pilot onto upstream/version-16

Ports the russ/bryanwork fork (previously based on upstream/develop, version
string 17.0.0-dev) onto upstream/version-16 for deployment compatibility with
the customer UAT box.

Net-new files (no conflicts): AP closed-loop python/json/JS under
erpnext/accounts/ap_closed_loop/, erpnext/accounts/doctype/document_capture/,
erpnext/accounts/doctype/ap_closed_loop_settings/, plus docs/, AGENTS.md,
CLAUDE.md, .tmp/, .claude/settings.json.

Reapplied upstream-file edits (all small):
- erpnext/setup/utils.py: 1-line frappe.db.get_values → frappe.get_all swap
- erpnext/tests/utils.py: idempotent bootstrap with ignore_if_duplicate=True
- erpnext/workspace_sidebar/invoicing.json: add Invoice Capture + AP Closed
  Loop Settings sidebar links

Pre-migration state preserved at tag `pre-v16-migration`.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

**Verify:** `git log -1 --stat | tail -10` shows 60+ files changed with a sensible line count.

### Step 6 — Local toolchain rebuild

```
cd /home/rsmith/frappe-bench
bench setup requirements
bench build --app erpnext
bench --site erpnext.localhost migrate
bench restart   # if running via bench start; otherwise supervisorctl
```

**Verify:**
- `bench version` shows `erpnext` on a v16-ish version string (likely `16.x.x` post-migrate; the fork's `erpnext/__init__.py` will inherit v16's version unless we deliberately edit it).
- `bench --site erpnext.localhost console` → `frappe.get_all("DocType", filters={"name": "Document Capture"}, pluck="name")` returns `["Document Capture"]`.
- Visit `http://erpnext.localhost:8000/app/ap-invoice-capture/view/list` in the browser — the list renders.

### Step 7 — Run tests

```
cd /home/rsmith/frappe-bench
bench --site erpnext.localhost run-tests --app erpnext --module erpnext.accounts.ap_closed_loop.test_walking_skeleton
bench --site erpnext.localhost run-tests --app erpnext --module erpnext.accounts.doctype.document_capture.test_document_capture
```

**Verify:** Both modules pass green. `IntegrationTestCase` exists on `frappe/version-16` (verified at `frappe/tests/classes/integration_test_case.py`), so the imports work.

### Step 8 — Smoke-test the AP workflow end-to-end

Use the browser against the local site:

1. Log in as Administrator.
2. Navigate to **Invoicing → Invoice Capture** (sidebar link added by the fork).
3. Create a new Document Capture document.
4. Walk through the auto-progression cascade buttons and confirm each step transitions state correctly.
5. Hit the inline Mock Payment button and confirm the payment writeback succeeds.

**Verify:** Each step matches the behavior the fork delivers on `russ/bryanwork`. Capture any divergences for investigation.

### Step 9 — Update fork-tracking docs

Per `CLAUDE.md` working rules, fork-scope changes require updating `docs/architecture/FORK-CHANGES.md` (and `FORK-CHANGES-PLAIN.md` as the paired explainer).

- Update both files to note the new base branch and any path differences from the develop-based version.
- Update the `Last verified against repo` date on `docs/architecture/UI-SITEMAP.md` if any sidebar rendering changed.

### Step 10 — Push the new branch

```
cd /home/rsmith/frappe-bench/apps/erpnext
git push -u origin russ/bryanwork-v16
```

**Do not delete `russ/bryanwork` yet.** Keep it as a parallel history until the v16 branch has run for at least a few days in local dev and the team is comfortable.

---

## 5. Risks and mitigations

| Risk | Likelihood | Severity | Mitigation |
|---|---|---|---|
| `bench migrate` fails on the AP DocTypes because the site was set up against develop's DocType schema and v16 has slightly different field types somewhere | Low (no fork DocType references v17-only field types) | Medium | Pre-migration `bench backup`. If migrate fails, restore and investigate offending patch / field. |
| A Frappe API the fork uses behaves differently on v16 vs develop (silent semantic change, not a `feat!`) | Low | Medium | Tests cover the AP workflow. Run them after migrate; failures will surface this. |
| `frappe.tests.IntegrationTestCase` API has v17-only methods the fork relies on | Low (the test files were written when local was already on v16-ish frappe — and frappe/v16 has the class) | Low | Tests will fail loudly. Easy to fix. |
| `erpnext/__init__.py` `__version__` collides between the fork's old `17.0.0-dev` and v16's value | Low — the `git checkout pre-v16-migration -- erpnext/accounts/...` paths don't include `__init__.py` so v16's value wins | None | Verified by path-scoping the checkout. |
| Workspace JSON `modified` timestamp drift causes a Frappe sync prompt on next `bench migrate` | Medium | Low | This is benign — `bench migrate` will sync the workspace doc. The fork's timestamp `2026-05-27 22:40:00.000000` should be later than v16's, so v16 picks it up cleanly. |
| Some Python C-extension wheel isn't 3.14-compatible on local dev | N/A — local dev does not need Python 3.14. The customer-side upgrade is what touches the toolchain. | n/a | Local stays on whatever Python the bench was set up with. |
| The 36 fork commits include things we don't realize we depend on (e.g. a tweak to a non-fork file we forgot about) | Low — `git diff --stat upstream/develop..HEAD` shows the full set | Low | Re-run that diff after step 4 and confirm the new branch's diff against `upstream/version-16` covers all of it. |

---

## 6. Rollback

If any step from 5–8 fails irrecoverably:

```
cd /home/rsmith/frappe-bench/apps/erpnext
git checkout russ/bryanwork     # back to the original branch
cd /home/rsmith/frappe-bench
bench --site erpnext.localhost --force restore <path-to-pre-migration-backup.sql.gz>
bench build --app erpnext
bench restart
```

The original `russ/bryanwork` branch is never touched during this plan, and the `pre-v16-migration` tag is pushed to `origin`. Recovery is local and fast.

---

## 7. Post-migration work (not part of this plan, but follows from it)

1. **Update `docs/architecture/FORK-CHANGES.md` and `FORK-CHANGES-PLAIN.md`** to reflect the v16 base.
2. **Decide on the future of `russ/bryanwork`** — leave as archive, or eventually delete after a soak period.
3. **Coordinate with the customer** about the UAT-box upgrade described in `docs/planning/v16-upgrade-business-case.md`.
4. **Plan how the fork keeps current with v16** — periodic `git merge upstream/version-16` cadence, who runs it, how conflicts are handled.

---

## 8. Sources

### Repo-internal (verified live on 2026-05-28)

- Local bench root: `/home/rsmith/frappe-bench`
- `apps/frappe` HEAD: `69be97c chore(release): Bumped to Version 16.18.3` on branch `version-16`
- `apps/erpnext` HEAD: `67ede6bc77` on branch `russ/bryanwork`
- `apps/erpnext/erpnext/__init__.py`: `__version__ = "17.0.0-dev"`
- Diff `upstream/develop..HEAD`: 69 files, 10,440 insertions, 4 deletions
- Diff `upstream/version-16..upstream/develop` for `erpnext/tests/utils.py` and `erpnext/workspace_sidebar/invoicing.json`: empty (byte-identical)
- Diff `upstream/version-16..upstream/develop` for `erpnext/setup/utils.py`: small, but the function the fork patches (`_enable_all_roles_for_admin`) has identical body on v16
- Merge commits on `russ/bryanwork` not reachable from `upstream/develop`: 10 (these are why a literal rebase is the wrong tool)

### Upstream

- [GitHub — frappe/erpnext `version-16` branch](https://github.com/frappe/erpnext/tree/version-16)
- [GitHub — frappe/erpnext releases (current tip v16.20.0)](https://github.com/frappe/erpnext/releases)
- [GitHub — frappe/frappe `version-16` branch](https://github.com/frappe/frappe/tree/version-16)
- [Frappe Forum — v16 release announcement](https://discuss.frappe.io/t/frappe-erpnext-and-frappe-hr-version-16-release/159053)

### Project docs

- `docs/planning/v16-upgrade-business-case.md` — motivation and customer-side context
- `docs/architecture/FORK-CHANGES.md` — current fork scope (will need updating in post-migration step 1)
- `CLAUDE.md` — grounding rule and working rules cited above
