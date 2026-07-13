from __future__ import annotations

from typing import Any


DEFAULT_SPARK_RULESET: dict[str, Any] = {
    "blue": {
        "effects": {1: 5, 2: 12, 3: 21},
        "three_star_stat_target": 1100,
        "guaranteed_initial_inheritance": True,
    },
    "pink": {
        "minimum_aptitude": "A",
        "guaranteed_initial_inheritance": True,
    },
    "green": {
        "minimum_character_rarity": 3,
        "direct_parent_initial_guaranteed": True,
        "grandparent_initial_guaranteed": False,
    },
    "white_skill": {
        "normal_probability": 0.20,
        "double_circle_probability": 0.25,
        "gold_probability": 0.40,
        "exclude_unique": True,
    },
    "white_race": {
        "base_probability": 0.20,
        "shared_g1_is_affinity_progress": True,
    },
    "scenario": {
        "effects": {1: 10, 2: 20, 3: 30},
    },
}


def compatibility_tier(total: int | float) -> dict[str, Any]:
    value = int(total or 0)
    if value > 150:
        return {
            "symbol": "◎",
            "name": "double_circle",
            "minimum": 151,
            "total": value,
        }
    if value >= 50:
        return {
            "symbol": "◯",
            "name": "single_circle",
            "minimum": 50,
            "total": value,
        }
    return {
        "symbol": "△",
        "name": "triangle",
        "minimum": 0,
        "total": value,
    }


def blue_stat_effect(stars: int) -> int:
    try:
        normalized = int(stars)
    except (TypeError, ValueError):
        return 0
    return int(DEFAULT_SPARK_RULESET["blue"]["effects"].get(normalized, 0))


def estimate_initial_blue_stats(factors: list[dict[str, Any]] | None) -> int:
    """Estimate guaranteed initial stat from blue lineage factors only."""
    total = 0
    for row in factors or []:
        if not isinstance(row, dict):
            continue
        category = str(row.get("category") or "").strip().lower()
        if category not in {"blue", "stat"}:
            continue
        total += blue_stat_effect(int(row.get("stars") or row.get("star") or 0))
    return total
