# AI Rules — Hard Constraints (project-wide)

## Auth & Secrets

1. Never log raw `auth_key`, `viewer_id`, `udid`, or Steam ticket outside protected runtime auth storage.
2. Never commit `uma_runtime/`, Steam keys, auth caches, or account files.
3. `refresh_auth_before_serving()` must complete before game API traffic.

## API Protocol

4. All game endpoints use msgpack + AES-CBC through `UmaClient.call()`; never construct raw game HTTP.
5. Scenario routing belongs in `UmaClient.call()`: scenario 1 remaps supported `single_mode_free/*` operations to `single_mode/*`; scenario 2 remaps them to `single_mode_team/*`; other scenarios retain `single_mode_free/*`.
6. Use built-in recovery for 205, 208, 214, 501, and 917. Only `data_headers.result_code == 1` is success.

## Career Loop

7. `CareerRunner.start()` owns a background thread. Never run `_run()` from FastAPI request handling.
8. `StateRecoveryError` requires `_fresh_career_state()` before another decision.
9. Drain `unchecked_event_array` before `next_decision()`.
10. Training failure validation compares game state/result, not event id alone.

## Data Integrity

11. Static `data/*.json` is generated from `master.mdb`; never hand-edit it.
12. Analyze career logs with `scripts/analyze_career_log.py`; do not read raw multi-megabyte logs first.
13. `command_info_array[].failure_rate` is game failure chance. Trust it over bot diagnostics.

## Behavior

14. API-bound waits use `dna_sleep`, `dna_gauss`, or `dna_uniform`; no raw `time.sleep()`.
15. Public career-loop dev mode stays opt-in.
16. Keep bot diagnostics outside wire payload fields.
