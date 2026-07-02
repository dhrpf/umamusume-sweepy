"""Minimal MCTS planner."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import random
import time
from typing import Any

from career_bot.mcts.core.config import MCTSConfig
from career_bot.mcts.core.state import Action, GameState
from career_bot.mcts.sim.base import SimulatorBase


@dataclass
class SearchResult:
    action: Action | None
    score: float
    simulations: int
    visits: dict[int, int] = field(default_factory=dict)


class MCTSPlanner:
    def __init__(self, simulator: SimulatorBase, config: MCTSConfig | None = None, preset: dict[str, Any] | None = None):
        self.sim = simulator
        self.config = config or MCTSConfig()
        self.preset = preset or {}
        self.rng = random.Random(self.config.rng_seed)

    def search(self, root: GameState) -> SearchResult:
        actions = root.available_actions or self.sim.generate_actions(root)
        if not actions:
            return SearchResult(None, self.sim.evaluate(root, self.preset), 0)

        deadline = time.monotonic() + max(0.0, self.config.time_budget_sec)
        visits = [0] * len(actions)
        totals = [0.0] * len(actions)
        sims = 0

        while sims < self.config.max_simulations and (self.config.time_budget_sec <= 0 or time.monotonic() < deadline):
            idx = self._select(visits, totals)
            child = self.sim.simulate_action(root, actions[idx], self.rng)
            value = self._rollout(child)
            visits[idx] += 1
            totals[idx] += value
            sims += 1

        best_idx = max(range(len(actions)), key=lambda i: (totals[i] / visits[i]) if visits[i] else float("-inf"))
        best_score = (totals[best_idx] / visits[best_idx]) if visits[best_idx] else float("-inf")
        return SearchResult(actions[best_idx], best_score, sims, {i: v for i, v in enumerate(visits) if v})

    def _select(self, visits: list[int], totals: list[float]) -> int:
        for i, v in enumerate(visits):
            if v == 0:
                return i
        total_visits = sum(visits)
        log_total = math.log(max(total_visits, 1))
        return max(
            range(len(visits)),
            key=lambda i: totals[i] / visits[i] + self.config.explore_weight * math.sqrt(log_total / visits[i]),
        )

    def _rollout(self, state: GameState) -> float:
        depth = 0
        current = state
        while depth < self.config.rollout_depth and not self.sim.is_terminal(current):
            actions = self.sim.generate_actions(current)
            if not actions:
                break
            action = self._rollout_policy(current, actions)
            current = self.sim.simulate_action(current, action, self.rng)
            depth += 1
        return self.sim.evaluate(current, self.preset)

    def _rollout_policy(self, state: GameState, actions: tuple[Action, ...]) -> Action:
        ratio = state.vital / state.max_vital if state.max_vital else 1.0
        if ratio < self.config.rest_vital_ratio:
            for action in actions:
                if action.action_type == "rest":
                    return action
        return max(actions, key=lambda action: self._action_value(state, action))

    def _action_value(self, state: GameState, action: Action) -> float:
        if action.action_type == "rest":
            missing = max(state.max_vital - state.vital, 0.0)
            return min(action.vital_delta, missing) * 0.01
        if action.action_type == "outing":
            missing = max(state.max_vital - state.vital, 0.0)
            return min(action.vital_delta, missing) * 0.006 + max(0, 5 - state.motivation) * 0.05
        targets = [float(x or 1.0) for x in list((self.preset or {}).get("expect_attribute") or [900, 450, 650, 250, 650])]
        while len(targets) < 5:
            targets.append(1.0)
        stats = [state.speed, state.stamina, state.power, state.guts, state.wiz]
        value = 0.0
        for i, gain in enumerate(action.stat_gains[:5]):
            deficit = max(targets[i] - stats[i], 0.0)
            value += gain * (1.0 + deficit / max(targets[i], 1.0))
        value += action.stat_gains[5] * 0.2
        value += action.partner_count * 2.0
        value -= action.failure_rate * 100.0
        if state.vital + action.vital_delta < 0:
            value -= 1000.0
        return value
