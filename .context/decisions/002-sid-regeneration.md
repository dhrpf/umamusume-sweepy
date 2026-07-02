ADR-002: SID regeneration — make_sid vs next_sid

Context
  SID is auth token; 1055/session-stale demands fresh derivation.

Decision
  `regen_sid()` always calls `make_sid(viewer_id, udid_str)` — never `next_sid` mid-session.
  `next_sid()` only used when loading saved SID from prior state cache (e.g., `_fresh_career_state` takes `next_sid(dh['sid'])`).
  214 (res_ver) auto-updates + retries WITHOUT SID regen.

Consequences
  - Calling `regen_sid` inside a retry except after 208 is a protocol violation.
  - Rule #2 in `.claude/rules/api.md` codifies.

See: `uma_api/client.py:210-214,678-679,888,961`
