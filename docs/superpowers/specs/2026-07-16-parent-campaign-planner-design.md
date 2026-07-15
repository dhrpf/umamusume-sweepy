# Parent Campaign Planner Design

Date: 2026-07-16
Status: Proposed design, ready for implementation planning after user review

## Summary

Add a top-level `/campaigns` Web UI for creating, saving, executing, pausing, resuming, and reviewing parent-building campaigns.

A campaign starts from a required Final Uma, recommends strong Final Parent candidates, recommends an assisted four-Uma affinity loop, generates a shared G1 race agenda and campaign-specific career presets, then repeatedly runs and evaluates careers until one Final Parent candidate satisfies all required spark constraints and can participate in a final inheritance setup with total affinity of at least 150.

The design reuses and evolves the existing SQLite-backed `career_bot/campaigns/` subsystem instead of creating a second campaign implementation.

## Goals

1. Let the user choose a Final Uma first.
2. Let the user define multiple blue and pink spark targets with per-target minimum stars and `required` or `preferred` priority.
3. Recommend three Final Parent candidates, including strong existing owned veterans when they are already close to the target.
4. Recommend an assisted four-Uma affinity loop using owned characters by default, while showing non-owned characters only as optional ideal upgrades.
5. Let the user pin or replace loop members.
6. Let the user manually assign decks while the planner generates campaign-specific career presets.
7. Save campaigns durably and allow multiple saved campaigns per account, with at most one actively executing campaign per account.
8. Resolve the best currently available legacy setup before each run, with pre-run review by default and an optional auto-use-best mode.
9. Evaluate each completed veteran, preserve the best useful candidates, and continue rotating until the required target is met.
10. Stop automatically when all required spark targets are satisfied and the best allowed final setup reaches affinity `>= 150`.
11. Allow the user to continue after success to optimize preferred targets.
12. Keep the campaign execution boundary clean enough that generic workflow infrastructure can later be extracted without rewriting campaign-domain logic.

## Non-Goals for V1

- White skill sparks are not campaign completion targets.
- The planner does not automatically choose support decks.
- The planner does not require every member of the four-Uma loop to become a 9-star parent.
- The planner does not require both final parents to be campaign-built 9-star parents.
- The planner does not create a generic workflow engine before the campaign feature needs it.
- The planner does not delete rejected veterans from the game.

## Design Basis

The campaign model follows a four-Uma legacy loop:

- Four characters with strong mutual compatibility form a reusable loop.
- One character is trained at a time.
- The newly completed trainee becomes a parent in a later run.
- Existing parents shift toward grandparent positions as the loop rotates.
- Older lineage eventually falls out of the active inheritance tree.
- A trainee may appear as one grandparent in a four-character loop. That same-character relationship contributes no affinity, but the loop can still be viable if the total setup remains strong.
- Shared G1 wins are valuable because they increase race compatibility across lineage.
- The loop is a factory for producing a strong Final Parent; the Final Uma is the consumer of that result.

The planner must keep spark quality and affinity as separate concepts:

- Spark constraints determine whether the Final Parent lineage satisfies the campaign target.
- Affinity determines whether the final inheritance setup is acceptable.
- A campaign is successful only when both conditions are satisfied.

## User Flow

### 1. Open the top-level Campaigns page

Route:

```text
/campaigns
```

The page is separate from the existing dashboard inheritance planner.

### 2. Select Final Uma

Final Uma is mandatory before recommendations are generated.

### 3. Define spark targets

The user can add multiple blue or pink spark targets.

Examples:

```text
REQUIRED
Stamina  >= 9 stars
Long     >= 6 stars

PREFERRED
Medium   >= 3 stars
```

Each target contains:

- category: `blue` or `pink`
- normalized spark name
- minimum total stars
- priority: `required` or `preferred`

White skill sparks remain display-only metadata in V1.

### 4. Recommend Final Parent candidates

The planner returns three ranked candidates.

A candidate may be:

1. An existing owned veteran instance that already has useful lineage.
2. A campaign-produced veteran from previous work.
3. A character recommendation that does not yet have a strong instance.

Candidate scoring considers:

- progress toward required spark constraints
- progress toward preferred spark constraints
- best achievable final affinity with an allowed second parent
- existing veteran quality
- estimated remaining campaign effort
- lineage usefulness and G1 overlap

An existing veteran that is already close to completion may rank above a theoretically stronger character that would require rebuilding from scratch.

### 5. Recommend the four-Uma affinity loop

After selecting the Final Parent target, the planner recommends several four-character loop options.

Default source pool:

- owned characters only

The UI may additionally show:

- ideal non-owned upgrade suggestions

The recommendation must optimize for the actual campaign target, not merely raw pairwise compatibility.

Loop scoring considers:

- mutual character compatibility across expected rotations
- predicted stable-loop affinity
- compatibility with the required Final Uma setup
- shared running style where useful
- distance aptitude overlap
- realistic shared G1 calendar coverage
- ability to support the requested spark targets

The user can:

- select a recommended loop
- pin one or more members
- replace an unpinned member
- recalculate the recommendation

The Final Uma may also appear as one loop character if the simulated rotations remain acceptable. The planner must model the zero-affinity same-character relationship rather than forbidding the arrangement categorically.

### 6. Assign decks and campaign options

Deck assignment is manual.

The user selects a deck for each loop member or step as needed.

Campaign options include:

- `allow_rental`: whether friend/rental veterans may be used
- `auto_use_best_veteran`: whether the pre-run resolver may auto-select the best matching veteran
- normal resource strategy already supported by campaign execution

Pre-run review is the default.

### 7. Generate campaign plan

The planner generates:

- initial rotation order
- virtual lineage state
- per-step expected trainee and parent roles
- shared G1 agenda
- campaign-specific base presets
- step-specific preset overrides
- projected affinity information

The base preset is created once for the campaign/member context, while race and other step-specific overrides are recalculated before each run.

### 8. Save campaign

The campaign becomes durable in the existing SQLite campaign store.

Many campaigns may be saved per account, but only one campaign may actively execute for an account at a time.

### 9. Execute runs until target completion

Before each run:

1. Recalculate current campaign context.
2. Resolve the best valid legacy setup from current inventory.
3. Show the pre-run review unless auto-use is enabled.
4. Generate or update step-specific preset overrides.
5. Start one career through the existing career runner.

After each run:

1. Detect the newly created veteran.
2. Evaluate it against required targets, preferred targets, affinity potential, and lineage continuity.
3. Auto-reject it from campaign progression if it is clearly dominated.
4. Request post-run review when the new result has a meaningful trade-off.
5. Select it automatically when it directly satisfies the campaign target without ambiguity.
6. Replan the next rotation.

The veteran remains in the game even when the campaign rejects it.

## Completion Rules

A campaign reaches `TARGET_READY` when:

1. One Final Parent candidate satisfies every `required` spark target on the same relevant lineage.
2. The best allowed final inheritance setup using that Final Parent reaches total affinity `>= 150`.

Preferred targets do not block completion.

After target completion:

- campaign execution stops automatically
- the user may choose `CONTINUE FOR PREFERRED`

If continuing, the already-achieved required target remains recorded as achieved while the campaign seeks better preferred outcomes.

## Final Setup and Second Parent Policy

The Final Parent is validated as part of a complete final setup:

```text
Final Uma
├── Final Parent produced or selected by campaign
└── Best allowed second parent
```

The second parent can come from:

- owned veterans
- campaign-produced veterans
- friend/rental veterans when `allow_rental` is enabled

Result status is presented as:

- `READY`: required sparks satisfied and affinity `>= 150` without rental dependency
- `READY WITH RENTAL`: required sparks satisfied and affinity `>= 150` only with an allowed rental setup
- `IN PROGRESS`: campaign conditions are not yet satisfied

When rentals are disabled, an owned-only setup below 150 must not complete the campaign even if a rental combination would have passed.

## Legacy Resolver

The campaign stores intent and role requirements, not only permanently frozen veteran instance IDs.

Before each run, the resolver considers:

1. Required campaign-produced lineage instances.
2. Better owned veteran instances that still preserve campaign objectives.
3. Friend/rental veterans when allowed.
4. Bootstrap/fallback veterans during early loop formation.

A legacy slot may be:

- `LOCKED`: must use a specific campaign lineage instance
- `FLEXIBLE`: may be replaced when another current veteran improves or preserves the objective

Resolver scoring considers:

- lineage continuity
- projected affinity
- required target contribution
- preferred target contribution
- shared G1 overlap

### Pre-run review

Default behavior:

```text
Planned veteran: A
Recommended veteran: B
Reason:
- higher projected affinity
- better required spark contribution
- more shared G1 wins
```

The user approves the recommendation.

### Auto-use mode

When `auto_use_best_veteran` is enabled, the resolver may select the deterministic best candidate automatically.

Every automatic replacement must create an audit event containing the old choice, new choice, and reasons.

## Race Agenda

The campaign planner generates a shared G1 agenda for the selected four-Uma loop.

Race categories:

- `CORE`: expected to be won by each relevant loop member because it materially supports shared race compatibility
- `OPTIONAL`: useful additional overlap when the run can afford it
- `DEFERABLE`: may be skipped in one year when it would harm training and targeted later where appropriate

The planner should prefer a realistic shared calendar over blindly scheduling every possible G1.

The agenda feeds campaign-specific preset generation through mandatory and optional race overrides.

Existing race compatibility and shared G1 helpers should be reused where possible.

## Preset Policy

Deck selection remains manual.

Career preset generation is assisted and automatic.

For each campaign member, the planner can generate a campaign-specific base preset that includes:

- scenario
- running style
- parent-run behavior
- target stat emphasis for blue-spark goals
- shared G1 agenda
- appropriate mandatory and optional race lists

Before each run, step-specific overrides are recalculated from current lineage and campaign progress.

The campaign executor must not duplicate the career runner. It prepares one run and delegates gameplay execution to the existing runner.

## Architecture

Use a campaign-specific domain subsystem with workflow-friendly boundaries.

Recommended structure:

```text
career_bot/campaigns/
  models.py
  store.py
  runner.py
  planner.py
  scorer.py
  resolver.py
  executor.py
  lineage_planner.py
  run_setup.py
  legacy/
```

Exact file boundaries may adapt to the existing `career_bot/campaigns/` implementation, but responsibilities should remain isolated.

### Components

#### Campaign Planner

Produces and revises the campaign plan.

Responsibilities:

- Final Parent recommendations
- four-Uma loop recommendations
- virtual rotation planning
- race agenda generation
- preset policy generation

#### Spark Target Evaluator

Evaluates blue and pink targets.

Responsibilities:

- required target completion
- preferred target scoring
- candidate progress summaries
- dominated-candidate comparison support

#### Affinity Simulator

Uses existing master-data affinity logic and actual veteran lineage where available.

Responsibilities:

- current actual affinity
- projected rotation affinity
- final setup validation
- hard `>= 150` gate

#### Legacy Resolver

Resolves concrete current veteran instances for planned lineage roles.

#### Campaign Executor

Coordinates campaign states and one career run at a time.

It must not own game-turn logic.

#### Campaign Store

Reuse and evolve the existing SQLite-backed `CampaignStore`.

#### Web API

Expose campaign planner and executor operations to `/campaigns`.

#### Web UI

A separate top-level page for creation, review, progress, candidate history, and execution controls.

## B-to-C Migration Strategy

The chosen architecture is campaign-specific now, but execution contracts should be generic-friendly.

Generic-friendly concepts from the start:

- persisted workflow state
- current step
- step result
- pause/resume
- single-active-job lock
- audit events
- safe transition validation

Campaign-specific concepts remain campaign-specific:

- affinity scoring
- spark targets
- legacy resolution
- loop rotation
- race agenda
- veteran evaluation

A future generic workflow engine should be able to extract common executor/store contracts without moving campaign-domain scoring into generic infrastructure.

## Persistence

Reuse the existing database:

```text
uma_runtime/campaigns.sqlite3
```

Existing tables already provide a strong base:

```text
campaigns
campaign_events
campaign_candidates
```

### Campaign spec versus runtime context

`spec_json` stores user intent and durable configuration:

- Final Uma
- spark targets
- Final Parent target
- four loop members
- deck assignments
- rental policy
- auto-use policy
- resource strategy
- generated preset policy

`context_json` stores changing execution state:

- rotation index
- current planned step
- virtual/current lineage
- current best candidate
- concrete resolved legacy slots
- required target progress
- preferred target progress
- projected final setup
- pending pre-run or post-run review

### Existing schema evolution

Do not replace the current campaign store.

Extend the existing Pydantic campaign models and store context as needed.

Prefer additive schema evolution and versioned spec/context formats over creating a second campaign database.

## State Machine

The existing campaign state model should be evolved rather than discarded.

Conceptual lifecycle:

```text
DRAFT
  -> READY
  -> SELECTING_LINEAGE / PRE_RUN_REVIEW
  -> RUNNING_CAREER
  -> EVALUATING_RESULT
  -> POST_RUN_REVIEW or REPLAN
  -> next run
```

Terminal or holding states include:

- `NEEDS_USER_INPUT`
- `WAITING_FOR_TP`
- `PAUSED`
- `COMPLETED`
- `FAILED`
- `CANCELLED`

The exact enum may retain the existing names where they already map cleanly to these concepts.

Every state transition must be persisted before control returns to the caller.

## Single Active Campaign Rule

An account may have many saved campaigns but at most one actively executing campaign.

Other campaigns may remain:

- draft
- ready
- paused
- completed

The active lock should integrate with the existing Sweepy workflow lease/control-plane behavior where appropriate instead of introducing an unrelated competing lock.

## Candidate Evaluation and Keep/Reject Policy

Use separate scoring models for different decisions.

### Loop recommendation score

Factors:

- mutual compatibility
- predicted stable affinity
- shared G1 potential
- running-style alignment
- distance overlap
- Final Uma compatibility

### Final Parent candidate score

Factors:

- required spark progress
- preferred spark progress
- best achievable final affinity
- existing veteran quality
- remaining effort estimate

### Per-run resolver score

Factors:

- lineage continuity
- projected affinity
- required contribution
- preferred contribution
- shared G1 overlap

### Auto-reject

A completed veteran can be rejected from campaign progression when it does not improve:

- required target progress
- preferred target score
- affinity potential
- lineage continuity

The veteran is not deleted.

### Post-run review

Required for meaningful trade-offs, for example:

```text
Current best:
Stamina 9
Long 4

New candidate:
Stamina 8
Long 6
```

The UI must show the trade-off and let the user choose.

### Auto target-ready

When all required targets pass and final setup affinity is at least 150, the candidate can be selected and the campaign stopped automatically.

## Recovery and Resume

### Application restart with no active career

Reload the persisted campaign and resume from the last safe persisted boundary.

### Application restart with an active career

Compare the current career setup against the campaign's expected current run.

If it matches:

- resume the current run context

If it does not match:

- pause the campaign
- report that the current career does not match the planned campaign step

Do not automatically delete or restart an unrelated active career.

### Flexible veteran unavailable

Re-resolve the slot from current inventory.

### Locked veteran unavailable

Move to user review and explain that the required campaign lineage instance cannot be found.

### Rental unavailable

If rentals are allowed but the planned rental cannot be resolved:

1. Try another valid rental or owned fallback.
2. Recalculate the setup.
3. Pause or request review when no valid fallback preserves the campaign objective.

Do not silently start a materially worse lineage setup.

## Web UI

Top-level route:

```text
/campaigns
```

Primary views:

### Campaign List

Shows saved campaigns and status:

- active
- paused
- draft
- ready
- completed

Only one campaign per account may show active execution.

### Create Campaign

Wizard or staged form:

1. Select Final Uma.
2. Add required/preferred blue or pink spark targets.
3. Review three Final Parent recommendations.
4. Select one Final Parent target.
5. Review assisted four-Uma loop recommendations.
6. Pin or replace loop members.
7. Assign decks.
8. Configure rental and auto-use settings.
9. Review generated campaign plan.
10. Save.

### Active Campaign Dashboard

Shows:

- Final Uma
- target Final Parent
- required progress
- preferred progress
- current loop rotation
- current lineage
- next trainee
- next resolved parents
- projected affinity
- shared G1 agenda
- run count
- current state
- recent campaign events
- best candidates

### Pre-run Review

Shows:

- planned versus resolved veteran choices
- reasons for replacements
- projected affinity
- spark contributions
- rental dependency
- selected deck
- generated preset and race agenda

Actions:

- approve run
- choose another candidate when permitted
- pause campaign

### Post-run Review

Shows the old best candidate versus the new result when the trade-off is ambiguous.

### Completion View

Shows:

- required targets satisfied
- best final setup
- final affinity
- rental dependency if any
- selected Final Parent veteran

Actions:

- finish campaign
- continue for preferred targets

## API Surface

Exact endpoint names may adapt to existing patterns, but the Web UI needs operations equivalent to:

```text
GET    /api/campaigns
POST   /api/campaigns/recommend-final-parents
POST   /api/campaigns/recommend-loop
POST   /api/campaigns
GET    /api/campaigns/{id}
POST   /api/campaigns/{id}/activate
POST   /api/campaigns/{id}/pause
POST   /api/campaigns/{id}/resume
POST   /api/campaigns/{id}/prepare-next-run
POST   /api/campaigns/{id}/approve-run
POST   /api/campaigns/{id}/select-candidate
POST   /api/campaigns/{id}/continue-preferred
POST   /api/campaigns/{id}/cancel
```

Where existing MCP/domain methods already implement equivalent behavior, Web endpoints should delegate to shared domain services rather than reimplement campaign logic in `main.py`.

## Error Handling

Rules:

- Validation failures return structured, user-readable reasons.
- Recommendation failure must distinguish no-owned-loop, no-valid-affinity-setup, and missing master data.
- A campaign run must never begin when required pre-run review is unresolved.
- A campaign must never complete on spark targets alone when final affinity is below 150.
- A campaign must never complete using rental dependency when rentals are disabled.
- A missing locked lineage instance must require user action.
- Repeated or replayed requests should respect existing idempotency/operation mechanisms where applicable.

## Testing Strategy

Core planner tests must run without logging into the game.

### Unit tests

- blue spark target evaluation
- pink spark target evaluation
- required versus preferred semantics
- total-star threshold examples such as `Stamina >= 9` and `Long >= 6`
- Final Parent candidate comparison
- existing veteran starting-point preference
- four-Uma loop scoring
- pinned-member loop recomputation
- virtual lineage transitions
- same-character grandparent zero-affinity handling
- shared G1 agenda generation
- Legacy Resolver locked/flexible behavior
- rental allowed/disabled behavior
- final affinity hard gate at exactly 150
- dominated candidate rejection
- ambiguous candidate review
- single-active-campaign rule

### Simulation tests

Run 10-20 virtual rotations over deterministic fixtures and verify:

- parent/grandparent transitions
- old lineage eviction
- loop member recurrence
- campaign progress monotonicity where expected
- final setup simulation consistency

### Integration tests

- create -> persist -> reload produces the same campaign
- prepare run -> approve -> career request generation
- completed career -> candidate evaluation -> replan
- restart with matching active career resumes safely
- restart with mismatched active career pauses safely
- target completion stops campaign
- continue-for-preferred resumes optimization
- event history records automatic veteran substitutions

## Security and Privacy

Campaign persistence must not store:

- credentials
- auth tokens
- raw session material
- raw private API payloads
- real account identifiers in tracked examples or tests

Stored runtime records should use the existing sanitization mechanisms.

Documentation and fixtures use neutral account placeholders such as `acct01`.

## Open Implementation Notes

These are implementation choices, not unresolved product requirements:

- The existing `FactorTarget` model already supports required flags, minimum stars, lineage scope, and sum aggregation. It should be evolved carefully rather than replaced blindly.
- The existing `CampaignStore`, `CampaignRunner`, lineage planner, legacy scanner, race planner, and veteran inventory code should be audited for reusable behavior before adding parallel modules.
- Existing campaign states may map to pre-run/post-run review through `NEEDS_USER_INPUT` plus structured `next_action`/context instead of adding many new enum values.
- The final implementation should keep Web UI orchestration thin and domain logic testable outside FastAPI.

## Acceptance Criteria

The feature is complete when a user can:

1. Open `/campaigns`.
2. Select a Final Uma.
3. Configure multiple required/preferred blue or pink spark targets.
4. Receive three ranked Final Parent recommendations that may include existing owned veterans.
5. Select a Final Parent target.
6. Receive assisted four-Uma loop recommendations based primarily on owned characters.
7. Pin/replace loop members and manually assign decks.
8. Save the campaign in the existing SQLite campaign store.
9. Activate one campaign for the account.
10. Review or auto-accept the best currently available veteran setup before each run.
11. Execute career runs through the existing career runner.
12. Persistently evaluate results and rotate lineage across restarts.
13. Stop automatically only when all required spark constraints are met and final setup affinity is `>= 150`.
14. Distinguish `READY`, `READY WITH RENTAL`, and `IN PROGRESS` outcomes.
15. Continue optimizing preferred targets after required completion when requested.
