from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .models import CampaignSparkTarget

SparkKey = tuple[str, str]


def _normalized_text(value: Any) -> str:
    enum_value = getattr(value, "value", value)
    return str(enum_value or "").strip().lower()


def spark_key(category: Any, name: Any) -> SparkKey:
    return (_normalized_text(category), _normalized_text(name))


def _clamp_ratio(actual: int, minimum: int) -> float:
    return max(0.0, min(float(actual) / max(1, int(minimum)), 1.0))


def _target_row(target: CampaignSparkTarget, actual_stars: int) -> dict[str, Any]:
    ratio = _clamp_ratio(actual_stars, target.minimum_stars)
    return {
        "category": target.category.value,
        "name": target.name,
        "minimum_stars": target.minimum_stars,
        "priority": target.priority.value,
        "actual_stars": actual_stars,
        "ratio": ratio,
        "matched": ratio >= 1.0,
    }


def _validate_target(target: CampaignSparkTarget | Mapping[str, Any]) -> CampaignSparkTarget:
    if isinstance(target, CampaignSparkTarget):
        return target
    payload = dict(target)
    for key in ("category", "name", "priority"):
        if key in payload:
            payload[key] = _normalized_text(payload[key])
    return CampaignSparkTarget.model_validate(payload)


def _average_progress(rows: Sequence[dict[str, Any]]) -> float:
    if not rows:
        return 1.0
    return sum(float(row["ratio"]) for row in rows) / len(rows)


def _normalized_totals(totals: Mapping[Any, Any]) -> dict[SparkKey, int]:
    normalized: dict[SparkKey, int] = {}
    for raw_key, value in totals.items():
        if not isinstance(raw_key, tuple) or len(raw_key) != 2:
            continue
        try:
            stars = int(value or 0)
        except (TypeError, ValueError):
            stars = 0
        key = spark_key(raw_key[0], raw_key[1])
        normalized[key] = max(normalized.get(key, 0), max(0, stars))
    return normalized


def evaluate_spark_targets(
    targets: Sequence[CampaignSparkTarget | Mapping[str, Any]],
    totals: Mapping[Any, Any],
) -> dict[str, Any]:
    normalized_totals = _normalized_totals(totals)
    rows = []
    for target in targets:
        validated = _validate_target(target)
        actual_stars = normalized_totals.get(
            spark_key(validated.category, validated.name),
            0,
        )
        rows.append(_target_row(validated, actual_stars))

    required_rows = [row for row in rows if row["priority"] == "required"]
    preferred_rows = [row for row in rows if row["priority"] == "preferred"]

    return {
        "rows": rows,
        "required_complete": all(row["matched"] for row in required_rows),
        "preferred_complete": all(row["matched"] for row in preferred_rows),
        "required_progress": _average_progress(required_rows),
        "preferred_progress": _average_progress(preferred_rows),
    }
