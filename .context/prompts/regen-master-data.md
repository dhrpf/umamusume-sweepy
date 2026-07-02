# Protocol: regen-master-data

**Trigger**: game patched, new skill ids, master.mdb updated, race schedule missing

## Pre-checks

1. **Confirm master.mdb present**:
   ```bash
   UMA_MASTER_MDB=/path/to/master.mdb python -c "from career_bot import master_data; print(master_data.status('.'))"
   ```
   Printed path must match new patch's mdb (`master_data.py:30-51`).
2. **Env vars**:
   - `UMA_MASTER_MDB` — override path (`master_data.py:32-34`).
   - `LOCALAPPDATA` — Windows only. If unset, walks compatdata 3224770.
3. **Mtime check**: game patch overwrites compatdata master.mdb — verify mtime is newer than `data/*.json` mtimes.

## Steps

1. Run: `python scripts/generate_master_data.py` (or `--db-path <path>`).
   - Wrapper at `scripts/generate_master_data.py:17` → calls `master_data.generate(ROOT, db_path)`.
2. Confirm `data/` outputs: `skill_map.json`, `chara_list.json`, `support_list.json`, `race_map.json`, `factor_map.json`, `chara_aptitude.json` + `uma_race_data.json`.
3. If any output empty, check `sqlite3` succeeded — game patch sometimes corrupts mdb. Fall back to known-good copy.
4. **Bounce proc** — `career_bot/skills.py`, `races.py`, `scenarios/ura.py` read `data/*.json` at import time. Stale data survives regen if server not restarted.

## Downstream breakage if stale

| Consumer | Reads | Breaks |
|---|---|---|
| `career_bot/skills.py` | `skill_map.json` | new skill ids invisible, bought wrong |
| `career_bot/races.py:15` | `race_map.json` | new programs missing from `forced_program()` / `mandatory_available()` / `wanted_available()` |
| `career_bot/scenarios/ura.py:56-69` | `support_list.json` | stale types propagate to all decisions |
| `public/.../app.js` | `uma_race_data.json` | UI race calendar shows old date/grade |
| `career_bot/mcts/sim/ura.py:19-28` | `params.json` (separate) | **unaffected** by mdb regen |
| `main.py` frontend cache | mtime-keyed | auto-invalidated by json mtime bump |

## Verify

```bash
ls -la data/*.json public/assets/data/uma_race_data.json  # mtime newer than patch
# Spot check: new skill id / race instance / program id present
pytest tests/test_mcts_*.py tests/test_mant_strategy.py tests/test_ura_*.py
```

## Known Traps

- `master_data.py:32-34` env override wins over `settings.json` — stale inherited `UMA_MASTER_MDB` regenerates against WRONG mdb.
- `master_data.py:44-46` Proton path uses `~/.steam/steam` — some installs use `~/.local/share/Steam`. Verify symlink.
- `master_data.py:30-51` has three branches (env → compatdata → AppData). Override silently changes source.
- `synthesize_*` cast mdb TEXT → `int(id)` — `int(None)` throws. Always filter `if not skill_id: continue`.
- `runner.py` + `main.py` read `data/*.json` at import — must bounce proc after regen.
- `career_bot/events.py` may cache text maps at import — check for side-channel `data/` reads.
- `runtime_output_root()` at `runner.py:31-41` — run `generate_master_data.py` from repo root or ROOT resolves wrong.
