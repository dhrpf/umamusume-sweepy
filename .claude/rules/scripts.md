# Rule: Scripts & Tests

Paths: `scripts/**`, `tests/**`

## Scripts

1. `scripts/analyze_career_log.py` is the canonical career log analyzer. Always use it for post-run analysis; never read raw log JSON.
2. `scripts/generate_master_data.py` parses `master.mdb` and emits `data/*.json`. Run after game patches — output is committed.
3. `scripts/import_uma_guide.py` pulls external guide data into `data/uma_guides/`. Run only when updating borrowed strategy.
4. `scripts/calibrate_simulator.py` ingests real-game runs and tunes MCTS weights. Don't hand-tune weights in code.
5. `scripts/add_trackblazer_meta.py` decorates race records with trailblazer metadata. Idempotent; safe to re-run.
6. Career logs live at `uma_runtime/<acct>/bot_logs/career_log_<ts>.json`. Find latest with `ls -t`.

## Tests

7. `conftest.py` is minimal — add project-wide fixtures there, not inline in tests.
8. Command: `pytest` from repo root. Requires `venv/` (refer to `requirements.txt`).
9. Test mocks: prefer patching `UmaClient.call` over spinning up a Frida server. Integration tests are opt-in only.
10. `test_mcts_*.py` validates planner invariants (simulation count, state validity, config parsing). Don't break on warning-only failures — adjust thresholds.
11. `test_ura_*.py` validates URA strategy gates. The known `fail_percent` vs `failure_rate` bug is NOT a regression check — don't add a test that fails on it.
12. `test_mant_strategy.py` exercises Mant energy/section logic. Add new test when extending scenario behavior.
13. `test_runner_command_metadata.py` and `test_runner_event_recovery.py` are critical path. Any failure here blocks release.
