ADR-010: Known-bug parity — URA `fail_percent` vs `failure_rate`

Context
  `ura.py:609` reads `cmd.get("fail_percent")` but game sends `"failure_rate"` → bot sees 0% fail chance.

Decision
  DON'T fix backwards. Preserving bug parity until runner is aligned.
  URA rest-gate at line 287 reads `"failure_rate"` correctly — only triggers when ALL trainings ≥ 30%.

Consequences
  - Rule id 11 in `.claude/rules/scenarios.md` codifies.
  - Regression test asserting correct fail% IS forbidden.
  - Fix must land on runner side.

See: `career_bot/scenarios/ura.py:609,287`; `.claude/rules/scenarios.md:11-12`
