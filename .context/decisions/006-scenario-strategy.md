ADR-006: Scenario Strategy pattern

Context
  Route career decisions across scenarios without if/else in runner.

Decision
  `ScenarioStrategy` base class:
    - `scenario_id` class attr
    - `next_decision(state, preset) -> Decision`
    - `Decision.action` ∈ {command, event, race, race_progress, finish, idle, done}
  Runner dispatches via dict lookup, then action-based branching.
  `_choice()` used by event drain.

Consequences
  - New action → update runner dispatch (rule #2 in scenarios.md).
  - New scenario → subclass + STRATEGIES registration + scenario-specific `SUMMER_CAMP_TURNS` lookup.

See: `career_bot/scenarios/base.py:4-15`; `career_bot/runner.py:25-28,109-110,234-363`
