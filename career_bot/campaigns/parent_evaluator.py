from __future__ import annotations

from typing import Any

from .models import FactorAggregation, FactorScope, LineageDepth, ParentGoal


RANK_ORDER = [
    "G",
    "G+",
    "F",
    "F+",
    "E",
    "E+",
    "D",
    "D+",
    "C",
    "C+",
    "B",
    "B+",
    "A",
    "A+",
    "S",
    "S+",
    "SS",
    "SS+",
    "UG",
    "UF",
    "UE",
    "UD",
]

APTITUDE_VALUES = {
    "G": 1.0,
    "F": 2.0,
    "E": 3.0,
    "D": 4.0,
    "C": 5.0,
    "B": 6.0,
    "A": 7.0,
    "S": 8.0,
}


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(float(value), maximum))


def _rank_index(value: Any) -> int:
    normalized = str(value or "G").strip().upper()
    try:
        return RANK_ORDER.index(normalized)
    except ValueError:
        return 0


def _aptitude_ratio(value: Any) -> float:
    if isinstance(value, (int, float)):
        numeric = float(value)
        if numeric <= 0:
            return 0.0
        return _clamp(numeric / 8.0)
    normalized = str(value or "").strip().upper()
    if not normalized:
        return 0.0
    base = normalized.rstrip("+")
    score = APTITUDE_VALUES.get(base, 0.0)
    if normalized.endswith("+") and score:
        score += 0.5
    return _clamp(score / 8.0)


def _factor_values(rows: Any) -> dict[str, list[int]]:
    result: dict[str, list[int]] = {}
    if not isinstance(rows, list):
        return result
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or row.get("factor_name") or "").strip().lower()
        if not name:
            continue
        try:
            stars = int(row.get("stars") or row.get("star") or row.get("level") or 0)
        except (TypeError, ValueError):
            stars = 0
        result.setdefault(name, []).append(max(0, stars))
    return result


def _factor_stars(
    values: dict[str, list[int]],
    name: str,
    aggregation: FactorAggregation,
) -> int:
    rows = values.get(name) or []
    if not rows:
        return 0
    if aggregation is FactorAggregation.SUM:
        return int(sum(rows))
    return int(max(rows))


def evaluate_parent_candidate(
    goal: ParentGoal | dict[str, Any],
    candidate: dict[str, Any],
    *,
    baseline_score: float | None = None,
) -> dict[str, Any]:
    validated_goal = ParentGoal.model_validate(goal)
    candidate = dict(candidate or {})
    reasons: list[str] = []
    weaknesses: list[str] = []
    matched_targets: list[str] = []
    missing_targets: list[str] = []

    candidate_factors = _factor_values(candidate.get("candidate_factors"))
    lineage_factors = _factor_values(candidate.get("lineage_factors"))
    direct_lineage_factors = _factor_values(candidate.get("direct_lineage_factors"))
    full_lineage_factors = _factor_values(candidate.get("full_lineage_factors"))
    required_targets = [row for row in validated_goal.target_factors if row.required]
    factor_ratios: list[float] = []
    factor_evidence: list[dict[str, Any]] = []
    extra_stars = 0

    for target in validated_goal.target_factors:
        if target.scope is FactorScope.CANDIDATE:
            source = candidate_factors
        elif target.lineage_depth is LineageDepth.DIRECT:
            source = direct_lineage_factors or lineage_factors
        else:
            source = full_lineage_factors or lineage_factors

        stars = _factor_stars(source, target.name, target.aggregation)
        label = f"{target.name}:{target.scope.value}"
        matched = stars >= target.minimum_stars
        factor_evidence.append(
            {
                "name": target.name,
                "scope": target.scope.value,
                "aggregation": target.aggregation.value,
                "lineage_depth": target.lineage_depth.value,
                "observed_stars": stars,
                "required_stars": target.minimum_stars,
                "matched": matched,
            }
        )
        ratio = _clamp(stars / max(1, target.minimum_stars))
        factor_ratios.append(ratio)
        if matched:
            matched_targets.append(label)
            extra_stars += max(0, stars - target.minimum_stars)
            if target.aggregation is FactorAggregation.SUM:
                reasons.append(
                    f"Matched {target.name} {target.lineage_depth.value}-lineage total "
                    f"at {stars}★"
                )
            else:
                reasons.append(
                    f"Matched {target.name} {target.scope.value} factor at {stars}★"
                )
        else:
            if target.required:
                missing_targets.append(label)
                weaknesses.append(
                    f"Missing required {target.name} {target.scope.value} factor "
                    f"({stars}/{target.minimum_stars}★)"
                )
            else:
                weaknesses.append(
                    f"Optional {target.name} {target.scope.value} factor is below target"
                )

    factor_ratio = sum(factor_ratios) / len(factor_ratios) if factor_ratios else 1.0
    factor_score = factor_ratio * 30.0
    factor_bonus = min(5.0, extra_stars * 2.5)

    rank = str(candidate.get("rank") or "G").strip().upper()
    rank_ok = _rank_index(rank) >= _rank_index(validated_goal.minimum_rank)
    rank_score = 10.0 if rank_ok else 10.0 * _clamp(
        (_rank_index(rank) + 1) / max(1, _rank_index(validated_goal.minimum_rank) + 1)
    )
    if rank_ok:
        reasons.append(f"Rank {rank} meets minimum rank {validated_goal.minimum_rank}")
    else:
        weaknesses.append(
            f"Rank {rank} is below minimum rank {validated_goal.minimum_rank}"
        )

    aptitudes = candidate.get("aptitudes") if isinstance(candidate.get("aptitudes"), dict) else {}
    aptitude_targets = [*validated_goal.surface_targets, *validated_goal.distance_targets]
    aptitude_ratios = [_aptitude_ratio(aptitudes.get(name)) for name in aptitude_targets]
    aptitude_score = (
        sum(aptitude_ratios) / len(aptitude_ratios) * 15.0
        if aptitude_ratios
        else 0.0
    )
    if aptitude_ratios and all(value >= APTITUDE_VALUES["A"] / 8.0 for value in aptitude_ratios):
        reasons.append("Target surface and distance aptitudes are A or better")
    elif aptitude_targets and any(value < APTITUDE_VALUES["B"] / 8.0 for value in aptitude_ratios):
        weaknesses.append("One or more target aptitudes are below B")

    stats = candidate.get("stats") if isinstance(candidate.get("stats"), dict) else {}
    preferred_values = []
    for stat_name in validated_goal.preferred_stats:
        try:
            preferred_values.append(max(0.0, float(stats.get(stat_name) or 0.0)))
        except (TypeError, ValueError):
            preferred_values.append(0.0)
    stat_ratio = (
        sum(_clamp(value / 1200.0) for value in preferred_values) / len(preferred_values)
        if preferred_values
        else 0.0
    )
    stat_score = stat_ratio * 15.0
    if preferred_values and min(preferred_values) >= 900:
        reasons.append("Preferred stats are all at least 900")
    elif preferred_values and max(preferred_values) > 0 and min(preferred_values) < 700:
        weaknesses.append("One or more preferred stats are below 700")

    try:
        compatibility = _clamp(float(candidate.get("compatibility_score") or 0.0) / 100.0)
    except (TypeError, ValueError):
        compatibility = 0.0
    try:
        race_history = _clamp(float(candidate.get("race_history_score") or 0.0) / 100.0)
    except (TypeError, ValueError):
        race_history = 0.0

    compatibility_score = compatibility * 15.0
    race_score = race_history * 10.0
    total = round(
        factor_score
        + factor_bonus
        + aptitude_score
        + rank_score
        + stat_score
        + compatibility_score
        + race_score,
        2,
    )

    required_ok = len(missing_targets) == 0 and len(required_targets) >= 0
    accepted = bool(required_ok and rank_ok)
    baseline_delta = None if baseline_score is None else round(total - float(baseline_score), 2)
    if not accepted:
        decision = "reject"
    elif baseline_delta is None or baseline_delta > 5:
        decision = "accept"
    elif baseline_delta < -5:
        decision = "reject"
        weaknesses.append(
            f"Candidate scores {abs(baseline_delta):.2f} below the current baseline"
        )
    else:
        decision = "ambiguous"
        reasons.append("Candidate is close enough to the baseline to require comparison")

    return {
        "trained_chara_id": int(candidate.get("trained_chara_id") or 0),
        "name": str(candidate.get("name") or ""),
        "rank": rank,
        "score": total,
        "accepted": accepted,
        "decision": decision,
        "baseline_score": baseline_score,
        "baseline_delta": baseline_delta,
        "matched_targets": matched_targets,
        "missing_targets": missing_targets,
        "factor_evidence": factor_evidence,
        "components": {
            "factors": round(factor_score + factor_bonus, 2),
            "aptitudes": round(aptitude_score, 2),
            "rank": round(rank_score, 2),
            "preferred_stats": round(stat_score, 2),
            "compatibility": round(compatibility_score, 2),
            "race_history": round(race_score, 2),
        },
        "reasons": reasons,
        "weaknesses": weaknesses,
    }
