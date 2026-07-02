# Rule: Career Loop, Races, Skills, Items, Presets

Paths: `career_bot/runner.py`, `career_bot/races.py`, `career_bot/skills.py`, `career_bot/items.py`, `career_bot/presets.py`, `career_bot/delay.py`, `career_bot/events.py`

## Runner

1. `CareerRunner` owns: strategy, race_planner, skill_buyer, item_manager, report. Never construct these outside the runner thread.
2. `_run_loop`: drain events → decide → execute → (optionally) buy skills → advance. Don't reorder steps.
3. Crash path: programming errors re-raise; API errors (`Network error`, 201, 205, 208, 213, 214, 709, 1055, 1503) are absorbed. Don't blanket-suppress.
4. State recovery: `_fresh_career_state()` tries relogin paths in sequence. Never short-circuit; let it fail.
5. `_track_turn_scores` writes `chara_info` snapshots to report.events every turn. Don't pollute the report with intermediate states.
6. `_debug_turn` dumps a `bot_status` key into the report. Keep it idempotent and side-effect free.
7. Threading: all status mutations go through `self.lock`. Don't read `self.status` unlocked.

## Race Planner

8. `RacePlanner.forced_program()` = must-run race (section target deadline). Always run it first.
9. `RacePlanner.mandatory_available()` = optional-but-on-deck races. Use when no forced is available.
10. `RacePlanner.wanted_available()` = planner's choice from preset race list. Rank with race scores, not insertion order.
11. `reject_race(program_id)`: runner calls this on 205/208 race entry failure. Don't re-add rejected programs.
12. `program_name(program_id)` → look up via `data/race_map.json[meta.*]`. Cache on first hit.

## Skills

13. `SkillBuyer.score_skill()` uses affinity, rarity, preset priority, blacklist. Don't modify priority upstream of `expect_attribute`.
14. Skill groups are bucketed by `skill_id // 10`. Used for de-duplication before purchase.
15. `attempt_events`: every buy attempt appends one row. Don't truncate — consumers analyze them post-run.

## Items

16. `MantItemManager` buys from `free_data_set.pick_up_item_info_array`. Never craft payloads directly.
17. Item budget = `coin_num` from `free_data_set`. Use `_owned_map` for inventory checks.
18. `_skip_buy(name, owned, preset)` centralizes skip logic. Don't duplicate skip checks in handle_pre_race.
19. Pre-race item use: `handle_pre_race()` returns `(state, used)`. Caller checks `recover_after_use_error`.
20. Failed uses accumulate in `failed_use_this_turn`; failed buys in `failed_exchange_this_snapshot`. Reset per-turn or per-snapshot accordingly.

## Presets

21. `PresetStore.load(name)` → JSON from `data/presets/`. Hydrate via `hydrate_preset`; never re-validate names not in the store.
22. Pydantic models (`LoginRequest`, `StartCareerRequest`, etc.) validate at the FastAPI boundary, not inside the runner.
23. `serialize_preset` / `hydrate_preset` handle roundtrips to the web UI. Don't add fields without dual support.
24. Default skill format: `normalize_skill_list` accepts list of IDs or dicts. Don't break old format.

## Delay

25. `dna_sleep`, `dna_uniform`, `dna_gauss`, `dna_randint` are the only allowed delays. Never call `time.sleep` on API paths.
26. TP strategy helpers (`decide_tp_action`, `compute_regen_wait_seconds`) live in `delay.py`, not runner.
27. GateKeeper wraps per-turn pacing metadata. Don't insert extra `dna_sleep` calls around it.
