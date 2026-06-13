# Randomized Run Delay + Selectable TP Strategy

**Date:** 2026-06-13
**Status:** Approved, pending implementation plan

## Problem

When `dev_mode` is on, `manage_career_loop` runs careers back-to-back with only a
fixed ~6-second gap, and TP exhaustion is handled by a single binary flag
(`stop_on_empty_tp`): either spend carats to top up, or stop the loop.

Two gaps:

1. No human-like pacing between runs. We want a randomized delay drawn from a
   configurable range (e.g. 10–50 minutes) between consecutive careers.
2. No "wait for natural TP regen" option. Today the only way to avoid spending
   carats is to stop the loop entirely. We want the loop to optionally idle until
   TP regenerates to the `use_tp` minimum, then continue — no carats spent, no stop.

## Goals

- Configurable, randomized inter-run delay range (minutes), per preset.
- Selectable TP-empty strategy per preset: `carat` (restore by spending carats) or
  `wait` (idle until TP regenerates to `use_tp`).
- Expose both as controls in the web UI near the DEV-mode toggle.

## Non-Goals

- A user-facing "stop loop on empty TP" mode. The existing `stop_on_empty_tp` flag
  stays in code as an orthogonal back-compat override but is not surfaced as a
  new UI choice.
- Changing carat-spend behavior itself (`recovery_tp` logic untouched).

## Configuration

Three new fields, stored in preset JSON (`data/presets/*.json`) and mirrored on
`RunCareerRequest`:

```jsonc
"run_delay_min_min": 10,   // min minutes between careers (int, >= 0)
"run_delay_max_min": 50,   // max minutes between careers (int, >= min)
"tp_mode": "carat"          // "carat" | "wait"
```

Flow of values:

- Preset store is dict-based (`PresetStore` / `SavePresetRequest` accept arbitrary
  preset dicts), so no schema plumbing is required to persist the fields.
- `RunCareerRequest` gains the three fields with safe defaults:
  `run_delay_min_min: int = 0`, `run_delay_max_min: int = 0`, `tp_mode: str = "carat"`.
- The web UI loads the fields from the selected preset, sends them on the run
  payload, and saves them back into the preset on preset save.
- `manage_career_loop` reads the delay range from `req`.
- `start_career_from_request` reads `req.tp_mode`.

Validation / defaults:

- If `tp_mode` is missing or unrecognized → treat as `"carat"`.
- If `run_delay_max_min < run_delay_min_min` → clamp max up to min.
- If both delay values are 0 → fall back to the current ~6s gap (no long idle).

## Component Changes

### `start_career_from_request` (main.py ~834)

When `req.use_tp and current_tp < req.use_tp`:

1. If `stop_on_empty_tp` is True → return `TP_EXHAUSTED` (unchanged, orthogonal
   override, evaluated first).
2. Else if `req.tp_mode == "wait"` → return
   `{"success": False, "detail": "TP_REGEN_WAIT", "current_tp": current_tp, "use_tp": req.use_tp}`.
   No carats spent, no error raised.
3. Else (`tp_mode == "carat"`, default) → existing `recovery_tp` retry loop,
   unchanged.

The function already calls `load/index` at its top on every invocation
(main.py:816), refreshing `tp_info` from the server. So a `wait`-mode retry sees
fresh TP automatically; no extra refresh logic needed.

### `manage_career_loop` (main.py ~1261)

**Inter-run delay.** Replace the fixed `for _ in range(6): dna_sleep(1.0, 1.0)`
gap (executed after a career finishes, before the next start) with:

- Compute `delay_sec = random.uniform(min_min, max_min) * 60` using the resolved
  range. If range is `(0, 0)` → use the current ~6s fallback.
- Sleep `delay_sec` in 1-second slices, checking `backend_loop_stop` each slice
  and returning early if set.

**Wait-for-regen.** In the start-retry block, when
`started.get("detail") == "TP_REGEN_WAIT"`:

- Compute the wait from the TP deficit, since regen is a fixed ~10 min/TP
  (1 TP = 10 min, 30 TP = 5 h, 100 TP cap):
  `wait_sec = (use_tp - current_tp) * 600 + 60` (60s buffer so the threshold is
  actually crossed), floored at 60s so it never busy-loops.
- Log the wait (current_tp / use_tp / computed wait).
- Sleep `wait_sec` in 1-second slices, checking `backend_loop_stop`
  (return early if set).
- Retry the start. The retry re-reads fresh TP via `load/index` and recomputes,
  so any timing drift self-corrects on the next pass. Do **not** increment
  `consecutive_fails`. Loop until TP recovers (start succeeds) or the loop is
  stopped.

This replaces today's `return` on TP exhaustion specifically for `wait` mode; the
`TP_EXHAUSTED` path (carat-mode + `stop_on_empty_tp`) still returns/stops as
before.

### Web UI (`public/`)

Near the hidden DEV-mode toggle:

- Two number inputs: delay min (minutes), delay max (minutes).
- One dropdown: TP mode — "Carat restore" (`carat`) / "Wait for regen" (`wait`).

Behavior:

- Populated from the currently selected preset when a preset is loaded.
- Saved into the preset on preset save (alongside existing preset fields).
- Included in the run request payload when starting a career.

## Data Flow

```
preset JSON ──load──> UI controls ──run payload──> RunCareerRequest
                          │                              │
                          └──save──> preset JSON         ├─ run_delay_* ─> manage_career_loop (delay)
                                                         └─ tp_mode ─────> start_career_from_request (TP strategy)
```

## Error Handling

- `wait` mode never raises on low TP; it returns `TP_REGEN_WAIT` and the loop
  idles. Other start failures still flow through the existing `consecutive_fails`
  path.
- All long sleeps (delay and regen-poll) are 1-second-sliced and honor
  `backend_loop_stop` so stop remains responsive.
- Unknown `tp_mode` value degrades to `carat`.

## Testing

- **Delay range:** resolved delay value lands within `[min, max]` minutes;
  `(0, 0)` resolves to the fallback gap; `max < min` clamps correctly.
- **TP wait mode:** `start_career_from_request` returns `TP_REGEN_WAIT` (no carat
  spend) when `tp_mode="wait"` and `current_tp < use_tp`, using a mocked
  `UmaClient`.
- **Regen wait calc:** deficit-based wait equals `(use_tp - current_tp) * 600 + 60`,
  floored at 60s (e.g. deficit 3 → 1860s; deficit 0 or tiny → 60s floor).
- **TP carat mode:** carat path returns identical behavior to today (regression).
- **Stop responsiveness:** setting `backend_loop_stop` during a delay/regen sleep
  causes the loop to return promptly (within ~1s).
