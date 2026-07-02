"""Simulator interface for MCTS."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from career_bot.mcts.core.state import Action, GameState


class SimulatorBase(ABC):
    enabled: bool = True

    @abstractmethod
    def simulate_action(self, state: GameState, action: Action, rng) -> GameState:
        """Apply action."""

    @abstractmethod
    def generate_actions(self, state: GameState) -> tuple[Action, ...]:
        """Generate legal actions."""

    @abstractmethod
    def is_terminal(self, state: GameState) -> bool:
        """Terminal career state?"""

    @abstractmethod
    def evaluate(self, state: GameState, preset: dict[str, Any]) -> float:
        """Score state."""
