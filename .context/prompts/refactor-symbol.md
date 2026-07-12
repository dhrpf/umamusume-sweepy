# Protocol: refactor-symbol

**Trigger**: rename, extract, move, inline a symbol

## Pre-checks

1. Get symbol definition via `get_symbol_source` (file + line).
2. `find_references` — enumerate every use site. Sweepy-coupled spots:
   - `STRATEGIES` dict at `runner.py:25-28` (hard registry).
   - `Decision.action` dispatch at `runner.py:264-363` (switch on string).
   - Scenario import block at `runner.py:13`.
3. Check hard constraints BEFORE proposing:
   - `.claude/rules/api.md` — protocol (crypto, SID, device strings).
   - `.claude/rules/career-loop.md` — runner dispatch + StateRecoveryError absorption.
   - Rules override suggestion; don't "simplify" away a rule-mandated step.

## Steps (preflight → edit → verify)

### Preflight

- `get_blast_radius(symbol)` for indirect deps.
- `tests/test_runner_command_metadata.py` + `tests/test_runner_event_recovery.py` — refactors near runner dispatch break these.
- `main.py` routes — Pydantic models must stay wire-compatible.
- Cross-package: verify `runtime_output_root()` (`runner.py:31-41`) won't break for cwd-relative lookups.
- `CareerRunner._recover_blocked_state` and `_fresh_career_state` call client recovery paths. Renaming `hard_reset()` or `login()` requires updating both recovery contracts.

### Edit

- One symbol move per commit.
- Update `runner.py:13` import + `runner.py:25-28` if scenario class moves.
- Update `career_bot/master_data.py` `synthesize_*` if symbol touches those paths.

### Post-edit

- `register_edit(paths_changed)` (per CLAUDE.md PostToolUse hook).

## Verify

```bash
pytest tests/test_runner_command_metadata.py tests/test_runner_event_recovery.py tests/test_mant_strategy.py tests/test_ura_*.py -x
```

```bash
# Cross-package move safety:
grep -rn "OldName" career_bot/ main.py public/  # must be zero hits
```

## Known Traps

- `runner.py:25-28` `STRATEGIES` — class looked up by `scenario_id` at `runner.py:110`. Move without update = runtime crash.
- `runner.py:264-363` action dispatch — mutation of decision payload keys (`current_turn`, `event_id`, etc.) breaks dispatch everywhere.
- `rules/api.md:6` — never repack/regen SID inside retry except after 208.
- `rules/api.md:4` — `result_code` lives in `response.data_headers`, not top-level. Refactor of response parsing must preserve.
- `runtime_output_root()` walks up to first `.git`. Move `uma_runtime/` consumers → verify path resolution.
- `runner.py:561` `hard_reset()` — method rename breaks recovery waterfall silently.
