from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


_BLUE_STATS = {"speed", "stamina", "power", "guts", "wisdom"}
_RUNNING_STYLES = frozenset({1, 2, 3, 4})
_SUPPORTED_SCENARIO_IDS = frozenset({1, 2, 3, 4})


def _require_supported_int(value: Any, *, field: str, supported: frozenset[int]) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value not in supported:
        allowed = ", ".join(str(item) for item in sorted(supported))
        raise ValueError(f"{field} must be one of: {allowed}")
    return value


def _copy_race_ids(value: Any, *, field: str) -> list[int]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError(f"{field} must be a sequence of positive integer IDs")
    race_ids = list(value)
    if any(isinstance(race_id, bool) or not isinstance(race_id, int) or race_id <= 0 for race_id in race_ids):
        raise ValueError(f"{field} must contain only positive integer IDs")
    return race_ids


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
    validated_running_style = _require_supported_int(
        running_style,
        field="running_style",
        supported=_RUNNING_STYLES,
    )
    validated_scenario_id = _require_supported_int(
        scenario_id,
        field="scenario_id",
        supported=_SUPPORTED_SCENARIO_IDS,
    )
    preset = {
        "name": str(name),
        "running_style": validated_running_style,
        "scenario_id": validated_scenario_id,
        "parent_run": True,
        "mandatory_race_list": _copy_race_ids(core_races, field="core_races"),
        "extra_race_list": _copy_race_ids(optional_races, field="optional_races"),
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
    if not isinstance(parent_run, bool):
        raise TypeError("parent_run must be a bool")
    return {
        "mandatory_race_list": _copy_race_ids(core_races, field="core_races"),
        "extra_race_list": _copy_race_ids(optional_races, field="optional_races"),
        "parent_run": parent_run,
    }
