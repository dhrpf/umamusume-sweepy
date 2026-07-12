# Error Code Catalog

Policy legend: ⟲ retry, ✗ re-raise, ⚠ log+absorb, ⊙ silent-skip, ↔ state-refresh.

## Success

| Code | Name | Semantics | Policy | Ref |
|---|---|---|---|---|
| 1 | SUCCESS | `data_headers["result_code"] == 1` | passthrough | `UmaClient.call` |

## Handled API Results

| Code | Name | Semantics | Policy | Ref |
|---|---|---|---|---|
| 102 | RACE_ALREADY_DONE | race state already consumed | ⊙ race-end/out special cases; otherwise recover state | `CareerRunner._race`, `_race_progress` |
| 201 | SESSION_EXPIRED | auth or SID stale | ↔ refresh state / headless re-auth where caller owns loop | `main.py`, `CareerRunner._fresh_career_state` |
| 202 | START_SESSION_AGAIN | login transient | ⟲ sleep in `UmaClient.login()` | `UmaClient.login` |
| 205 | PROXY_TEMP_ERROR | per-call transient | ⟲ built-in retry; race entry rejects failed program | `UmaClient.call`, `RacePlanner.reject_race` |
| 208 | SERVER_BUSY | server lock | ⟲ built-in retry; selected item/skill calls may return response | `UmaClient.call` |
| 213 | TP_RECOVERY_BLOCKED | TP refresh denied | ↔ refresh state + retry when caller handles it | `main.py`, runner recovery |
| 214 | RES_VER_STALE | resource version changed | ⟲ update `res_ver`, reset transport/SID, start session, retry endpoint | `UmaClient.call` |
| 217 | EVENT_STALE | event/resource state stale | ⟲ alternate event choices; exhaust → fresh state | `CareerRunner._drain_events` |
| 2502 | STYLE_CHANGE_REJECTED | style change unavailable/already set | ⊙ fall through to normal race entry | `UmaClient.race_entry`, runner race flow |
| 394 | LOAD_BUSY | `load/index` busy after wait | ⟲ bounded login retry | `UmaClient.login` |
| 501 | SESSION_INVALID | active session fully stale | ↔ close transport → reload `auth_cache.json` → require cached Steam credentials → refresh ticket → `login()` bootstrap → retry original endpoint once; second 501 → `StateRecoveryError` | `UmaClient.call`, `_reload_cached_auth`, `_refresh_ticket_and_login` |
| 709 | VIEWER_ID_MISMATCH | server viewer id differs | ⟲ adopt returned viewer id + regenerate SID | `UmaClient.call` |
| 917 | RECOVERY_REQUIRED | response cannot continue in place | ↔ client raises `StateRecoveryError`; runner refreshes career state | `UmaClient.call`, `CareerRunner._run` |
| 1055 | VIEWER_ID_INVALID | viewer id rejected | ↔ anonymous bootstrap, then transition recovery when needed | `UmaClient.login` |
| 1503 | RESUME_ALREADY_DONE | race already resumed | ⚠ absorbed only in race/reconcile paths | `CareerRunner` |

## Re-raised

- Unknown `result_code` raises `API error {code}`.
- Programming errors re-raise from runner; do not add arbitrary codes to recovery handling.
- `StateRecoveryError` means callers must obtain fresh state, not repeat stale strategy decisions.

## Tests covering recovery

- `tests/test_login.py` — login, transition, 501 cache-backed cold relogin.
- `tests/test_runner_event_recovery.py` — event drain and fresh-state recovery.
- `tests/test_runner_501_recovery.py` — runner 501 reconciliation.

## Rules

- Read result code from `response["data_headers"]["result_code"]`.
- `1` is only success gate.
- Error names are operational labels, not server enums.
