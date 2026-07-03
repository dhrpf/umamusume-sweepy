# CareerRunner Workflow (`career_bot/runner.py`)

Deep map of the career-loop engine. Pairs with ADR-007 (`decisions/007-runner-chain.md`).
Companion rules: `.claude/rules/career-loop.md`. Read that for hard constraints; this for control flow.

---

## 0. Roles

`CareerRunner` = one career run, one background thread. Owns:
`strategy` (scenario 1/4), `race_planner`, `skill_buyer`, `item_manager`, `report`.
All status mutation under `self.lock`. Never read `self.status` unlocked.

Lifecycle: `start()` (main thread) → spawns `_run()` thread → dispatch loop → `finally` writes report.

| Method | Line | Role |
|---|---|---|
| `start` | 105 | build strategy/planner/buyer/manager, new report, spawn thread |
| `_run` | 170 | **main loop** — dispatch, crash absorb, finally-report |
| `_fresh_career_state` | 771 | **relogin+reload** — the universal recovery primitive |
| `_drain_events` | 826 | resolve `unchecked_event_array` (217 choice-retry) |
| `_recover_blocked_state` | 534 | playing_state 6 minigame / hard_reset |
| `_race` | 995 | full race: entry→start→(clocks)→end→out |
| `_race_progress` | 1195 | **resume** an already-in-flight race |
| `_reload_after_reconcile` | 1179 | post-102 stale-payload reload |
| `_buy_skills` | 1368 / `_handle_items` | 1394 | purchase phases |

---

## 1. Main loop `_run` (170–424)

Per iteration (turn):

```
_should_stop?                         176   → break
read turn from chara_info             178-180
turn changed → client.wait_turn_delay 182-185   (GateKeeper pacing)
_mark(turn) + _track_turn_scores      187-188   (report snapshot)
reset per-turn skill/item scratch     191-199
unchecked_event_array → _drain_events 201-206
_blocked_playing_state → _recover     208-216   (still blocked → break)
_debug_turn                           218
strategy.next_decision(state,preset)  219-228   (StateRecoveryError → _fresh → continue)
add_decision(report)                  231-232
── if action==command ──              234-256
    _handle_items (pre-race/shop)     236
    re-drain events                   238-240
    re-decide (may StateRecoveryError)244-253
dispatch action                       261-363
if action != finish → _buy_skills(force=False) 365-366
_advance                              368
```

Dispatch targets (261–363):

| action | line | does |
|---|---|---|
| `idle` | 261 | mark reason, **break** |
| `done` | 264 | mark finished, **break** |
| `event` | 268 | `_event`; 201/205/208/Network → `_fresh`+continue; 217 → `_handle_event_217` (None → abort) |
| `command` | 286 | `exec_command`; drain; 201/205/208/Net/StateRecovery → `_fresh`+continue; 102/1503 → `_recover_blocked_state` |
| `race` | 313 | `_race` |
| `race_progress` | 317 | `_race_progress` (resume) |
| `finish` | 321 | `_buy_skills(force)` → race_out stale race → drain(50) → SP>200 reretry → `finish_career` ×5 retry → break |
| else | 360 | mark, break |

### Crash absorb (369–408)
`recoverable` tags (378-381): `Network error, API error, StateRecoveryError, 102, 201, 205, 208, 213, 214, 217, 2502, 917, 709, 1055, 1503` + `HTTP 5xx/429`.
Recoverable → `_fresh_career_state` (best-effort), append `crash_trace.txt`, keep report.
**Not recoverable → re-raise** (programming bug surfaces).
102/1503 are "already done" *logic* signals — handled inline per-call, NOT blanket-swallowed here.

### finally (409–424)
stop_requested → report "stopped"; finished → "finished"; else "error". Always `write_report`.

---

## 2. Recovery primitive `_fresh_career_state` (771–806)

The single relogin path. Everything routes here.

```
8 attempts:
  attempt>0 → client.login()          778-787   (re-raise Net/102/201/208)
  load_career(scenario_id) OR         788-793   sc1→single_mode/load, else single_mode_free/load
  drain events if present              794-795
  reset scoped buyer/item failures     796-797
  success → return state
  fail → dna_sleep(10) retry
exhausted → client.hard_reset() (809) or RuntimeError
```

Trap: wrong `scenario_id` in status → loads wrong strategy silently (rules trap).

---

## 3. Race execution `_race` (995–1177)

Full race from scratch (`decision.action=="race"`).

```
scenario 4 → item_manager.handle_pre_race    996-1013  (recover_after_use_error → _fresh)
race_entry(program_id)                        1025-1042
  205/208 → planner.reject + strategy.reject_race + _fresh; if in history → skip  1027-1041
drain events                                  1045-1049
running_style mismatch → re-entry w/ style    1055-1067
race_start(is_short=1)                        1071-1087
  2502 → _fresh + drain + retry; 2502 again → return fresh  1074-1084
parse rank                                    1089-1090
burn_clocks loop (rank>1 & clocks) → continue+restart  1096-1128
drain post-race events                        1130-1133
race_end                                      1136-1162
  5xx StateRecovery → _fresh, move on         1140-1143
  102/1503 → RELOGIN → race_out(fresh_turn)   1145-1161   ★ (has [DBG] prints)
race_out                                      1164-1175
  102/1503/217 → reconciled, keep going       1172-1173
```

★ **race_end 102 rule**: 102 = server already committed race result. Calling `race_out` on the
stale session → **217** (resource busy). MUST `_fresh_career_state` (relogin) first, then
`race_out(fresh_turn)`. This is the canonical pattern; the two `_race_progress` resume paths mirror it.

---

## 4. Race resume `_race_progress` (1195–1367)

Runs when strategy sees a race already in flight (`action=="race_progress"`), e.g. bot restarted
mid-race or server ahead of client. `playing_state` drives it. Two race_end sites — **both mirror ★**.

```
── path A: phase branch (early) ──
  phase=="end":
    race_end → 102/1503 → RELOGIN → race_out(fresh_turn)   ★
  else fall-through to race_out (102/217 → _reload_after_reconcile)

── path C: race_start_info resume (1289–1367) ──
  running_style mismatch → race_entry          1301-1311
  playing_state==2 → race_start (2502 handling) 1312-1331
  playing_state 4/5 → skip start               1332-1334
  playing_state==1 → skip race_end             1335-1336
  else race_end                                1338-1359
    102/1503 → RELOGIN → race_out(fresh_turn)  1342-1357   ★
  race_out                                     1360-1366
    102/1503/201/217/StateRecovery → _reload_after_reconcile  1362-1364
```

`_reload_after_reconcile` (1179): `load_career`; has chara → return fresh; empty → `{"data":{}}`
(lets `next_decision` detect completion); load fail → return stale payload.

**Why ★ matters (the bug this doc's fix closed):** old path A-else & path C logged the 102 and
called `race_out` immediately → 217 → 217 on load → stuck retry storm at turn 0. Fix = relogin
before race_out in every race_end-102 branch.

---

## 5. Events `_drain_events` (826–887)

Loop `limit` times over `unchecked_event_array[0]`:

```
strategy._choice(event) → choice_number (must use gain_select_id_index)  836
choice None → pass _event/_current_turn (strategy picks)  840-841
_event → check_event                          842-843
  217 → try alternate choices                  857-874
    all exhausted (ev_key seen) → return       876-879
    else mark exhausted → _fresh               880-882
  HTTP5xx/Net → _fresh (or re-raise)           848-855
```

`_handle_event_217` (888) = same for main-loop `event` action; returns None → career aborts.
`_exhausted_events` set keyed `(event_id, turn)` prevents infinite reload.

---

## 6. Blocked state `_recover_blocked_state` (534–568)

`_blocked_playing_state` (530) = playing_state ∉ {1,2,3,4,5}.
`==6` → `minigame_end` (205 → skip) → drain. Else → `hard_reset` / `_fresh`.

playing_state map: 1=home, 2=race-entered, 3=training-pick, 4=race-in-progress, 5=race-finishing, 6=minigame.

---

## 7. Purchase phases

`_buy_skills` (1368): `skill_buyer.buy`; `recover_after_error` → `_fresh`. Runs after every
non-finish action (force=False) + at finish (force=True).
`_handle_items` (1394): scenario 4 only; buy+use; `recover_after_*_error` → `_fresh`.

---

## Recovery decision table

| Signal | Meaning | Action |
|---|---|---|
| 102 on race_end | race already committed | **relogin → race_out(fresh_turn)** ★ |
| 102/1503 on command | state past this action | `_recover_blocked_state` + continue |
| 201 / 205 / 208 / Network | session/transient | `_fresh_career_state` + continue |
| 217 on race_out | resource busy (usually post-102) | reconcile / `_reload_after_reconcile` |
| 217 on check_event | choice rejected | alt choices → `_fresh` |
| 2502 on race_start | pending transition | `_fresh` + drain + retry once |
| 214 | res_ver stale | client-layer auto-bump (`client.py:887`) |
| playing_state 6 | minigame | `minigame_end` |
| playing_state ∉1-5 | unknown block | `hard_reset` |
| non-recoverable | programming bug | **re-raise** (crash visible) |

---

## Extension notes

- New dispatch action → add branch in `_run` (261-363) **and** allow in `scenarios` Decision (rules:scenarios.md:2).
- New recovery signal → add tag to recoverable list (378-381) only if truly transient; else let it crash.
- Never add `_fresh_career_state` calls inside strategy code — recovery is runner's job.
- All race_end 102 branches must relogin before race_out. If you add a 4th race path, mirror ★.
