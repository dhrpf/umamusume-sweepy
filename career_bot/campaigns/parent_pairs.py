from __future__ import annotations

import itertools
from typing import Any, Callable, Mapping, Sequence

from career_bot.affinity import card_to_chara_id

from .aptitude_planner import evaluate_aptitude_pair
from .targets import evaluate_spark_targets


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _trained_id(row: Mapping[str, Any]) -> int:
    return _int(row.get("trained_chara_id") or row.get("instance_id") or row.get("id"))


def _base_chara_id(row: Mapping[str, Any]) -> int:
    explicit = _int(row.get("base_chara_id") or row.get("chara_id"))
    if explicit > 0:
        return explicit
    card_id = _int(row.get("card_id") or row.get("race_cloth_id"))
    return card_to_chara_id(card_id) if card_id else 0


def _normalized_category(value: Any) -> str:
    normalized = str(value or "").strip().casefold()
    return {
        "stat": "blue",
        "blue": "blue",
        "aptitude": "pink",
        "pink": "pink",
    }.get(normalized, normalized)


def _spark_totals(row: Mapping[str, Any]) -> dict[tuple[str, str], int]:
    totals: dict[tuple[str, str], int] = {}
    tree = row.get("factor_tree") if isinstance(row.get("factor_tree"), Mapping) else row.get("tree")
    tree = tree if isinstance(tree, Mapping) else {}
    for node in tree.values():
        if not isinstance(node, Mapping):
            continue
        bucket_rows = []
        for bucket in ("blue", "pink"):
            for factor in node.get(bucket) or []:
                if isinstance(factor, Mapping):
                    bucket_rows.append((bucket, factor))
        for factor in node.get("factors") or []:
            if isinstance(factor, Mapping):
                bucket_rows.append((_normalized_category(factor.get("category")), factor))
        for bucket, factor in bucket_rows:
            if bucket not in {"blue", "pink"}:
                continue
            name = str(factor.get("name") or factor.get("factor_name") or "").strip().casefold()
            if not name or name.startswith("unknown factor"):
                continue
            key = (bucket, name)
            totals[key] = totals.get(key, 0) + max(0, _int(factor.get("stars") or factor.get("star")))
    return totals


def _pair_spark_totals(first: Mapping[str, Any], second: Mapping[str, Any]) -> dict[tuple[str, str], int]:
    totals = _spark_totals(first)
    for key, stars in _spark_totals(second).items():
        totals[key] = totals.get(key, 0) + stars
    return totals


def _projected_affinity(
    scorer: Callable[[int, Mapping[str, Any], Mapping[str, Any]], Any],
    trainee_card_id: int,
    first: Mapping[str, Any],
    second: Mapping[str, Any],
) -> int:
    value = scorer(int(trainee_card_id), first, second)
    if isinstance(value, Mapping):
        return _int(value.get("total", value.get("affinity")))
    return _int(value)


def rank_parent_pairs(
    candidates: Sequence[Mapping[str, Any]],
    *,
    trainee_card_id: int,
    aptitude_targets: Sequence[Mapping[str, Any]],
    factor_targets: Sequence[Mapping[str, Any]],
    affinity_scorer: Callable[[int, Mapping[str, Any], Mapping[str, Any]], Any],
    aptitude_targets_for_pair: Callable[
        [Mapping[str, Any], Mapping[str, Any]],
        Mapping[str, Any] | Sequence[Mapping[str, Any]],
    ] | None = None,
) -> list[dict[str, Any]]:
    trainee_base = card_to_chara_id(int(trainee_card_id)) if int(trainee_card_id or 0) else 0
    normalized = [dict(row) for row in candidates or [] if isinstance(row, Mapping) and _trained_id(row) > 0]
    ranked: list[dict[str, Any]] = []
    for first, second in itertools.combinations(normalized, 2):
        first_id = _trained_id(first)
        second_id = _trained_id(second)
        first_base = _base_chara_id(first)
        second_base = _base_chara_id(second)
        if first_id == second_id:
            continue
        if first.get("rental") is True and second.get("rental") is True:
            continue
        if first_base > 0 and second_base > 0 and first_base == second_base:
            continue
        if trainee_base and trainee_base in {first_base, second_base}:
            continue

        pair_aptitude_targets = list(aptitude_targets or [])
        aptitude_warnings: list[str] = []
        if aptitude_targets_for_pair is not None:
            generated = aptitude_targets_for_pair(first, second)
            if isinstance(generated, Mapping):
                pair_aptitude_targets = [
                    dict(row)
                    for row in (generated.get("targets") or [])
                    if isinstance(row, Mapping)
                ]
                aptitude_warnings = [
                    str(value)
                    for value in (generated.get("warnings") or [])
                    if str(value or "").strip()
                ]
            else:
                pair_aptitude_targets = [
                    dict(row)
                    for row in (generated or [])
                    if isinstance(row, Mapping)
                ]
        aptitude = evaluate_aptitude_pair(pair_aptitude_targets, first, second)
        factor_progress = evaluate_spark_targets(
            factor_targets,
            _pair_spark_totals(first, second),
        )
        projected_affinity = _projected_affinity(
            affinity_scorer,
            trainee_card_id,
            first,
            second,
        )
        rank_score = _int(first.get("rank_score")) + _int(second.get("rank_score"))
        parents = sorted((first, second), key=_trained_id)
        ranked.append(
            {
                "parents": [dict(row) for row in parents],
                "trained_chara_id": [_trained_id(row) for row in parents],
                "aptitude": aptitude,
                "aptitude_targets": pair_aptitude_targets,
                "aptitude_warnings": aptitude_warnings,
                "factor_progress": factor_progress,
                "projected_displayed_affinity": projected_affinity,
                "rank_score": rank_score,
            }
        )

    ranked.sort(
        key=lambda row: (
            -int(bool(row["aptitude"]["feasible"])),
            -float(row["aptitude"]["coverage"]),
            -float(row["factor_progress"]["required_progress"]),
            -float(row["factor_progress"]["preferred_progress"]),
            -int(row["projected_displayed_affinity"]),
            -int(row["rank_score"]),
            tuple(row["trained_chara_id"]),
        )
    )
    return ranked


__all__ = ["rank_parent_pairs"]
