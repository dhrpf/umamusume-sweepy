"""Unity Cup (Aoharu) scenario strategy.

This strategy reuses the URA decision engine for normal turns, adds the
scenario-specific team-race states, and biases training toward Unity Training
members and Spirit Bursts exposed through ``team_data_set``.
"""

from career_bot.scenarios.base import Decision
from career_bot.scenarios.ura import UraStrategy


class UnityStrategy(UraStrategy):
    scenario_id = 2
    display_name = "Unity Cup"
    api_prefix = "single_mode_team"
    allowed_playing_states = frozenset({1, 2, 3, 4, 5, 7, 8, 9})
    TEAM_RACE_PHASES = {7: "full", 8: "end", 9: "out"}

    def __init__(self, race_planner=None):
        super().__init__(race_planner)
        self._unity_cmd_map = {}

    def _ensure_mcts(self, preset):
        """The current URA simulator does not model Unity mechanics."""
        return None

    def next_decision(self, state, preset):
        data = state.get("data") or {}
        chara = data.get("chara_info") or {}
        team_commands = (data.get("team_data_set") or {}).get("command_info_array") or []
        self._unity_cmd_map = {
            (int(cmd.get("command_type") or 0), int(cmd.get("command_id") or 0)): cmd
            for cmd in team_commands
        }

        if data.get("unchecked_event_array") or "single_mode_finish_common" in data:
            return super().next_decision(state, preset)

        playing_state = int(chara.get("playing_state") or 0)
        phase = self.TEAM_RACE_PHASES.get(playing_state)
        if phase:
            turn = int(chara.get("turn") or 0)
            return Decision(
                "team_race",
                {
                    "current_turn": turn,
                    "phase": phase,
                    "_strategy": self,
                },
                f"unity cup team race ({phase})",
            )

        return super().next_decision(state, preset)

    def _training_score_bonus(self, cmd, chara, preset, turn):
        team_cmd = self._unity_cmd_map.get(
            (
                int(cmd.get("command_type") or 0),
                int(cmd.get("command_id") or 0),
            )
        ) or {}
        cfg = (preset or {}).get("unity_config") or {}
        unity_weight = float(cfg.get("unity_training_weight", 0.6))
        burst_weight = float(cfg.get("spirit_burst_weight", 5.0))

        guide_members = len(team_cmd.get("guide_event_partner_array") or [])
        soul_members = len(team_cmd.get("soul_event_partner_array") or [])
        spirit_bursts = len(team_cmd.get("sp_soul_event_partner_array") or [])
        unity_members = guide_members + soul_members
        bonus = unity_members * unity_weight + spirit_bursts * burst_weight

        reasons = []
        if unity_members:
            reasons.append(
                f"Unity Training {unity_members} × {unity_weight:g}"
            )
        if spirit_bursts:
            reasons.append(
                f"Spirit Burst {spirit_bursts} × {burst_weight:g}"
            )

        return bonus, reasons, {
            "unity_members": unity_members,
            "unity_spirit_bursts": spirit_bursts,
            "unity_bonus": round(bonus, 3),
        }
