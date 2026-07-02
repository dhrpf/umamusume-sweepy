# End-to-End Workflows

## 1. Auth Capture (startup waterfall)

```
main.py:2670 refresh_auth_before_serving()
  ↓ load_auth_cache() fast path → main.py:2507
cache miss ↓
  ↓ launch_game() → main.py:2518  xdg-open steam://rungameid/3224770
  ↓ _find_and_attach → main.py:2570-2578  attach Frida to PROCESS_NAME
  ↓ JS hook + wait → main.py:2581-2594  on_message handler
  ↓ has_fresh_auth_config() → main.py:2488-2504  (app_ver/res_ver/auth_key_len/viewer_id/udid/auth_key)
  ↓ save_auth_cache() + kill → main.py:2588-2593
  ↓ auto_login_from_cache() → main.py:2672  get_ticket/gated_client.login/_build_dashboard_from_login_response
  ↓ uvicorn.run() → main.py:2674
```

Variant: `/api/capture-login` route at `main.py:1559-1637` (HTTP-triggered, same steps 3-7).
`FRIDA_REMOTE` at `main.py:2556-2558` → remote vs local. `logout()` at `main.py:1640-1657` resets globals.

Failure modes:
- No game process in 180s → `main.py:2578` error → `SystemExit(1)` at `main.py:2671`
- Frida inject fail → `main.py:2595-2602` cleanup → False
- No cache + no capture → False
- No saved Steam ticket → `main.py:2619-2621` False
- Steam Guard → `main.py:2642-2643`
- 201 session expired → `main.py:1150-1155` retry loop in `start_career_from_request`

## 2. Start a career

```
/api/career/start → main.py:1659-1668
  ↓ start_career_from_request(req) → main.py:1123-1326
      guard active_client / duplicate (1123-1127)
      validate_start_selection → 1132
      load/index + 201/394 retry → 1137-1162
      decide_tp_action → 1171-1175  (stop|wait|carat)
      recovery_tp → 1182-1190
      affinity_calc.calculate_affinity → 1209-1221
      leftover career finish/delete → 1248-1272
      pre_single_mode → 1275
      start_career payload → 1280-1321
  ↓ apply_career_result → 1328-1347
  ↓ return chara_info + account → 1666
```

Dev-loop variant: `/api/career/run` at `main.py:1848-1925`:
- If active → `active_client.load_career()` at `main.py:1877`
- Else → `start_career_from_request` at `main.py:1902`
- `dev_mode=True` → `manage_career_loop` daemon thread `main.py:1903-1904`
- Else → `career_runner.start()` at `main.py:1923`

`manage_career_loop` → `main.py:1701-1846`:
- TP regen loop + `tool/start_session` refresh (`acquire_start` inner at `1716-1784`)
- `career_runner.start()` at `main.py:1799`
- Poll loop at `main.py:1801-1805`

`CareerRunner.start()` → `career_bot/runner.py:105-153`:
- Set strategy_cls, build report, `threading.Thread(target=self._run)` → `runner.py:152-153`

`CareerRunner._run()` → `career_bot/runner.py:170-424`:
- `_should_stop()` → `runner.py:176`
- Per-turn skill/item snapshot reset → `191-198`
- `_drain_events` → `201-203`
- `_recover_blocked_state` → `208-216`
- `strategy.next_decision()` → `218-220`
- dispatch {event|command|race|race_progress|finish} → `234-363`
- `_buy_skills` (skip if finish) → `365-366`
- `_advance` → `368`
- write_report → `418-424`
- Check recoverable list at `378-381` (102, 201, 205, 208, 213, 214, 217, 2502, 709, 1055, 1503, HTTP 5xx)

## 3. Stop/pause a running career

```
/api/career/runner/stop → main.py:2028-2034
  ↓ backend_loop_stop = True → main.py:2032
  ↓ career_runner.stop() → runner.py:155-157  (stop_requested = True, under lock)
  ↓ poll loop honors flag → main.py:1802-1804
  ↓ _should_stop() at top of each iteration → runner.py:176
  ↓ _interruptible_sleep wakes every 1s → main.py:1673-1698
  ↓ finally: report marked "stopped" → runner.py:410-413
```

- `/api/career/runner/stop` at `main.py:2039-2042` → burn_clocks update via `runner.py:165-168`
- Signal handler `main.py:2660-2661` → `_shutdown_handler` → `career_runner.stop()`
- Stop never aborts mid-turn — only after current iteration ends.

## 4. Analyze a career log

**Entry**: `python3 scripts/analyze_career_log.py uma_runtime/<acct>/bot_logs/career_log_<ts>.json`
**No FastAPI route** — CLI only.

```python
scripts/analyze_career_log.py:365  analyze(sys.argv[1])
  :20-32   load_race_map → data/race_map.json
  :34-52   load_skill_data → data/skill_data.json
  :69-104  header (preset, scenario_id, status, error, duration, final_turn)
  :106-138 final stats (SPD/STA/POW/GUT/INT, total, fans, motivation, skill_pt)
  :140-177 training distribution (CMD_TYPE_MAP / CMD_ID_MAP)
  :159-192 race results (race_start_info.program_id → race_map.meta[] → program_id → name)
  :194-210 motivation step-detect
  :212-255 high failure_rate flags (command_info_array[].failure_rate ≥ 20%)
  :257-297 training failures (pre/post stat delta ≤ 5)
  :299-317 stat progression / 12 turns
  :319-331 skills learned (skill_array[level>0] → skill_data)
  :333-362 issues summary
```

Input: `report.write_report()` → `career_bot/report.py:153-173` at `<runtime>/bot_logs/career_log_<YYYYMMDD_HHMMSS>.json` + `latest_career_log.json`.
Metadata-only adjacent: `_read_career_meta` at `main.py:1971-1981` → `/api/career/history`.

## 5. Regen master data

**Entry**: `python3 scripts/generate_master_data.py [--db-path PATH]`

```
scripts/generate_master_data.py:17  master_data.generate(ROOT, db_path)
career_bot/master_data.py:74    UMA_MASTER_MDB override
  :77-78  settings.json.master_data.master_mdb_path
  :43-47  Linux Proton compatdata 3224770
  :38/51  Windows LOCALAPPDATA
  :615-636 load_master_data  (DIRECT_TABLES + TEXT_DATA_CATEGORIES)
  :602-612 synthesize_legacy_jsons
```

### Outputs

| File | Synthesize fn | Ref |
|---|---|---|
| `data/skill_data.json` | `synthesize_skill_data` | `master_data.py:183` |
| `data/chara_list.json` | `synthesize_chara_list` | `master_data.py:211` |
| `data/support_list.json` | `synthesize_support_list` | `master_data.py:249` |
| `data/race_map.json` | `synthesize_race_map` | `master_data.py:435` |
| `data/factor_map.json` | `synthesize_factor_map` | `master_data.py:539` |
| `data/chara_aptitude.json` | `synthesize_chara_aptitude` | `master_data.py:575` |
| `public/assets/data/uma_race_data.json` | `synthesize_public_race_data` | `master_data.py:430` |

### Consumers (proc bounce required after regen)

| Consumer | Reads |
|---|---|
| `career_bot/skills.py:71` | `skill_data.json` |
| `career_bot/races.py:15` | `race_map.json` |
| `career_bot/scenarios/ura.py:61` | `support_list.json` |
| `main.py:244-249` | `chara_list.json`, `support_list.json` |
| `main.py:610-617` | `factor_map.json`, `race_map.json` |
| `career_bot/aptitude.py:36` | `chara_aptitude.json` |
| `career_bot/mcts/sim/ura.py:19-28` | `params.json` (separate, **not mdb**) |

Regeneration also wired into `/api/master-data/...` → `main.py:224-245` (boots if mdb present).

### File reference

| Concern | File |
|---|---|
| Boot/auto-login/routes | `main.py` |
| CareerRunner lifecycle | `career_bot/runner.py` |
| Report writer | `career_bot/report.py` |
| Log analysis CLI | `scripts/analyze_career_log.py` |
| Master data CLI | `scripts/generate_master_data.py` |
| MDB synthesize | `career_bot/master_data.py` |
| Skill buyer | `career_bot/skills.py` |
| Parent aptitude | `career_bot/aptitude.py` |
