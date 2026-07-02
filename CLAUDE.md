# Sweepy — Uma Musume Career Automation Bot

FastAPI server that automates Uma Musume career runs via intercepted auth + msgpack API. See `README.md` for boot/setup.

## Architecture

| Area | Entry |
|---|---|
| HTTP server / routes / career loop | `main.py` (~2600 lines) |
| Game API client (msgpack, crypto, device spoofing) | `uma_api/client.py` |
| Career turn runner / lifecycle | `career_bot/runner.py` |
| Scenario strategies | `career_bot/scenarios/{mant,ura}.py` |
| Race planning | `career_bot/races.py` |
| Skill buying | `career_bot/skills.py` |
| Item buying/use + shop | `career_bot/items.py` |
| Preset loading/validation | `career_bot/presets.py` |
| Static data (race/skill/factor maps) | `career_bot/master_data.py` |
| MCTS planner (alpha) | `career_bot/mcts/` |
| Frontend (vanilla JS SPA) | `public/` |

## Path-Scoped Rules

Rules auto-load when you touch matching paths.

| Paths | Rule file |
|---|---|
| `uma_api/**`, `capture_dailies.py`, `launcher.py` | `.claude/rules/api.md` |
| `career_bot/scenarios/**`, `career_bot/master_data.py` | `.claude/rules/scenarios.md` |
| `career_bot/runner.py`, `career_bot/races.py`, `career_bot/skills.py`, `career_bot/items.py`, `career_bot/presets.py`, `career_bot/delay.py`, `career_bot/events.py` | `.claude/rules/career-loop.md` |
| `main.py` | `.claude/rules/server.md` |
| `career_bot/mcts/**` | `.claude/rules/mcts.md` |
| `public/**` | `.claude/rules/frontend.md` |
| `scripts/**`, `tests/**` | `.claude/rules/scripts.md` |

Full hard-constraint rules: `.context/ai-rules.md`
Glossary: `.context/glossary.md`

## Tier 2 (load on trigger)

Trigger | File
---|---
"broken" / "crash" / "not buying" / "race entry fail" | `.context/prompts/fix-bug.md`
"add scenario" / "career type" | `.context/prompts/add-scenario.md`
"rename" / "extract" / "move" / "inline" | `.context/prompts/refactor-symbol.md`
"patched" / "new skill ids" / "master.mdb" | `.context/prompts/regen-master-data.md`
Runner chain / event drain / skill buy / `_advance` | `.context/decisions/007-runner-chain.md`
Runner control flow / race resume / recovery / 102 relogin / dispatch actions | `.context/runner-workflow.md`
Error code / absorb vs retry | `.context/errors.md`
Env vars (UMA_MASTER_MDB, FRIDA_REMOTE, PORT) | `.context/env.md`
Why msgpack+aes / rule-based default | `.context/decisions/001-msgpack-aes.md` + `002-sid-regeneration.md` + `005-rulebased-vs-mcts.md`
Auth / start / regenerate sequence | `.context/workflows.md`
Known-bug parity | `.context/decisions/010-fail-percent-bug-parity.md`
Failure modes | `.context/anti-patterns.md`
