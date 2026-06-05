# ERPNext Development Guide — Local (WSL) Setup

> **Scope:** day-to-day development against the `NexeraDigital/erpnext` fork on Windows 11 + WSL2.
> **Bench location:** `~/frappe-bench` on Ubuntu-22.04. App at `~/frappe-bench/apps/erpnext`.
> **Site:** `erpnext.localhost`. Admin login: `Administrator` / `admin`. MariaDB root password: `frappe`.

---

## TL;DR

```bash
# from Windows, open a WSL terminal:
wsl -d Ubuntu-22.04

# start everything (leave this running)
cd ~/frappe-bench
bench start

# in another WSL terminal — interactive shell with frappe loaded
bench --site erpnext.localhost console
```

Then open `http://erpnext.localhost:8000` in Chrome/Edge.

**Edit → save → refresh.** That's the loop.

---

## What `bench start` runs

| Process | What it does | Auto-reloads on |
|---|---|---|
| `web` | Flask dev server (Python) on port 8000 | `.py` saves |
| `watch` | esbuild watcher rebuilding JS/CSS bundles | `.js` / `.scss` saves |
| `worker` | Background job consumer | `.py` saves |
| `schedule` | Cron-style hook runner | `.py` saves |
| `socketio` | Realtime push to browser on port 9000 | not relevant for app dev |
| `redis_cache` / `redis_queue` | Cache + queue backends | n/a |

Stop everything with `Ctrl+C` in the `bench start` terminal.

---

## The four kinds of code

### 1. Server logic (Python)

**Location:** `apps/erpnext/erpnext/**/*.py`

Edit → save → refresh the page that calls it. `web` reloads automatically. No restart needed.

Example file paths for this fork:
- `erpnext/accounts/doctype/document_capture/document_capture.py` — the main DocType controller
- `erpnext/accounts/ap_closed_loop/walking_skeleton.py` — pure-python end-to-end flow

### 2. Client-side (JavaScript)

**Location:** `apps/erpnext/erpnext/public/js/` or `<doctype-folder>/<doctype>.js`

Edit → save → wait ~2 seconds for the `watch` process to rebuild (visible in `bench start` log) → hard-refresh the browser (`Ctrl+Shift+R`).

### 3. DocType schema (JSON)

**Recommended workflow:** edit via the desk at `/app/doctype` — Frappe writes the JSON to disk for you and applies the DB migration automatically.

**If you hand-edit JSON:**
```bash
bench --site erpnext.localhost migrate
```

### 4. Tests

**Location:** `test_*.py` next to the code they cover.

```bash
bench --site erpnext.localhost run-tests \
  --module erpnext.accounts.ap_closed_loop.test_walking_skeleton

bench --site erpnext.localhost run-tests \
  --module erpnext.accounts.doctype.document_capture.test_document_capture
```

---

## Debugging — escalating tools

### Python (server-side)

Three tools, in order of how invasive they are:

**1. Print statement (instant feedback)**

```python
print("DEBUG:", some_var, flush=True)
```

Output appears in the `web.1` lines of your `bench start` terminal.

**2. Interactive console (poke at data)**

```bash
bench --site erpnext.localhost console
```

iPython shell with `frappe` pre-imported and the site connected:

```python
inv = frappe.get_doc("Document Capture", "APIC-2026-00001")
inv.run_method("validate_for_purchase_invoice")
frappe.db.sql("SELECT name, outstanding_amount FROM `tabPurchase Invoice` LIMIT 5", as_dict=True)
```

**3. VS Code breakpoints (step through code)**

1. Stop `bench start` (Ctrl+C).
2. Open VS Code at the bench root: `cd ~/frappe-bench && code .`
3. F5 with **Bench Web (debug)** selected (see `.vscode/launch.json`).
4. Click the gutter next to a line to set a breakpoint.
5. Trigger the code (visit a URL, click a button). VS Code pauses on the line.

> **Note:** `gunicorn_workers` is set to 1 globally so breakpoints fire reliably.

### JavaScript (browser)

- Open Chrome DevTools (`F12`).
- Add `debugger;` in any `.js` file.
- Save → wait for `watch` to rebuild → hard-refresh.
- Browser pauses on the `debugger;` line.

The global `frappe` object is available in the DevTools console:

```javascript
frappe.db.get_doc("Document Capture", "APIC-2026-00001")
  .then(doc => console.log(doc));

cur_frm.refresh();        // refresh the current form
frappe.boot;              // see what the user can see
```

### Slow request or weird SQL

Append `?recorder=1` to any URL, then visit `/app/recorder` to see every SQL query for that request with timings.

### Something errored — find what

`/app/error-log` in the desk — every uncaught Python exception lands here with full traceback and request context.

For programmatic logging without throwing:

```python
frappe.log_error(message="something happened", title="my-debug-tag")
```

---

## The "I'm stuck" checklist

When something doesn't behave as expected, run through these in order:

1. **Hard-refresh** (`Ctrl+Shift+R`) — stale browser cache fakes "my change didn't work."
2. **Check the `bench start` terminal** — exceptions often print there before showing up in the UI.
3. **`bench --site erpnext.localhost clear-cache`** — fixes "I changed a DocType but the form shows old fields."
4. **`bench --site erpnext.localhost migrate`** — fixes "I added a field but the DB column is missing."
5. **Check `/app/error-log`** — for anything that 500'd.
6. **Set a breakpoint** at the entry point of the failing request and step through.

---

## Calling the fork's API directly

Every `@frappe.whitelist()` function is reachable at:

```
http://erpnext.localhost:8000/api/method/<dotted.python.path>
```

Examples (per `docs/architecture/FORK-CHANGES.md`):

```
POST /api/method/erpnext.accounts.doctype.document_capture.document_capture.create_capture_from_uploaded_file
POST /api/method/erpnext.accounts.doctype.document_capture.document_capture.run_fake_extraction_for?capture=APIC-2026-00001
POST /api/method/erpnext.accounts.doctype.document_capture.document_capture.build_closure_evidence_for?capture=APIC-2026-00001
```

Use a session cookie from the logged-in browser, or a server-issued API key/secret.

---

## A typical day, end to end

Adding a button to `Document Capture` that runs a new validation:

1. Edit `apps/erpnext/erpnext/accounts/doctype/document_capture/document_capture.py` — add a new `@frappe.whitelist()` function.
2. Edit `document_capture.js` — add a `frm.add_custom_button(...)` that calls your new endpoint.
3. Save both. `web` reloads instantly; `watch` rebuilds the JS in ~2 seconds.
4. Hard-refresh the Document Capture form in the browser → click the new button.
5. If Python errored → check `web.1` lines of `bench start` or `/app/error-log`.
6. If JS errored → DevTools console.
7. If the button does nothing → `debugger;` in the JS handler, `print(...)` in the Python function.
8. Write a test in `test_document_capture.py`. Run with `bench --site erpnext.localhost run-tests --module ...`.
9. Commit and push from `~/frappe-bench/apps/erpnext`.

---

## Don'ts

- **Don't edit `C:\GitHub\erpnext-1\`** — that's a Windows-side clone that will drift from the WSL clone. The real working tree is `~/frappe-bench/apps/erpnext`.
- **Don't move the bench to `/mnt/c/`** — cross-filesystem I/O is ~10× slower and breaks file watchers.
- **Don't run two `bench start` instances** — port 8000, 11000, 13000 conflict.
- **Don't bump `gunicorn_workers` above 1** while debugging — breakpoints fire in random workers and miss your traffic.
- **Don't use `--no-verify`** on git commits to skip hooks unless you know exactly what you're skipping.

---

## Reference

- `.vscode/launch.json` (in `~/frappe-bench/`) — VS Code debug configurations for web, worker, scheduler, and the fork's tests.
- `docs/architecture/FORK-CHANGES.md` — the fork's scope, design principles, and complete file inventory.
- [Frappe Framework debugging docs](https://docs.frappe.io/framework/user/en/debugging)
- [Using the VSCode Debugger with Frappe (wiki)](https://github.com/frappe/frappe/wiki/Using-the-VSCode-Debugger-with-Frappe)
- [Frappe community forum](https://discuss.frappe.io/)
