# End-to-End Workflows

## Auth Startup

```text
refresh_auth_before_serving()
→ load_auth_cache() fast path, or capture live Frida auth
→ auto_login_from_cache()
→ get_ticket()
→ GateKeeper(UmaClient).login()
→ tool/start_session + load/index
→ build dashboard
→ serve FastAPI
```

`auth_cache.json` holds game auth/config under runtime output. Steam refresh token lives at `runtime_output_root()/steam_refresh_tokens/<username>.jwt`.

## Client Session Recovery

`UmaClient.call()` owns per-endpoint protocol retries. On first 501:

```text
close stale requests session
→ reload runtime auth_cache.json
→ require Steam username/password seed
→ generate fresh Steam ticket
→ UmaClient.login()
  → fresh requests session
  → tool/start_session
  → load/index
→ retry original endpoint
```

Second 501 raises `StateRecoveryError`; runner fetches fresh career state. `login()` can attempt anonymous bootstrap and transition-code recovery after session-invalid responses. 214 updates resource version and resets transport/SID before retry.

## Start Career

```text
/api/career/start
→ validate_start_selection
→ load/index / TP decision
→ recover TP if allowed
→ cleanup stale career if needed
→ pre_single_mode
→ UmaClient.start_career
→ CareerRunner.start
```

## Career Loop

```text
CareerRunner._run
→ drain pending events
→ recover blocked state
→ strategy.next_decision
→ dispatch action
→ buy skills when not finishing
→ advance turn
```

Recovery uses `CareerRunner._fresh_career_state`:

```text
load_career
→ client.login() on retry
→ reload career state
→ hard_reset fallback after retries
```

## Career Log Analysis

```bash
venv/bin/python scripts/analyze_career_log.py \
  uma_runtime/<account>/bot_logs/career_log_<timestamp>.json
```

Do not inspect raw career logs before this analyzer.

## Master Data Regeneration

```bash
venv/bin/python scripts/generate_master_data.py [--db-path /path/to/master.mdb]
```

Regeneration writes derived `data/*.json` and public race data. Restart server afterwards because consumers load data at import time.
