# CareerRunner Workflow (`career_bot/runner.py`)

Deep map of career loop. Hard constraints: `.claude/rules/career-loop.md`. Chain rationale: `decisions/007-runner-chain.md`.

## Roles

`CareerRunner` owns one career thread, strategy, race planner, skill buyer, item manager, and report. All status mutation runs under `self.lock`.

| Method | Role |
|---|---|
| `start` | build career dependencies; spawn `_run` thread |
| `_run` | turn loop, dispatch, recovery, report finalization |
| `_fresh_career_state` | reload/relogin/hard-reset recovery |
| `_drain_events` | consume `unchecked_event_array`; handles alternate 217 choices |
| `_recover_blocked_state` | resolve abnormal `playing_state` |
| `_race` / `_race_progress` | new and resumed race flows |
| `_buy_skills` / `_handle_items` | purchase and Mant item phases |

## Turn Loop

`_run()` repeats:

```text
stop check
→ turn pacing + report snapshot
→ reset per-turn item/skill recovery state
→ _drain_events
→ _recover_blocked_state
→ strategy.next_decision
→ command item phase, re-drain, re-decide when needed
→ dispatch action
→ _buy_skills unless finish
→ _advance
```

Dispatch actions remain `idle`, `done`, `event`, `command`, `race`, `race_progress`, and `finish`. New action strings require runner dispatch support.

## Recovery

`_fresh_career_state()` owns stale-state recovery:

```text
load_career(scenario_id)                 # cheap current-state fetch
→ client.login() on later recovery attempt # fresh HTTP transport + bootstrap
→ retry load_career
→ client.hard_reset() only after retry budget is exhausted
```

`UmaClient.login()` may use anonymous bootstrap and transition recovery. A top-level 501 first follows client cold recovery:

```text
close stale HTTP session
→ reload runtime auth_cache.json
→ refresh Steam ticket
→ login(): start_session + load/index
→ retry interrupted endpoint once
```

Second 501 becomes `StateRecoveryError`, which returns control to runner recovery.

## Error Rules

- Recoverable failures are refreshed through `_fresh_career_state`; programming defects re-raise.
- 501 is invalid session/cold relogin. 917 is escalated by client as `StateRecoveryError`.
- 214 updates resource version, resets client transport/SID, starts session, then retries endpoint.
- 102/1503 mean state already advanced. Race-end paths reload fresh state before `race_out`.
- 217 on events tries alternate choices before fresh-state recovery.

## Blocked State

`_recover_blocked_state()` handles `playing_state == 6` through `minigame_end`; other unknown blocked states use recovery/hard reset. Never move this work into strategy code.

## Extension Rules

- Preserve event drain before strategy decision.
- Keep all status updates locked.
- Add recovery tags only for proven transient conditions.
- Never call raw `time.sleep()` around API work; use DNA pacing helpers.
