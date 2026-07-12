# ADR-010: Training Failure Field

## Context

Training options provide `command_info_array[].failure_rate`.

## Decision

URA and Mant read `failure_rate` for training-risk scoring. Preserve this field name in strategy code and tests. If a live capture differs, inspect payload before adding compatibility logic.

## Consequences

- Do not add `fail_percent` fallbacks without capture evidence.
- Rest gates and command scoring must use game-provided failure data.

See: `career_bot/scenarios/ura.py`, `career_bot/scenarios/mant.py`.
