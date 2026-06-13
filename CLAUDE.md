# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Bot

```bash
# Install dependencies (first time)
npm install
pip install -r requirements.txt

# Start (Linux/CachyOS — requires frida-server running in Wine first)
FRIDA_REMOTE=127.0.0.1:27042 npm start

# Start frida-server in Wine (separate terminal, keep running)
WINEPREFIX=~/.local/share/Steam/steamapps/compatdata/3224770/pfx \
  "$HOME/.local/share/Steam/steamapps/common/Proton - Experimental/files/bin/wine" \
  ~/frida-server-17.9.1-windows-x86_64.exe

WINEPREFIX=~/.local/share/Steam/steamapps/compatdata/3224770/pfx \
  "$HOME/.local/share/Steam/compatibilitytools.d/GE-Proton10-34/files/bin/wine" \
  ~/frida-server-17.9.1-windows-x86_64.exe

# Capture game API calls for reverse engineering
FRIDA_REMOTE=127.0.0.1:27042 venv/bin/python capture_dailies.py output.json

# Test Frida attach only (game must be running)
FRIDA_REMOTE=127.0.0.1:27042 venv/bin/python test_frida.py
```

The server runs at `http://127.0.0.1:1616` (override with `PORT` env var).

## Architecture

**Entry point:** `main.py` — FastAPI server (~1700 lines). Handles auth capture, web UI serving, all `/api/*` endpoints, and the career loop thread.

**Auth flow:**
1. `refresh_auth_before_serving()` — checks `uma_runtime/auth_cache.json` first; if missing, launches the game via Steam and uses Frida to hook Unity's TLS layer (`GameAssembly.dll`) to intercept the first API call and extract `viewer_id`, `udid`, `auth_key`, `app_ver`, `res_ver`
2. `auto_login_from_cache()` — on startup, if cache has Steam credentials, calls `get_ticket()` (Node.js via `steam-user`) to get a fresh Steam session ticket, then logs into the game server headlessly
3. Steam login key (`uma_runtime/steam_login_keys/<username>.txt`) — persisted after first login to avoid Steam Guard on subsequent restarts

**API client:** `uma_api/client.py` — `UmaClient` wraps all game API calls. Wire protocol is msgpack encrypted with custom key. `pack()`/`unpack()` handle serialization. `get_hwid()`, `get_gpu()`, `get_os()` spoof device identity (cross-platform: Windows uses registry, Linux uses `/sys/class/dmi/id/` and `lspci`).

**Career automation:**
- `career_bot/runner.py` — `CareerRunner` runs in a background thread. Drives a career turn-by-turn: reads game state, calls the strategy, executes training/race/event commands via `UmaClient`
- `career_bot/scenarios/mant.py` — `MantStrategy` is the only active scenario (scenario_id=4). Decision engine for training selection, item usage, skill buying
- `career_bot/races.py` — `RacePlanner` selects which races to enter based on preset config
- `career_bot/skills.py` — `SkillBuyer` manages skill acquisition
- `career_bot/items.py` — `MantItemManager` handles item use/shop

**Loop control:** `manage_career_loop()` in `main.py` — runs career → waits for finish → starts next career. Enabled via `dev_mode=True` on the run request (default). `stop_on_empty_tp=True` halts the loop when TP < `use_tp` instead of spending gems to recover.

**Preset system:** JSON files in `data/presets/`. Loaded by `PresetStore`. Presets define scenario, support deck composition, race targets, skill priorities, item budget. Default preset: `"xguri parent"`.

**Runtime output:** `uma_runtime/` at repo root (or `UMA_RUNTIME_DIR` env var). Contains `auth_cache.json`, `steam_login_keys/`, `trace_logs/`, career reports.

**Static data:** `data/*.json` — `race_map.json`, `skill_data.json`, `factor_map.json` are large reference files loaded at startup. `master_data.py` reads `master.mdb` from the game's Proton prefix (`~/.steam/steam/steamapps/compatdata/3224770/pfx/...`) and generates derived JSON files.

**Frontend:** Single-page app in `public/` served by FastAPI. The DEV mode toggle (enables career loop) is hidden — revealed by clicking the "SWEEPY改二" title 11 times, or via `localStorage.setItem('uma_dev_career', 'true')`.

## Key Environment Variables

| Variable | Purpose |
|---|---|
| `FRIDA_REMOTE` | Connect to frida-server (e.g. `127.0.0.1:27042`) instead of local Frida |
| `UMA_RUNTIME_DIR` | Override runtime output directory |
| `UMA_MASTER_MDB` | Override path to game's `master.mdb` |
| `UMA_PROCESS_NAME` | Override game process name for Frida attach |
| `PORT` | Override web server port (default 1616) |
| `SWEEPY_AUTH_CAPTURE_TIMEOUT_SEC` | Timeout for Frida auth capture (default 180s) |

## Linux-Specific Notes

- Frida cannot attach to Wine processes directly (bootstrapper SIGSEGV). Must use `frida-server.exe` running inside the game's Proton Wine prefix.
- `get_gpu()` uses `lspci` on Linux; `get_hwid()` uses `/sys/class/dmi/id/` and `/etc/machine-id`.
- `master.mdb` is auto-detected at the Proton compatdata path for app 3224770.
- `launch_game()` uses `xdg-open steam://rungameid/3224770` on Linux.
- Game process appears in `frida-ps` as the full Windows path `S:\common\UmamusumePrettyDerby\UmamusumePrettyDerby.exe` — the attach code matches by substring.
