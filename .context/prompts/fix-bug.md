# Protocol: fix-bug

**Trigger**: crash, wrong action, race entry failure, skill/item buy failure, wrong MCTS score.

## Pre-checks

1. Scope symptom:
   - traceback → `CareerRunner._run` crash path
   - wrong strategy action → scenario `next_decision()`
   - race failure → `RacePlanner` + `CareerRunner._race`
   - skill/item failure → buyer/item manager
   - MCTS score → simulator `evaluate()`
2. Confirm `scenario_id`: 4=Mant, 1=URA, 2=Aoharu endpoint remap.
3. Analyze latest career log with `scripts/analyze_career_log.py` or `/log-insider`.
4. Inspect locked runner status: `last_action`, `last_error`.

## Steps

1. Read affected `CareerRunner._run` dispatch branch.
2. For API errors, inspect `UmaClient.call()` then runner recovery:
   - 501: close stale transport → reload `auth_cache.json` → fresh Steam ticket → `login()` bootstrap → retry once.
   - 917: client raises `StateRecoveryError`; runner must fetch fresh career state.
   - 214: client updates resource version, resets transport/SID, starts session, retries endpoint.
   - Other transient failures: verify existing recovery path before adding handling.
3. For strategy bugs, trace `next_decision()` through scoring/gates/choice code. Training failure field is `failure_rate` in both URA and Mant.
4. Patch smallest correct hunk. Do not refactor adjacent behavior.
5. Keep programming errors visible; do not broaden runner recovery without proof.

## Verify

```bash
venv/bin/python -m pytest tests/test_runner_command_metadata.py tests/test_runner_event_recovery.py tests/test_runner_501_recovery.py -x
```

Add a no-network regression test for any new branch. Smoke matching scenario through `/api/career/start` only when game environment is available.

## Known Traps

- Event drain runs before decision; recovery changes must stay idempotent.
- `Decision.command` payload needs `current_turn` and command identifier metadata.
- Race state reconciliation requires fresh state before follow-up calls after already-done responses.
- Preserve `data_headers.result_code` parsing; top-level result code is wrong.
