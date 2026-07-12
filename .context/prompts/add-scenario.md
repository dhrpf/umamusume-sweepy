# Protocol: add-scenario

**Trigger**: new `scenario_id`, career type, minigame integration.

## Pre-checks

1. Confirm id is absent from `CareerRunner.STRATEGIES`.
2. Choose rule-based strategy or MCTS simulator:
   - Rule-based: implement scenario `next_decision(state, preset) -> Decision`.
   - MCTS: subclass `SimulatorBase`; keep it pure and calibrated.

## Rule-Based Steps

1. Create `career_bot/scenarios/<name>.py` with scenario id and `next_decision`.
2. Return supported actions only: `command`, `event`, `race`, `race_progress`, `finish`, `idle`, `done`.
3. Command payload includes `current_turn` plus command identifier metadata.
4. Import strategy in `career_bot/runner.py`; add scenario id to `STRATEGIES`.
5. Confirm FastAPI preset/start validation accepts scenario id.
6. Add strategy tests following existing Mant/URA test patterns.

## MCTS Steps

1. Add simulator under `career_bot/mcts/sim/`.
2. Extend `GameState`/actions only through canonical MCTS models.
3. Provide calibrated parameter loading and honor MCTS budgets.
4. Do not switch runner startup behavior without explicit configuration.

## Verify

```bash
venv/bin/python -m pytest tests/test_mant_strategy.py tests/test_ura_*.py tests/test_mcts_*.py -x
```

## Known Traps

- `UmaClient.call()` remaps core endpoints for scenario 1 and 2; avoid manual endpoint rewrites.
- Event drain occurs before strategy decision.
- Registered scenario id must match `load_career` and start payload.
- A new action without runner dispatch breaks loop control.
