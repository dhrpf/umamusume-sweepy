ADR-007: Runner loop chain order

Context
  Each turn: recover state → heal events → pick action → maybe buy skills → advance.

Decision
  `_run_loop` order:
    1. `_drain_events`
    2. Recovery (playing_state ↦ {1-5})
    3. `_debug_turn`
    4. `strategy.next_decision()` (may raise StateRecoveryError)
    5. if command → `_handle_items(pre-race/items)` → re-drain → re-decide
    6. execute (event/race/command/finish)
    7. `_buy_skills` (unless finished)
    8. `_advance`
  Crash path: programming errors re-raise; API errors (Network error, 201, 205, 208, 213, 214, 217, 2502, 709, 1055, 1503) absorbed.
  102/1503 are "already done" logic errors — never swallow.

Consequences
  - Rule id 2 in `.claude/rules/career-loop.md` codifies. Don't reorder.

See: `career_bot/runner.py:170-394`
