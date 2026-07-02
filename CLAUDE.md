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

## Analyzing Career Runs

Career logs live at `uma_runtime/<account>/bot_logs/career_log_<timestamp>.json`. They are large (10-15MB+, 400K+ lines) — never read raw.

**Quick analysis:** Run `python3 scripts/analyze_career_log.py <path-to-log.json>` for a full formatted report (stats, races, training distribution, failures, progression, skills). Find the latest log with `ls -t uma_runtime/*/bot_logs/career_log_*.json | head -1`.

For custom analysis beyond the script, use `execute_code` with Python `json.load()`.

### Log Structure

```
{
  "started_at", "ended_at", "preset_name", "scenario_id",
  "status": "finished"|"error",
  "error": null | string,
  "final_turn": 60,
  "turns": [{ "turn": N, "api_calls": [...] }]
}
```

Each `api_calls` entry: `{ ts, direction: "REQ"|"RES", endpoint, data, turn }`.

### Key Endpoints Per Turn

| Endpoint | Direction | Contains |
|---|---|---|
| `single_mode/check_event` | RES | `data.chara_info` (stats/vital/motivation/turn), `data.home_info.command_info_array` (training options), `data.unchecked_event_array` (pending events) |
| `single_mode/exec_command` | REQ | `payload.command_type` (1=SPD 2=STA 3=POW 4=GUT 5=INT 7=REST 8=OUTING), `payload.command_id` |
| `single_mode/exec_command` | RES | Post-training `chara_info`, triggered events |
| `single_mode/race_entry` | REQ | Race entered (no program_id in payload for URA) |
| `single_mode/race_start` | RES | `data.race_start_info.program_id` |
| `single_mode/race_end` | RES | `data.race_history[].{program_id, result_rank}`, `data.race_reward_info.{result_rank, gained_fans}` |
| `single_mode/gain_skills` | REQ | `payload.skill_id_array` (empty = no skills bought) |
| `single_mode/finish` | REQ | Career end |

### chara_info Fields

Stats: `speed`, `stamina`, `power`, `wiz` (=INT), `guts`, `vital`, `max_vital`.
State: `motivation` (1=最悪 2=悪い 3=普通 4=好調 5=絶好調), `turn`, `fans`, `state`, `playing_state`.
Aptitudes: `proper_ground_turf/dirt`, `proper_running_style_*`, `proper_distance_*`.
Skills: `skill_array[].{skill_id, level}` — level>0 means learned.

### command_info_array (Training Options)

Each entry in `home_info.command_info_array`:
```
{
  "command_type": 1,        // 1=training, 7=rest, 8=outing
  "command_id": 101,        // 101-106=normal, 601-605=summer camp
  "failure_rate": 31,       // game's ACTUAL failure % (0-99)
  "is_enable": 1,
  "training_partner_array": [1, 3],
  "params_inc_dec_info_array": [
    {"target_type": 1, "value": 40},  // 1=SPD 2=STA 3=POW 4=GUT 5=INT 10=VIT 30=skillpt
    ...
  ],
  "level": 5
}
```

Bot-injected fields (not from game): `_label`, `_decision_detail`, `_decision_options`.
- `_decision_detail.failure_rate` — bot's INTERNAL failure_rate (may differ from game's due to bugs)
- `_decision_options` — all scored options sorted by score, with `reasons[]`

### Summer Camp

Camp cmd_ids: 601-605 (SPD/STA/POW/GUT/INT). Camp turns defined in scenario code as `SUMMER_CAMP_TURNS`.

### Analysis Checklist (use execute_code for all)

1. **Header**: preset, scenario, status, error, duration, final_turn
2. **Final stats**: last turn's chara_info → SPD/STA/POW/INT/GUT total, fans, skills learned
3. **Training distribution**: count command_types from exec_command REQs → SPD/STA/POW/GUT/INT/REST/OUTING
4. **Race results**: race_end RES → `race_history[0].{program_id, result_rank}`, `race_reward_info.gained_fans`. Cross-ref program_id with `data/race_map.json` (keyed under `meta` dict, lookup by program_id value)
5. **Skill purchases**: gain_skills REQ → `skill_id_array` (empty = nothing bought)
6. **Motivation tracking**: track `motivation` changes across turns
7. **Failure rate analysis**: compare `command_info_array[].failure_rate` (game) vs `_decision_detail.failure_rate` (bot) for the chosen command. Training failure = stats barely change or drop + event 1007
8. **Vitality management**: track vital across turns, flag when training at high failure_rate
9. **Big stat jumps**: diff stats between consecutive turns, flag gains ≥40 (scenario bonuses, good training)

### Detecting Training Failures

A training failure shows as: stats don't increase (or drop slightly), event_id 1007 fires in exec_command RES. Compare pre/post stats. Gains ≤5 with a training action = likely failure.

### Important: Turn Boundaries & Decision State

The bot's decision for turn N may be made from the PREVIOUS turn's last `check_event` RES — after all events resolve, `chara_info.turn` advances and the state carries over. Multiple `check_event` calls per turn = events being processed sequentially. The exec_command is sent after the last event resolves. To find the ACTUAL state used for the decision, look at the last `check_event` RES with `unchecked_event_array=[]` and `command_info_array` present before the `exec_command` REQ — this may be in the previous turn's api_calls array.

### Known Bug: failure_rate Key Mismatch

In `career_bot/scenarios/ura.py` line 609: bot reads `cmd.get("fail_percent")` but game sends `"failure_rate"` → bot always sees 0% failure. The early rest-gate at line 287 reads `"failure_rate"` correctly but only triggers when ALL training options have ≥30% fail (Wit training at low VIT often has <30%, so the gate doesn't fire).
