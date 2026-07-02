# Glossary — Sweepy Project Terms

| Term | Meaning |
|---|---|
| Uma Musume | Japanese gacha game; the target being automated |
| Sweepy / UAT | The bot; originally /vg/'s "Uma Automaton Team" |
| career | One full 2-year (≈70 turn) playthrough of a single chara |
| run / career run | One invocation of `CareerRunner.start()` |
| scenario | Campaign type (1=URA Finale, 2=Aoharu Team, 4=Mant/MANT). Selects strategy + endpoint prefix |
| chara | Trainee character (e.g. Special Week). Don't confuse with "character" |
| turn | One game turn ≈ one in-game month. ~70 turns per career |
| training | stat-gain action; command_types 101-106 (normal), 601-605 (summer camp) |
| SPD/STA/POW/GUT/INT(WIT) | The five trainable stats: Speed/Stamina/Power/Guts/Wisdom |
| WIT | = Wisdom = INT = wiz field. Game uses "wiz"; bot uses both "Wit" and "wiz" |
| vital | HP/training energy. 0-100 (can exceed with items). Game calls it HP in some contexts |
| motivation | Mood 1(worst)-5(best). Affects training gains |
| command_type | 1=training, 2=rest, 3=recreation/outing, 7=rest (URA), 8=medic, plus race_contest types |
| exec_command | API that performs training/rest/recreation. Returns post-action events |
| check_event | API that resolves pending events in `unchecked_event_array` |
| unchecked_event_array | Pending events to drain before making a decision |
| command_info_array | Training options from the game, with failure_rate and stat deltas |
| event_id 1007 | The "training failed" event |
| _label, _decision_detail, _decision_options | Bot-injected diagnostics; not from the game. Safe for debug logs |
| race_entry | Enter a race. Server may reject (205/208/213) |
| race_start / race_end | Begin and resolve race; `race_history[0].result_rank` = finishing position |
| gain_skills | Buy skill; empty `skill_id_array` = keep points |
| single_mode_finish | End the career. Required for a clean finish |
| support card | Deckmates that bond with chara; type (Speed/Stamina/.../Wit) trains that stat |
| bond (evaluation) | Affinity between chara and support. Orange=50+; unlocks bond bonuses |
| training partner | Support present during a training action; boosts gains |
| evaluation_info_array | Bond map: `target_id` -> `evaluation` |
| section / turn group | Gameplay phase; URA Finale is segmented by forced race schedule |
| facility level | Training facility rank. Up after 4 uses (`TRAINING_LEVEL_UP`) |
| summer camp | Turns 37-40, 61-64 where cmd_ids shift to 601-605 |
| forced race | Mandatory race target whose deadline blocks training decisions |
| race program | Single countable race instance, identified by `program_id` |
| program_id | Race identifier. Map to name via `data/race_map.json` under `meta.*` |
| race_planner | `RacePlanner` instance; selects races (forced, wanted, fallback) |
| skill buyer | `SkillBuys` — prioritizes which skills to acquire |
| Mant / MANT | Scenario 4 = current default. `MantStrategy` |
| URA | Scenario 1 = endgame campaign. `UraStrategy` |
| MCTS | Monte Carlo Tree Search — alpha planner in career_bot/mcts/ |
| preset | JSON (in data/presets/) defining scenario, deck, skill, item, race policy |
| msgpack | Binary wire format; encrypted with AES |
| Frida | Dynamic instrumentation used to hook Unity TLS and capture auth |
| frida-server | Windows exe running inside the Proton Wine prefix |
| ticket | Steam session ticket from steam-user (Node.js) used to log in |
| refresh_token | Persisted Steam credential at `uma_runtime/steam_login_keys/<user>.txt` |
| auth_cache.json | Persisted viewer_id + udid + auth_key + app_ver + res_ver |
| viewer_id, udid, auth_key | The three-legged auth pair for game API; never expose publicly |
| res_ver | Resource version; 214 code bumps it |
| aoharu | Scenario 2 (team racing). Uses `single_mode_team/*` endpoints |
| trailblazer | Slang: a chara built to clear a specific race/section |
| dna_sleep, dna_gauss | Randomized delay functions (anti-pattern detection) |
