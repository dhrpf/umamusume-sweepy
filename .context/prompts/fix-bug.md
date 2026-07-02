# Protocol: fix-bug

**Trigger**: crash, wrong action, race entry fails, skill/item buy fails, MCTS wrong score

## Pre-checks

1. **Scope by symptom**:
   - crash/traceback → `career_bot/runner.py:369-404` (crash path writes `crash_trace.txt`)
   - strategy picks wrong action → `career_bot/scenarios/{mant,ura}.py` `next_decision()`
   - race never entered → `career_bot/races.py:8` / `career_bot/runner.py:313`
   - skill/item buy fail → `career_bot/skills.py:482` / `career_bot/items.py:847`
   - MCTS wrong score → `career_bot/mcts/sim/ura.py:123` `evaluate()`
2. **Ask runner**: `scenario_id` (`runner.py:109` — 4=mant, 1=ura). Symptoms differ per scenario.
3. **Career log**: `ls -t uma_runtime/*/bot_logs/career_log_*.json | head -1` → parse with `/log-insider` skill.
4. **Runner dump**: `runner.status["last_action"]`, `runner.status["last_error"]` at `runner.py:120-134`.

## Steps

1. Read offending `Decision.action` dispatch branch in `runner.py`:
   - event → `268-285`
   - command → `286-312`
   - race → `313-316`
   - race_progress → `317-320`
   - finish → `321-359`
2. If API error:
   - Confirm recoverable code list at `runner.py:378-381` includes it.
   - Check `_fresh_career_state()` + `uma_api/client.py` relogin waterfall.
3. If strategy bug:
   - Read `next_decision()` in scenario file. Trace `_score_command` / `_find_rest` / `_find_medic` / `_choice`.
   - Field name check — `failure_rate` is correct API field; `fail_percent` is KNOWN BUG at `ura.py:612`. Preserve parity.
4. Patch minimal — one hunk. Don't refactor adjacent.
5. If runner crash: verify hit lands outside recoverable-tags list before adding re-raise.

## Verify

```bash
pytest tests/test_mant_strategy.py tests/test_ura_*.py tests/test_runner_command_metadata.py tests/test_runner_event_recovery.py -x
```

- If no test covers new branch → add one mirroring `tests/` style (pytest, no network).
- Manual smoke: `/api/career/start` with matching `scenario_id`. Confirm no regression 5 turns in.

## Known Traps

- `ura.py:612` reads `fail_percent` not `failure_rate`. **DO NOT fix.** (rules:scenarios.md:11)
- `mant.py:383` reads `failure_rate` correctly. Different file, different behavior.
- `runner.py:377` recoverable list — arbitrary `"9999"` swallows real bugs.
- `runner.py:182-184` turn delay gate — strategy called twice per turn if bypassed.
- `runner.py:789` `load_career(scenario_id=...)` — wrong id = wrong strategy silently.
- Event drain before decision (`runner.py:201-207`) — mutation must stay idempotent.
