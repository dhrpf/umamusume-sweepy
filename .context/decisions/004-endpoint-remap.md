# ADR-004: Endpoint Path Remap per scenario_id

## Context

Career endpoints differ by scenario: URA (1) uses `single_mode/*`, Mant (4) uses `single_mode_free/*`, and Aoharu (2) uses `single_mode_team/*`.

## Decision

`UmaClient.call()` rewrites supported `single_mode_free/<operation>` paths before sending:

- Scenario 1 → `single_mode/<operation>`
- Scenario 2 → `single_mode_team/<operation>`
- Other scenarios → unchanged

Supported operations include load/start, commands/events, race lifecycle, finish/factor selection, style changes, skills, multi-item use/exchange, and minigame completion. Extend both scenario remap branches when adding a supported core operation.

## Consequences

Call client methods with canonical paths; do not hardcode scenario endpoint families in runner or strategies. Capture live traffic before extending remap coverage.

See: `UmaClient.call`.
