# Rule: MCTS Planner (alpha)

Paths: `career_bot/mcts/**`

## Status

1. MCTS is alpha — NOT wired into `CareerRunner.start()` (scenario_ids 1 & 4 still use rule-based strategies). Don't flip MCTS on without explicit opt-in config.
2. Simulator (`mcts/sim/*.py`) is the only side-effectful layer. Planner is pure. Don't add network/DB calls to `planner.py`.

## State

3. `GameState` dataclass: `speed, stamina, power, guts, wiz, vital, max_vital, motivation, turn`. Don't add ad-hoc attributes — extend the dataclass.
4. `sim.generate_actions(state)` returns `tuple[Action, ...]` in canonical order. `Action.stat_gains` length = 6 (speed/stamina/power/guts/wiz/skillpt).
5. Terminal state = `state.turn >= horizon` or `vital <= 0`. Don't hardcode a third terminal.

## Planner

6. `MCTSConfig.time_budget_sec` and `max_simulations` are the two budget knobs. Honor both — whichever fires first stops the search.
7. UCB1 selection with `rng_seed` for reproducibility. Never remove the seed without updating the calibration suite.
8. Rollout policy = `_rollout_policy(state, actions)`: rest when `vital/max_vital < config.rest_vital_ratio`, else max `_action_value`.
9. `_action_value`: sum deficit-weighted gains + `stat_gains[5] * 0.2` + partners*2 - fail_rate*100 - 1000 if `vital + delta <= 0`. Read it as one function; don't decompose.

## Simulator

10. `SimulatorBase.evaluate(state, preset)` is the final-scoring heuristic. `preset.expect_attribute` is the 5-vector target.
11. `ura.py` sim is the only concrete simulator so far. Adding a new scenario = subclass `SimulatorBase`, no copy-paste.
12. Calibration (`mcts/calibration/`): `extract.py` pulls real-game state sequences, `fit.py` tunes weights. Don't tune weights by hand when calibration data exists.

## Pointers for Extension

13. Adding a new stat-bonus model: write a new simulator subclass, register in `STRATEGIES` if the scenario_id is new, pass via `MCTSConfig`.
14. Saving/loading a planner state: serialize `MCTSConfig + GameState`, not the planner object itself.
