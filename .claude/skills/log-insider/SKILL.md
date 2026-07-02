---
name: log-insider
description: "Use when the user asks anything about UMA bot API trace logs or career run logs — including: 'what happened at turn X', 'show me training distribution', 'did motivation drop', 'what did it buy at gain_skills', 'compare to baseline', 'why did it fail', 'race results', 'final stats', 'failure rate', 'trace_logs', 'api_payloads', 'career_log', 'bot_logs', or any path under uma_runtime. Trigger even if the user just pasts a career log path, says 'botlog', or references trace_logs without naming this skill."
---

# /log-insider

Query UMA bot career logs and API trace payloads with natural language.

## Log Sources (auto-detect by path)

| Path pattern | Shape | Parse as |
|---|---|---|
| `uma_runtime/<acct>/bot_logs/career_log_*.json` | flat JSON | career log |
| `uma_runtime/<acct>/trace_logs/api_payloads/*.jsonl` | JSONL, one line/call | api payloads |

For both, if path is **not given**, pick most recent:
```bash
ls -t uma_runtime/*/bot_logs/career_log_*.json 2>/dev/null | head -1
ls -t uma_runtime/*/trace_logs/api_payloads/*.jsonl 2>/dev/null | head -1
```

## Parsing Rules

### Career log JSON
```
top: {started_at, ended_at, preset_name, scenario_id, status, error,
      final_turn, turns: [{turn, api_calls: [{ts, direction, endpoint, data, turn}]}]}
```
- `api_calls` is flat (no double nesting). `data` = game payload directly.
- Each `api_calls[].turn` field is the turn number. Group by it.
- Filter on `direction` ("REQ"/"RES") + `endpoint`.

### API payloads JSONL
```
each line: {ts, direction, endpoint, data: {payload} | {response_code, data_headers, data: {...}}, req_id}
```
- **REQ**: actual request at `data.payload`
- **RES**: actual game state at `data.data` (**double-nested**). `chara_info`, `home_info`,
  `unchecked_event_array`, `ura_data_set` live here. Outer `data.response_code` / `data.data_headers`
  are transport wrappers.
- Turn number: not on entry — infer from `check_event` RES `chara_info.turn` (JSONL) or
  use `req_id` to correlate with REQ.
- Flat call-by-call (no `turns` grouping). Build turn groups by tracking `chara_info.turn` advancing.

## Workflow

1. **Detect log type** by path pattern (above). For turn-based queries on JSONL,
   first build turn-index to know which lines belong to each turn.
2. **Use `execute_code`** with Python (`json.load()` for career log, line-by-line
   `json.loads(line)` for JSONL). Never Read the whole file — 10-40MB+.
3. **Answer concisely.** Tabular or key:value, not prose. Abbreviate stats
   SPD/STA/POW/GUT/INT/VIT. For "what happened at turn N" return chara_info summary +
   command chosen + events.

## Common Queries

| Intent | Technique |
|---|---|
| Stats at turn N | `check_event` RES `data.data.chara_info` at that turn (JSONL) or `api_calls` grouped by turn |
| Chosen training | `exec_command` REQ `payload.command_type`/`command_id` |
| Race results | `race_end` RES → `race_history[0].{program_id, result_rank}`, `race_reward_info` |
| Skill purchases | `gain_skills` REQ → `payload.skill_id_array` |
| Rest vs train count | group `exec_command` REQ by `payload.command_type`: 1=SPD 2=STA 3=POW 4=GUT 5=INT 7=REST 8=OUTING |
| Motivation over time | track `chara_info.motivation` per turn (1=最悪 2=悪い 3=普通 4=好調 5=絶好調) |
| Failure detection | `exec_command` RES stat delta ≤5 or event_id=1007 |
| Compare bot failure_rate vs real | compare `command_info_array[].failure_rate` (game) vs
  `_decision_detail.failure_rate` (bot) for chosen `command_id` |
| Summer camp turns | `command_id` 601-605 |
| Bot-injected fields | `_label`, `_decision_detail{score, reasons[], failure_rate}`,
  `_decision_options[{score, reasons[]}]` on `command_info_array` entries |
| Career run summary (preset/status/turn count/final stats) | use `analyze_career_log.py` — see below |

## Career Run Summary

For analysis of a whole career run (training distribution, race timeline, progression,
skill purchases, failures) use:
```bash
python3 scripts/analyze_career_log.py <path-to-career-log.json>
```
Format of script output is stable — any deviations from the known format means either
the log is malformed or the script has a bug. Report as-is if unsure.

## Output Format

Log identity first (path → account, preset, scenario, status, final_turn).

Then answer directly. Stat blocks:
```
T30 | SPD 312 STA 201 POW 171 GUT 128 INT 244 | VIT 72/150 | MOT 好調 | CMD:STA(x3.2) lvl5
```

For the full `chara_info` field reference, read [`references/fields.md`](references/fields.md)
**lazily** — only when a query needs a field not yet seen this session.

## Don'ts

- Don't Read/head/cat the whole file. Use `execute_code`.
- Don't assume `data.data` nesting for career logs (flat `data` — differs from JSONL RES).
- Don't guess field names not in the reference.
