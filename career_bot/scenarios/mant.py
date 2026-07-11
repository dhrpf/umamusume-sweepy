"""Mant (Trackblazer) strategy for Uma Musume career automation.

Ported from EdenUmaBots/Umamusume-Icarus — the reference Trackblazer
implementation: training scorer + per-distance targets + milestone phasing +
energy / consecutive-race / charm-aware / Sirius-Throne group-outing layers.
"""
import json
import os
from pathlib import Path

from career_bot.events import EventManager
from career_bot.trackblazer_guide import load_guide
from career_bot import trackblazer_rules as tb_rules
from career_bot.scenarios.base import Decision, ScenarioStrategy

TRAINING_COMMANDS = {101: 0, 105: 1, 102: 2, 103: 3, 106: 4, 601: 0, 602: 1, 603: 2, 604: 3, 605: 4}
DECK_PARTNERS = {1, 2, 3, 4, 5, 6}

# Energy-rescue (ported from UmaAuto's MANT scenario): owned consumables that can
# lift vitality enough to run a strong training instead of wasting the turn on a
# pure rest.
ENERGY_ITEM_VALUES = {2001: 20, 2002: 40, 2003: 65, 2101: 100}
GOOD_LUCK_CHARM_ID = 10001

# ── Team Sirius + Heirs to the Throne (Group support cards) ─────────────────
TEAM_SIRIUS_SUPPORT_ID = 30081
THRONE_SUPPORT_ID = 30067
SIRIUS_THRONE_GROUP_IDS = frozenset({TEAM_SIRIUS_SUPPORT_ID, THRONE_SUPPORT_ID})
GROUP_OUTING_COMMAND_ID = 390
JUNIOR_FOCUS_LAST_TURN = 11
GROUP_CARD_OUTING_MAX = 2
CARD_SIGNATURE_CHARA = {TEAM_SIRIUS_SUPPORT_ID: 1001, THRONE_SUPPORT_ID: 1017}
RECREATION_BLACKOUT_TURNS = frozenset({36, 37, 38, 39, 40, 60, 61, 62, 63, 64})
RACE_VALUE_CAMP_TURNS = frozenset({37, 38, 39, 40, 61, 62, 63, 64})
SIRIUS_THRONE_RECREATION_SCHEDULE = {
    18: (1002, TEAM_SIRIUS_SUPPORT_ID, "Silence Suzuka"),
    22: (1016, TEAM_SIRIUS_SUPPORT_ID, "Narita Brian"),
    26: (1017, THRONE_SUPPORT_ID, "Symboli Rudolf"),
    28: (1030, TEAM_SIRIUS_SUPPORT_ID, "Rice Shower"),
    32: (1001, TEAM_SIRIUS_SUPPORT_ID, "Special Week"),
    35: (1003, THRONE_SUPPORT_ID, "Tokai Teio"),
    43: (1013, TEAM_SIRIUS_SUPPORT_ID, "Mejiro McQueen"),
    47: (1073, THRONE_SUPPORT_ID, "Tsurumaru Tsuyoshi"),
    51: (None, THRONE_SUPPORT_ID, "Throne card step 1"),
    55: (1035, TEAM_SIRIUS_SUPPORT_ID, "Winning Ticket"),
    58: (None, TEAM_SIRIUS_SUPPORT_ID, "Sirius card step 1"),
    59: (None, THRONE_SUPPORT_ID, "Throne card step 2"),
}
BAD_EFFECT_NAMES = {
    1: "Night Owl",
    2: "Slacker",
    3: "Skin Outbreak",
    4: "Slow Metabolism",
    5: "Migraine",
    6: "Practice Poor",
}


class MantStrategy(ScenarioStrategy):
    scenario_id = 4

    def __init__(self, race_planner=None):
        self.race_planner = race_planner
        self.event_manager = None
        if self.race_planner and self.race_planner.base_dir:
            self.event_manager = EventManager(self.race_planner.base_dir)
        self.current_preset = {}
        self.last_training_scores = []
        self.last_decision_trace = {}
        self.trackblazer_guide = load_guide(self.race_planner.base_dir) if self.race_planner and self.race_planner.base_dir else {}
        self.training_effects = self._load_training_effects()
        self._scheduled_outing_blocked = False
        self._card_outing_blocked = False
        self._pending_outing_is_card = False

    def _load_training_effects(self):
        if not self.race_planner or not self.race_planner.base_dir:
            return {}
        path = Path(self.race_planner.base_dir) / "data" / "training_effects_core.json"
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        rows = payload.get("training_effects") if isinstance(payload, dict) else payload
        out = {}
        for row in rows or []:
            try:
                key = (
                    int(row.get("scenario_id") or self.scenario_id),
                    int(row.get("command_id") or 0),
                    int(row.get("level") or 0),
                    int(row.get("result_state") or 0),
                )
            except Exception:
                continue
            out[key] = row
        return out

    def _official_command_id(self, command):
        command_id = int((command or {}).get("command_id") or 0)
        if command_id in (601, 602, 603, 604, 605):
            idx = TRAINING_COMMANDS.get(command_id)
            return [101, 105, 102, 103, 106][idx] if idx is not None else command_id
        return command_id

    def _official_training_baseline(self, command):
        if not self.training_effects or not command:
            return None
        command_id = self._official_command_id(command)
        level = max(1, self._training_level(command))
        key = (int(self.scenario_id), command_id, level, 2)
        row = self.training_effects.get(key)
        if row:
            return row
        for (scenario_id, cid, lvl, _state), value in self.training_effects.items():
            if scenario_id == int(self.scenario_id) and cid == command_id and lvl == level:
                return value
        return None

    def _official_training_effect_items(self, command):
        row = self._official_training_baseline(command)
        if not row:
            return []
        return [
            {"target_type": int(item.get("target_type") or 0), "value": int(item.get("effect_value") or 0), "_source": "master_training_effect"}
            for item in row.get("effects") or []
        ]

    def _stale_completed_race_state(self, data, chara, race):
        if not race or not race.get("program_id"):
            return False
        try:
            program_id = int(race.get("program_id") or chara.get("race_program_id") or 0)
            turn = int(chara.get("turn") or 0)
        except Exception:
            return False
        if not program_id or not turn:
            return False
        history = data.get("race_history") or []
        already_recorded = any(
            int((row or {}).get("program_id") or 0) == program_id and int((row or {}).get("turn") or 0) == turn
            for row in history
        )
        commands = ((data.get("home_info") or {}).get("command_info_array") or [])
        has_enabled_home_command = any(int((cmd or {}).get("is_enable") or 0) for cmd in commands)
        return already_recorded and has_enabled_home_command

    def next_decision(self, state, preset):
        self.current_preset = preset or {}
        data = state.get("data") or {}
        chara = data.get("chara_info") or {}
        self.current_chara = chara
        try:
            self._dump_recreation_debug(data, chara, preset or {})
        except Exception:
            pass
        home = data.get("home_info") or {}
        if "single_mode_finish_common" in data:
            return Decision("finish", {"current_turn": chara["turn"]}, "finished")
        events = data.get("unchecked_event_array") or []
        if events:
            event = events[0] or {}
            choice = self._choice(event)
            payload = {"event_id": event.get("event_id"), "chara_id": event.get("chara_id", 0), "choice_number": choice, "current_turn": chara["turn"]}
            if choice is None:
                payload = {"event_id": event.get("event_id"), "_event": event, "_current_turn": chara["turn"]}
            return Decision("event", payload, "event")
        if chara.get("state") == 3:
            return Decision("finish", {"current_turn": chara["turn"]}, "ready to finish")
        race = data.get("race_start_info")
        playing_state = (chara.get("playing_state") or 0)
        if self._stale_completed_race_state(data, chara, race):
            playing_state = 1
            race = None
        if playing_state == 3:
            return Decision("race_progress", {"current_turn": chara["turn"], "phase": "start", "race_start_info": race, "chara_info": chara}, "resume race start")
        if playing_state == 5:
            return Decision("finish", {"current_turn": chara["turn"]}, "goal failed / career end")
        if race and race.get("program_id") and playing_state in (2, 4):
            return Decision("race_progress", {"current_turn": chara["turn"], "phase": "start", "race_start_info": race, "chara_info": chara}, "race start")
        return self._trackblazer_core().decide(state, preset)

    def _trackblazer_core(self):
        core = getattr(self, "_trackblazer", None)
        if core is None:
            from career_bot.scenarios.mant_trackblazer import MantTrackblazerCore
            core = self._trackblazer = MantTrackblazerCore(self)
        return core

    def _choice(self, event):
        choices = ((event.get("event_contents_info") or {}).get("choice_array") or [])
        if not choices:
            return 0
        if len(choices) > 1:
            return None
        return 0

    def _rainbow_partner_count(self, command, chara):
        if not command:
            return 0
        for key in ("is_rainbow", "is_friendship_training", "friendship_training", "is_special_training"):
            if command.get(key):
                return 1
        bonds = self._bond_map(chara or {})
        count = 0
        for partner_id in command.get("training_partner_array") or []:
            try:
                partner_id = int(partner_id)
            except Exception:
                continue
            if partner_id in DECK_PARTNERS and int(bonds.get(partner_id, 0) or 0) >= 80:
                count += 1
        return count

    def _rest_command(self, commands):
        for cmd in commands:
            if cmd.get("command_type") == 7 and cmd.get("command_id") == 701:
                return cmd
        return None

    def _recreation_command(self, commands):
        # Skip the group-outing command (390): it only ever leaves the strategy via
        # _scheduled_recreation / _free_group_outing with a real select_id, never bare.
        for cmd in commands:
            if cmd.get("command_type") == 3 and int(cmd.get("command_id") or 0) != GROUP_OUTING_COMMAND_ID:
                return cmd
        return None

    def _deck_has_group_cards(self, chara):
        ids = {int(c.get("support_card_id") or 0) for c in (chara.get("support_card_array") or [])}
        return bool(ids & SIRIUS_THRONE_GROUP_IDS)

    def _strategy_mode(self, chara, preset):
        cfg = ((preset or {}).get("mant_config") or {})
        mode = cfg.get("sirius_throne_strategy")
        if mode in ("scheduled", "free", "off"):
            return mode
        return "scheduled" if self._deck_has_group_cards(chara) else "off"

    def _strategy_mode_is(self, chara, preset, want):
        return self._strategy_mode(chara, preset) == want

    def _schedule_active(self, chara, preset):
        return self._strategy_mode(chara, preset) == "scheduled"

    def _char_outing_state(self, chara, chara_id):
        for row in chara.get("evaluation_info_array") or []:
            for g in row.get("group_outing_info_array") or []:
                if int(g.get("chara_id") or 0) == chara_id:
                    return int(g.get("is_outing") or 0), int(g.get("story_step") or 0)
        return 0, 0

    def _card_row_state(self, chara, support_id):
        slot = next((int(c.get("position") or 0) for c in chara.get("support_card_array") or []
                     if int(c.get("support_card_id") or 0) == support_id), None)
        if slot is None:
            return 0, 0
        row = next((r for r in chara.get("evaluation_info_array") or []
                    if int(r.get("target_id") or 0) == slot), None)
        if not row:
            return 0, 0
        return int(row.get("is_outing") or 0), int(row.get("story_step") or 0)

    def _group_card_slots(self, chara):
        return [int(c.get("position") or 0) for c in chara.get("support_card_array") or []
                if int(c.get("support_card_id") or 0) in SIRIUS_THRONE_GROUP_IDS]

    def _get_group_outing_cmd(self, enabled):
        return next((c for c in enabled if c.get("command_type") == 3
                     and int(c.get("command_id") or 0) == GROUP_OUTING_COMMAND_ID), None)

    def _build_outing_command(self, outing_cmd, select_id):
        chosen = dict(outing_cmd)
        chosen["select_id"] = int(select_id)
        return chosen

    def _bondable_count(self, command, chara):
        bonds = self._bond_map(chara)
        count = 0
        for partner_id in command.get("training_partner_array") or []:
            try:
                pid = int(partner_id)
            except (TypeError, ValueError):
                continue
            if pid in DECK_PARTNERS and int(bonds.get(pid, 0) or 0) < 80:
                count += 1
        return count

    def _outing_plan(self):
        plan = []
        card_step_count = {}
        for t in sorted(SIRIUS_THRONE_RECREATION_SCHEDULE):
            chara_id, support_id, _label = SIRIUS_THRONE_RECREATION_SCHEDULE[t]
            if chara_id is not None:
                plan.append({"turn": t, "kind": "char", "support_id": support_id,
                             "chara_id": chara_id, "select_id": chara_id})
            else:
                card_step_count[support_id] = card_step_count.get(support_id, 0) + 1
                plan.append({"turn": t, "kind": "card", "support_id": support_id,
                             "step": card_step_count[support_id],
                             "select_id": CARD_SIGNATURE_CHARA.get(support_id, 0)})
        return plan

    def _scheduled_recreation(self, enabled, turn, chara, preset):
        if getattr(self, "_scheduled_outing_blocked", False):
            return None
        outing_cmd = self._get_group_outing_cmd(enabled)
        if not outing_cmd:
            return None
        if turn in RECREATION_BLACKOUT_TURNS:
            return None
        cfg = ((preset or {}).get("mant_config") or {})
        card_enabled = (cfg.get("sirius_throne_card_outing", True)
                        and not getattr(self, "_card_outing_blocked", False))
        for step in self._outing_plan():
            if step["turn"] > turn:
                break
            if step["kind"] == "char":
                is_outing, story_step = self._char_outing_state(chara, step["chara_id"])
                if story_step >= 1 or is_outing != 1:
                    continue
                self._pending_outing_is_card = False
                return self._build_outing_command(outing_cmd, step["select_id"])
            if not card_enabled:
                continue
            crow_io, crow_ss = self._card_row_state(chara, step["support_id"])
            if crow_ss >= step["step"] or crow_io != 1:
                continue
            if self._char_outing_state(chara, step["select_id"])[1] < 1:
                continue
            self._pending_outing_is_card = True
            return self._build_outing_command(outing_cmd, step["select_id"])
        return None

    def _free_outing_select_id(self, chara):
        for row in chara.get("evaluation_info_array") or []:
            for g in row.get("group_outing_info_array") or []:
                if int(g.get("is_outing") or 0) == 1 and int(g.get("story_step") or 0) < 1:
                    return int(g.get("chara_id") or 0)
        return 0

    def _free_group_outing(self, enabled, turn, chara):
        if getattr(self, "_scheduled_outing_blocked", False):
            return None
        if not self._deck_has_group_cards(chara):
            return None
        if turn in RECREATION_BLACKOUT_TURNS:
            return None
        outing_cmd = self._get_group_outing_cmd(enabled)
        if not outing_cmd:
            return None
        self._pending_outing_is_card = False
        return self._build_outing_command(outing_cmd, self._free_outing_select_id(chara))

    def _dump_recreation_debug(self, data, chara, preset):
        cfg = ((preset or {}).get("mant_config") or {})
        if not cfg.get("dump_recreation_debug", True):
            return
        if not self.race_planner or not getattr(self.race_planner, "base_dir", None):
            return
        if not self._schedule_active(chara, preset):
            return
        home = data.get("home_info") or {}
        rec_cmds = [c for c in (home.get("command_info_array") or []) if c.get("command_type") == 3]
        if not rec_cmds:
            return
        turn = int(chara.get("turn") or 0)
        try:
            out_dir = os.path.join(str(self.race_planner.base_dir), "uma_runtime", "bot_logs")
            os.makedirs(out_dir, exist_ok=True)
            path = os.path.join(out_dir, f"recreation_debug_t{turn}.json")
            payload = {
                "turn": turn,
                "scheduled": SIRIUS_THRONE_RECREATION_SCHEDULE.get(turn),
                "recreation_commands": rec_cmds,
                "support_card_array": chara.get("support_card_array") or [],
                "evaluation_info_array": chara.get("evaluation_info_array") or [],
                "unchecked_event_array": data.get("unchecked_event_array") or [],
            }
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _medic_command(self, commands):
        for cmd in commands:
            if cmd.get("command_type") == 8 and cmd.get("command_id") == 801:
                return cmd
        return None

    def _has_curable_bad_status(self, chara, preset):
        wanted = self._cure_condition_names(preset)
        if not wanted:
            return False
        for effect_id in chara.get("chara_effect_id_array") or []:
            try:
                effect_id = int(effect_id)
            except (TypeError, ValueError):
                continue
            name = BAD_EFFECT_NAMES.get(effect_id)
            if name and self._condition_key(name) in wanted:
                return True
        return False

    def _cure_condition_names(self, preset):
        result = set()
        names = preset.get("cure_asap_conditions") or []
        if isinstance(names, str):
            names = names.split(",")
        for name in names:
            key = self._condition_key(name)
            if key:
                result.add(key)
        return result

    def _condition_key(self, name):
        text = str(name or "").strip()
        if not text or text.startswith("("):
            return ""
        return "".join(ch.lower() for ch in text if ch.isalnum())

    def _failure_allowed(self, command, preset, has_charm=False):
        cfg = ((preset or {}).get("mant_config") or {})
        failure = int((command or {}).get("failure_rate") or 0)
        max_failure = int(cfg.get("maximum_failure_chance") or 20)
        if failure <= max_failure:
            return True
        if has_charm and cfg.get("enable_charm_aware_training", True):
            main_gain = self._command_main_stat_gain(command)
            _cm = cfg.get("charm_min_main_gain")
            charm_min = int(_cm) if _cm is not None else tb_rules.DEFAULT_CHARM_MIN_MAIN_GAIN
            charm_fail_limit = int(cfg.get("charm_failure_admit_limit") or 100)
            if main_gain >= charm_min and failure <= charm_fail_limit:
                return True
        if not cfg.get("enable_risky_training", False):
            return False
        main_gain = self._command_main_stat_gain(command)
        min_gain = int(cfg.get("risky_training_min_stat_gain") or 20)
        risky_max = int(cfg.get("risky_training_max_failure_chance") or 30)
        return main_gain >= min_gain and failure <= risky_max

    def _training_level(self, command):
        for key in ("training_level", "facility_level", "level", "command_level", "training_lv", "facility_lv"):
            try:
                level = int((command or {}).get(key) or 0)
            except Exception:
                level = 0
            if level:
                return max(1, min(5, level))
        return 0

    def _command_stat_gain(self, cmd, sp_weight=0):
        if not cmd:
            return 0
        total = 0
        for item in cmd.get("params_inc_dec_info_array") or []:
            tt = item.get("target_type")
            if tt in [1, 2, 3, 4, 5]:
                total += int(item.get("value") or 0)
            elif (tt == 6 or tt == 30) and sp_weight > 0:
                total += int(item.get("value") or 0) * sp_weight
        if total == 0:
            for field in ["speed", "stamina", "power", "guts", "wiz"]:
                total += int(cmd.get(field) or 0)
            if sp_weight > 0:
                total += int(cmd.get("lp") or cmd.get("skill_point") or 0) * sp_weight
        return total

    def _bond_map(self, chara):
        result = {}
        for row in chara.get("evaluation_info_array") or []:
            result[row.get("target_id", 0)] = row.get("evaluation", 0)
        return result

    def choose_from_event(self, event, current_turn):
        if self.event_manager:
            return self.event_manager.choose(event, self.current_preset, current_turn, getattr(self, "current_chara", None))
        return 1

    def _decision_payload_from_command(self, command, chara):
        command_type = command.get("command_type", 1)
        command_id = command.get("command_id")
        command_group_id = command.get("command_group_id", 0)
        if command_type == 3:
            command_group_id = command_id
            command_id = 0
        return {
            "command_type": command_type,
            "command_id": command_id,
            "command_group_id": command_group_id,
            "select_id": command.get("select_id", 0),
            "current_turn": chara["turn"],
            "current_vital": chara.get("vital", 0),
        }

    def _recent_race_chain_count(self, data, current_turn):
        rows = data.get("action_history") or data.get("turn_history") or []
        if not isinstance(rows, list):
            return 0
        count = 0
        for row in reversed(rows[-10:]):
            if not isinstance(row, dict):
                continue
            try:
                turn = int(row.get("turn") or row.get("current_turn") or 0)
            except Exception:
                continue
            if turn >= int(current_turn or 0):
                continue
            action = str(row.get("action") or row.get("command") or row.get("type") or "").lower()
            if "race" in action:
                count += 1
            elif action:
                break
        return count

    def _owned_item_count(self, data, item_id):
        try:
            item_id = int(item_id or 0)
        except Exception:
            return 0
        total = 0
        free = (data or {}).get("free_data_set") or {}
        for row in free.get("user_item_info_array") or []:
            try:
                if int(row.get("item_id") or 0) == item_id:
                    total += int(row.get("num") or row.get("current_num") or row.get("item_num") or 0)
            except Exception:
                continue
        return total

    def _rescue_energy_value(self, data, vital, rest_threshold, margin):
        target = rest_threshold + margin
        owned = {}
        free = (data or {}).get("free_data_set") or {}
        for row in free.get("user_item_info_array") or []:
            try:
                iid = int(row.get("item_id") or 0)
            except Exception:
                continue
            if iid in ENERGY_ITEM_VALUES:
                owned[iid] = owned.get(iid, 0) + int(row.get("num") or row.get("current_num") or row.get("item_num") or 0)
        best = None
        for iid, qty in owned.items():
            if qty > 0 and vital + ENERGY_ITEM_VALUES[iid] > target:
                if best is None or ENERGY_ITEM_VALUES[iid] < ENERGY_ITEM_VALUES[best]:
                    best = iid
        return ENERGY_ITEM_VALUES[best] if best is not None else None

    def _can_rescue_training(self, data, chara, preset, best, best_score, vital, failure, rest_threshold):
        cfg = ((preset or {}).get("mant_config") or {})
        if not cfg.get("rescue_good_training", True):
            return False
        if best is None or int(best.get("command_type") or 0) != 1:
            return False
        if best_score is None or best_score <= 0:
            return False
        if vital < int(cfg.get("rescue_min_vital") or 25):
            return False
        rainbow = self._rainbow_partner_count(best, chara)
        camp_all_out = (
            cfg.get("summer_all_out", True)
            and self._deck_has_group_cards(chara)
            and int(chara.get("turn") or 0) in RACE_VALUE_CAMP_TURNS
            and self._strategy_mode(chara, preset) == "scheduled"
        )
        strong = best_score >= float(cfg.get("rescue_score_threshold") or 0.55) or camp_all_out
        if rainbow < 1 and not strong:
            return False
        margin = int(cfg.get("rescue_vital_margin") or 12)
        energy_val = self._rescue_energy_value(data, vital, rest_threshold, margin)
        has_charm = self._owned_item_count(data, GOOD_LUCK_CHARM_ID) > 0
        hard_cap = int(cfg.get("rescue_failure_hard_cap") or 50)
        if failure >= hard_cap:
            return has_charm
        if vital <= rest_threshold:
            return energy_val is not None
        if failure >= 35:
            return has_charm or energy_val is not None
        return False

    def _command_main_stat_gain(self, cmd):
        if not cmd:
            return 0
        main_target_by_command = {101: 1, 601: 1, 105: 2, 602: 2, 102: 3, 603: 3, 103: 4, 604: 4, 106: 5, 605: 5}
        main_target = main_target_by_command.get(int(cmd.get("command_id") or 0))
        if main_target:
            for item in (cmd.get("params_inc_dec_info_array") or self._official_training_effect_items(cmd)):
                try:
                    if int(item.get("target_type") or 0) == main_target:
                        return int(item.get("value") or 0)
                except Exception:
                    continue
        return int(self._command_stat_gain(cmd))

    def explain_decision(self, state, preset, decision):
        data = state.get("data") or {}
        chara = data.get("chara_info") or {}
        turn = int(chara.get("turn") or 0)
        scored = list(self.last_training_scores) if self.last_training_scores else []
        trace = {
            "turn": turn,
            "action": decision.action,
            "reason": decision.reason,
            "energy": int(chara.get("vital") or 0),
            "mood": int(chara.get("motivation") or 0),
            "training_candidates": scored[:5],
        }
        if self.event_manager and getattr(self.event_manager, "last_choice_trace", None):
            trace["last_event_choice"] = self.event_manager.last_choice_trace
        self.last_decision_trace = trace
        return trace
