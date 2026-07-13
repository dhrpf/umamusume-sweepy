from __future__ import annotations

import itertools
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from career_bot.affinity import _load_g1_saddles, calculate_affinity, card_to_chara_id

from .rules import compatibility_tier


_RUNNING_STYLE_FIELDS = {
    "front_runner": "proper_running_style_nige",
    "pace_chaser": "proper_running_style_senko",
    "late_surger": "proper_running_style_sashi",
    "end_closer": "proper_running_style_oikomi",
}
_DISTANCE_FIELDS = {
    "sprint": "proper_distance_short",
    "mile": "proper_distance_mile",
    "medium": "proper_distance_middle",
    "long": "proper_distance_long",
}


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _record_id(record: dict[str, Any]) -> int:
    return _int(
        record.get("trained_chara_id")
        or record.get("instance_id")
        or record.get("id")
    )


def _base_chara_id(record: dict[str, Any]) -> int:
    card_id = _int(record.get("card_id") or record.get("chara_id"))
    return card_to_chara_id(card_id) if card_id else 0


def _g1_wins(record: dict[str, Any], g1_ids: set[int]) -> set[int]:
    return {
        _int(value)
        for value in (record.get("win_saddle_id_array") or [])
        if _int(value) in g1_ids
    }


def _record_quality(record: dict[str, Any], g1_ids: set[int]) -> tuple[int, int, int, int]:
    stats = sum(
        _int(record.get(key))
        for key in ("speed", "stamina", "power", "guts", "wiz", "wit")
    )
    factor_count = len(record.get("factor_id_array") or record.get("factor_info_array") or [])
    return (
        _int(record.get("rank_score")),
        len(_g1_wins(record, g1_ids)),
        factor_count,
        stats,
    )


def _best_style(record: dict[str, Any]) -> tuple[str, int]:
    rows = [
        (name, _int(record.get(field)))
        for name, field in _RUNNING_STYLE_FIELDS.items()
    ]
    return max(rows, key=lambda item: item[1], default=("unknown", 0))


def _distance_overlap(records: list[dict[str, Any]], minimum: int) -> list[str]:
    return [
        name
        for name, field in _DISTANCE_FIELDS.items()
        if all(_int(record.get(field)) >= minimum for record in records)
    ]


def _compact_record(
    record: dict[str, Any],
    *,
    names: dict[int, str],
    g1_ids: set[int],
) -> dict[str, Any]:
    record_id = _record_id(record)
    style, style_score = _best_style(record)
    return {
        "trained_chara_id": record_id,
        "card_id": _int(record.get("card_id")),
        "base_chara_id": _base_chara_id(record),
        "name": names.get(record_id) or str(record.get("name") or f"Veteran #{record_id}"),
        "rank": record.get("rank"),
        "rank_score": _int(record.get("rank_score")),
        "running_style": style,
        "running_style_aptitude": style_score,
        "g1_wins": sorted(_g1_wins(record, g1_ids)),
    }


def _best_rotation(
    *,
    trainee_record: dict[str, Any],
    other_groups: list[list[dict[str, Any]]],
    mdb_path: Path,
    affinity_calculator: Callable[..., dict[str, Any]],
) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    trainee_card_id = _int(trainee_record.get("card_id"))
    for first_group_index, second_group_index in itertools.combinations(range(3), 2):
        first_group = other_groups[first_group_index]
        second_group = other_groups[second_group_index]
        for parent1, parent2 in itertools.product(first_group, second_group):
            try:
                affinity = affinity_calculator(
                    mdb_path,
                    trainee_card_id,
                    parent1,
                    parent2,
                )
            except Exception:
                continue
            total = _int(affinity.get("total"))
            candidate = {
                "total": total,
                "chara_compat": _int(affinity.get("chara_compat")),
                "race_compat": _int(affinity.get("race_compat")),
                "parent_ids": [_record_id(parent1), _record_id(parent2)],
                "parent_base_chara_ids": [
                    _base_chara_id(parent1),
                    _base_chara_id(parent2),
                ],
            }
            if best is None or (
                candidate["total"],
                candidate["race_compat"],
                candidate["chara_compat"],
            ) > (
                best["total"],
                best["race_compat"],
                best["chara_compat"],
            ):
                best = candidate
    return best


def scan_legacy_loop_pools(
    records: list[dict[str, Any]],
    *,
    mdb_path: str | Path,
    veteran_names: dict[int, str] | None = None,
    minimum_affinity: int = 151,
    max_characters: int = 12,
    records_per_character: int = 2,
    limit: int = 10,
    affinity_calculator: Callable[..., dict[str, Any]] = calculate_affinity,
    g1_saddle_ids: set[int] | None = None,
) -> dict[str, Any]:
    """Rank four-character bootstrap pools using cached, actual lineage records.

    The scanner never calls the game API. For each distinct base-character pool,
    every character is simulated as trainee and its best current two-parent pair
    is selected from the other three character groups. The pool is ranked by its
    worst rotation affinity first; shared G1 and style/distance overlap are
    secondary. Alt costumes collapse to the same base character.
    """
    path = Path(mdb_path).expanduser().resolve()
    if not path.exists() and g1_saddle_ids is None:
        raise FileNotFoundError(f"master.mdb not found: {path}")
    g1_ids = set(g1_saddle_ids) if g1_saddle_ids is not None else set(_load_g1_saddles(str(path)))
    names = {int(key): str(value) for key, value in (veteran_names or {}).items()}

    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in records or []:
        if not isinstance(row, dict):
            continue
        base_id = _base_chara_id(row)
        if base_id <= 0 or _record_id(row) <= 0:
            continue
        grouped.setdefault(base_id, []).append(row)

    per_character = max(1, min(int(records_per_character), 5))
    for base_id, rows in grouped.items():
        rows.sort(key=lambda row: _record_quality(row, g1_ids), reverse=True)
        grouped[base_id] = rows[:per_character]

    ranked_characters = sorted(
        grouped,
        key=lambda base_id: _record_quality(grouped[base_id][0], g1_ids),
        reverse=True,
    )[: max(4, min(int(max_characters), 20))]

    pools: list[dict[str, Any]] = []
    for base_ids in itertools.combinations(ranked_characters, 4):
        groups = [grouped[base_id] for base_id in base_ids]
        rotations = []
        valid = True
        for index, base_id in enumerate(base_ids):
            trainee_record = groups[index][0]
            other_groups = [group for other_index, group in enumerate(groups) if other_index != index]
            best = _best_rotation(
                trainee_record=trainee_record,
                other_groups=other_groups,
                mdb_path=path,
                affinity_calculator=affinity_calculator,
            )
            if best is None:
                valid = False
                break
            best.update(
                {
                    "trainee_base_chara_id": base_id,
                    "trainee_card_id": _int(trainee_record.get("card_id")),
                    "trainee_trained_chara_id": _record_id(trainee_record),
                    "tier": compatibility_tier(best["total"]),
                }
            )
            rotations.append(best)
        if not valid:
            continue

        representatives = [group[0] for group in groups]
        totals = [row["total"] for row in rotations]
        shared_g1 = set.intersection(
            *[_g1_wins(record, g1_ids) for record in representatives]
        ) if representatives else set()
        style_counts = Counter(_best_style(record)[0] for record in representatives)
        dominant_style, dominant_style_count = style_counts.most_common(1)[0]
        strict_distance_overlap = _distance_overlap(representatives, minimum=7)
        usable_distance_overlap = _distance_overlap(representatives, minimum=6)
        worst = min(totals)
        average = round(sum(totals) / len(totals), 2)
        pool = {
            "base_chara_ids": list(base_ids),
            "members": [
                _compact_record(record, names=names, g1_ids=g1_ids)
                for record in representatives
            ],
            "affinity": {
                "minimum_target": int(minimum_affinity),
                "worst": worst,
                "average": average,
                "best": max(totals),
                "tier": compatibility_tier(worst),
                "meets_target": worst >= int(minimum_affinity),
                "rotations": rotations,
            },
            "shared_g1": sorted(shared_g1),
            "shared_g1_count": len(shared_g1),
            "running_style": {
                "dominant": dominant_style,
                "matching_members": dominant_style_count,
                "all_match": dominant_style_count == 4,
            },
            "distance_overlap": {
                "strict_a_or_better": strict_distance_overlap,
                "usable_b_or_better": usable_distance_overlap,
            },
        }
        pools.append(pool)

    tier_rank = {"double_circle": 2, "single_circle": 1, "triangle": 0}
    pools.sort(
        key=lambda pool: (
            bool(pool["affinity"]["meets_target"]),
            tier_rank.get(pool["affinity"]["tier"]["name"], -1),
            pool["affinity"]["worst"],
            pool["shared_g1_count"],
            pool["running_style"]["matching_members"],
            len(pool["distance_overlap"]["usable_b_or_better"]),
            pool["affinity"]["average"],
        ),
        reverse=True,
    )
    capped = max(1, min(int(limit), 50))
    return {
        "minimum_affinity": int(minimum_affinity),
        "characters_considered": len(ranked_characters),
        "distinct_characters_available": len(grouped),
        "records_considered": sum(len(grouped[key]) for key in ranked_characters),
        "pool_count": len(pools),
        "pools": pools[:capped],
        "notes": [
            "Scanner uses the last cached load/index and never calls the game API.",
            "Affinity uses actual cached parent/grandparent lineage records.",
            "Shared G1 wins are ranked above spark/stat quality.",
            "Legacy loops improve spark proc affinity; they do not increase 3-star roll odds.",
        ],
    }
