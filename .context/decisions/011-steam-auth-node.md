# ADR-011: Steam Auth via Node Bridge

## Context

Steam session tickets require `steam-user`; project does not depend on a compatible Python replacement.

## Decision

`TICKET_GEN_JS` runs through `node -e` with `steam-user`. It persists refresh token at:

```text
runtime_output_root()/steam_refresh_tokens/<username>.jwt
```

It returns Steam id plus session ticket. `REFRESH_TOKEN_EXPIRED` requires user login refresh; Steam Guard requires interactive handling.

## Consequences

- `node` and repo `node_modules` are runtime dependencies for ticket generation.
- Preserve stderr/status handling; do not redirect it blindly.
- 501 cold recovery regenerates ticket only after reloading cached runtime auth.

See: `_steam_keyfile_path`, `get_ticket`, `UmaClient._refresh_ticket_and_login`.
