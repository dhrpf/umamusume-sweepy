# 012 — Event choice_number must use gain_select_id_index

## Status: ACCEPTED

## Problem
Bot got 205 on every `check_event`. Trace showed server returned choices with
`gain_select_id_index` ∈ {4,2,5} but bot sent `choice_number=1` (the
`select_index`). Server rejects unknown choice ids → 205.

## Root cause
`select_index` is a position-based label (always starts at 1). Server tracks
options by `gain_select_id_index` (effect-map position). They can diverge when
events have >3 options or gaps in the id space.

## Fix
`_choice()` / `_choose_from_reward()` now return
`choice.get("gain_select_id_index", choice.get("select_index", 0))`. Fallback to
`select_index` only if `gain_select_id_index` absent (older capture format).

Affected: `career_bot/scenarios/mant.py`, `career_bot/scenarios/ura.py`,
`tests/test_ura_event_choice.py`.

## Verification
`pytest tests/test_ura_event_choice.py` → 3 passed.
