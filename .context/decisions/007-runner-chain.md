# ADR-007: Runner loop chain order

## Context

Each turn: drain events → recover blocked state → decide → execute → maybe buy skills → advance.

## Decision

`CareerRunner._run()` order:
1. `_drain_events`
2. `_recover_blocked_state`
3. `_debug_turn`
4. `strategy.next_decision()`; `StateRecoveryError` refreshes state
5. Command path: `_handle_items` → re-drain → re-decide
6. Dispatch event/race/command/finish
7. `_buy_skills` unless finishing
8. `_advance`

Programming errors re-raise. Recoverable API failures include network errors, `StateRecoveryError`, 102, 201, 205, 208, 213, 214, 217, 2502, 501, 709, 917, 1055, and 1503. 501 uses client cold relogin; 917 escalates to `StateRecoveryError`.

## Consequences

Do not reorder loop phases. 102/1503 are state-reconciliation signals; handle at endpoint-specific runner branches, never blanket-swallow.

See: `CareerRunner._run`, `_fresh_career_state`, `.claude/rules/career-loop.md`.
