---
name: sweepy-parent-builder
description: Use when a Discord user asks Hermes to launch, inspect, stop, or operate Sweepy accounts, especially to build goal-driven Umamusume parents such as Medium/Turf lineage candidates. Use the Sweepy MCP tools with explicit account routing, durable operation IDs, resource budgets, workflow leases, and campaign progress reporting.
version: 1.3.1
author: Sweepy contributors
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [sweepy, umamusume, mcp, discord, campaign, parent-builder]
    related_skills: []
---

# Sweepy Parent Builder

## Overview

This skill operates the local multi-account Sweepy bot through its MCP server. Hermes translates the user's Discord request into a safe, durable campaign, while Sweepy handles process lifecycle, game API calls, Career turns, retries, candidate scoring, and persistent state.

Never drive Career turn-by-turn from Hermes. Use campaign-level tools and let Sweepy's CareerRunner handle gameplay.

## When to Use

Use this skill when the user asks to:

- launch, stop, restart, inspect, or read logs for a named Sweepy account;
- run Dailies on one account;
- start or monitor a normal Career;
- create a parent for a target such as Turf, Dirt, Sprint, Mile, Medium, or Long;
- continue, pause, resume, or cancel a parent campaign;
- compare or select generated parent candidates.

Do not use it for:

- arbitrary shell commands;
- raw game endpoint calls;
- reading auth caches, SID, Steam tickets, trace payloads, or device identifiers;
- deleting Careers or veterans;
- controlling an account that the user did not name or approve.

## Mandatory Safety Rules

1. Call `list_accounts` first.
2. Pass the explicit `account` to every account-specific tool.
3. Never silently default to the first account when multiple accounts exist.
4. Call `get_account_runtime` and `get_bot_state` before starting a workflow.
5. Never start Career, Dailies, and a parent campaign concurrently on the same account.
6. Respect confirmation boundaries. Process lifecycle and campaign creation/start require an explicit user-approved preview. Once a campaign budget is approved, `fully_automatic` and `ambiguity_only` may execute campaign child steps with `confirm=true` inside that budget; `per_generation` requires a preview for each run.
7. Reuse the same `operation_id` for a preview and its confirmed execution.
8. Never reuse one operation ID for different actions or arguments.
9. Prefer a stable Discord identifier:

```text
<discord-message-id>:<action>:<campaign-or-account>
```

Examples:

```text
128392001:create-campaign:alpha
128392001:start-campaign:campaign-uuid
128392001:prepare-run:campaign-uuid:1
128392001:start-career:campaign-uuid:1
```

10. A repeated tool result with `replayed=true` is successful retry protection, not an error.

## Account Lifecycle Procedure

### Inspect

```text
list_accounts
→ get_account_runtime(account)
→ get_bot_state(account) when API is reachable
```

### Launch

```text
launch_bot(account, confirm=false, operation_id=...)
→ explain the process change
→ launch_bot(account, confirm=true, same operation_id)
→ wait_until_ready(account, require_login=true)
```

If the runtime is externally managed, do not try to duplicate or kill it. Report that the user must stop the manually launched process themselves.

### Stop or Restart

Process lifecycle changes require confirmation:

```text
stop_bot(account, confirm=false, operation_id=...)
restart_bot(account, confirm=false, operation_id=...)
```

Use `force=true` only after graceful stop failed and the user explicitly approved force escalation.

Workflow-level `stop_career` and `stop_dailies` are safer operations, but still provide an operation ID for retry protection.

## Natural Language Goal Mapping

Map user wording to `ParentCampaignSpec`:

| User wording | Structured value |
|---|---|
| Turf / grass | `surface_targets: ["turf"]` |
| Dirt | `surface_targets: ["dirt"]` |
| Short / sprint | `distance_targets: ["sprint"]` |
| Mile | `distance_targets: ["mile"]` |
| Medium | `distance_targets: ["medium"]` |
| Long | `distance_targets: ["long"]` |
| no carat / jangan pakai carat | `tp_mode: "wait"`, `maximum_carats: 0` |
| no clock / jangan pakai clock | `use_clocks: false`, `maximum_clocks: 0` |
| ask only when unclear | `approval_mode: "ambiguity_only"` |
| approve every generation | `approval_mode: "per_generation"` |
| fully automatic | `approval_mode: "fully_automatic"` |

A campaign requires hard limits. When the user does not give them, propose conservative defaults in the confirmation summary rather than starting silently:

```yaml
maximum_runs: 10
maximum_carats: 0
maximum_clocks: 0
maximum_runtime_hours: 12
tp_mode: wait
use_clocks: false
approval_mode: ambiguity_only
stop_when_target_reached: true
```

Never convert `tp_mode: wait` into carat spending.

## Deterministic Cached Inventory Queries

For questions such as “Do I have a Power 9★ veteran?” or “Show this veteran's sparks,” use the decoded inventory tools directly:

```text
find_cached_veterans(
  account,
  blue_factor="Power",
  minimum_lineage_stars=9,
  scope="direct_lineage"
)

get_cached_veteran_details(account, trained_chara_id)
```

Mandatory interpretation rules:

1. Never infer factor names or stars from raw factor IDs. Only trust decoded MCP fields.
2. Final stats are not blue factors. A final Power stat of 1200 does not imply a Power spark.
3. A `Power 9★` parent means decoded Power blue stars total 9 across `self + direct parent 1 + direct parent 2`.
4. White race, white skill, scenario, green, and pink sparks must never be counted as blue-factor stars.
5. Always mention the cached snapshot `refreshed_at` when answering inventory questions.
6. Do not use terminal, source search, or master.mdb for normal inventory questions. If decoded MCP tools cannot answer, report the missing capability instead of improvising a parser in Discord.
7. Use `list_cached_veterans` only for browsing. Use `find_cached_veterans` for factor filters and `get_cached_veteran_details` for evidence and breakdowns.

A correct answer should cite decoded evidence, for example:

```text
Synthetic Veteran: Power 9★
- self: Power 3★
- parent 1: Power 3★
- parent 2: Power 3★
- final Power stat: 700 (separate from factors)
```

## Deterministic Friend Support Selection

When the user explicitly says to use a named friend support, prefer the atomic tool instead of asking them to open Sweepy UI or doing a two-step candidate roundtrip:

```text
ensure_friend_support(
  account,
  name="Super Creek",
  support_type="Stamina",
  limit_break=4,
  confirm=true,
  operation_id=...
)
```

Use `find_friend_supports` only when the user asks to inspect/search or when multiple support-card variants need to be shown before selection. Use `select_friend_support` only after the user has chosen one opaque candidate from that list.

`LB4` means exact `limit_break_count=4`, not minimum LB4.

Selection rules:

1. Never construct, request, display, or infer a friend `viewer_id`. Use the opaque `candidate_id` returned by MCP.
2. Reject candidates that conflict with the selected deck or use the same support character as the trainee.
3. If several owners provide the same support-card ID, use `recommended_candidate_id`; owner ranking is deterministic.
4. If multiple support-card variants match the same character name, ask the user to choose a support type or exact card. Do not silently choose between Stamina, Wit, Speed, or other variants.
5. If the user's message explicitly says to use/select the support, that message is approval to call `ensure_friend_support(confirm=true)` immediately with a unique operation ID. Do not ask for another “gas” or confirmation when one deterministic card variant exists.
6. If `ensure_friend_support` returns `requires_user_choice`, show the decoded variants and ask which exact card/type to use. If the user only asks to search or inspect, call `find_friend_supports` and do not mutate selection.
7. After selection, call `get_bot_state(account)` and verify the selected friend support before continuing the campaign.
8. Never use terminal, source search, raw API calls, or `/api/selection` directly for this task.

Example:

```text
ensure_friend_support(
  account="alpha",
  name="Super Creek",
  support_type="Stamina",
  limit_break=4,
  confirm=true,
  operation_id=...
)
→ get_bot_state(account="alpha")
```

## Headless Trainee and Deck Selection

Do not ask the user to open Sweepy Web UI to select a trainee or support deck for a new campaign.

Map explicit trainee requests into the campaign spec:

- "pakai Oguri" / "use Oguri" -> `trainee.mode="named"`, `trainee.name="Oguri Cap"`
- an explicit numeric card ID -> `trainee.mode="named"`, `trainee.card_id=<id>`

Map unrestricted trainee requests into:

- "parent bebas" / "character bebas" / "yang penting affinity tinggi" -> `trainee.mode="auto"`, `trainee.objective="highest_affinity"`

For both named and automatic trainee modes, Sweepy rejects trainees that conflict with the selected friend support, rejects infeasible lineages, then chooses the highest-affinity feasible trainee + parent combination. Hermes must not guess the winning trainee itself.

Support deck mapping:

- explicit deck name -> `deck.mode="named"`, `deck.name=<name>`
- no deck named -> `deck.mode="auto"`

`deck.mode="auto"` first excludes decks that conflict with the selected friend support, then deterministically prefers decks matching `goal.preferred_stats`, followed by total limit breaks. It does not alter or create the Career preset.

Friend support remains separate. If the user names one, use `ensure_friend_support`. Never expose or construct a viewer ID.

Examples:

```text
User: "bray bikinin parent stamina 9*, pake Oguri"

Campaign mapping:
- target factor: Stamina 9★ direct lineage
- trainee={"mode":"named","name":"Oguri Cap","objective":"highest_affinity"}
- deck={"mode":"auto"}
- existing budget/confirmation rules still apply
```

```text
User: "bray bikinin parent stamina 9*, parent bebas yang penting affinitynya tinggi"

Campaign mapping:
- target factor: Stamina 9★ direct lineage
- trainee={"mode":"auto","objective":"highest_affinity"}
- deck={"mode":"auto"}
- Hermes does not choose a character name; Sweepy evaluates owned trainees and returns the resolved choice.
```

## Parent Campaign Workflow

### 1. Preflight

```text
list_accounts
get_cached_account_snapshot(account)
get_account_runtime(account)
```

Always mention the snapshot `refreshed_at`. Cached cards, decks, and veterans are offline inventory, not proof that TP/session/live runner state is current.

Launch the bot when needed, then:

```text
wait_until_ready(account, require_login=true)
get_bot_state(account)
list_career_presets(account)
```

Before creating a new legacy-style goal, use the offline tools when useful:

```text
scan_cached_legacy_loops(account, minimum_affinity=151)
preview_shared_g1_agenda(terrain="Turf", distances=["Mile", "Medium", "Long"])
get_legacy_spark_rules()
```

These tools never call the game API. Prefer a pool whose worst rotation remains double-circle, then shared G1 coverage, style overlap, and distance overlap. Never claim the loop raises 3-star spark roll odds; it raises affinity and therefore the proc chance of sparks that already exist.

Before `prepare_parent_campaign_run`, the live session must have a selected friend support. Trainee and support deck may be absent when the campaign spec uses `named` or `auto` selection policies. Parents never need manual selection because the lineage planner chooses them.

If friend support is missing and the user named a desired support, call `ensure_friend_support` before reporting a blocker. Ask the user for input only when no valid support can be found or the support-card variant is ambiguous.

### Factor target semantics

Campaign factor targets are explicit and deterministic:

- `scope="candidate", aggregation="max", minimum_stars=3` means the resulting veteran itself must print that 3★ factor.
- `scope="lineage", aggregation="max"` means at least one selected lineage node must meet the star threshold.
- `scope="lineage", aggregation="sum", lineage_depth="direct", minimum_stars=9` means decoded stars must total 9 across exactly `self + direct parent 1 + direct parent 2`.
- `lineage_depth="full"` includes self, both direct parents, and all four grandparents.
- Final stats never count toward factor totals.
- For a required direct-lineage total, the lineage planner rejects parent pairs that cannot possibly reach the target even if the new candidate rolls 3★. Therefore Power 9★ requires both selected direct parents to have self Power 3★; a 3★+2★ pair is infeasible because the maximum result is 8★.

For a requested `Power 9★` parent, send:

```json
{
  "name": "power",
  "minimum_stars": 9,
  "scope": "lineage",
  "aggregation": "sum",
  "lineage_depth": "direct",
  "required": true
}
```

If the user says aptitude is unrestricted, use empty arrays:

```json
{
  "surface_targets": [],
  "distance_targets": []
}
```

Do not invent Turf/Mile defaults merely because the schema used to require non-empty aptitude targets. Race-agenda preferences are separate from hard aptitude acceptance targets.

### 2. Preview the Campaign

Call `preview_parent_campaign(spec)` and summarize:

- account;
- target surface and distance;
- candidate-vs-lineage factor requirements;
- preset;
- maximum runs;
- carat and clock limits;
- runtime limit;
- approval mode.

Then call:

```text
create_parent_campaign(spec, confirm=false, operation_id=...)
```

After approval, repeat with `confirm=true` and the same operation ID.

### 3. Start the Campaign

```text
start_parent_campaign(campaign_id, confirm=false, operation_id=...)
→ user approval
→ start_parent_campaign(campaign_id, confirm=true, same operation_id)
```

Inspect the returned `state` and `next_action`.

### 4. Follow `next_action`

#### `launch_bot`

Launch the campaign account, wait until ready, then call:

```text
advance_parent_campaign(campaign_id, operation_id=unique-step-id)
```

#### `wait_for_login`

Do not ask for credentials in Discord. Tell the user to complete login through Sweepy's web UI. Poll readiness at a reasonable interval, then call `advance_parent_campaign`.

#### `select_lineage`

```text
prepare_parent_campaign_run(
  campaign_id,
  pool="both",
  confirm=true,
  operation_id=unique-generation-id
)
```

The campaign's initial approval authorizes lineage preparation within its hard budget. Summarize the selected pair, compatibility, target sparks, and shared-race score in the next progress update. Sweepy rejects two-rental setups automatically. It supports two owned parents or one owned plus one rental. A direct parent must never be the same base character as the trainee; alternate costumes count as the same character. The trainee character may still appear deeper in the grandparent lineage when affinity remains acceptable.

For `approval_mode: per_generation`, first call with `confirm=false`, show the lineage preview to the user, then repeat with `confirm=true` using the same operation ID.

#### `start_career`

```text
run_parent_campaign_career(
  campaign_id,
  confirm=true,
  operation_id=unique-run-id
)
```

For `fully_automatic` and `ambiguity_only`, the user-approved campaign budget authorizes each run up to the hard limits; do not ask again for every generation. For `per_generation`, call with `confirm=false`, explain that this consumes one run and TP according to policy, then wait for approval before repeating with `confirm=true` and the same operation ID.

If the tool returns `recovery_action="prepare_parent_campaign_run"`, do not retry Career. The stored lineage has already been invalidated without consuming run, TP, clocks, or carats. Follow the campaign's new `next_action=select_lineage` and prepare again with a new operation ID. If prepare reports no feasible pair and the inheritance response lacks target/base-character evidence, restart the Sweepy bot process to load the current recommender before retrying preparation.

#### `monitor_career`

Poll `get_bot_state(account)` or `get_parent_campaign_summary(campaign_id)` at a moderate interval. Do not call turn actions. When Career is no longer running:

```text
collect_parent_campaign_result(
  campaign_id,
  operation_id=unique-collection-id
)
```

#### `evaluate_result`

Use `collect_parent_campaign_result`. Sweepy finds the newly created veteran, evaluates rank, required candidate/lineage factors, aptitudes, preferred stats, compatibility, and race history, then updates campaign state.

#### `select_candidate`

Call:

```text
list_parent_candidates(campaign_id)
```

Show the best candidates with:

- score;
- accepted status;
- matched and missing targets;
- reasons;
- weaknesses;
- baseline delta.

Ask the user to choose, then use `select_parent_candidate(..., confirm=true)`.

#### `wait_for_tp`

Report current TP policy and budget. Do not refill with carats when `maximum_carats` is zero. Resume only when policy permits.

### 5. Repeat or Finish

Campaign states:

- `SELECTING_LINEAGE`: prepare the next generation/run;
- `RUNNING_CAREER`: monitor only;
- `EVALUATING_RESULT`: collect the result;
- `NEEDS_USER_INPUT`: present candidate choices;
- `WAITING_FOR_TP`: wait without violating resource policy;
- `COMPLETED`: report the selected candidate and why it passed;
- `FAILED`: report budget or execution failure;
- `PAUSED`: do nothing until resumed;
- `CANCELLED`: stop campaign updates.

Use `get_parent_campaign_summary` for Discord updates, `get_parent_campaign` for full state/events/candidates, and `get_recent_operations(account)` when Discord retries or tool execution status is unclear.

## Discord Update Policy

Send an update only for meaningful events:

- bot launched, stopped, restarted, or crashed;
- login required;
- campaign created or started;
- lineage selected;
- Career run started or finished;
- candidate accepted, rejected, or ambiguous;
- TP waiting;
- budget nearly exhausted or exhausted;
- user input required;
- campaign completed, failed, paused, or cancelled.

Do not post every Career turn or every polling cycle.

A concise progress update should include:

```text
Account: alpha
Campaign: <id>
State: RUNNING_CAREER
Run: 3 / 10
Carats: 0 / 0
Clocks: 0 / 0
Best candidate: 84.5
Next: monitor Career
```

## Recovery Rules

1. If Hermes restarts, call `get_parent_campaign` and continue from `next_action`.
2. If MCP reports an operation in progress, do not execute it again with a new ID. Inspect `get_recent_operations` first.
3. If a confirmed call is retried, reuse its original operation ID.
4. If the bot process died, inspect logs, restart only after confirmation, wait for readiness, then call `advance_parent_campaign`.
5. If campaign lease conflicts with Career or Dailies, do not override it. Report the active lease and ask whether the existing workflow should be stopped.
6. If no new veteran appears after Career completion, report the collection error and inspect account refresh/state before retrying with a new collection operation ID.

## Common Pitfalls

1. **Omitting account.** Always use the explicit account named by the user.
2. **Creating a new operation ID on retry.** This defeats idempotency and can double-spend.
3. **Using one operation ID for multiple actions.** Sweepy rejects it as an argument/action conflict.
4. **Starting Career directly instead of through campaign tools.** This bypasses campaign usage and result tracking.
5. **Selecting two rental parents.** The game/Career payload supports at most one rental parent.
6. **Selecting the trainee or an alternate costume as a direct parent.** Same base character gives zero direct compatibility and is hard-rejected by Sweepy. It is only legal deeper in the grandparent lineage.
7. **Calling collection while Career is running.** Wait until the runner is finished.
8. **Treating an ambiguous candidate as automatic acceptance.** Present the comparison to the user unless approval mode is fully automatic.
9. **Polling too aggressively.** Use moderate intervals and only notify on state changes.
10. **Requesting credentials in Discord.** Login is completed in Sweepy's local web UI.

## Verification Checklist

- [ ] `list_accounts` was called and the account is explicit.
- [ ] Runtime and bot state were inspected.
- [ ] No conflicting workflow lease exists.
- [ ] Campaign spec has hard run, carat, clock, and runtime limits.
- [ ] User approved the preview before any process/resource mutation.
- [ ] Preview and confirmation reused the same operation ID.
- [ ] Parent lineage was prepared before starting Career.
- [ ] Career was started with `run_parent_campaign_career`, not raw `run_career`.
- [ ] Result collection occurred only after Career stopped.
- [ ] Discord updates are event-driven rather than turn-by-turn.
- [ ] Terminal campaign state and selected candidate were reported clearly.
