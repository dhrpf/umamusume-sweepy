from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, Sequence


_GRADE_NUMBERS = {
    "G": 1,
    "F": 2,
    "E": 3,
    "D": 4,
    "C": 5,
    "B": 6,
    "A": 7,
    "S": 8,
}
_NUMERIC_GRADES = {value: key for key, value in _GRADE_NUMBERS.items()}
_STAR_REQUIREMENTS = {
    "C": (1, "B"),
    "D": (4, "B"),
    "E": (7, "B"),
    "F": (10, "B"),
    "G": (10, "C"),
}
_APTITUDE_ALIASES = {
    "turf": "turf",
    "dirt": "dirt",
    "sprint": "short",
    "short": "short",
    "mile": "mile",
    "medium": "medium",
    "middle": "medium",
    "long": "long",
}
_DISPLAY_NAMES = {
    "turf": "turf",
    "dirt": "dirt",
    "short": "sprint",
    "mile": "mile",
    "medium": "medium",
    "long": "long",
}


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _normalized_aptitude(value: Any) -> str:
    text = str(value or "").strip().casefold()
    return _APTITUDE_ALIASES.get(text, "")


def _grade(value: Any) -> str:
    if isinstance(value, str):
        normalized = value.strip().upper()
        return normalized if normalized in _GRADE_NUMBERS else ""
    return _NUMERIC_GRADES.get(_int(value), "")


def _race_id(row: Mapping[str, Any]) -> int:
    return _int(row.get("program_id") or row.get("id"))


def generate_aptitude_targets(
    *,
    trainee_card_id: int,
    race_ids: Sequence[int],
    race_rows: Sequence[Mapping[str, Any]],
    base_aptitudes: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    wanted = {int(value) for value in race_ids or [] if _int(value) > 0}
    supporting: dict[str, list[int]] = defaultdict(list)
    order: list[str] = []
    for row in race_rows or []:
        if not isinstance(row, Mapping):
            continue
        program_id = _race_id(row)
        if program_id not in wanted:
            continue
        for raw in (row.get("terrain"), row.get("distance")):
            key = _normalized_aptitude(raw)
            if not key:
                continue
            if key not in supporting:
                order.append(key)
            if program_id not in supporting[key]:
                supporting[key].append(program_id)

    base = base_aptitudes.get(str(int(trainee_card_id or 0)), {})
    if not isinstance(base, Mapping):
        base = {}
    targets: list[dict[str, Any]] = []
    warnings: list[str] = []
    for key in order:
        raw_grade = base.get(key)
        grade = _grade(raw_grade)
        label = _DISPLAY_NAMES.get(key, key)
        if not grade:
            warnings.append(f"Missing base aptitude data for {label}")
            continue
        if _GRADE_NUMBERS[grade] >= _GRADE_NUMBERS["B"]:
            continue
        requirement = _STAR_REQUIREMENTS.get(grade)
        if requirement is None:
            warnings.append(f"Unsupported base aptitude grade {grade} for {label}")
            continue
        required, target_grade = requirement
        targets.append(
            {
                "aptitude": label,
                "starting_grade": grade,
                "required_red_stars": required,
                "achievable_target_grade": target_grade,
                "supporting_race_ids": list(supporting[key]),
            }
        )
    return {"targets": targets, "warnings": warnings}


def _factor_stars(node: Mapping[str, Any], aptitude: str) -> int:
    wanted = _normalized_aptitude(aptitude)
    result = 0
    for factor in node.get("pink") or []:
        if not isinstance(factor, Mapping):
            continue
        name = str(factor.get("name") or factor.get("factor_name") or "").strip()
        if not name or name.casefold().startswith("unknown factor"):
            continue
        if _normalized_aptitude(name) != wanted:
            continue
        result += max(0, _int(factor.get("stars") or factor.get("star")))
    return result


def _parent_evidence(parent: Mapping[str, Any], parent_number: int, aptitude: str) -> list[dict[str, Any]]:
    tree = parent.get("factor_tree") if isinstance(parent.get("factor_tree"), Mapping) else parent.get("tree")
    tree = tree if isinstance(tree, Mapping) else {}
    result = []
    for node_key, source in (("self", "direct_veteran"), ("parent1", "gp1"), ("parent2", "gp2")):
        node = tree.get(node_key)
        if not isinstance(node, Mapping):
            continue
        stars = _factor_stars(node, aptitude)
        if stars <= 0:
            continue
        result.append({"parent": parent_number, "source": source, "stars": stars})
    return result


def evaluate_aptitude_pair(
    targets: Sequence[Mapping[str, Any]],
    parent1: Mapping[str, Any],
    parent2: Mapping[str, Any],
) -> dict[str, Any]:
    evidence: dict[str, dict[str, Any]] = {}
    shortfalls: list[dict[str, Any]] = []
    coverage_parts: list[float] = []
    feasible = True
    for target in targets or []:
        aptitude = str(target.get("aptitude") or "").strip().lower()
        required = max(0, _int(target.get("required_red_stars")))
        if not aptitude or required <= 0:
            continue
        sources = [
            *_parent_evidence(parent1 or {}, 1, aptitude),
            *_parent_evidence(parent2 or {}, 2, aptitude),
        ]
        total = sum(_int(row.get("stars")) for row in sources)
        evidence[aptitude] = {
            "required_red_stars": required,
            "total_stars": total,
            "sources": sources,
        }
        coverage_parts.append(min(total / required, 1.0))
        if total < required:
            feasible = False
            shortfalls.append(
                {
                    "aptitude": aptitude,
                    "required_red_stars": required,
                    "actual_red_stars": total,
                    "missing_red_stars": required - total,
                }
            )
    coverage = sum(coverage_parts) / len(coverage_parts) if coverage_parts else 1.0
    return {
        "feasible": feasible,
        "coverage": coverage,
        "evidence": evidence,
        "shortfalls": shortfalls,
    }


__all__ = ["evaluate_aptitude_pair", "generate_aptitude_targets"]
