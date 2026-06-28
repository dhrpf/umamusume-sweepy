# Trailblazer (mant) — UG Rating Strategy

> Synthesized from public English-language guides (auto-captioned transcripts
> in this folder) plus the in-code rank tables in `public/app.js`. Used as the
> reference doc when tuning `career_bot/presets.py`, `mant.py`, and presets
> under `data/presets/`.

## 1. What "UG" actually is

The career's final letter rating is computed from a `rank_score` integer
returned by the game. The dashboard's `VET_RANK_LABELS`
(`public/app.js:2319-2337`) defines the full ladder. **UG is rank id 19** —
the entry tier of the "Ultimate" (U-prefix) ranks. The full Ultimate ladder
goes UG → UG+ → UF → UF+ → UE → … → UA → UA+ → US → US+.

| Tier | rank_id | Notes |
|---|---|---|
| SS+ | 18 | Final pre-Ultimate rank |
| **UG** | **19** | Entry into Ultimate — inheritance threshold target |
| UG+ | 20 | |
| UF, UF+, UE, UE+, UD, UD+, UC, UC+, UB, UB+, UA, UA+ | 21–32 | |
| US, US+ | 33, 34 | Cap |

**Observed rank_score samples** (from the Taiki Shuttle UG4 run,
`NV4_oYM0aMo`):

- UG4 ≈ **21,320** rank_score (3rd-from-top sub-tier within UG bucket)
- UG5 was within reach (~+200–300 more)
- A common Seiun Sky stream run also finished UG (`HQT005_062k`)

Working baseline: **UG entry ≈ 20,500 rank_score**, UG+ ≈ 22,000 (cross-check
when we capture more end-of-run telemetry from real runs).

## 2. The five pillars that determine `rank_score`

1. **Total stat sum** with diminishing returns past ~1100 and a soft cap at
   1200 (the blue-factor threshold). Stats _near 1000_ have extra scaling
   ("stats closer to 1,000 have more scaling" — MaybeVoid).
2. **Skill points spent / unique skills owned.** Aim for ~2,500–2,800 skill
   points so you can buy 8–10 skills at the end. Final shop wave matters.
3. **Race wins / fan count.** Total races run = **34–37** for mile/medium/long
   umas (JackieX's usual range). 30–31 is conservative, 40–41 is aggressive.
   You **must win the G1s** that anchor your set bonuses.
4. **Set bonuses.** Hitting full G1 sets (Triple Crown, Mile, Sprinter etc.)
   adds large stat lumps. Mile set is the lowest barrier; most umas can hit
   it via a single mile spark from a legacy parent.
5. **Aptitude grades.** Every aptitude in the planned race plan should be
   **B minimum, A ideal**. Fix gaps with parent / legacy sparks.

## 3. Hard deck rules

- **Race bonus ≥ 50%** on the deck (Trailblazer multiplies stat gains by
  race bonus over the whole career).
- Keep a sane stat-card ratio — don't trade your speed/pwr coverage for raw
  race bonus.
- F2P-viable benchmark: a ~50% race-bonus deck can still UG with luck.
  MLB whales sit around 60–65%.
- **Rico** (SSR, 3LB+) is a "rest-button with stats" — huge comfort if you
  own her.

## 4. Stat targets per running style (refined from `presets.py`)

Sweepy ordering: `[SPD, STA, PWR, GUT, WIT]`. Numbers are the "near-target"
zone — the bot should be allowed to push past these toward the 1200 hard cap
once race bonus + summer megaphones land.

| Style | Floor for UG attempt | Stretch (UG+ / UG3+) |
|---|---|---|
| Front Runner (1)  | 1200 / 1100 / 600  / 0 / 500 | 1200 / 1200 / 900  / 0 / 700 |
| Pace Chaser  (2)  | 1200 /  900 / 1100 / 0 / 500 | 1200 / 1100 / 1200 / 0 / 700 |
| Late Surger  (3)  | 1200 /  700 / 1100 / 0 / 600 | 1200 /  900 / 1200 / 0 / 800 |
| End Closer   (4)  | 1200 / 1100 / 1100 / 0 / 500 | 1200 / 1200 / 1200 / 0 / 700 |

Rule: **"triple-capped on three stats" + ~2.7k skill points ≈ UG**
(MaybeVoid Taiki Shuttle).

## 5. Turn-by-turn rules the bot must encode

### 5.1 Pre-debut (first 15 turns)

- Race takes **20 energy** in Trailblazer (not 15). Save energy for the post-
  junior 3-training window.
- Evenly raise bonds; **all support cards should hit rainbow before first
  summer camp** (turn ~36).
- At most 2 rests in this window (usually 0–1). Prefer **wit click** when
  energy is tight.
- Last 2 turns before junior race: time the rest so the junior race lands
  with enough energy for **3 trainings immediately after**.

### 5.2 Race vs train threshold

- Default "train if best training ≥ +40 total stats, else race" is a **good
  baseline, scale down for low-bonus umas** (a 0% speed-bonus uma like
  Mayano never hits +40 → would never train speed → never UGs).
- New preset knob: `train_min_total_stat_gain` (default 40, drop to 28–32
  for low-bonus umas).

### 5.3 Racing & energy

- Racing at 0 energy → guaranteed mood-down. Use 20-vita right before, OR a
  **Max Energy Drink** to convert the mood-down into nothing.
- After a race, **prefer the bottom dialogue option** — chance of getting
  −10/−15 energy if you placed 2nd/3rd, which lets you chain another race.
- **Avoid 4 races in a row** anywhere except special umas (Oguri,
  Smart Falcon) in late-second/third year.
- **Last day of each year** is a "scam window" — chained-race bad effects
  don't proc, so you can stack races there safely.

### 5.4 Clocks

- **Never burn clocks on G3/G2** unless 1st place — 2nd/3rd give only 60%
  payout vs 100%, and the clock is worth way more on a missed G1.
- **Always clock missed G1s** that anchor your set bonuses.
- If a run is already glued (low race bonus, lost a key G1, can't finish set
  bonus), stop burning clocks.

### 5.5 Summer camp (turns 36–40 and 60–64)

- All facilities at max level; pop **60% megaphone + matching stat angle**
  on rainbow turns.
- Bot must **hold ≥2 Empowering Megaphones** entering each summer camp so
  all 4 camp turns are covered.
- If summer turns are bad (no rainbow, no whistle), racing still beats a
  bad training.

### 5.6 Last 3 turns (turns 70–72)

- **Item duration weirdness**: a race counts as a turn. A 2-turn megaphone
  used pre-race gets eaten by the race transition.
- The bot must **reserve 3 Master Cleat Hammers** for the final-3 races.
- **Never** use a hammer on a training turn during the final 3; the race
  entry consumes the buff and converts +20 → +15 stat reward.

### 5.7 Skill buying

- Aim for **~2,700+ skill points unspent** entering the final shop wave.
- Lower `learn_skill_threshold` (default 888) → roughly 700–800 — Trailblazer
  rank score scales hard with the number of skills learned; we should bias
  toward buying skills rather than hoarding points.

## 6. Where to encode each rule in the codebase

| Rule | Encode in | Field / hook |
|---|---|---|
| Target rank (UG) | `presets.py` | `target_rank: int = 19` |
| Race count budget (34–37) | `presets.py` + `races.py` | `min_races`, `max_races` |
| Race bonus floor | `presets.py` | `race_bonus_target` (descriptive — backend can warn if violated by the deck) |
| Train-vs-race +40 rule | `mant.py::_best_command` | new pre-race comparison using `train_min_total_stat_gain` |
| Stats-near-1000 scaling bonus | `mant.py::_score_command` | small additive multiplier when current stat is in [800, 1050] |
| Floor / cap stat profiles | `presets.py::STYLE_STAT_PROFILES` | already exists — tighten WIT floors |
| Summer-camp megaphone lock | `items.py` (future) | reserve 2× Empowering Megaphone going into turn 36 / 60 |
| Last-3-turns hammer lock | `items.py` (future) | hold 3× Master Cleat Hammer for turns 70–72; only use on race |
| Skill buying aggression | `presets.py` | lower default `learn_skill_threshold` |
| Final-3 race priority | `races.py::choose` | (existing — already prefers wanted G1 races) |

This iteration ships items #1, #2, #4, #5, #8 (preset fields + `_score_command`
+ `_best_command`). Items.py changes are flagged in `context.md §next steps`
for a follow-up session because that file is already complex.
