ADR-011: Steam auth via node bridge

Context
  Capture flow needs Steam session ticket. No clean Python SteamUser lib.

Decision
  Embed `TICKET_GEN_JS` inline → spawn `node -e` with `steam-user` npm package.
  Writes refresh token to `~/.uma_runtime/steam_refresh_tokens/<user>.jwt`.
  Extracts `session_ticket` on login.
  Exit codes: `REFRESH_TOKEN_EXPIRED` (fail), `NEED_GUARD:2fa` (2), other (3).

Consequences
  - `node` binary is hard dep (raised in `check_deps`).
  - `node_modules` must be installed at repo root.
  - Captured stderr used for status JSON parsing — don't redirect logs carelessly.

See: `uma_api/client.py:50-157,457-460,466+`
