# Browser Testing Setup — Playwright MCP for Claude Code

> **Purpose:** Give Claude Code the ability to drive a real browser against the local ERPNext site (click, type, screenshot, assert) so it can run the UI portions of the test plans in `docs/testplans/`.
>
> **Audience:** A developer (or their Claude Code agent) setting up browser testing on a fresh checkout. The steps are written so Claude Code can execute them end-to-end.
>
> **Why this isn't committed:** the generated `.mcp.json` contains a **machine-specific absolute path** to the browser binary, so it's gitignored. Each machine generates its own. This doc is the reproducible recipe.

---

## 0. TL;DR (the one path that actually works on WSL)

```bash
# 1. Register Playwright MCP with Claude Code (project scope)
cd <repo-root>          # e.g. /home/<you>/frappe-bench/apps/erpnext
claude mcp add playwright --scope project -- npx @playwright/mcp@latest

# 2. Install a Chromium build + its system libraries
npx --yes playwright install chromium
sudo npx playwright install-deps chromium   # needs sudo; installs libnss3, libnspr4, libasound2t64, etc.
#   If `sudo npx` fails with "npx not found" (nvm PATH issue), install the libs directly:
#   sudo apt-get install -y libnss3 libnspr4 libasound2t64

# 3. Find the installed Chromium binary path
ls -d ~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome

# 4. Point the MCP at that exact binary (edit .mcp.json — see §3 for the exact content)

# 5. Restart Claude Code so it loads the new MCP config
#    (exit, then `cd <repo-root> && claude`)

# 6. Verify: ask Claude to navigate to http://erpnext.localhost:8000/login
```

The non-obvious part is step 4: **do not rely on the MCP's auto-download.** See §2 for why.

---

## 1. Prerequisites

- **Claude Code** installed (`claude --version`).
- **Node 18+** and **npx** (this repo's bench uses Node 24 via nvm).
- A **running local ERPNext bench** serving at `http://erpnext.localhost:8000` (`bench start`).
- **sudo access** once, to install browser system libraries (see §2.2).
- Linux / WSL2. (These notes were written on Ubuntu under WSL2.)

---

## 2. The WSL gotcha (read this before you start)

Playwright MCP's `--browser chromium` default tries to auto-download a *specific* Chromium build version matched to its bundled `playwright-core`. On some WSL setups that download **completes (100%) but the extraction silently fails** — it writes only metadata files (`ABOUT`, `MEIPreload`, `WidevineCdm`) and never the `chrome` executable. This is a known Playwright bug:

- https://github.com/microsoft/playwright/issues/36412 (size-mismatch / partial extraction)
- https://github.com/microsoft/playwright-mcp/issues/943 (WSL install needs extra steps)

The symptom you'll see from Claude Code:

```
Error: Browser "chrome-for-testing" is not installed.
Run `npx @playwright/mcp install-browser chrome-for-testing` to install
```

…and re-running `install-browser` appears to succeed (exit 0) but never produces a working browser.

**The fix that works:** install a Chromium build the normal way (`npx playwright install chromium`, which *does* extract correctly), then point the MCP straight at that binary with `--executable-path`. This skips the broken auto-download entirely.

### 2.1 Install Chromium (the reliable way)

```bash
npx --yes playwright install chromium
```

This extracts to `~/.cache/ms-playwright/chromium-<build>/chrome-linux64/chrome`.

### 2.2 Install the system libraries the browser needs

A freshly downloaded Chromium won't launch on a bare WSL until the shared libs are present. Check first:

```bash
BIN=$(ls -d ~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome | tail -1)
ldd "$BIN" | grep "not found"
```

If anything is listed (typically `libnss3`, `libnspr4`, `libnssutil3`, `libasound2`), install them. Preferred:

```bash
sudo npx playwright install-deps chromium
```

If `sudo npx` fails because npx isn't on root's PATH (common with nvm), install directly:

```bash
sudo apt-get install -y libnss3 libnspr4 libasound2t64
# On Ubuntu 22.04 the last package is `libasound2` (no t64 suffix).
```

Re-run the `ldd ... | grep "not found"` check — it should now print nothing. Confirm the browser launches:

```bash
"$BIN" --version      # expect e.g. "Google Chrome for Testing 148.0.7778.96"
```

---

## 3. The `.mcp.json` content

`claude mcp add` (step 1) writes a default `.mcp.json` at the repo root. Replace its `args` so the MCP uses the binary you just verified. The file should look like this — **substitute your own absolute path** from §2.1:

```json
{
  "mcpServers": {
    "playwright": {
      "type": "stdio",
      "command": "npx",
      "args": [
        "@playwright/mcp@latest",
        "--executable-path",
        "/home/<YOU>/.cache/ms-playwright/chromium-<BUILD>/chrome-linux64/chrome",
        "--headless",
        "--allowed-hosts",
        "erpnext.localhost"
      ],
      "env": {}
    }
  }
}
```

Flag rationale:
- `--executable-path` — the whole point; pins to the working binary, no auto-download.
- `--headless` — WSL has no display by default; headless avoids needing WSLg/X.
- `--allowed-hosts erpnext.localhost` — restricts the browser to the local ERPNext host (small safety boundary). Add more hosts comma-separated if a test needs them.

> **Why the absolute path forces the gitignore:** `.mcp.json` is gitignored precisely because this path differs per machine and per Chromium build number. Never commit it.

---

## 4. Activate and verify

MCP servers load their config **only at Claude Code startup**. After editing `.mcp.json`:

1. Exit Claude Code (`Ctrl-D` or `/exit`).
2. Restart from the repo root: `cd <repo-root> && claude`.
3. Verify by asking Claude to navigate to the login page. Expected: it returns the page title "Login" with no `chrome-for-testing` error.

If it still errors after restart, the project-scoped `.mcp.json` may need approval — run `claude mcp list` to confirm `playwright` is registered and enabled.

---

## 5. Screenshots — where they go

Playwright MCP saves screenshots relative to the repo root by default, which clutters it. **Always pass a `filename` under the per-feature screenshot folder:**

```
docs/testplans/screenshots/<feature-slug>/<descriptive-name>.png
```

Example: `docs/testplans/screenshots/phase0-ai-provider-settings/phase0-after-save.png`.

The `docs/testplans/screenshots/` tree is committed (screenshots are test evidence), but the MCP's transient runtime dir `.playwright-mcp/` (accessibility snapshots, console logs, traces) is gitignored.

---

## 6. Typical test flow (reference)

```
browser_navigate     → http://erpnext.localhost:8000/login
browser_snapshot     → read the accessibility tree to find element refs
browser_type         → fill Email = Administrator, Password = admin
browser_click        → Login
browser_navigate     → http://erpnext.localhost:8000/app/<doctype-slug>
browser_snapshot     → find the field/button refs you need
browser_take_screenshot (filename: docs/testplans/screenshots/<slug>/...)
... drive the feature, asserting on snapshot text and screenshots ...
```

Use `browser_snapshot` (accessibility text) to *find and click* elements; use `browser_take_screenshot` to capture human-reviewable evidence. After UI actions that write data, verify the result with `bench --site erpnext.localhost mariadb` / `bench ... execute`, not just the screenshot — the DB is the source of truth.

---

## 7. Cleanup between runs

- Test data written through the UI should be removed afterward (e.g. encrypted passwords via `frappe.utils.password.remove_encrypted_password`).
- `.playwright-mcp/` can be deleted any time; it's regenerated and gitignored.
- The Chromium build and system libs persist — install once per machine.

---

## 8. Sources

- [Playwright MCP — official repo](https://github.com/microsoft/playwright-mcp)
- [Playwright — Browsers doc](https://playwright.dev/docs/browsers)
- [microsoft/playwright#36412 — chromium download completes but extraction fails](https://github.com/microsoft/playwright/issues/36412)
- [microsoft/playwright-mcp#943 — WSL install needs extra steps](https://github.com/microsoft/playwright-mcp/issues/943)
