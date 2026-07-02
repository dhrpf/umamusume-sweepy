# Rule: Scenario Strategies

Paths: `career_bot/scenarios/**`, `career_bot/master_data.py`

## Invariants

1. `next_decision(state, preset) -> Decision`. Must be pure under `StateRecoveryError`; raise it when state missing instead of returning garbage.
2. Decision.action ∈ {`command`, `event`, `race`, `race_progress`, `finish`, `idle`, `done`}. Never add new actions without updating `runner.py` dispatch.
3. Every `Decision.command` payload must include `current_turn` and one of (`command_id`, `command_group_id`).
4. Summer camp turns vary per scenario — read `SUMMER_CAMP_TURNS`, don't hardcode `{37..40, 61..64}`.
5. Summer camp command_ids 601-605 map to same stats as 101-106. Keep `TRAINING_COMMANDS` and `TRAINING_ENERGY` synchronized.

## Mant (scenario_id=4)

6. `MantStrategy` is the default/active strategy. Changes here affect all non-preset-override runs.
7. Sections: `get_section(turn)` maps turn -> gameplay phase (early/mid/late). Don't cache across turns.
8. Recreation PAL logic: first 3 outings pick support, after = main chara `1017`. Track via `pal_recreation_count`.
9. Energy gates: `ENERGY_FAST_MEDIC=80`, `ENERGY_MEDIC_GENERAL=85`. Only fire medic above these thresholds.
10. Bad effects namespace: `BAD_EFFECT_NAMES = {1:Night Owl, ..., 19:Not Ready}`. Add names as discovered, never assume completeness.

## URA (scenario_id=1)

11. Known bug at `ura.py:609`: reads `cmd.get("fail_percent")` but game sends `"failure_rate"` → bot sees 0% fail chance. DON'T fix backwards — preserving bug parity until runner is aligned.
12. URA rest-gate (line 287) reads `"failure_rate"` correctly; only triggers when ALL trainings ≥ 30%.
13. Pre-camp bond bonus: `camp_bond_bonus = max(0, ORANGE_BOND - avg_bond) * 0.3`. Used to push partners to orange before summer camp.
14. Training score sequence (in priority order): base gain → partner count → bond deficit (non-orange) → deck match +25 → free Wit/energy → Guts energy penalty -10 → near level-up +12 → pre-camp bond → fail gate (skip if gain < 2× fail%).
15. Stat targets and weights live at top of file (`URA_STAT_TARGETS`, `URA_STAT_WEIGHTS`, `URA_STAT_OVER_WEIGHTS`). Tune sim, not prod, unless A/B tested.

## Static Data

16. `career_bot/master_data.py` reads `master.mdb` from Proton compatdata at `~/.local/share/Steam/steamapps/compatdata/3224770/pfx/...`. Override with `UMA_MASTER_MDB`.
17. `write_json`, `read_json`, `dump_table` — always use these for persistence; don't roll `json.dump` directly.
18. `synthesize_skill_data`, `synthesize_chara_list`, `synthesize_support_list` output to `data/*.json`. Regenerate after a game patch.
19. Text map (`text_map`) keys by tuple `(category, index)`. Don't assume index-ordering is unique across categories.
20. Grade mapping: 1=G (worst) ... 8=S (best). Field `proper_ground_turf/dirt` etc. is 1-based, not 0-based.
