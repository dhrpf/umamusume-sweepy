"""MCTS planner configuration."""

from __future__ import annotations

from dataclasses import dataclass, fields


@dataclass(frozen=True)
class MCTSConfig:
    time_budget_sec: float = 5.0
    max_simulations: int = 1000
    explore_weight: float = 1.41
    widening_alpha: float = 0.5
    rollout_depth: int = 15
    rest_vital_ratio: float = 0.3
    overshoot_penalty: float = 0.3
    shortfall_exponent: float = 2.0
    rng_seed: int | None = None
    use_expected_value: bool = False

    @classmethod
    def from_preset(cls, preset: dict | None) -> "MCTSConfig":
        raw = (preset or {}).get("mcts_config") or {}
        names = {f.name for f in fields(cls)}
        kwargs = {k: v for k, v in raw.items() if k in names}
        return cls(**kwargs)
