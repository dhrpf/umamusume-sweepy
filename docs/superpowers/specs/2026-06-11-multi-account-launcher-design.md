# Multi-Account Launcher Design

**Date:** 2026-06-11  
**Status:** Approved

## Problem

The bot currently runs one game account. Multiple game accounts (each with a different `viewer_id`/`udid`) share the same Steam login but need independent runtime state (auth cache, steam keys, trace logs). Users want to run all accounts in parallel, with automatic restart on crash, managed from a single process.

## Solution

A `launcher.py` script reads `accounts.json`, spawns one `python main.py` subprocess per account, isolates each via env vars, and monitors/restarts on crash. **Zero changes to `main.py`** — it already respects `UMA_RUNTIME_DIR` and `PORT`.

---

## Components

### `accounts.json` (new, repo root)

Lists all accounts. Example:

```json
[
  { "name": "acct1", "port": 1616 },
  { "name": "acct2", "port": 1617 }
]
```

**Fields per entry:**

| Field | Required | Description |
|---|---|---|
| `name` | yes | Account identifier, used as runtime subdir name |
| `port` | yes | Port for this instance's web server |
| `enabled` | no | Default `true`. Set `false` to skip without deleting |
| `extra_env` | no | Dict of additional env vars for this account |

---

### `launcher.py` (new, repo root)

**Startup:**
1. Parse optional `sys.argv[1]` — if provided, filter to that account name only; error if not found in `accounts.json`
2. Load `accounts.json`, skip entries with `"enabled": false`
3. Spawn one subprocess per account

**Per subprocess:**
- Command: `python main.py`
- Env: copy of current env, with overrides:
  - `UMA_RUNTIME_DIR` → `<repo_root>/uma_runtime/<name>/`
  - `PORT` → `<port>`
  - Any `extra_env` keys from the account entry
- stdout/stderr: read in a background thread, each line prefixed with `[<name>] ` and printed

**Restart on crash:**
- Monitor thread watches each process with `process.wait()`
- Exit code 0 → clean shutdown, do not restart
- Non-zero exit → crash, log `[<name>] crashed (exit <code>), restarting in 5s`, wait 5s, respawn
- Respawn is skipped if global shutdown is in progress

**Shutdown (Ctrl+C / SIGINT):**
1. Set global `shutdown` flag (stops all restart loops)
2. Call `process.terminate()` on all live subprocesses
3. Wait up to 10s for all to exit; `process.kill()` any that remain
4. Exit launcher with code 0

---

### Runtime isolation

Each account gets its own subdirectory under `uma_runtime/`:

```
uma_runtime/
  acct1/
    auth_cache.json
    steam_login_keys/
    trace_logs/
  acct2/
    auth_cache.json
    steam_login_keys/
    trace_logs/
```

`runtime_output_root()` in `uma_api/client.py` already reads `UMA_RUNTIME_DIR` first — no code changes needed.

---

### `package.json` update

Add `"launch"` script:

```json
"scripts": {
  "start": "python main.py",
  "launch": "python launcher.py"
}
```

Usage:
```bash
npm run launch              # all enabled accounts
npm run launch -- acct1     # single account
python launcher.py          # all enabled accounts
python launcher.py acct1    # single account
```

---

## First-time setup per account

1. Start launcher (or single account)
2. Open `http://127.0.0.1:<port>` for that account
3. Log in via UI — saves auth to `uma_runtime/<name>/auth_cache.json`
4. Steam key saved to `uma_runtime/<name>/steam_login_keys/`
5. Subsequent starts auto-login from cache

---

## What doesn't change

- `main.py` — untouched
- `uma_api/client.py` — untouched
- `career_bot/` — untouched
- All existing env vars (`FRIDA_REMOTE`, `UMA_MASTER_MDB`, etc.) still work — inherited by each subprocess
- Single-account usage (`npm start`) still works exactly as before
