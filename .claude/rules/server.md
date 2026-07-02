# Rule: FastAPI Server

Paths: `main.py`

## Request Lifecycle

1. Pydantic models (`LoginRequest`, `StartCareerRequest`, `RunCareerRequest`, `SaveRacesRequest`, etc.) define the API schema. Never accept raw `Request` in a route that has a model.
2. `validate_start_selection(req)` rejects bad combinations (duplicate cards, invalid scenario). Always call before mutating state.
3. `apply_deck_type_counts(preq, req, chara_info)` injects deck-type metadata into the preset response. Don't skip it on `/start`.
4. Routes under `/api/career/*` are mutating. Return 202 with a career_id, not a result, when work is async.
5. `/api/career/start` is synchronous-ish (starts runner thread). Return `{status: "started"}`, not runner state.

## Auth Capture

6. `refresh_auth_before_serving(timeout_sec=180)` runs before the app serves. Block startup until auth valid or timeout.
7. `auto_login_from_cache()` tries Steam ticket → chain_by_transition → fail. Don't bypass cache when fresh.
8. `capture_login()` launches the game via `xdg-open steam://rungameid/3224770` (Linux), hooks TLS with Frida. Override with `FRIDA_REMOTE`.
9. `save_auth_cache(cfg)` writes to `uma_runtime/auth_cache.json`. Always load via `load_auth_cache()`, don't read the file directly.
10. Steam ticket path: `uma_runtime/steam_login_keys/<username>.txt`. Don't cache in Python memory; read fresh.

## Career Loop

11. `manage_career_loop(req, preset, initial_result)` runs career → waits → starts next career when dev_mode=True. Never expose loop control on a public route.
12. Dev toggle is intentionally hidden (11-tap title or `localStorage.uma_dev_career`). Don't add a visible toggle without README update.
13. `stop_on_empty_tp=True` halts loop when TP < use_tp; default is to recover with gems. Choose per preset.

## Static Files

14. `public/` is served at `/`. Don't add CSP headers that would block inline scripts used by the SPA.
15. `uma_race_data.json` cache: mtime-keyed in `_career_history` loader. Don't re-parse all JSON on every call.
16. Career logs at `uma_runtime/<acct>/bot_logs/career_log_<ts>.json`. `analyze_career_log.py` is the official consumer.

## Dashboard / Home

17. `get_account_status(data, career_data)` renders the dashboard panel. Use it; don't compute inline in the route.
18. `_load_data_file(filename)` caches per-file in-process. Don't bypass for freshness-sensitive reads.
19. `_deck_meta_from_ids`, `_support_cards_from_ids` handle card name resolution. Don't access raw IDs in templates.

## Env Vars

20. `UMA_RUNTIME_DIR`, `UMA_MASTER_MDB`, `UMA_PROCESS_NAME`, `PORT`, `SWEEPY_AUTH_CAPTURE_TIMEOUT_SEC`, `FRIDA_REMOTE`. Parse at module init, not inside request handlers.
