# Error Code Catalog

Policy legend: ⟲ retry, ✗ re-raise, ⚠ log+absorb, ⊙ silent-skip, ↔ state-refresh.

## Success

| Code | Name | Semantics | Policy | Ref |
|---|---|---|---|---|
| 1 | SUCCESS | `dh["result_code"]==1` — only gate that passes | passthrough | `uma_api/client.py:849` |

## Absorbable (handled inside `_run_loop` / retry path)

| Code | Name | Semantics | Policy | Ref |
|---|---|---|---|---|
| 102 | RACE_ALREADY_DONE | race state consumed; race_end/race_out no-op | ⊙ silent-skip on race_end/race_out; ⚠ absorbed elsewhere | `uma_api/client.py:884`, `runner.py:304,350,1198,1205` |
| 201 | SESSION_EXPIRED | auth/SID stale | ↔ `auto_login_from_cache()` in loop; `_fresh_career_state` re-raises to force relogin | `main.py:1152,1765,1811`, `runner.py:784,272,299` |
| 202 | START_SESSION_AGAIN | login glitch | ⟲ sleep 4.15s in-login only | `uma_api/client.py:1030` |
| 205 | PROXY_TEMP_ERROR | per-call transient | ⟲ up to 3× w/ jitter; minigame → ⚠; race_entry → reject permanently | `uma_api/client.py:850`, `runner.py:552,1029` |
| 208 | SERVER_BUSY | server lock | ⟲ up to 6×; gain_skills/multi_item_exchange → return | `uma_api/client.py:855` |
| 213 | TP_RECOVERY_BLOCKED | TP refresh denied | ↔ refresh state + retry; in crash allowlist | `main.py:1192`, `runner.py:379` |
| 214 | RES_VER_STALE | server resource_version bumped | ⟲ auto-update `self.res_ver`, retry same ep | `uma_api/client.py:864` |
| 217 | EVENT_STALE | check_event failed | ⟲ alternate choice indices; exhaust → fresh_career_state | `career_bot/runner.py:845-885` |
| 2502 | STYLE_CHANGE_REJECTED | running_style already set / N/A for scenario | ⊙ fall through to plain race_entry | `uma_api/client.py:1244`, `runner.py:1273,1282` |
| 394 | LOAD_BUSY | load/index busy right after TP wait | ⟲ sleep 2.5s in login | `client.py:1027`, `main.py:1157` |
| 709 | VIEWER_ID_MISMATCH | server viewer_id ≠ ours | ⟲ update viewer_id + regen SID; outer login swallows | `uma_api/client.py:837,970` |
| 1055 | VIEWER_ID_INVALID | viewer_id rejected | ↔ chain_by_transition_code → get_by_transition_code re-auth | `uma_api/client.py:844,973` |
| 1503 | RESUME_ALREADY_DONE | race_end on already-resumed | ⚠ absorbed in exec_command, race_end, race_out | `career_bot/runner.py:304,1198,1297,1304` |

## Re-raised (✗) unless in absorb allowlist

- `rc != 1` AND not in above → raises `API error {rc}`.
- `_run_loop` crash path re-raises if not in 378-381 recoverable list.
- `runner.py:378-381` is the definitive allowlist. Don't add without checking `StateRecoveryError` contract.

## Tests covering error paths

- `tests/test_runner_event_recovery.py:18` — 217 drain + refresh
- `tests/test_login.py:139,220` — 202 in start_session → 1 success path

## Flags

- `102` policy bifurcation: silent-skip vs absorb depends on endpoint.
- `213` undocumented in `api.md` but actively handled.
- `rc==1` is the ONLY success gate. Never short-circuit it.
- No code-name enum exists — names inferred from git history/comments.
