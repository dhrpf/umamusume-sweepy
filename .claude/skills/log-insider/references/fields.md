# career_log Field Reference

## chara_info (single_mode/check_event RES)
| Field | Meaning |
|---|---|
| `speed`, `stamina`, `power`, `guts`, `wiz` | Core stats (wiz=INT) |
| `vital` / `max_vital` | Current/max vitality (0-150+) |
| `motivation` | 1=最悪 2=悪い 3=普通 4=好調 5=絶好調 |
| `fans` | Fan count |
| `turn` | Career turn number (1=start) |
| `state` | Game state bitmask |
| `playing_state` | 0=normal, 1+=racing/etc |
| `skill_point` | Accumulated skill points |
| `skill_array[]` | `{skill_id, level}` — level>0 means learned |
| `skill_tips_array[]` | Available skill hints (not yet learned) |
| `proper_ground_turf/dirt` | Turf/dirt aptitude (G/B/A/S rank scales) |
| `proper_running_style_{nige,oikomi,sashi,senko}` | Running style aptitude |
| `proper_distance_{short,middle,mile,long}` | Distance aptitude |
| `talent_level` | Ranks star aptitudes |
| `support_card_array[]` | Equipped support cards |

## home_info.command_info_array[] (training options)
| Field | Meaning |
|---|---|
| `command_type` | 1=training 7=rest 8=outing |
| `command_id` | 101=SPD 102=STA 103=POW 104=GUT 105=INT 106=WIT(legacy) 601-605=summer camp |
| `failure_rate` | Game's ACTUAL failure % (0-99) — **not** what bot sees (see "Known Bug" below) |
| `is_enable` | 1=available |
| `level` | Training level (1-5, affects gains) |
| `training_partner_array[]` | Partner umas/cards present |
| `params_inc_dec_info_array[]` | Expected gains: `{target_type, value}` |
| `target_type` | 1=SPD 2=STA 3=POW 4=GUT 5=INT 10=VIT 30=skillpt |

### Bot-injected fields (only on chosen command)
- `_label`: human-readable action ("SPD lvl5")
- `_decision_detail.score` / `.failure_rate` / `.reasons[]`: bot's internal assessment
- `_decision_options[]`: all scored options sorted by score, each with `reasons[]`

## exec_command REQ payload
```
{payload: {command_type, command_id, command_info_array_index?, ...}}
```

## gain_skills REQ payload
```
{payload: {skill_id_array: [...]}}  // empty = nothing bought
```

## race_end RES payload fields
- `race_history[0].{program_id, result_rank}` — program_id cross-refs `data/race_map.json`
- `race_reward_info.{result_rank, gained_fans}`

## unchecked_event_array
Non-empty = pending event(s). Each entry has `event_id`, `event_type`. Wait for empty before
exec_command — that's the "decision point" state.

## event_id 1007
Training failure. Fires in `exec_command` RES when training failed.

## Known Bug (ura.py line 609)
Bot reads `cmd.get("fail_percent")` but game sends `"failure_rate"` → bot always sees 0%
for individual commands. The gate at line 287 reads `failure_rate` correctly but triggers
only when ALL training options have ≥30% fail. Cross-check by comparing game `failure_rate`
(job replay) vs `_decision_detail.failure_rate` (what bot believed it saw).

## check_event flow per turn
```
1. check_event REQ  (may fan out to resolve events sequentially)
2. check_event RES  ← chara_info + home_info + unchecked_event_array
   (if unchecked_event_array non-empty → loop)
3. exec_command REQ (chosen action)
4. exec_command RES ← post-action chara_info + events fired
```
Multiple `check_event` calls per turn = events being processed sequentially. The
decision for turn N is made from the last `check_event` RES where
`unchecked_event_array=[]` and `command_info_array` is present, **before** the
`exec_command` REQ.
