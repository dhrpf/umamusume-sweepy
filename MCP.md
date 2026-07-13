# Sweepy MCP Server

Sweepy exposes a local Model Context Protocol (MCP) server for AI agents that need to inspect bot state and operate approved workflows.

The MCP server is a multi-account control plane over Sweepy's existing FastAPI services. It can also supervise each account's `launcher.py` process without exposing arbitrary shell execution. It never reads auth cache files directly and redacts credential-shaped fields from all responses.

Durable control-plane state is stored in `uma_runtime/control-plane.sqlite3`. Override it with `SWEEPY_JOBS_DB`. Parent campaigns are stored separately in `uma_runtime/campaigns.sqlite3`; override that path with `SWEEPY_CAMPAIGNS_DB`. These databases contain only redacted operations, workflow leases, campaign specifications, compact events, lineage summaries, and evaluated candidates—never credentials or raw game payloads.

## Requirements

Install the project dependencies:

```bash
venv/bin/pip install -r requirements.txt
```

Start Sweepy normally and log in through the web UI first. For multi-account setups, the MCP adapter reads enabled account names and ports from `accounts.json`.

Example:

```json
[
  {"name": "acct01", "port": 1616, "enabled": true},
  {"name": "acct02", "port": 1617, "enabled": true}
]
```

Each account-specific MCP tool accepts an `account` argument. When more than one account is enabled, omitting `account` is rejected rather than silently targeting the first port.

`SWEEPY_ACCOUNTS_FILE` can point to a different registry file. `SWEEPY_BASE_URL` and `PORT` remain available as single-account fallbacks when no accounts registry exists.

For supervisor-managed launch, put `FRIDA_REMOTE` in each account's `extra_env`, or provide `SWEEPY_FRIDA_REMOTE` to the MCP process. Process metadata and combined launcher output are stored under `uma_runtime/<account>/` with restrictive file permissions.

## Local stdio transport

Most desktop/CLI MCP hosts should let the host launch the server itself. Replace `/absolute/path/to/umamusume-sweepy` with the absolute path to your checkout:

```json
{
  "mcpServers": {
    "sweepy": {
      "command": "/absolute/path/to/umamusume-sweepy/venv/bin/python",
      "args": [
        "/absolute/path/to/umamusume-sweepy/sweepy_mcp.py"
      ],
      "env": {
        "SWEEPY_ACCOUNTS_FILE": "/absolute/path/to/umamusume-sweepy/accounts.json"
      }
    }
  }
}
```

The server uses stdio by default. It does not print application logs to stdout because stdout carries MCP JSON-RPC messages.

## Streamable HTTP transport

For an agent that connects over HTTP:

```bash
SWEEPY_ACCOUNTS_FILE=/absolute/path/to/umamusume-sweepy/accounts.json \
venv/bin/python sweepy_mcp.py --transport streamable-http
```

The default MCP endpoint is:

```text
http://127.0.0.1:8765/mcp
```

Override the bind address and port with:

```bash
SWEEPY_MCP_HOST=127.0.0.1
SWEEPY_MCP_PORT=8765
```

Keep the MCP server bound to loopback unless authentication and transport security are added.

## Tools

| Tool | Behavior |
|---|---|
| `list_accounts` | Lists enabled account names and local web ports from `accounts.json` |
| `get_account_runtime` | Reads managed process, API reachability, login, Career, and Dailies activity |
| `get_bot_logs` | Reads a capped and redacted tail of the per-account supervisor log |
| `launch_bot` | Starts `launcher.py <account>` as a detached process group; requires `confirm=true` |
| `stop_bot` | Gracefully stops the managed launcher; requires `confirm=true` |
| `restart_bot` | Gracefully stops and relaunches the managed launcher; requires `confirm=true` |
| `wait_until_ready` | Polls API readiness and can optionally require a logged-in session |
| `get_recent_operations` | Lists durable mutation history for one account |
| `get_cached_account_snapshot` | Reads the last successful `load/index` projection without calling the game API |
| `list_cached_veterans` | Lists owned veterans from the offline snapshot |
| `get_legacy_spark_rules` | Returns compatibility thresholds and configurable spark rules |
| `scan_cached_legacy_loops` | Ranks four-character affinity-loop pools from cached lineage records |
| `preview_shared_g1_agenda` | Builds an offline G1 agenda with summer-camp and race-chain guards |
| `get_bot_state` | Compact account, Career runner, Dailies runner, workflow lease, and turn-delay state for one account |
| `list_career_presets` | Lists preset names and execution settings |
| `get_legend_races` | Lists currently available Daily Legend Race bosses |
| `run_dailies` | Starts selected Dailies; requires `confirm=true` |
| `stop_dailies` | Requests a safe stop |
| `run_career` | Starts or resumes Career using the current UI selection; requires `confirm=true` |
| `stop_career` | Stops Career and the multi-career loop |
| `refresh_account` | Reloads account state from the game |
| `refill_tp` | Refills TP; requires `confirm=true` |
| `set_turn_delay` | Changes API pacing; requires `confirm=true` |
| `preview_parent_campaign` | Validates a structured parent goal and hard resource budgets |
| `create_parent_campaign` | Creates a durable campaign in DRAFT state; requires confirmation |
| `list_parent_campaigns` | Lists campaigns for one account |
| `get_parent_campaign` | Reads campaign state, events, and ranked candidates |
| `start_parent_campaign` | Starts orchestration and acquires a campaign workflow lease |
| `advance_parent_campaign` | Reconciles campaign state after launch, login, or runner completion |
| `pause_parent_campaign` / `resume_parent_campaign` | Pauses or resumes durable orchestration |
| `cancel_parent_campaign` | Cancels a campaign and releases its lease |
| `prepare_parent_campaign_run` | Chooses a supported lineage and updates the account selection |
| `run_parent_campaign_career` | Starts one budgeted Career run through the campaign |
| `collect_parent_campaign_result` | Finds and evaluates the new veteran after Career completion |
| `list_parent_candidates` | Lists candidate scores, reasons, and weaknesses |
| `select_parent_candidate` | Resolves a user-input candidate decision |

Read-only resources:

- `sweepy://accounts` lists enabled accounts.
- `sweepy://snapshot/{account}` returns the last successful offline `load/index` projection.
- `sweepy://runtime/{account}` returns process and API readiness state.
- `sweepy://state/{account}` returns compact bot state for the selected account.
- `sweepy://operations/{account}` returns recent durable MCP mutations.

The prompt `operate_sweepy` gives an MCP host a safe workflow for operating the bot.

## Confirmation policy

Actions that spend resources or alter execution state return a preview when `confirm=false`:

```json
{
  "success": false,
  "requires_confirmation": true,
  "operation_id": "7aa81561-...",
  "action": "run_dailies",
  "details": {
    "account": "acct02",
    "team_trials": true,
    "daily_shop": false
  }
}
```

After the user approves, the agent calls the same tool again with the same `account`, the same `operation_id`, and `confirm=true`. Hermes should use a stable Discord message/event ID as `operation_id` when available.

A repeated mutation with the same operation ID and identical arguments returns the stored result with `replayed=true`; it does not execute the HTTP/game operation again. Reusing an operation ID with a different account, action, or arguments is rejected.

Career/Dailies workflow stop tools do not require confirmation because stopping a workflow is considered safer, but they still accept `operation_id` for retry safety. Process lifecycle tools (`launch_bot`, `stop_bot`, and `restart_bot`) always require confirmation because they change OS process state. `force=true` on `stop_bot` may escalate from SIGTERM to SIGKILL only after confirmation.

## Workflow leases and account locks

Career and Dailies acquire a durable per-account workflow lease. A Career lease blocks Dailies on that same account and vice versa. Different accounts remain independent and can run concurrently.

Every mutation also uses a short per-account mutation lock, preventing two Discord/MCP requests from changing the same account simultaneously. Stale locks and workflow leases expire automatically. Calling `get_bot_state` reconciles the durable lease with the actual Career/Dailies runner state.

Example retry-safe call:

```json
{
  "account": "acct02",
  "team_trials": true,
  "daily_shop": true,
  "confirm": true,
  "operation_id": "discord-message-129384756"
}
```

## Process lifecycle

A typical Hermes flow is:

```text
list_accounts
→ get_account_runtime(account="acct02")
→ launch_bot(account="acct02", confirm=false)
→ ask the user to approve the exact process change
→ launch_bot(account="acct02", confirm=true)
→ wait_until_ready(account="acct02", require_login=true)
→ get_bot_state(account="acct02")
```

The supervisor writes `uma_runtime/<account>/supervisor.json` and validates the saved PID, process group, and command line before sending any signal. It will not stop a manually launched or PID-reused process that it cannot prove it owns. If an account API is already reachable but no valid supervisor metadata exists, the process is reported as externally managed and duplicate launch is refused.

## Career selection

`run_career` intentionally does not accept raw deck, parent, friend, or trainee identifiers. It uses the selection already saved by the Sweepy web UI.

Before asking an agent to start a new Career:

1. Open the intended account's Sweepy port in the browser.
2. Select the trainee, support deck, friend support, and two parents.
3. Select or save a Career preset.
4. Ask the agent to list accounts, inspect that account's state, list its presets, and start the chosen one.

This keeps complex selection logic in the existing UI and prevents an agent from inventing account object identifiers.

## Offline load/index account snapshots

Every successful game endpoint call to `load/index` writes an atomic per-account snapshot:

```text
uma_runtime/<account>/load-index-cache.json
```

The client-level hook updates raw-safe cards, support cards/decks, and full owned trained-character lineage records even when `load/index` is called from a recovery path. When the same response passes through the web dashboard builder, the file is enriched with names, factors, lineage trees, stats, and aptitudes.

The snapshot:

- is written with mode `0600`;
- never contains SID, auth keys, Steam tickets, UDID, device ID, IP address, viewer ID, cookies, passwords, tokens, or raw response envelopes;
- is updated only by a successful `load/index` response;
- can be read while the bot web server is offline;
- exposes `refreshed_at`, so Hermes must state that cached inventory may be stale.

Reading `get_cached_account_snapshot`, `list_cached_veterans`, `scan_cached_legacy_loops`, or `sweepy://snapshot/{account}` does not call the game API.

## Legacy affinity-loop previews

The offline scanner collapses alternate costumes to one base character, keeps the strongest cached records per character, then evaluates four-character pools with the existing server-validated affinity calculator. Every member is simulated as trainee and receives its best current two-parent pairing from the other three character groups.

Pool ranking is lexicographic:

1. worst rotation affinity and circle tier;
2. shared G1 wins;
3. matching running style;
4. distance overlap;
5. average affinity and cached record quality.

Compatibility tiers are:

```text
>150   double circle
50-150 single circle
<50    triangle
```

`preview_shared_g1_agenda` reads generated race master data locally. It selects one occurrence per G1 program, prefers senior repeats when useful, avoids configured summer-camp turns, and prevents more than the requested number of consecutive race turns. A scheduled race contributes affinity progress only when won.

The preview tools intentionally do not mutate presets or start Careers yet. They provide the evidence for the next durable Legacy Loop campaign layer.

## Parent campaigns

A parent campaign separates the user's goal from the underlying Career runs. Example Medium/Turf specification:

```json
{
  "account": "acct02",
  "goal": {
    "surface_targets": ["turf"],
    "distance_targets": ["medium"],
    "minimum_rank": "S",
    "preferred_stats": ["speed", "stamina"]
  },
  "strategy": {
    "preset_name": "MANT Parent",
    "maximum_runs": 10,
    "maximum_carats": 0,
    "maximum_clocks": 0,
    "maximum_runtime_hours": 12,
    "tp_mode": "wait",
    "use_clocks": false,
    "approval_mode": "ambiguity_only",
    "stop_when_target_reached": true
  }
}
```

Minimum safe sequence:

```text
preview_parent_campaign
→ create_parent_campaign
→ start_parent_campaign
→ launch/wait/advance when requested
→ prepare_parent_campaign_run
→ run_parent_campaign_career
→ monitor get_bot_state
→ collect_parent_campaign_result
→ repeat, complete, or ask the user to select a candidate
```

The lineage planner uses `/api/inheritance/recommend`, skips unsupported two-rental pairs, resolves recommendation IDs back into full current-session parent objects, and persists a compact lineage summary. Career remains turn-by-turn controlled by Sweepy's existing CareerRunner.

Candidate evaluation uses required factor scope, minimum rank, Turf/Distance aptitudes, preferred stats, compatibility, and race history. Results contain component scores, matched/missing targets, reasons, weaknesses, and a baseline delta.

## Hermes / Discord installation

The repository includes an installable Hermes skill and an idempotent installer:

```bash
cd /absolute/path/to/umamusume-sweepy
venv/bin/python scripts/install_hermes_sweepy.py --dry-run
venv/bin/python scripts/install_hermes_sweepy.py
```

The installer:

- copies `hermes-skills/mcp/sweepy-parent-builder/SKILL.md` into `~/.hermes/skills/mcp/`;
- creates a timestamped backup of `~/.hermes/config.yaml` when changes are needed;
- adds the Sweepy stdio MCP server;
- enables the `sweepy` toolset for both Hermes CLI and Discord;
- sets `supports_parallel_tool_calls: false` so account mutations are serialized.

Restart or reload the Hermes session after installation so the new skill and MCP tools are discovered.

## Security boundaries

The MCP server does not expose tools for:

- login credentials or Steam Guard codes;
- reading auth cache or trace files;
- arbitrary game API calls;
- deleting Careers;
- removing veterans;
- following or unfollowing accounts;
- purchasing arbitrary shop items.

Response redaction covers SID, auth keys, Steam tickets, tokens, UDID, device ID, IP address, passwords, cookies, and raw captured bodies.
