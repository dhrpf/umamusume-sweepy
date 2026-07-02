# Protocol: add-scenario

**Trigger**: new scenario_id, career type, minigame integration

## Pre-checks

1. Confirm scenario_id not in `STRATEGIES` at `runner.py:25-28` (only `1` UraStrategy, `4` MantStrategy exist).
2. Decide: **rule-based** vs **MCTS**:
   - Rule-based: subclass `ScenarioStrategy` (`base.py:11`), implement `next_decision`.
   - MCTS: subclass `SimulatorBase` (`mcts/sim/base.py:11-28`), implement `simulate_action`, `generate_actions`, `is_terminal`, `evaluate`.

## Steps — rule-based

1. Create `career_bot/scenarios/<name>.py`:
   - `scenario_id = <N>`
   - `next_decision(self, state, preset) -> Decision` — return one of 7 actions (`base.py:5`).
   - Payload contract: `"command"` MUST include `current_turn` + (`command_id` XOR `command_group_id`).
2. Import at top of `runner.py:13`.
3. Add entry to `STRATEGIES` dict at `runner.py:25-28`.
4. Verify dispatch unpacks: `runner.py:110` lookup, `220`/`245` call sites, `264-363` action branches.
5. Preset wiring: `career_bot/presets.py` validation must accept new `scenario_id` (check `validate_start_selection` in `main.py`).
6. Tests mirroring `tests/test_mant_strategy.py`.

## Steps — MCTS (opt-in only)

1. Create `career_bot/mcts/sim/<name>.py` subclass `SimulatorBase` (`mcts/sim/base.py:11`). Mirror `ura.py:19-28`.
2. Load params from sibling JSON.
3. Wire into `MCTSConfig` if needed (`mcts/core/config.py`).
4. **DO NOT** flip on in `CareerRunner.start()` (`career_bot/runner.py:105`) without explicit flag.

## Verify

- `pytest tests/ -x` unchanged.
- Start career with new `scenario_id`. Confirm `next_decision` fires (add debug print).
- If MCTS: `pytest tests/test_mcts_*.py` green.

## Known Traps

- `base.py:12` `next_decision` abstract — must override.
- `Decision.action` must be one of 7 at `base.py:5` — else runner hits `else` at `runner.py:360-363` and BREAKS LOOP.
- Every `"command"` Decision.payload MUST include `current_turn` + (`command_id` XOR `command_group_id`).
- `runner.py:201-207` drains events BEFORE strategy — strategy receives poisoned state if this contract breaks.
- `runner.py:789` `load_career(scenario_id=...)` must match your registered id.
- MCTS `is_terminal` missing → planner never stops.
