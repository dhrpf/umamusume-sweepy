ADR-009: TP strategy — carat vs wait decision

Context
  Career costs TP. Must decide: pay gems (carat), wait for natural regen (600s/TP + 60s buffer + 60s floor), or halt.

Decision
  `decide_tp_action(use_tp, current_tp, tp_mode, stop_on_empty_tp)` returns:
    - ok: enough TP
    - stop: stop_on_empty_tp True
    - wait: tp_mode == "wait"
    - carat: everything else
  `pick_delay_seconds` converts min-minute ranges to seconds for inter-run pacing.
  tp_mode normalized to lowercase; anything but "wait" → "carat".

Consequences
  - Default fallback delay 6s for (0,0) range.
  - `stop_on_empty_tp=True` halts when TP < use_tp; default recovers with gems.

See: `career_bot/delay.py:128-182`
