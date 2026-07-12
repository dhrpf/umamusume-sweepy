# ADR-002: SID Regeneration — make_sid vs next_sid

## Context

SID identifies API session state. New login/bootstrap needs fresh derivation; successful responses advance the SID chain.

## Decision

- `regen_sid()` derives SID with `make_sid(viewer_id, udid_str)` for new session/bootstrap state.
- `next_sid()` advances from response `data_headers.sid` after a successful response.
- Do not regenerate SID inside ordinary retries.
- Result 214 updates resource version, closes and recreates transport, reapplies headers/proxy, resets and regenerates SID, starts session, then retries endpoint.

## Consequences

Incorrect SID advancement creates replay/session failures. Keep SID changes inside `UmaClient` recovery paths.

See: `make_sid`, `next_sid`, `UmaClient.regen_sid`, `UmaClient.call`.
