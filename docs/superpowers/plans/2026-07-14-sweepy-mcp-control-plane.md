# Sweepy MCP Control Plane Implementation Plan

> **For agentic workers:** Implement task-by-task with TDD. Keep process lifecycle, bot operation, and campaign orchestration separated so Hermes can recover safely after MCP or Discord restarts.

**Goal:** Turn Sweepy's MCP adapter into a multi-account control plane that can launch, stop, restart, inspect, and operate each bot instance, then add durable goal-driven campaigns such as “build a Medium/Turf parent on account acct02.”

**Architecture:**

```text
Hermes Agent / Discord
        │
        ▼
Sweepy MCP (stdio or streamable HTTP)
        │
        ├── Account Registry ── accounts.json
        ├── Supervisor ──────── process lifecycle, logs, readiness, PID safety
        ├── Bot Operator ────── account state, Career, Dailies, resource controls
        └── Campaign Manager ── durable goals, candidate scoring, retries, budgets
                  │
                  ▼
       Per-account Sweepy FastAPI instance
       acct01 :1616 / acct02 :1617 / ...
```

**Core constraints:**

- Every mutation must name an account explicitly when more than one account is enabled.
- No arbitrary shell execution and no arbitrary game API tool.
- Process lifecycle actions require preview/confirmation.
- One workflow lease per account; different accounts may run concurrently.
- Credentials, auth cache, raw payloads, device identifiers, and trace data never leave the MCP boundary.
- Campaign state must survive Hermes, MCP, launcher, and bot restarts.
- Hermes handles natural-language intent and Discord updates; Sweepy handles deterministic execution and turn-by-turn gameplay.

**Tech stack:** Python stdlib process management, FastAPI/httpx, MCP Python SDK 1.x, SQLite for durable campaigns, pytest.

---

## Phase 1 — Multi-account Supervisor

### Task 1: Durable process metadata and safe PID validation

**Files:**
- Create: `sweepy_supervisor.py`
- Create: `tests/test_sweepy_supervisor.py`

- [x] Add a runtime/status model derived from `accounts.json`.
- [x] Store supervisor metadata under `uma_runtime/<account>/supervisor.json`.
- [x] Store combined launcher output under `uma_runtime/<account>/supervisor.log`.
- [x] Validate a saved PID before signaling it by checking process existence, process group, and command-line ownership.
- [x] Treat stale or reused PIDs as stopped and remove stale metadata.
- [x] Never expose environment variables or credentials in status/log metadata.

### Task 2: Launch, stop, restart, and readiness

**Files:**
- Modify: `sweepy_supervisor.py`
- Modify: `tests/test_sweepy_supervisor.py`

- [x] `launch(account)` starts `launcher.py <account>` in a detached process group.
- [x] Preserve inherited `FRIDA_REMOTE` and account `extra_env` through existing launcher behavior.
- [x] Refuse duplicate launch when the managed launcher is alive or the account API is already reachable externally.
- [x] `stop(account)` sends SIGTERM to the managed process group and waits for graceful shutdown.
- [x] `stop(account, force=true)` escalates to SIGKILL only after an explicit confirmed call.
- [x] `restart(account)` performs a graceful stop followed by launch.
- [x] `wait_until_ready(account)` polls the local `/api/session` and runner endpoints without performing game mutations.
- [x] Status distinguishes process running, API reachable, logged in, Career running, and Dailies running.

### Task 3: Supervisor MCP tools

**Files:**
- Modify: `sweepy_mcp.py`
- Modify: `tests/test_sweepy_mcp.py`
- Modify: `MCP.md`

- [x] Add `get_account_runtime(account)`.
- [x] Add `get_bot_logs(account, lines=100)` with line and byte caps.
- [x] Add `launch_bot(account, confirm=false)`.
- [x] Add `stop_bot(account, confirm=false, force=false)`.
- [x] Add `restart_bot(account, confirm=false)`.
- [x] Add `wait_until_ready(account, timeout_seconds=30)`.
- [x] Include account and exact lifecycle change in confirmation previews.
- [x] Reject process stop/restart without confirmation even if workflow stop tools remain confirmation-free.
- [x] Prevent force stop unless `force=true` and `confirm=true`.

### Task 4: Supervisor integration verification

- [x] Protocol handshake exposes the lifecycle tools and their `account` schemas.
- [x] Account routing and read-only runtime calls are covered for single- and multi-account registries.
- [x] Full unit suite passes.
- [x] Automated subprocess smoke test launches a detached dummy account, reads logs, validates ownership, and stops it cleanly.
- [ ] Optional real-account launch/readiness/stop smoke test after explicit user approval.

---

## Phase 2 — Operation IDs, Locks, and Durable Jobs

### Task 5: Per-account workflow leases

**Files:**
- Create: `sweepy_jobs.py`
- Create: `tests/test_sweepy_jobs.py`

- [x] Add one mutation lock/lease per account.
- [x] Persist lease owner, workflow type, heartbeat, and expiry.
- [x] Career and Dailies cannot overlap on the same account.
- [x] Different accounts can execute concurrently.
- [x] Stale leases are recoverable after process crashes.

### Task 6: Idempotent MCP mutations

- [x] Add optional `operation_id` to lifecycle, Career, Dailies, TP, and current control-plane mutations; campaign mutations will inherit the same wrapper in Phase 3.
- [x] Persist completed/in-progress operation results.
- [x] Retrying the same Discord message or MCP call does not launch or spend twice.
- [x] Reject reuse of an operation ID with different arguments.

### Task 7: Durable job/event log

- [x] Persist operation history and account events to SQLite.
- [x] Expose compact `get_recent_operations(account)`.
- [x] Never persist credentials or raw API payloads.

---

## Phase 3 — Parent Campaign Manager

### Task 8: Structured parent goal model

**Files:**
- Create: `career_bot/campaigns/models.py`
- Create: `tests/test_campaign_models.py`

- [x] Define purpose, account, surface targets, distance targets, stat/factor preferences, budgets, and stop conditions.
- [x] Separate candidate requirements from lineage requirements.
- [x] Require hard limits: maximum runs, carats, clocks, and runtime.
- [x] Support approval modes: fully automatic, per generation, ambiguity only.

### Task 9: Campaign persistence and state machine

**Files:**
- Create: `career_bot/campaigns/store.py`
- Create: `career_bot/campaigns/runner.py`
- Create: `tests/test_campaign_store.py`
- Create: `tests/test_campaign_runner.py`

- [x] Persist campaigns in `uma_runtime/campaigns.sqlite3`.
- [x] Implement states: DRAFT, READY, STARTING_BOT, WAITING_FOR_LOGIN, SELECTING_LINEAGE, RUNNING_CAREER, EVALUATING_RESULT, WAITING_FOR_TP, NEEDS_USER_INPUT, PAUSED, COMPLETED, FAILED, CANCELLED.
- [x] Resume after Hermes/MCP/bot restart.
- [x] Maintain account lease and operation idempotency.
- [x] Stop when target or budget is reached.

### Task 10: Parent candidate evaluator

**Files:**
- Create: `career_bot/campaigns/parent_evaluator.py`
- Create: `tests/test_parent_evaluator.py`

- [x] Score factors, aptitudes, lineage, compatibility, stats, and race history.
- [x] Produce structured reasons and weaknesses, not only a numeric score.
- [x] Compare against current parent baseline and detect clear improvements vs ambiguous choices.
- [x] Keep raw trained-character responses inside Sweepy; MCP receives compact candidate summaries.

### Task 11: Campaign MCP surface

- [x] `preview_parent_campaign`.
- [x] `create_parent_campaign`.
- [x] `start_parent_campaign` / `advance_parent_campaign`.
- [x] `get_parent_campaign` / `get_parent_campaign_summary`.
- [x] `pause_parent_campaign` / `resume_parent_campaign` / `cancel_parent_campaign`.
- [x] `prepare_parent_campaign_run` / `run_parent_campaign_career` / `collect_parent_campaign_result`.
- [x] `list_parent_candidates` / `select_parent_candidate`.
- [x] All campaign mutations include account, budget, operation ID, and confirmation preview where spending/state changes occur.

---

## Phase 4 — Hermes / Discord Integration

### Task 12: Hermes skill

**Files:**
- Create: `hermes-skills/sweepy-parent-builder/SKILL.md` or install into Hermes skill directory.

- [x] Always call `list_accounts` and select an explicit account.
- [x] Translate natural language such as “Medium Turf parent” into a structured preview.
- [x] Summarize budgets and request confirmation before starting.
- [x] Poll campaign state, not turn-by-turn Career actions.
- [x] Post Discord updates only on meaningful events: candidate found, target reached, bot crash, budget exhausted, TP wait, or user decision required.

### Task 13: Discord-friendly progress summaries

- [x] Add compact campaign summaries suitable for chat.
- [x] Include account, run number, budgets used, best candidate, next action, and whether user input is required.
- [x] Avoid raw logs unless explicitly requested.

---

## Security and Operations Checklist

- [x] Lifecycle tools cannot execute arbitrary commands.
- [x] Account names are validated against `accounts.json`; no path traversal.
- [x] PID signaling verifies ownership before sending a signal.
- [x] Logs are capped and recursively redacted before MCP output.
- [x] MCP stays on stdio or loopback unless authentication is added.
- [x] Process lifecycle and campaign mutations create audit entries.
- [x] No new tests contain live account identifiers, auth values, tickets, SID, UDID, device IDs, or copied raw payloads.
- [x] `exchange_shop.json` and capture artifacts remain ignored/untracked.

---

## Current Execution Target

Phases 1–4 are implemented in the repository. Remaining operational verification is a real-account smoke test through Hermes/Discord, which must only be run with explicit approval because it can launch a process and consume TP during a campaign Career.
