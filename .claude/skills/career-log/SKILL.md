---
name: career-log
description: Analyze Uma Musume career bot logs. Use whenever the user asks to review, analyze, or look at a career run/log, mentions career_log JSON files, or wants stats/race results/training analysis from a bot run. Also trigger when user references uma_runtime bot_logs or asks about training failures, race results, skill purchases, or stat progression from a career.
---

# Career Log Analyzer

Analyzes career bot JSON logs (10-15MB+, never read raw) and produces a formatted report.

## When triggered

Run the bundled analysis script via Bash. The script handles all extraction and formatting.

## Usage

```bash
python3 scripts/analyze_career_log.py <path-to-career-log.json>
```

The log path is typically: `uma_runtime/<account>/bot_logs/career_log_<timestamp>.json`

If the user says "review this run" or "analyze the latest log" without a path, find the most recent log:

```bash
ls -t uma_runtime/*/bot_logs/career_log_*.json | head -1
```

## What the report covers

1. **Header** — preset, scenario, status, error, duration, final turn
2. **Final stats** — SPD/STA/POW/GUT/INT, total, fans, motivation, skill pts, skills learned count
3. **Training distribution** — count of each command type (SPD/STA/POW/GUT/INT/REST/OUTING)
4. **Race results** — name-resolved via `data/race_map.json`, rank, fans gained
5. **Motivation timeline** — only changes shown
6. **Vitality & failure rate flags** — training at >=20% game failure_rate
7. **Training failures** — stat gain <=5 after training action (likely failed)
8. **Stat progression** — every 12 turns
9. **Skills learned** — final skill list with names from `data/skill_data.json`

## After the report

Summarize key findings and flag problems:
- High failure rate training (especially >50%)
- Many training failures
- Low total stats
- Missing race wins
- Unusual training distribution
- Known bugs (e.g., `fail_percent` vs `failure_rate` key mismatch)

## Log structure notes

These are critical for anyone modifying the script:
- API call data is nested: `call['data']['data']` not `call['data']`
- `chara_info` lives at `call['data']['data']['chara_info']`
- `command_info_array` at `call['data']['data']['home_info']['command_info_array']`
- Race program_id: use `race_start_info.program_id` from `race_start` RES (reliable), not `race_history` from `race_end` (can have instance IDs)
- Race names: resolved via `data/race_map.json` → `meta` dict, match by `program_id` field
- Skill names: resolved via `data/skill_data.json`
