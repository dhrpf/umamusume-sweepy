# Protocol: regen-master-data

**Trigger**: game patch, new skill ids, `master.mdb` update, missing race schedule.

## Pre-checks

1. Confirm target database:

```bash
UMA_MASTER_MDB=/path/to/master.mdb \
  venv/bin/python -c "from career_bot import master_data; print(master_data.status('.'))"
```

2. `UMA_MASTER_MDB` overrides automatic Proton/Windows discovery.
3. Confirm source database mtime is newer than generated data.

## Steps

```bash
venv/bin/python scripts/generate_master_data.py [--db-path /path/to/master.mdb]
```

Script resolves project `ROOT`; current shell cwd does not redirect output root.

Confirm outputs:

```text
data/skill_data.json
data/chara_list.json
data/support_list.json
data/race_map.json
data/factor_map.json
data/chara_aptitude.json
public/assets/data/uma_race_data.json
```

Restart server afterwards. Skills, races, strategies, and frontend loaders cache generated data at process/import scope.

## Verify

```bash
ls -la data/*.json public/assets/data/uma_race_data.json
venv/bin/python -m pytest tests/test_mcts_*.py tests/test_mant_strategy.py tests/test_ura_*.py
```

## Traps

- Stale `UMA_MASTER_MDB` silently generates coherent but wrong data.
- Do not hand-edit generated JSON.
- `params.json` for MCTS is separate from master-data generation.
