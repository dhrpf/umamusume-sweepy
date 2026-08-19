# Independent Training Dashboard Design

**Date:** 2026-07-26
**Status:** Approved design, implemented

## Goal

Add a dedicated dashboard that lets the account already bound to the current Sweepy instance queue and run Uma Musume Global's Independent Training mode without keeping the game open for each approximately 50-minute run.

The dashboard must keep three concepts separate:

1. **Independent Setup** — what the game server uses to run one career.
2. **Queue Policy** — how many runs Sweepy should execute and what to do when TP is insufficient.
3. **Runtime State** — what is currently queued, running, being collected, completed, or blocked.

A Career Preset is not required to create or run an Independent Training job.

## Scope

### MVP includes

- A separate `/independent-training` page.
- Read-only identity of the account bound to the current dashboard instance.
- An Independent Setup form for trainee, two parents, support deck, friend support, scenario, running style, training policy, priority skills, and race agenda.
- A Queue Policy form for repeat count and insufficient-TP behavior.
- Persistent queued-run snapshots.
- One active Independent Training execution per dashboard instance.
- Server-side start, completion detection, collection, skill/factor finalization, an optional target-driven one-time factor reroll, and automatic start of the next queued run.
- Recovery after a Sweepy restart by reconciling persisted state with `idle_single_mode/status`.
- Clear blocking when another career-related workflow owns the bound account.
- Recent completed-run summaries and actionable failure state.

### Deferred

- Importing compatible fields from Career Presets.
- Editing an already queued snapshot.
- Drag-and-drop queue reordering.
- Scheduling by wall-clock time.
- Multiple named Independent Setups.
- Automatic comparison or ranking of completed veterans.
- Starting jobs for an account other than the one bound to the instance.

## Capture-grounded game lifecycle

The supplied capture establishes this protocol:

1. `idle_single_mode/pre_start`
2. `idle_single_mode/start`
3. Server returns `progress_info.start_time` and `progress_info.end_time`; the observed duration is exactly 3,000 seconds.
4. At or after the server end time, reconcile through `idle_single_mode/status` and collect through `idle_single_mode/end`.
5. `end` returns the completed `chara_info` and progress log, but the career is not yet a registered veteran.
6. Complete post-processing through the scenario-specific `gain_skills`, `factor_select`, optional `factor_lottery`, and `finish` endpoints. `factor_lottery` is called only when the queued snapshot enables reroll and the initial factor result misses its configured targets.
7. Refresh account data so the new veteran and current TP are visible before starting the next run.

Countdowns in the UI are derived from the server-provided end time. They are display estimates, never the source of truth.

## Ownership and concurrency

The dashboard does not offer an account selector. It resolves the account from the existing active dashboard session and displays the account name read-only.

The Independent Training executor acquires the existing durable per-account workflow lease using workflow type `independent_training`. Normal Career and Campaign execution cannot overlap with Independent Training and return HTTP 409 on conflict. Dailies may run while the server processes an Independent Training run because they do not mutate career state. Both workers share the bound `UmaClient`, whose complete `call()` transaction is serialized so SID regeneration and cached session state cannot race across threads.

The service may have many queued snapshots but at most one active server run. Queue approval occurs once when the user starts the queue; subsequent snapshots start automatically without per-run approval.

## Independent Setup

Each queued run stores a complete immutable snapshot with these fields:

- `card_id`
- `support_card_ids` (five owned support cards)
- `friend_viewer_id`
- `friend_card_id`
- `parent_id_1`
- `parent_id_2`
- `rental_viewer_id`
- `rental_trained_chara_id`
- `scenario_id`
- `deck_id`
- `running_style`
- `difficulty_id`, `difficulty`, and `is_boost`
- `boost_story_event_id`
- `training_policy_ground_type`
- `training_policy_param_rate_set_id`, restricted to `1` (Balanced), `2` (Stamina), or `3` (Sprint)
- ordered `priority_skill_array`, chosen by skill name and sent only to the Independent Training server policy
- ordered `final_skill_ids`, chosen separately by skill name for optional final purchase
- ordered `race_array` entries containing `year` and `program_id`, derived from the Dashboard visual race planner rather than entered as raw IDs
- `factor_reroll`, containing:
  - `enabled`, default `false`
  - ordered `targets`, each containing normalized spark `category`, `name`, and `minimum_stars`

When factor reroll is enabled, at least one valid target is required. Targets describe only the newly trained veteran's own generated factors, not inherited parent or full-lineage totals. For example, an Aptitude target of `Dirt >= 2` matches only when the candidate factor result contains a Dirt spark worth at least two stars.

Selection validation reuses the existing Career start constraints where applicable: distinct support cards, a valid friend support from the current private Dashboard session, valid parent pairing, and no trainee/parent identity conflict. Independent-only fields are additionally range-checked and unknown keys are rejected. Friend viewer IDs remain in page memory and the protected queue snapshot only; the browser never persists them.

The normal Independent Training TP cost is runtime state, not part of the immutable setup. Immediately before each start, Sweepy reads the base cost from the latest `load/index` response at `common_define.single_mode_trainer_point_use_value`, reads authoritative time from the latest response `data_headers.servertime`, and queries configured `master.mdb.campaign_data` for an active row with `target_type = 1` and `effect_type_1 = 4`. An active row's `effect_value_1` replaces the base cost; otherwise the base cost is used. A missing base cost, missing/inaccessible campaign table, invalid campaign value, or missing authoritative server time blocks the start before TP recovery or the mutating request. The resolved cost is recalculated for every queued run and passed as `use_tp`, so a queue remains correct across campaign start/end boundaries. The dashboard displays the latest detected value read-only; it does not offer a manual TP-cost field.

Changing the form after runs are queued affects only future queue additions. Existing snapshots remain unchanged.

## Queue Policy

The user adds between 1 and 100 copies of the current setup snapshot in one action.

`tp_mode` has three MVP values:

- `wait`: keep the queue active and wait for natural TP recovery.
- `carat`: use the existing TP recovery flow when TP is insufficient; stop in `NEEDS_ATTENTION` if recovery is rejected or unaffordable.
- `stop`: do not spend currency and stop before starting the next run.

The queue also stores `stop_after_current`. Pressing **Stop queue** prevents another run from starting but does not force-delete the active server run. The active run remains tracked and is collected normally; wasting a 50-minute run would be an unusually expensive implementation of a stop button.

Queued snapshots can be removed only before they start.

## State model

Run states:

- `QUEUED`
- `STARTING`
- `RUNNING`
- `COLLECTING`
- `FINALIZING`
- `COMPLETED`
- `FAILED`
- `NEEDS_ATTENTION`
- `CANCELLED`

Queue-level state is derived from its runs and executor state rather than maintained as a second conflicting state machine.

Normal flow:

`QUEUED → STARTING → RUNNING → COLLECTING → FINALIZING → COMPLETED`

Failures before the server accepts `start` may transition to `FAILED` and allow a retry. Once the server accepts a run, ambiguous errors transition to `NEEDS_ATTENTION`; Sweepy must reconcile before issuing another start so duplicate server careers cannot be created.

## Persistence and recovery

Independent Training data lives in a dedicated SQLite database under `UMA_RUNTIME_DIR`, using WAL mode and atomic transactions. It stores:

- queue/run identity and ordering;
- the minimal immutable setup snapshot required to resume execution;
- state and optimistic version;
- server start/end timestamps;
- safe result summary;
- error and next-action text;
- append-only state events.

Raw responses, the bound account's authentication viewer ID, SID, device data, and Steam credentials are never persisted in this database. Friend/rental viewer IDs required by the game are stored only inside the protected runtime snapshot and are omitted from logs, event payloads, and result summaries.

On process recovery:

1. Load the non-terminal run for the bound account.
2. Acquire or recover the workflow lease.
3. Call `idle_single_mode/status`.
4. Match the server run to the persisted snapshot using non-secret career identity fields such as card, parents, deck/support composition, scenario, and server start time.
5. Resume `RUNNING`, collect a completed run, or enter `NEEDS_ATTENTION` on mismatch.
6. Never issue `idle_single_mode/start` while server state is ambiguous.

## Finalization policy

Independent Training's ordered `priority_skill_array` guides only the server-run 50-minute training. It is not a purchase list. The separate ordered `final_skill_ids` controls optional final skill purchase through the existing safe skill-buying rules, without loading a Career Preset. An empty final list skips explicit purchase priorities, and invalid or overspending skill payloads are not blindly retried.

Factor finalization follows the captured scenario-specific sequence:

1. `factor_select` creates the initial candidate, normally `lottery_id = 1`.
2. Normalize that candidate's own `factor_info_array` through the existing master-data factor semantics and evaluate every configured target.
3. If reroll is disabled or the initial candidate satisfies all targets, skip `factor_lottery` and finish with the initial candidate.
4. If reroll is enabled and any target is missed, call `factor_lottery` at most once for that run. The captured request uses the server-provided lottery count and consumes 30 TP. The UI discloses this possible extra cost.
5. The lottery response retains both the original and rerolled candidates. Prefer a candidate satisfying all targets. If neither satisfies all targets, compare candidates lexicographically by number of satisfied targets and then by the sum of each target's stars capped at its configured minimum; ties keep the original candidate.
6. Call `finish` with the chosen candidate's `factor_lottery_id`.

The store commits `factor_lottery_attempted = true` immediately before the mutating lottery call, then persists the returned candidate summaries and selected lottery ID as further finalization progress. Recovery must never issue a second `factor_lottery` call for the same run. If the process stops after committing the attempt marker but before proving a successful response, the run enters `NEEDS_ATTENTION`; it does not gamble another 30 TP on uncertainty. A known pre-call shortage of TP or exhausted `lottery_remain_num` skips the optional reroll, keeps the initial candidate, and records the reason. An ambiguous lottery response also transitions to `NEEDS_ATTENTION` for reconciliation instead of blindly retrying and risking a second charge.

The registered veteran ID and summary are read from the final response or refreshed account data. Any other failure after `idle_single_mode/end` keeps the run in `NEEDS_ATTENTION`; it does not start the next queued run.

## Backend boundaries

Create a focused `career_bot/independent_training/` package:

- `models.py`: validated setup, queue policy, and state types.
- `store.py`: SQLite persistence, atomic transitions, and event history.
- `service.py`: queue commands, lease ownership, reconciliation, and safe orchestration.
- `runner.py`: the single background executor and captured endpoint lifecycle.

`uma_api/client.py` receives small typed wrapper methods for the captured endpoints. All calls continue through `UmaClient.call()` so msgpack, encryption, SID, headers, recovery, and API delay rules remain centralized.

`main.py` only owns Pydantic web request models, dependency wiring, account/session resolution, and route-to-service error mapping. FastAPI request handlers never wait for the 50-minute job.

## Web API

All endpoints operate on the account bound to the current instance; no account input is accepted.

- `GET /api/independent-training/bootstrap` — current account identity, selectable dashboard data, saved race agendas from `pre_start`, last Independent settings, queue, active run, and recent results.
- `POST /api/independent-training/runs` — append `count` immutable setup snapshots.
- `POST /api/independent-training/start` — acquire the lease and start/resume the executor; returns HTTP 202.
- `GET /api/independent-training/status` — persisted executor state, queue, active run, countdown timestamps, and recent events. It does not call the game API on every browser poll.
- `POST /api/independent-training/stop-after-current` — prevent the next queued run from starting.
- `POST /api/independent-training/resume` — clear stop-after-current and resume queued work; returns HTTP 202.
- `DELETE /api/independent-training/runs/{run_id}` — cancel a run only while it is `QUEUED`.
- `POST /api/independent-training/reconcile` — explicitly retry safe reconciliation for `NEEDS_ATTENTION`; returns HTTP 202.

Validation failures return 422, missing active dashboard session returns 409, lease/state conflicts return 409, and unknown run IDs return 404.

## Dashboard UI

The page follows the existing Sweepy navigation and vanilla-JS conventions.

### Header

- Navigation back to Dashboard, Veterans, Dailies, and Campaigns.
- Current bound account displayed as read-only context.
- Executor badge: Idle, Running, Waiting for TP, Stopped, or Needs attention.

### Main sections

1. **Active run** — trainee, scenario, server start/end time, countdown, state, and next action.
2. **Independent Setup** — trainee, lineage, saved deck, selectable friend support from the Dashboard session, scenario/running style, training policy, named Independent priority skills, separately named final-purchase skills, the Dashboard's visual race planner and saved schedules, and a Factor reroll subsection. Technical friend, skill, and race IDs stay out of the user-facing controls. The subsection has an off-by-default toggle, target rows such as `Aptitude / Dirt / >= 2 stars`, and a warning that a reroll may consume 30 additional TP but can occur only once per run.
3. **Add runs** — repeat count and TP mode; previews how many snapshots will be appended.
4. **Queue** — ordered snapshots with compact setup summary and removal for queued items.
5. **Recent results** — completion time, veteran identity, grade/rank score when available, final stats, SP, and failure summary.

The UI polls the local status endpoint no faster than every five seconds. It never locally advances the state machine or assumes a run is complete merely because the countdown reached zero.

## Error handling

- A permanent validation or pre-start error marks only the affected run `FAILED` and stops automatic progression.
- A network/transient API failure follows existing `UmaClient.call()` recovery. If the result of a mutating operation is ambiguous, the run becomes `NEEDS_ATTENTION`.
- An active normal Career or Campaign blocks queue start without modifying either workflow; Dailies may overlap safely through serialized client calls.
- Insufficient TP follows the selected queue policy using the runtime-resolved per-run cost.
- Runtime/server mismatch never force-deletes the server career.
- Browser refresh and duplicate button presses are idempotent through state/version checks.

## Parent and deck selection UX

The setup form uses current dashboard data as the source of truth. Technical IDs remain part of the immutable queue snapshot, but the user selects identifiable records rather than typing database keys.

- Each parent option includes the character name, veteran ID, rank, and compact own-spark summary.
- Selecting a parent renders a preview with final stats, aptitudes, and the complete spark list from `tree.self.factors`, grouped as Blue, Red, Green, and White.
- The two parent pickers reject the same veteran and exclude the trainee's base character through the existing enqueue validation.
- Saved support decks are exposed by bootstrap with deck name and five card records.
- Selecting a saved deck sets `deck_id` and derives the five owned `support_card_ids`; those raw values are read-only implementation details rather than editable form fields.
- Each deck preview shows support-card name, type, rarity, and limit-break count.
- A previously saved deck or parent ID is restored only when it still exists in the current bootstrap response. Stale local storage never silently invents a setup.

## Testing

### Unit tests

- Setup validation and snapshot immutability.
- Store transitions, optimistic concurrency, event history, and queued-only cancellation.
- TP-cost resolution for base cost, active half-cost campaign, no campaign, missing master data, and invalid/stale inputs.
- TP policy decisions using the resolved runtime cost.
- Lease conflict and owner-safe release.
- Recovery matching and mismatch behavior.
- Client wrapper payloads and scenario-specific finalization order.
- Factor target normalization and all-target matching against the candidate's own factors.
- Disabled reroll, initial-target hit, one-time reroll, best-of-two selection, tie-to-original behavior, and insufficient-TP skip.
- Recovery after a persisted lottery attempt never calls `factor_lottery` again.

### Service tests

- One queued snapshot completes the full captured lifecycle.
- Multiple snapshots execute sequentially without per-run approval.
- Restart during `RUNNING`, `COLLECTING`, and `FINALIZING` resumes without duplicate start.
- Permanent and ambiguous failures stop subsequent runs.
- Stop-after-current collects the active run but leaves remaining snapshots queued.
- A missed Dirt two-star target performs exactly one lottery call, selects the best returned candidate, and continues to veteran registration even when neither candidate reaches the target.

### Web/API tests

- Bound-account behavior and absence of an account selector/parameter.
- HTTP 202 for asynchronous start/resume/reconcile.
- HTTP 409 for Career/Campaign conflicts while allowing Dailies to overlap Independent Training.
- Static page routes, named training-style options, detected TP-cost display, and essential UI controls.
- Frontend uses relative URLs and five-second-or-slower polling.

## Acceptance criteria

1. A logged-in dashboard user can configure and enqueue at least one Independent Training run without selecting an account or Career Preset.
2. Starting the queue returns immediately while execution continues in a background worker.
3. The dashboard shows server-grounded start/end timestamps and current lifecycle state.
4. A completed server run is finalized into a registered veteran before the next run starts.
5. Queue entries preserve the setup values present when they were added.
6. Another career-related workflow blocks Independent Training on the same bound account.
7. Restarting Sweepy during an accepted server run reconciles and resumes without starting a duplicate.
8. Stop-after-current never discards the active 50-minute run.
9. Sensitive capture/auth fields are absent from persisted events, fixtures, documentation, and logs.
10. Factor reroll is disabled by default; when enabled, an initial target miss can trigger no more than one `factor_lottery` call per run, including across process recovery.
11. The factor target is evaluated against the new veteran's own generated factors, and finalization selects the best available original or rerolled candidate before registration.
12. Focused backend/frontend tests and the existing affected regression suite pass.
13. Parent options are distinguishable by veteran ID and show the selected veteran's complete own-spark list.
14. A saved deck can be selected by name/composition and deterministically supplies exactly five owned support IDs to the queued snapshot.
