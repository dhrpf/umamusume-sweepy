ADR-004: Endpoint path remap per scenario_id

Context
  Career endpoints shift by scenario: URA=1 → `single_mode/*`, Mant=4 → `single_mode_free/*`, Aoharu=2 → `single_mode_team/*`.

Decision
  `UmaClient.call()` intercepts `single_mode_free/<op>` before send → rewrites prefix per `self.current_scenario_id`. Whitelist of 12 ops, client-side hardcoded.

Consequences
  - Adding a new op (e.g., minigame) requires touching both if-elif blocks.
  - Canonical path per op must be captured from live traffic.

See: `uma_api/client.py:700-717`
