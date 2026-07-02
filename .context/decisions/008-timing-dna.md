ADR-008: Timing DNA — seeded RNG + per-user sigma/speed

Context
  Uniform delays look bot-like. Need realistic inter-call jitter per installation.

Decision
  First run: write random 7-digit seed to `.timing_dna`. Reuse on subsequent boots.
  Seed → deterministic RNG picks once:
    - `_USER_SIGMA` ∈ [0.45, 0.75]
    - `_USER_SPEED_SHIFT` ∈ [0.92, 1.08]
    - distraction chance ∈ [1.5%, 6.5%]
  Each endpoint: `_BASE_DELAYS` (real_min, real_max, real_avg) × shift × endpoint-uniform-shift → lognormvariate(mu, sigma).
  Per-turn delay separately lognormal on TURN_DELAY_MIN/MAX=2.5-5.0.

Consequences
  - Same install → same profile across reboots unless `.timing_dna` deleted.
  - `GLOBAL_DELAYS_DISABLED` env override exists.
  - Never call `time.sleep` on API paths — use `dna_sleep`/`dna_uniform`/`dna_gauss`/`dna_randint`.

See: `career_bot/delay.py:7-126`
