from __future__ import annotations

from collections import defaultdict
from typing import Any


_POSITION_KEYS = {
    10: "parent1",
    20: "parent2",
    11: "grandparent1",
    12: "grandparent2",
    21: "grandparent3",
    22: "grandparent4",
}
_FACTOR_BUCKETS = {
    "stat": "blue",
    "aptitude": "pink",
    "unique": "green",
    "skill": "white_skill",
    "race": "white_race",
    "scenario": "scenario",
}
_DIRECT_KEYS = ("self", "parent1", "parent2")
_FULL_KEYS = (
    "self",
    "parent1",
    "parent2",
    "grandparent1",
    "grandparent2",
    "grandparent3",
    "grandparent4",
)


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _factor_ids(row: Any) -> list[int]:
    if not isinstance(row, dict):
        return []
    raw_ids = row.get("factor_id_array")
    if isinstance(raw_ids, list):
        return [factor_id for factor_id in (_int(value) for value in raw_ids) if factor_id]
    info = row.get("factor_info_array")
    if not isinstance(info, list):
        return []
    result = []
    for item in info:
        factor_id = _int(item.get("factor_id")) if isinstance(item, dict) else _int(item)
        if factor_id:
            result.append(factor_id)
    return result


def decode_factors(row: Any, factor_map: dict[str, Any]) -> list[dict[str, Any]]:
    """Decode factor IDs using generated master data without guessing semantics."""
    decoded = []
    for factor_id in _factor_ids(row):
        info = factor_map.get(str(factor_id))
        if not isinstance(info, dict):
            decoded.append(
                {
                    "factor_id": factor_id,
                    "name": f"Unknown factor {factor_id}",
                    "stars": 0,
                    "category": "unknown",
                }
            )
            continue
        decoded.append(
            {
                "factor_id": factor_id,
                "name": str(info.get("name") or f"Unknown factor {factor_id}"),
                "stars": max(0, _int(info.get("stars"))),
                "category": str(info.get("category") or "unknown").strip().lower(),
            }
        )
    return decoded


def _factor_node(row: Any, factor_map: dict[str, Any]) -> dict[str, Any]:
    buckets: dict[str, list[dict[str, Any]]] = {
        "blue": [],
        "pink": [],
        "green": [],
        "white_skill": [],
        "white_race": [],
        "scenario": [],
        "other": [],
    }
    for factor in decode_factors(row, factor_map):
        bucket = _FACTOR_BUCKETS.get(factor["category"], "other")
        buckets[bucket].append(factor)
    return {
        "card_id": _int(row.get("card_id")) if isinstance(row, dict) else 0,
        **buckets,
    }


def _blue_map(node: dict[str, Any]) -> dict[str, int]:
    result: dict[str, int] = defaultdict(int)
    for factor in node.get("blue") or []:
        name = str(factor.get("name") or "").strip()
        if name:
            result[name] += max(0, _int(factor.get("stars")))
    return dict(sorted(result.items()))


def _sum_blue(tree: dict[str, Any], keys: tuple[str, ...]) -> dict[str, int]:
    totals: dict[str, int] = defaultdict(int)
    for key in keys:
        for name, stars in _blue_map(tree.get(key) or {}).items():
            totals[name] += stars
    return dict(sorted(totals.items()))


def summarize_veteran(
    record: dict[str, Any],
    *,
    factor_map: dict[str, Any],
    display: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a deterministic decoded veteran summary for agent consumption."""
    display = display if isinstance(display, dict) else {}
    trained_chara_id = _int(
        record.get("trained_chara_id")
        or record.get("instance_id")
        or display.get("trained_chara_id")
        or display.get("instance_id")
    )
    tree: dict[str, Any] = {
        key: _factor_node({}, factor_map)
        for key in _FULL_KEYS
    }
    tree["self"] = _factor_node(record, factor_map)
    for row in record.get("succession_chara_array") or []:
        if not isinstance(row, dict):
            continue
        key = _POSITION_KEYS.get(_int(row.get("position_id")))
        if key:
            tree[key] = _factor_node(row, factor_map)

    self_blue = _blue_map(tree["self"])
    direct_parent_blue = {
        "parent1": _blue_map(tree["parent1"]),
        "parent2": _blue_map(tree["parent2"]),
    }
    direct_totals = _sum_blue(tree, _DIRECT_KEYS)
    full_totals = _sum_blue(tree, _FULL_KEYS)
    tags = [f"{name} 9★" for name, stars in direct_totals.items() if stars == 9]

    return {
        "trained_chara_id": trained_chara_id,
        "card_id": _int(record.get("card_id") or display.get("card_id")),
        "name": str(
            display.get("name")
            or record.get("name")
            or f"Veteran #{trained_chara_id}"
        ),
        "rank": _int(record.get("rank") or display.get("rank")),
        "rank_score": _int(record.get("rank_score") or display.get("rank_score")),
        "final_stats": {
            "speed": _int(record.get("speed")),
            "stamina": _int(record.get("stamina")),
            "power": _int(record.get("power")),
            "guts": _int(record.get("guts")),
            "wit": _int(record.get("wiz") or record.get("wit")),
        },
        "self_blue_factors": self_blue,
        "direct_parent_blue_factors": direct_parent_blue,
        "direct_lineage_blue_totals": direct_totals,
        "full_lineage_blue_totals": full_totals,
        "legacy_tags": tags,
        "factor_tree": tree,
    }


def find_veterans(
    records: list[dict[str, Any]],
    *,
    factor_map: dict[str, Any],
    display_by_id: dict[int, dict[str, Any]] | None = None,
    blue_factor: str = "",
    minimum_lineage_stars: int = 0,
    scope: str = "direct_lineage",
    limit: int = 50,
) -> dict[str, Any]:
    """Filter cached veterans using decoded factors, never final stats or raw IDs."""
    normalized_scope = str(scope or "direct_lineage").strip().lower()
    scope_fields = {
        "self": ("self_blue_factors", "self only"),
        "direct_lineage": (
            "direct_lineage_blue_totals",
            "self + direct parent 1 + direct parent 2",
        ),
        "full_lineage": ("full_lineage_blue_totals", "self + all six lineage members"),
    }
    if normalized_scope not in scope_fields:
        raise ValueError("scope must be self, direct_lineage, or full_lineage")
    field_name, definition = scope_fields[normalized_scope]
    display_by_id = display_by_id or {}
    wanted = str(blue_factor or "").strip().casefold()
    minimum = max(0, _int(minimum_lineage_stars))

    summaries = []
    canonical_name = str(blue_factor or "").strip().title()
    for record in records or []:
        if not isinstance(record, dict):
            continue
        trained_id = _int(record.get("trained_chara_id") or record.get("instance_id"))
        summary = summarize_veteran(
            record,
            factor_map=factor_map,
            display=display_by_id.get(trained_id),
        )
        factor_values = summary[field_name]
        if wanted:
            matching_name = next(
                (name for name in factor_values if name.casefold() == wanted),
                None,
            )
            matched_stars = _int(factor_values.get(matching_name, 0)) if matching_name else 0
            if matching_name:
                canonical_name = matching_name
            if matched_stars < minimum:
                continue
        else:
            matched_stars = max((_int(value) for value in factor_values.values()), default=0)
            if minimum and matched_stars < minimum:
                continue
        summary["matched_blue_stars"] = matched_stars
        summaries.append(summary)

    summaries.sort(
        key=lambda row: (
            -_int(row.get("matched_blue_stars")),
            -_int(row.get("rank_score")),
            _int(row.get("trained_chara_id")),
        )
    )
    bounded_limit = max(1, min(_int(limit) or 50, 500))
    matches = summaries[:bounded_limit]
    return {
        "query": {
            "blue_factor": canonical_name,
            "minimum_lineage_stars": minimum,
            "scope": normalized_scope,
            "definition": definition,
        },
        "match_count": len(summaries),
        "returned": len(matches),
        "matches": matches,
    }
