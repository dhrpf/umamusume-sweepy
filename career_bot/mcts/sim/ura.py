"""URA forward simulator for MCTS."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from typing import Any

from career_bot.mcts.core.config import MCTSConfig
from career_bot.mcts.core.state import Action, GameState
from career_bot.mcts.sim.base import SimulatorBase

NORMAL_COMMANDS = [101, 102, 103, 105, 106]
CAMP_COMMANDS = [601, 602, 603, 604, 605]
DEFAULT_FAILURE_CURVE = [[1.0, 0.00], [0.7, 0.05], [0.5, 0.15], [0.3, 0.30], [0.1, 0.50]]


class UraSimulator(SimulatorBase):
    def __init__(self, scenario_id: int = 1, params_path: str | None = None, config: MCTSConfig | None = None):
        self.scenario_id = scenario_id
        self.config = config or MCTSConfig()
        self.params_path = params_path or str(Path(__file__).with_name("params.json"))
        self.params: dict[str, Any] = {}
        self.enabled = False
        self.confidence = "disabled"
        self.warning: str | None = None
        self.load_params(self.params_path)

    def load_params(self, path: str | None = None) -> dict[str, Any]:
        try:
            with open(path or self.params_path, "r", encoding="utf-8") as f:
                params = json.load(f)
        except Exception as exc:
            self.params = {}
            self.enabled = False
            self.confidence = "disabled"
            self.warning = f"params unavailable: {exc}"
            return self.params
        if int(params.get("scenario_id", self.scenario_id)) != int(self.scenario_id):
            self.params = params
            self.enabled = False
            self.confidence = "disabled"
            self.warning = "scenario_id mismatch"
            return self.params
        n = int(params.get("calibrated_from") or 0)
        self.params = params
        if n < 10:
            self.enabled = False
            self.confidence = "disabled"
            self.warning = "insufficient calibration logs"
        elif n < 20:
            self.enabled = True
            self.confidence = "warning"
            self.warning = "low calibration sample"
        else:
            self.enabled = True
            self.confidence = "high"
            self.warning = None
        return self.params

    def generate_actions(self, state: GameState) -> tuple[Action, ...]:
        commands = CAMP_COMMANDS if _is_camp(state.turn) else NORMAL_COMMANDS
        actions = []
        for idx, command_id in enumerate(commands):
            level = self._level_for(command_id, idx, state)
            gains = self._training_gains(command_id, level)
            cost = float((self.params.get("vital_cost") or {}).get(str(command_id), 20))
            actions.append(Action(
                "train",
                idx,
                gains,
                -abs(cost),
                self.failure_rate_for_vital_ratio(_vital_ratio(state)),
                0,
                1,
                command_id,
                0,
            ))
        actions.append(Action("rest", 0, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0), float(self.params.get("rest_recovery") or 45), 0.0, 0, 7, 701, 0))
        actions.append(Action("outing", 0, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0), float(self.params.get("outing_recovery") or 35), 0.0, 0, 3, 301, 0))
        return tuple(actions)

    def simulate_action(self, state: GameState, action: Action, rng) -> GameState:
        if self.config.use_expected_value and action.action_type == "train":
            p_fail = action.failure_rate
            stats = [state.speed, state.stamina, state.power, state.guts, state.wiz]
            for i in range(5):
                stats[i] += action.stat_gains[i] * (1.0 - p_fail)
            sp = state.skill_points + action.stat_gains[5] * (1.0 - p_fail)
            vital = _clamp(state.vital + action.vital_delta, 0, state.max_vital)
            counts = _inc_count(state.training_counts, action.index) if action.action_type == "train" else state.training_counts
            return replace(state, turn=state.turn + 1, speed=stats[0], stamina=stats[1], power=stats[2], guts=stats[3], wiz=stats[4], skill_points=sp, vital=vital, training_counts=counts, available_actions=())

        failed = action.action_type == "train" and rng.random() < action.failure_rate
        if failed:
            vital = _clamp(state.vital + action.vital_delta - 5, 0, state.max_vital)
            counts = _inc_count(state.training_counts, action.index)
            return replace(state, turn=state.turn + 1, speed=max(0.0, state.speed - 2.0), vital=vital, training_counts=counts, available_actions=())

        stats = [state.speed, state.stamina, state.power, state.guts, state.wiz]
        if action.action_type == "train":
            for i in range(5):
                stats[i] += action.stat_gains[i]
            sp = state.skill_points + action.stat_gains[5]
            counts = _inc_count(state.training_counts, action.index)
            motivation = state.motivation
        elif action.action_type == "outing":
            sp = state.skill_points
            counts = state.training_counts
            chance = float(self.params.get("outing_motivation_chance") or 0.0)
            motivation = min(5, state.motivation + (1 if rng.random() < chance else 0))
        else:
            sp = state.skill_points
            counts = state.training_counts
            motivation = state.motivation
        vital = _clamp(state.vital + action.vital_delta, 0, state.max_vital)
        return replace(state, turn=state.turn + 1, speed=stats[0], stamina=stats[1], power=stats[2], guts=stats[3], wiz=stats[4], skill_points=sp, vital=vital, motivation=motivation, training_counts=counts, available_actions=())

    def is_terminal(self, state: GameState) -> bool:
        return state.turn >= 78

    def evaluate(self, state: GameState, preset: dict[str, Any]) -> float:
        targets = list((preset or {}).get("expect_attribute") or [900, 450, 650, 250, 650])
        targets = [float(t or 1) for t in targets[:5]]
        while len(targets) < 5:
            targets.append(1.0)
        stats = [state.speed, state.stamina, state.power, state.guts, state.wiz]
        total_target = max(sum(targets), 1.0)
        score = 0.0
        for actual, target in zip(stats, targets):
            if actual >= target:
                score += target + (actual - target) * self.config.overshoot_penalty
            else:
                score += actual * ((actual / target) ** max(self.config.shortfall_exponent - 1.0, 0.0))
        stat_score = score / total_target
        sp_bonus = min(state.skill_points / 2000.0, 0.1)
        fan_bonus = min(state.fans / 500000.0, 0.05)
        return stat_score + sp_bonus + fan_bonus

    def failure_rate_for_vital_ratio(self, ratio: float) -> float:
        curve = self.params.get("failure_curve") or DEFAULT_FAILURE_CURVE
        pts = sorted([(float(x), float(y)) for x, y in curve], reverse=True)
        if ratio >= pts[0][0]:
            return pts[0][1]
        if ratio <= pts[-1][0]:
            return pts[-1][1]
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            if x1 >= ratio >= x2:
                span = x1 - x2
                t = (x1 - ratio) / span if span else 0.0
                return y1 + (y2 - y1) * t
        return pts[-1][1]

    def _level_for(self, command_id: int, idx: int, state: GameState) -> int:
        return state.training_levels[idx] if idx < len(state.training_levels) else 1

    def _training_gains(self, command_id: int, level: int) -> tuple[float, float, float, float, float, float]:
        table = self.params.get("training_gains") or {}
        by_level = table.get(str(command_id)) or table.get(str(_normal_command(command_id))) or {}
        raw = by_level.get(str(level)) or by_level.get("1") or [0, 0, 0, 0, 0, 0]
        vals = [float(x) for x in list(raw)[:6]]
        while len(vals) < 6:
            vals.append(0.0)
        return (vals[0], vals[1], vals[2], vals[3], vals[4], vals[5])


def _normal_command(command_id: int) -> int:
    if command_id in CAMP_COMMANDS:
        return NORMAL_COMMANDS[CAMP_COMMANDS.index(command_id)]
    return command_id


def _is_camp(turn: int) -> bool:
    return 37 <= turn <= 40 or 61 <= turn <= 64


def _vital_ratio(state: GameState) -> float:
    return state.vital / state.max_vital if state.max_vital > 0 else 1.0


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _inc_count(counts: tuple[int, ...], idx: int) -> tuple[int, ...]:
    vals = list(counts or (0, 0, 0, 0, 0))
    while len(vals) < 5:
        vals.append(0)
    if 0 <= idx < len(vals):
        vals[idx] += 1
    return tuple(vals)
