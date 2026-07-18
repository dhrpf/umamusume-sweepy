from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import ceil
from typing import Any

from .models import CampaignSparkTarget

SparkKey = tuple[str, str]

_NODE_ALIASES = {
    "self": ("self",),
    "parent1": ("parent1", "p1"),
    "parent2": ("parent2", "p2"),
}


def _category(value: Any) -> str:
    return {
        "stat": "blue",
        "blue": "blue",
        "aptitude": "pink",
        "pink": "pink",
    }.get(str(value or "").strip().casefold(), "")


def _add_factor(
    totals: dict[SparkKey, int],
    category: str,
    factor: Mapping[str, Any],
) -> None:
    bucket = _category(category or factor.get("category"))
    name = str(
        factor.get("name") or factor.get("factor_name") or ""
    ).strip().casefold()
    if bucket not in {"blue", "pink"} or not name or name.startswith("unknown factor"):
        return
    try:
        stars = max(0, int(factor.get("stars") or factor.get("star") or 0))
    except (TypeError, ValueError):
        stars = 0
    key = (bucket, name)
    totals[key] = totals.get(key, 0) + stars


def _canonical_node(
    tree: Mapping[str, Any],
    canonical: str,
) -> Mapping[str, Any]:
    for alias in _NODE_ALIASES[canonical]:
        node = tree.get(alias)
        if isinstance(node, Mapping):
            return node
    return {}


def _node_totals(
    tree: Mapping[str, Any],
    nodes: Sequence[str],
) -> dict[SparkKey, int]:
    totals: dict[SparkKey, int] = {}
    for canonical in nodes:
        node = _canonical_node(tree, canonical)
        for bucket in ("blue", "pink"):
            for factor in node.get(bucket) or []:
                if isinstance(factor, Mapping):
                    _add_factor(totals, bucket, factor)
        for factor in node.get("factors") or []:
            if isinstance(factor, Mapping):
                _add_factor(totals, "", factor)
    return totals


def self_spark_totals(
    tree: Mapping[str, Any] | None,
) -> dict[SparkKey, int]:
    return _node_totals(tree or {}, ("self",))


def direct_lineage_spark_totals(
    tree: Mapping[str, Any] | None,
) -> dict[SparkKey, int]:
    return _node_totals(tree or {}, ("self", "parent1", "parent2"))


def ready_parent_targets(
    targets: Sequence[Mapping[str, Any] | CampaignSparkTarget],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for raw in targets:
        target = (
            raw
            if isinstance(raw, CampaignSparkTarget)
            else CampaignSparkTarget.model_validate(raw)
        )
        result.append(
            {
                "category": target.category.value,
                "name": target.name,
                "minimum_stars": min(
                    3,
                    max(1, ceil(target.minimum_stars / 3)),
                ),
                "priority": target.priority.value,
            }
        )
    return result


def parent_pair_targets(
    targets: Sequence[Mapping[str, Any] | CampaignSparkTarget],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for raw in targets:
        target = (
            raw
            if isinstance(raw, CampaignSparkTarget)
            else CampaignSparkTarget.model_validate(raw)
        )
        final_self_minimum = min(
            3,
            max(1, ceil(target.minimum_stars / 3)),
        )
        result.append(
            {
                "category": target.category.value,
                "name": target.name,
                "minimum_stars": max(
                    1,
                    target.minimum_stars - final_self_minimum,
                ),
                "priority": target.priority.value,
            }
        )
    return result


__all__ = [
    "SparkKey",
    "direct_lineage_spark_totals",
    "parent_pair_targets",
    "ready_parent_targets",
    "self_spark_totals",
]
