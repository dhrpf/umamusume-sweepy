# ADR-005: Rule-Based Default + Calibration-Gated MCTS

## Context

Rule-based strategies remain production default. MCTS needs calibrated simulator parameters before its results are trustworthy.

## Decision

`CareerRunner.STRATEGIES` maps Mant and URA strategies; runner does not select a planner directly. URA strategy can use its MCTS/simulator path when its configuration and calibrated simulator permit it.

`UraSimulator` calibration state:

- Fewer than 10 logs: disabled.
- 10–19 logs: enabled with warning confidence.
- 20 or more logs: enabled with high confidence.

MCTS honors both `time_budget_sec` and `max_simulations`. Simulator remains side-effect free; live API calls stay in runner/client layers.

## Consequences

- Do not silently enable a new scenario simulator from runner startup.
- Preserve calibration data and update simulator parameters through calibration workflow.
- Rule-based decision behavior remains fallback when MCTS is disabled.

See: `CareerRunner.STRATEGIES`, `UraStrategy`, `UraSimulator`.
