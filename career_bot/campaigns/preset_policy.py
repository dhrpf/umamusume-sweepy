from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


_BLUE_STATS = {"speed", "stamina", "power", "guts", "wisdom"}


def _target_value(target: Any, field: str) -> Any:
    if isinstance(target, Mapping):
        return target.get(field)
    return getattr(target, field, None)


def _normalized_text(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip().lower()


def build_campaign_base_preset(
    *,
    name: Any,
    running_style: Any,
    scenario_id: Any,
    spark_targets: Sequence[Any],
    core_races: Sequence[Any],
    optional_races: Sequence[Any],
) -> dict[str, Any]:
    preset = {
        "name": str(name),
        "running_style": int(running_style),
        "scenario_id": int(scenario_id),
        "parent_run": True,
        "mandatory_race_list": list(core_races),
        "extra_race_list": list(optional_races),
    }
    for target in spark_targets:
        if _normalized_text(_target_value(target, "category")) != "blue":
            continue
        stat = _normalized_text(_target_value(target, "name"))
        stat = "wisdom" if stat == "wit" else stat
        if stat in _BLUE_STATS:
            preset[f"expect_{stat}"] = 1100
    return preset


def build_step_overrides(
    *,
    core_races: Sequence[Any],
    optional_races: Sequence[Any],
    parent_run: bool = True,
) -> dict[str, Any]:
    return {
        "mandatory_race_list": list(core_races),
        "extra_race_list": list(optional_races),
        "parent_run": bool(parent_run),
    }
