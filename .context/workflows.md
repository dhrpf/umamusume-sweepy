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

## Update Protocol SALT After a Game Patch

Use this when SID generation starts failing after an Uma Musume client update, or when the protocol constants need to be revalidated. Steam and the game must already be running, and `frida-server` must be reachable through the configured `FRIDA_REMOTE` endpoint.

Run the runtime/metadata probe:

```bash
venv/bin/python scripts/probe_protocol_salt.py
```

The probe performs two checks without sending an API request:

```text
attach to the running IL2CPP game
→ invoke Gallop.Cryptographer.MakeMd5 with a known probe string
→ parse Il2CppStringLiteral entries from global-metadata.dat
→ find the exact literal where MD5(probe + literal) equals the game digest
```

Expected output contains one match:

```json
{
  "offset_hex": "0x143489",
  "salt_ascii": "co!=Y;(UQCGxJ_n82",
  "salt_hex": "636f213d593b2855514347784a5f6e3832",
  "length": 17
}
```

If `salt_ascii` differs from the value in `uma_api/client.py`, update:

```python
SALT = b'<new salt_ascii value>'
```

Then verify SID derivation and the full test suite:

```bash
venv/bin/python scripts/probe_protocol_salt.py
venv/bin/pytest
```

Interpret failures as follows:

- No matching literal: the game may have changed `MakeMd5`, the metadata layout, or the salt encoding.
- Managed method not found: inspect `Gallop.Cryptographer` through IL2CPP reflection; the class or method may have been renamed.
- Multiple matches: do not choose by offset alone; compare candidate length and validate the generated SID against a normal login flow.
- Probe succeeds but login still fails: revalidate `HEAD` with `scripts/probe_compress_request.py` and check auth/session recovery separately.

Do not extract the salt by scanning printable substrings around a raw byte offset. IL2CPP string-literal data is concatenated without NUL separators; use the literal table's length and `dataIndex` entries as the source of truth.
