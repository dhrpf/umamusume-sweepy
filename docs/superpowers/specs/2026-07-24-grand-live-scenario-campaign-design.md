# Grand Live Scenario and Campaign Support Design

**Date:** 2026-07-24

## Goal

Make game scenario `3` (Grand Live) fully playable through ordinary presets and Campaign runs. Sweepy must route Grand Live API traffic correctly, automate lesson purchases and concerts, account for performance-token value during training selection, expose the scenario in the UI, and preserve the selected scenario through the complete Campaign lifecycle.

Icarus 5.0 is the behavioral reference for the scenario flow. Sweepy's installed `master.mdb` is authoritative for lesson-square prices, rewards, colors, and song metadata.

## Scenario Identity

The game career `scenario_id` for Grand Live is `3`.

This is independent from veteran display labels. The existing veteran-detail mapping calls veteran scenario label `5` "Grand Live"; that value describes completed-veteran metadata and must not be reused for career API routing or preset validation.

## Architecture

Implement Grand Live as a rule-based overlay on `UraStrategy`, not as a fork of the career loop.

`GrandLiveStrategy` inherits the stable event, race, skill, finish, and ordinary command behavior from URA. It owns only Grand Live mechanics:

- lesson-board evaluation and purchases;
- concert dispatch;
- Grand Live training-score supplements;
- scenario-specific state handling;
- disabling unsupported MCTS decisions.

The game client owns endpoint routing and scenario-specific request wrappers. The runner owns dispatch of strategy decisions. Campaign remains scenario-agnostic and carries scenario `3` through its existing preset preparation and recovery flow.

## API Routing and Client Methods

When the active career scenario is `3`, `UmaClient.call()` remaps supported `single_mode_free/*` operations to `single_mode_live/*`. Callers continue using canonical operations; scenario checks do not leak into the runner or strategy.

Add explicit client methods for the Grand Live-only operations:

- `single_mode_live/master_square` purchases one selected lesson square;
- `single_mode_live/live_start` performs the current concert.

The client methods construct only the wire fields required by the endpoint and call the existing msgpack/AES transport. They inherit standard result-code recovery and never issue raw HTTP.

`reserve_square` is excluded. Reserving a visual board choice does not advance the scenario and is unnecessary for automation.

## Generated Master Data

Add a generator that reads Grand Live lesson and song records from `master.mdb` and produces one deterministic JSON artifact under `data/`.

For every purchasable square, generated data includes:

- square ID;
- square type: song or lesson;
- performance-token costs by color;
- granted song ID when applicable;
- reward metadata needed for ranking, including Skill Points;
- display name when resolvable.

For every song, generated data includes the identifiers needed to recognize owned and available songs.

The generator sorts records deterministically and validates duplicate IDs, negative costs, and missing square types. Static Grand Live JSON is never hand-edited.

Runtime loading fails closed for an unknown square: Sweepy logs the unknown ID and does not buy it. A missing or malformed generated artifact prevents scenario `3` from starting and surfaces an actionable configuration error instead of guessing prices; other scenarios remain available.

## Grand Live State

Grand Live responses may be partial. A lesson purchase can return updated scenario data without every ordinary career field. The strategy/runner state merge preserves the latest known:

- `chara_info`;
- `home_info`;
- unchecked events;
- command information;
- Grand Live performance balances;
- lesson board and owned songs;
- concert state.

A response field replaces prior state only when present. Empty arrays explicitly returned by the server are preserved as empty rather than treated as missing.

The normal decision loop recognizes both Grand Live playing states `5` and `10` as recoverable active states. Neither state is treated as an unknown terminal condition.

## Decisions and Runner Dispatch

Extend the strategy decision vocabulary with two internal actions:

- `lessons`: drain eligible lesson purchases;
- `live_perform`: start a due concert.

The runner dispatches these actions before ordinary training commands. Existing unchecked-event draining remains first.

At a decision point, ordering is:

1. drain unchecked events;
2. buy lessons when the board contains a verified affordable target;
3. perform a due concert after lesson purchases are exhausted;
4. handle race, finish, and recovery states;
5. choose an ordinary command with Grand Live scoring.

Lesson draining is bounded to 60 purchases per decision cycle. Each successful response is merged before choosing the next square. The bound prevents a malformed or cyclic board from trapping the runner indefinitely.

## Lesson Selection

The picker uses current performance balances, generated square metadata, owned songs, and server-provided progress for the upcoming concert. The song target counts songs credited to the upcoming concert, not the career's lifetime song total.

Priority is lexicographic:

1. Buy available songs until at least three songs are credited to the upcoming concert. Completed concerts reset this target through server state; Sweepy does not infer the reset from turn number.
2. Then buy a square that grants Skill Points.
3. Then buy the cheapest verified square to reroll or advance the board.

A square is eligible only when:

- its ID exists in generated master data;
- all required token costs are known;
- current balances cover every cost;
- buying it would not consume a token color already above 80% of the server-provided maximum when another eligible option avoids that color. If the server omits a maximum, disable this preference for that color rather than inventing a capacity.

When several squares have the same priority, prefer lower total token cost, then lower square ID for deterministic behavior.

If the board has no verified affordable square, return to the normal career decision. Unknown or ambiguous prices are never treated as zero.

## Concert Scheduling

Grand Live concerts are due at turns `24`, `36`, `48`, `60`, and `72`.

A concert is dispatched exactly once when server state marks it available. Turn number alone is insufficient; the strategy also checks current concert progress so resume/reconcile cannot replay an already completed live.

At a concert turn, Sweepy first drains verified lesson purchases, then calls `live_start`. The response is merged through the same partial-state path before the next decision.

## Training Scoring

Reuse URA's base command score, then add Grand Live value from:

- supplemental scenario stat or Skill Point gains attached to the command;
- expected performance-token yield.

Token yield is converted into score using preset field `performance_training_weight`, default `0.6`. The default changes only Grand Live scoring and does not alter existing presets for other scenarios.

MCTS is disabled for scenario `3`. The current simulator does not model token balances, rotating lesson boards, song thresholds, or concerts. If a Grand Live preset requests MCTS, the strategy logs a clear fallback and uses the rule-based scorer.

## Presets and UI

Preset validation accepts `scenario_id: 3` and round-trips:

```json
{
  "scenario_id": 3,
  "performance_training_weight": 0.6
}
```

Existing presets without the weight receive the default at read time. Validation accepts finite non-negative numeric values. Saving and reloading preserves an explicit zero or any other valid value.

The frontend adds Grand Live to the career scenario selector and shows `performance_training_weight` only when Grand Live is selected. Client-side serialization and edit-form hydration preserve the field. Veteran display labels remain unchanged because they use a separate namespace.

## Campaign Integration

Campaign accepts a base preset with `scenario_id: 3`. It must preserve both `scenario_id` and `performance_training_weight` through:

- campaign creation;
- `prepare_next_run()`;
- start payload construction;
- pause and resume;
- process restart recovery;
- active-run reconciliation;
- subsequent Campaign members and Final Uma runs.

Campaign does not implement a separate Grand Live optimizer. Every prepared run uses `GrandLiveStrategy` through the same runner registration as a manually started preset.

Campaign validation rejects Grand Live only when its base preset is otherwise invalid. It must not silently replace scenario `3` with a default scenario during cloning or normalization.

## Error Handling and Diagnostics

- Unknown lesson square: log its ID and skip it.
- Missing generated master data: reject starting scenario `3` with an actionable configuration error; do not affect other scenarios.
- Partially updated response: merge present fields and retain prior absent fields.
- Sixty-purchase guard reached: stop draining, log the guard, and yield to the next runner cycle.
- Concert endpoint failure: use standard API recovery; do not mark the concert complete without server evidence.
- Unsupported MCTS request: fall back to rule-based Grand Live scoring.
- Unknown playing state outside supported existing and Grand Live states: retain current runner failure behavior.

Diagnostics may include scenario, turn, square ID, cost, balances, priority reason, and concert number. They must not include account or authentication identifiers.

## Tests

Add focused automated coverage for:

- scenario `3` strategy registration;
- standard endpoint remapping to `single_mode_live/*`;
- `master_square` and `live_start` payloads;
- deterministic master-data generation and validation;
- song-first, Skill-Point-second, cheapest-third lesson priority;
- affordability and 80% token-cap behavior;
- unknown-square fail-closed behavior;
- partial-response state merging, including explicit empty arrays;
- 60-purchase drain guard;
- playing states `5` and `10`;
- concerts at turns 24/36/48/60/72 exactly once;
- Grand Live supplemental gain and token-yield scoring;
- default and explicit `performance_training_weight`;
- MCTS fallback;
- preset serialization and frontend exposure;
- Campaign create, prepare, start, resume, restart, reconcile, and next-member scenario preservation.

Run focused Grand Live tests first, then regression suites for URA, Unity/Aoharu, MANT, presets, API routing, frontend, and Campaign.

## Success Criteria

The work is complete when:

- a normal preset can start and finish scenario `3`;
- lesson purchases, songs, and all five concerts run automatically;
- no unknown or unverified square is purchased;
- Campaign can create, resume, reconcile, and advance Grand Live runs without losing scenario configuration;
- Grand Live uses rule-based scoring with performance value;
- existing scenario and Campaign regression tests remain green.

## Deliberate Limits

- No Grand Live MCTS simulator.
- No `reserve_square` calls.
- No Campaign-specific Grand Live optimizer.
- No copied partial price table from Icarus.
- No live-account integration run in automated tests.
