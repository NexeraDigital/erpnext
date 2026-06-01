# Test Plan — AI Provider Settings (OCR Phase 0)

> **Audience:** Cloud-hosted Claude instance executing tests on a clean ERPNext bench. You have no prior context about this repo, the conversation that produced this feature, or the developer's local state. Treat every step as a runbook.
>
> **Test plan rule:** per `CLAUDE.md` "Test plans (mandatory for every feature)" section.

---

## 1. Feature under test

**`erpnext/ai/` module — Phase 0 of the real OCR implementation plan.** Stands up the shared infrastructure for AI provider credentials so every AI-powered feature in this app (currently only AP OCR; future: supplier matching, account prediction, etc.) reads keys from one place.

What ships in Phase 0:

- A new top-level `erpnext/ai/` module registered in `erpnext/modules.txt`.
- A new Single DocType **`AI Provider Settings`** under `erpnext/ai/doctype/ai_provider_settings/`. Holds Anthropic and OpenAI API keys (Password fields, encrypted at rest), default model ids, and an Anthropic ZDR flag. Permissions: System Manager only, read + write.
- A helper module **`erpnext/ai/credentials.py`** exposing:
  - `AICredentials` dataclass with `provider`, `api_key`, `default_model`, `zdr_enabled`.
  - `get_ai_credentials(provider: str) -> AICredentials` — fetches decrypted credentials via Frappe's `frappe.utils.password.get_decrypted_password`. Raises `AICredentialsNotConfigured` (subclass of `frappe.ValidationError`) when no key is set, with a message that names the provider and points to `/app/ai-provider-settings` but never echoes any key value. Raises `ValueError` for unknown providers.
- Six unit tests under `erpnext/ai/tests/test_credentials.py` covering round-trip, missing-key error, message safety (no key substrings), unknown provider, blank default model, and ZDR provider-scoping.

**What does NOT ship in Phase 0** (intentional — those are later phases):
- No `AnthropicExtractor`.
- No changes to AP Invoice Capture.
- No call to the Anthropic API anywhere.
- No new fields on `AP Closed Loop Settings`.

If you observe any of those four, the change being tested has scope creep — report it and stop.

For context (do not need to read to execute this plan): `docs/planning/real-ocr-implementation-plan.md` §2 L9, §4.1, §8 Phase 0.

---

## 2. Branch / commit

- **Branch:** `russ/migrateToV16` on `origin` = `https://github.com/NexeraDigital/erpnext.git`
- **Base for this feature:** the commit on `russ/migrateToV16` that introduces `erpnext/ai/__init__.py` (use `git log --diff-filter=A -- erpnext/ai/__init__.py` to find it). At the time of writing, this had not yet been committed; the developer will commit it as the Phase 0 change before running this plan.
- **Frappe app:** must be on `version-16` branch, minimum tag `v16.18.3`. This plan was authored against `frappe v16.18.3` (commit `69be97cf31`).

---

## 3. Environment setup

You need a clean ERPNext bench. If you don't already have one, set it up as follows. Each step assumes the previous succeeded.

### 3.1 System prerequisites

- Linux (Ubuntu 22.04 or 24.04 recommended).
- Python 3.14 available as `python3.14` in `PATH`.
- Node 24+.
- MariaDB 10.6+ running locally; you must know the MariaDB root password.
- Redis 6+ available.

### 3.2 Create a fresh bench and install the apps

```bash
# Replace paths as appropriate for your VM.
cd ~
bench init --python python3.14 --frappe-branch version-16 frappe-bench-ai-test
cd frappe-bench-ai-test

# Fetch the ERPNext fork on the test branch.
bench get-app https://github.com/NexeraDigital/erpnext.git --branch russ/migrateToV16
```

### 3.3 Create a test site and install ERPNext

```bash
bench new-site ai-test.localhost \
  --mariadb-root-password '<your-mariadb-root-password>' \
  --admin-password admin \
  --install-app erpnext
```

### 3.4 Verify versions

```bash
bench --site ai-test.localhost version
```

**Expected output (minimum versions):**

```
frappe  16.18.3 version-16
erpnext 16.x.x  russ/migrateToV16
```

If the erpnext branch is not `russ/migrateToV16`, stop and check out the correct branch in `apps/erpnext/`.

### 3.5 Register the new `AI` module

The Phase 0 change adds `AI` to `erpnext/modules.txt`. New modules added after install need a one-time `Module Def` registration before migrate can sync their DocTypes. Run:

```bash
bench --site ai-test.localhost console <<'PY'
import frappe
if not frappe.db.exists("Module Def", "AI"):
    mod = frappe.new_doc("Module Def")
    mod.module_name = "AI"
    mod.app_name = "erpnext"
    mod.custom = 0
    mod.insert(ignore_permissions=True)
    frappe.db.commit()
    print("Module Def 'AI' created")
else:
    print("Module Def 'AI' already exists")
PY

bench --site ai-test.localhost migrate
```

### 3.6 Confirm the AI Provider Settings DocType exists

```bash
bench --site ai-test.localhost mariadb -e \
  "SELECT name, module, issingle FROM tabDocType WHERE name='AI Provider Settings'"
```

**Expected:** one row, `module=AI`, `issingle=1`. If empty, the new module/DocType did not sync — stop and investigate.

### 3.7 Start the bench

```bash
bench start
```

Leave running in a background terminal. The web UI is at `http://ai-test.localhost:8000`.

### 3.8 What you should NOT need

- No Anthropic API key. Phase 0 does not call any external API.
- No internet access from the test VM (other than initial `bench get-app`).
- No custom users — `Administrator` and one extra "Accounts Manager" user (created in §4) are sufficient.

---

## 4. Test data prerequisites

### 4.1 Users to create

Open `http://ai-test.localhost:8000/app/user` as `Administrator` (login: `Administrator`, password: `admin`). Create:

| Username | Role | Purpose |
|---|---|---|
| `test_sysmgr@example.com` | System Manager | Should be able to read/write `AI Provider Settings` |
| `test_acctmgr@example.com` | Accounts Manager (not System Manager) | Should be **denied** access to `AI Provider Settings` |

Set passwords on both to `testpass123!`. Verify by logging out and back in as each.

### 4.2 No DocType fixtures needed

The DocType is a Single and is auto-created empty on migrate. No prep needed beyond user creation.

### 4.3 Sample fake API key (never use a real key)

For round-trip testing, use the literal string:

```
sk-ant-FAKE-EXTERNAL-TEST-INSTANCE-DO-NOT-USE
```

This is obviously not a real key. If the helper ever returns this string when asked for `anthropic`, the round trip works. If a real Anthropic API ever sees this string, it will reject it as malformed — that's the intended safety.

---

## 5. Numbered test cases

Each case: **Preconditions → Action → Expected → Pass/Fail criterion.**

### TC-1 — DocType is reachable to System Manager

- **Preconditions:** Logged in as `test_sysmgr@example.com`.
- **Action:** Navigate to `http://ai-test.localhost:8000/app/ai-provider-settings`.
- **Expected:** Form renders. Title at top is "AI Provider Settings". Sections labelled "Anthropic" and "OpenAI" are visible. The Anthropic section contains fields: "Anthropic API Key" (password input, masked), "Anthropic Default Model" (text input, prefilled with `claude-haiku-4-5-20251001`), "Anthropic ZDR Enabled" (checkbox, unchecked).
- **Pass:** All four elements present and correct.

### TC-2 — DocType is hidden from Accounts Manager

- **Preconditions:** Logged out, then logged in as `test_acctmgr@example.com`.
- **Action:** Navigate to `http://ai-test.localhost:8000/app/ai-provider-settings`.
- **Expected:** "Not Permitted" / 403-style error, or a permissions warning. The form does NOT render. No field values are visible in the page source.
- **Pass:** Access denied, no field values leaked into HTML.

### TC-3 — Helper raises when no key set (clean state)

- **Preconditions:** No API key has been saved on the AI Provider Settings form. To reset, run:
  ```bash
  bench --site ai-test.localhost console <<'PY'
  from frappe.utils.password import remove_encrypted_password
  import frappe
  remove_encrypted_password("AI Provider Settings", "AI Provider Settings", "anthropic_api_key")
  frappe.db.commit()
  PY
  ```
- **Action:** Run the credentials test suite:
  ```bash
  bench --site ai-test.localhost run-tests \
    --module erpnext.ai.tests.test_credentials \
    --test test_raises_when_anthropic_key_not_set
  ```
- **Expected:** 1 test runs, passes, exit code 0.
- **Pass:** Test passes.

### TC-4 — Helper round-trips a stored key

- **Preconditions:** None (the test sets up its own state).
- **Action:**
  ```bash
  bench --site ai-test.localhost run-tests \
    --module erpnext.ai.tests.test_credentials \
    --test test_round_trip_anthropic_key
  ```
- **Expected:** 1 test runs, passes, exit code 0.
- **Pass:** Test passes.

### TC-5 — Exception message never contains key substrings

- **Preconditions:** None (the test sets up its own state).
- **Action:**
  ```bash
  bench --site ai-test.localhost run-tests \
    --module erpnext.ai.tests.test_credentials \
    --test test_exception_message_never_contains_key_substrings
  ```
- **Expected:** 1 test runs, passes, exit code 0.
- **Pass:** Test passes.

### TC-6 — Unknown provider raises ValueError

- **Action:**
  ```bash
  bench --site ai-test.localhost run-tests \
    --module erpnext.ai.tests.test_credentials \
    --test test_unknown_provider_raises_value_error
  ```
- **Expected:** 1 test runs, passes, exit code 0.
- **Pass:** Test passes.

### TC-7 — Full test suite passes

- **Action:** Run the entire credentials test module:
  ```bash
  bench --site ai-test.localhost run-tests --module erpnext.ai.tests.test_credentials
  ```
- **Expected:** `Ran 6 tests in <time>` and the final line `OK`. Exit code 0.
- **Pass:** All 6 tests pass.

### TC-8 — Key is encrypted at rest

- **Preconditions:** Save a known fake key via the form UI. Log in as `test_sysmgr@example.com`, open `/app/ai-provider-settings`, set the "Anthropic API Key" field to `sk-ant-FAKE-EXTERNAL-TEST-INSTANCE-DO-NOT-USE`, save.
- **Action:** Query MariaDB for the stored password row:
  ```bash
  bench --site ai-test.localhost mariadb -e \
    "SELECT LENGTH(\`password\`) AS pwd_len, encrypted FROM __Auth WHERE doctype='AI Provider Settings' AND fieldname='anthropic_api_key'"
  ```
- **Expected:** Exactly one row. `encrypted = 1`. `pwd_len` should NOT be the same as the plaintext length (50) — it should be much longer (typically ~160 chars for Fernet-encrypted text).
- **Pass:** `encrypted = 1` AND `pwd_len > 60`. (A row where `pwd_len = 50` would indicate the key is stored in plaintext — fail loudly.)

### TC-9 — Save-time whitespace trim

- **Preconditions:** Logged in as `test_sysmgr@example.com`.
- **Action:** Open `/app/ai-provider-settings`. In the "Anthropic API Key" field, paste a value with leading and trailing whitespace: `  sk-ant-FAKE-TRIM-TEST  ` (two spaces each side). Save the form.
- **Verify:** Re-open the form, blank-out the field by clicking the eye icon (or use `bench console` to fetch the stored value:
  ```bash
  bench --site ai-test.localhost console <<'PY'
  from frappe.utils.password import get_decrypted_password
  print(repr(get_decrypted_password("AI Provider Settings", "AI Provider Settings", "anthropic_api_key")))
  PY
  ```
- **Expected:** The fetched value is exactly `'sk-ant-FAKE-TRIM-TEST'` (no leading/trailing whitespace).
- **Pass:** No whitespace in the stored value.

### TC-10 — Negative: helper does not load anthropic SDK

- **Rationale:** Phase 0 must not introduce a dependency on the `anthropic` Python SDK; that comes in Phase 2.
- **Action:**
  ```bash
  bench --site ai-test.localhost console <<'PY'
  import sys
  import erpnext.ai.credentials  # noqa
  loaded = [m for m in sys.modules if m.startswith("anthropic")]
  print("ANTHROPIC_MODULES_LOADED:", loaded)
  PY
  ```
- **Expected:** Output contains `ANTHROPIC_MODULES_LOADED: []` (empty list).
- **Pass:** No `anthropic.*` module loaded by importing `erpnext.ai.credentials`.

### TC-11 — Negative: AP Invoice Capture behavior unchanged

- **Rationale:** Phase 0 explicitly says no AP-side behavior change. The fork's existing AP Invoice Capture tests should still pass.
- **Action:** Run the existing AP test suites unchanged:
  ```bash
  bench --site ai-test.localhost run-tests \
    --module erpnext.accounts.ap_closed_loop.test_walking_skeleton
  bench --site ai-test.localhost run-tests \
    --module erpnext.accounts.doctype.ap_invoice_capture.test_ap_invoice_capture
  ```
- **Expected:** Both modules return `OK`. Exit code 0 from both.
- **Pass:** Both modules pass.

---

## 6. Cleanup / rollback

After running the tests:

```bash
# Remove any test keys that were stored
bench --site ai-test.localhost console <<'PY'
from frappe.utils.password import remove_encrypted_password
import frappe
for fieldname in ("anthropic_api_key", "openai_api_key"):
    remove_encrypted_password("AI Provider Settings", "AI Provider Settings", fieldname)
frappe.db.commit()
print("Test keys removed")
PY

# Optionally drop the test site entirely
bench drop-site ai-test.localhost --mariadb-root-password '<your-mariadb-root-password>'
```

If the bench was created just for this test, delete the bench directory:

```bash
cd ~
bench stop
rm -rf frappe-bench-ai-test
```

---

## 7. Pass / fail summary

Fill in and return this checklist:

```
Test plan: AI Provider Settings (OCR Phase 0)
Branch:    russ/migrateToV16
Commit:    <git rev-parse HEAD of apps/erpnext>
Date:      <YYYY-MM-DD>
Tester:    <agent / VM id>

Environment:
  [ ] Section 3 (environment setup) completed without errors
  [ ] bench start runs cleanly
  [ ] tabDocType contains 'AI Provider Settings' with module=AI, issingle=1

Test cases:
  [ ] TC-1  DocType reachable to System Manager
  [ ] TC-2  DocType hidden from Accounts Manager
  [ ] TC-3  Helper raises when no key set
  [ ] TC-4  Helper round-trips a stored key
  [ ] TC-5  Exception message never contains key substrings
  [ ] TC-6  Unknown provider raises ValueError
  [ ] TC-7  Full credentials test suite passes (6 tests)
  [ ] TC-8  Key is encrypted at rest (encrypted=1, pwd_len > 60)
  [ ] TC-9  Save-time whitespace trim
  [ ] TC-10 Helper does not load anthropic SDK
  [ ] TC-11 Existing AP test suites still pass (unchanged)

Cleanup:
  [ ] Section 6 cleanup completed

Overall result:  [ ] PASS   [ ] FAIL
Notes / unexpected observations:
  <free text — anything the developer should know>
```

Return this checklist along with the raw `bench run-tests` output for TC-3, TC-4, TC-5, TC-6, TC-7, and TC-11.
