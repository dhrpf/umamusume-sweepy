ADR-005: Rule-based default + calibration-gated MCTS alpha

Context
  Need career planner. MCTS pure math but unrewarded without real-game params.

Decision
  `STRATEGIES` dict in `runner.py` only maps {4: MantStrategy, 1: UraStrategy}.
  MCTS NOT wired into `CareerRunner.start()` — grep confirms zero MCTS refs in runner/main.
  `SimulatorBase.enabled` True only when calibrated_from >= 20 logs:
    - <20 logs → warning confidence
    - <10 logs → disabled
  URA sim loads `params.json`; `MCTSConfig.time_budget_sec=5` + `max_simulations` dual-budget cutoff.

Consequences
  - MCTS can't be flipped on implicitly — opt-in required.
  - Calibration data grows in `mcts/calibration/`.
  - `use_expected_value` mode replaces rollout RNG with weighted sums.

See: `career_bot/runner.py:25-28,109-110`; `career_bot/mcts/sim/ura.py:19-59`; `career_bot/mcts/__init__.py`
