from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


MIN_FINAL_AFFINITY = 150

IN_PROGRESS = "IN_PROGRESS"
READY = "READY"
READY_WITH_RENTAL = "READY_WITH_RENTAL"


def _non_negative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _ratio(value: Any) -> float:
    try:
        return max(0.0, min(float(value or 0.0), 1.0))
    except (TypeError, ValueError):
        return 0.0


def _boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


def _pairing_affinity(pairing: Mapping[str, Any]) -> int:
    return _non_negative_int(
        pairing.get("affinity", pairing.get("total_affinity", pairing.get("score")))
    )


def _pairing_is_rental(pairing: Mapping[str, Any]) -> bool:
    return any(
        _boolish(pairing.get(key))
        for key in ("rental", "is_rental", "uses_rental", "rental_dependency")
    )


def _key_string(row: Mapping[str, Any]) -> str:
    for key in ("key", "candidate_id", "id", "name"):
        value = row.get(key)
        if value is not None:
            return str(value)
    return str(sorted((str(key), str(value)) for key, value in row.items()))


def evaluate_final_setup(
    required_complete: Any,
    pairings: Sequence[Mapping[str, Any]],
    allow_rental: bool,
) -> dict[str, Any]:
    allowed_pairings = [
        dict(pairing)
        for pairing in pairings
        if isinstance(pairing, Mapping)
        and (allow_rental or not _pairing_is_rental(pairing))
    ]
    if not allowed_pairings:
        return {
            "status": IN_PROGRESS,
            "best_affinity": 0,
            "best_pairing": None,
        }

    def best_from(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        return sorted(
            rows,
            key=lambda row: (
                -_pairing_affinity(row),
                _pairing_is_rental(row),
                _key_string(row),
            ),
        )[0]

    best_pairing = best_from(allowed_pairings)
    status = IN_PROGRESS
    if _boolish(required_complete):
        owned_passing = [
            row
            for row in allowed_pairings
            if not _pairing_is_rental(row)
            and _pairing_affinity(row) >= MIN_FINAL_AFFINITY
        ]
        if owned_passing:
            best_pairing = best_from(owned_passing)
            status = READY
        else:
            rental_passing = [
                row
                for row in allowed_pairings
                if _pairing_is_rental(row)
                and _pairing_affinity(row) >= MIN_FINAL_AFFINITY
            ]
            if rental_passing:
                best_pairing = best_from(rental_passing)
                status = READY_WITH_RENTAL

    best_affinity = _pairing_affinity(best_pairing)

    return {
        "status": status,
        "best_affinity": best_affinity,
        "best_pairing": best_pairing,
    }


def _candidate_affinity(row: Mapping[str, Any]) -> int:
    return _non_negative_int(row.get("best_affinity", row.get("affinity")))


def _candidate_effort(row: Mapping[str, Any]) -> float:
    return _ratio(row.get("effort", row.get("effort_ratio", row.get("remaining_effort"))))


def _candidate_score(row: Mapping[str, Any]) -> float:
    required_progress = _ratio(row.get("required_progress"))
    preferred_progress = _ratio(row.get("preferred_progress"))
    affinity_ratio = min(_candidate_affinity(row) / 200.0, 1.0)
    existing_bonus = 0.08 if _boolish(row.get("existing", row.get("is_existing"))) else 0.0
    effort_penalty = _candidate_effort(row) * 0.20
    return (
        required_progress * 0.50
        + preferred_progress * 0.10
        + affinity_ratio * 0.30
        + existing_bonus
        - effort_penalty
    )


def rank_final_parent_candidates(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    ranked = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        payload = dict(row)
        payload["score"] = _candidate_score(payload)
        ranked.append(payload)
    return sorted(ranked, key=lambda row: (-float(row["score"]), _key_string(row)))


__all__ = [
    "IN_PROGRESS",
    "MIN_FINAL_AFFINITY",
    "READY",
    "READY_WITH_RENTAL",
    "evaluate_final_setup",
    "rank_final_parent_candidates",
]
