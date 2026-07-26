"""Grand Live scenario overlay on the stable URA decision engine."""

import math

from career_bot.grand_live import select_lesson_pick
from career_bot.grand_live_data import load_default_square_reference
from career_bot.scenarios.base import Decision
from career_bot.scenarios.ura import UraStrategy


class GrandLiveStrategy(UraStrategy):
    scenario_id = 3
    display_name = "Grand Live"
    api_prefix = "single_mode_live"
    allowed_playing_states = frozenset({1, 2, 3, 4, 5, 10})
    calls_race_reward_on_resume = False
    PS5_POLL_LIMIT = 3

    def __init__(self, race_planner=None, square_reference=None):
        super().__init__(race_planner)
        self.square_reference = (
            square_reference
            if square_reference is not None
            else load_default_square_reference()
        )
        self._live_cmd_map = {}
        self._ps5_turn = None
        self._ps5_polls = 0
        self._performed_live_turns = set()

    def _ensure_mcts(self, preset):
        """The URA simulator does not model performances, songs, or lives."""
        return None

    @staticmethod
    def _command_key(command):
        return (
            int((command or {}).get("command_type") or 0),
            int((command or {}).get("command_id") or 0),
        )

    @staticmethod
    def _partner_id(partner):
        if isinstance(partner, dict):
            for key in ("partner_id", "chara_id", "target_id"):
                if partner.get(key) is not None:
                    try:
                        return int(partner[key])
                    except (TypeError, ValueError):
                        return 0
            return 0
        try:
            return int(partner)
        except (TypeError, ValueError):
            return 0

    def _state_for_ura(self, state, *, playing_state=None):
        """Copy only the command path that Grand Live must sanitize."""
        result = dict(state or {})
        data = dict(result.get("data") or {})
        result["data"] = data

        chara = dict(data.get("chara_info") or {})
        if playing_state is not None:
            chara["playing_state"] = int(playing_state)
        data["chara_info"] = chara

        home = dict(data.get("home_info") or {})
        commands = []
        for raw in home.get("command_info_array") or []:
            command = dict(raw)
            if int(command.get("command_type") or 0) == 1:
                command["training_partner_array"] = [
                    partner
                    for partner in command.get("training_partner_array") or []
                    if self._partner_id(partner) < 1000
                ]
            commands.append(command)
        home["command_info_array"] = commands
        data["home_info"] = home
        return result

    def _poll_state_five(self, turn):
        if self._ps5_turn != turn:
            self._ps5_turn = turn
            self._ps5_polls = 0
        if self._ps5_polls >= self.PS5_POLL_LIMIT:
            return False
        self._ps5_polls += 1
        return True

    def _reset_state_five(self):
        self._ps5_turn = None
        self._ps5_polls = 0

    def mark_live_performed(self, turn):
        self._performed_live_turns.add(int(turn))

    def next_decision(self, state, preset):
        data = (state or {}).get("data") or {}
        chara = data.get("chara_info") or {}
        turn = int(chara.get("turn") or 0)
        playing_state = int(chara.get("playing_state") or 0)
        live_data = data.get("live_data_set") or {}
        self._live_cmd_map = {
            self._command_key(command): command
            for command in live_data.get("command_info_array") or []
            if isinstance(command, dict)
        }

        if (
            "single_mode_finish_common" in data
            or int(chara.get("state") or 0) == 3
        ):
            return super().next_decision(self._state_for_ura(state), preset)

        if data.get("unchecked_event_array"):
            return super().next_decision(self._state_for_ura(state), preset)

        if playing_state == 5:
            if self._poll_state_five(turn):
                return Decision(
                    "state_poll",
                    {"current_turn": turn},
                    "Grand Live post-action settle",
                )
            return super().next_decision(
                self._state_for_ura(state, playing_state=1),
                preset,
            )
        self._reset_state_five()

        clean_lesson_screen = (
            playing_state in {1, 10}
            and not data.get("race_start_info")
        )
        if clean_lesson_screen:
            pick = select_lesson_pick(live_data, self.square_reference)
            if pick:
                return Decision(
                    "lessons",
                    {
                        "current_turn": turn,
                        "square_id": pick["square_id"],
                    },
                    f"master lesson {pick['square_id']}",
                )

        if playing_state == 10:
            if turn in self._performed_live_turns:
                return Decision(
                    "state_poll",
                    {"current_turn": turn},
                    "Grand Live concert submitted; refresh state",
                )
            return Decision(
                "live_perform",
                {"current_turn": turn},
                "perform Grand Live concert",
            )

        return super().next_decision(self._state_for_ura(state), preset)

    @staticmethod
    def _positive_gain(command):
        return float(UraStrategy._training_gain(command or {}))

    @staticmethod
    def _performance_gain(command):
        rows = (
            (command or {}).get("performance_value_array")
            or (command or {}).get("performance_gain_array")
            or []
        )
        total = 0.0
        if isinstance(rows, dict):
            rows = rows.values()
        for row in rows:
            if isinstance(row, dict):
                value = row.get(
                    "value",
                    row.get("performance_value", row.get("amount", 0)),
                )
            else:
                value = row
            try:
                total += max(0.0, float(value or 0))
            except (TypeError, ValueError):
                continue
        if total == 0:
            try:
                total = max(
                    0.0,
                    float((command or {}).get("performance_gain") or 0),
                )
            except (TypeError, ValueError):
                total = 0.0
        return total

    @staticmethod
    def _training_weight(preset):
        try:
            value = float(
                (preset or {}).get("performance_training_weight", 0.6)
            )
        except (TypeError, ValueError):
            return 0.6
        if not math.isfinite(value) or value < 0:
            return 0.6
        return value

    def _training_score_bonus(self, cmd, chara, preset, turn):
        live_command = self._live_cmd_map.get(self._command_key(cmd)) or {}
        supplemental = max(
            0.0,
            self._positive_gain(live_command) - self._positive_gain(cmd),
        )
        performance = self._performance_gain(live_command)
        weight = self._training_weight(preset)
        bonus = (supplemental + performance) * weight

        reasons = []
        if supplemental:
            reasons.append(f"Grand Live supplemental +{supplemental:g}")
        if performance:
            reasons.append(f"performance +{performance:g} × {weight:g}")
        return bonus, reasons, {
            "live_supplemental_gain": round(supplemental, 3),
            "live_performance_gain": round(performance, 3),
            "live_training_weight": round(weight, 3),
            "live_bonus": round(bonus, 3),
        }
