from __future__ import annotations

import copy
from typing import Any

from .models import ParentCampaignSpec


class LineagePlanningError(RuntimeError):
    pass


def _selected_trainee_id(session: dict[str, Any]) -> int:
    selection = session.get("selection") if isinstance(session.get("selection"), dict) else {}
    trainee = selection.get("trainee") if isinstance(selection.get("trainee"), dict) else {}
    return int(trainee.get("id") or trainee.get("card_id") or 0)


def build_inheritance_request(
    spec: ParentCampaignSpec | dict[str, Any],
    session: dict[str, Any],
    *,
    pool: str = "both",
    limit: int = 50,
) -> dict[str, Any]:
    validated = ParentCampaignSpec.model_validate(spec)
    target_card_id = _selected_trainee_id(session)
    if target_card_id <= 0:
        raise LineagePlanningError(
            "Current Sweepy selection has no trainee; select a trainee before planning lineage"
        )
    normalized_pool = str(pool or "both").strip().lower()
    if normalized_pool not in {"owned", "veteran", "both"}:
        raise LineagePlanningError("pool must be owned, veteran, or both")
    goal = validated.goal
    return {
        "target_card_id": target_card_id,
        "pool": normalized_pool,
        "goal": {
            "distance": goal.distance_targets[0],
            "surface": goal.surface_targets[0],
        },
        "limit": max(1, min(int(limit), 50)),
    }


def _source(parent: Any) -> str:
    if not isinstance(parent, dict):
        return ""
    source = str(parent.get("source") or "").strip().lower()
    return source if source in {"owned", "veteran"} else ""


def choose_lineage_setup(response: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(response, dict) or not response.get("success"):
        detail = response.get("detail") if isinstance(response, dict) else "invalid response"
        raise LineagePlanningError(f"Inheritance recommendation failed: {detail}")
    rows = response.get("results") if isinstance(response.get("results"), list) else []
    supported = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        sources = [_source(row.get("parent1")), _source(row.get("parent2"))]
        if any(not source for source in sources):
            continue
        if sources.count("veteran") > 1:
            continue
        supported.append(row)
    if not supported:
        raise LineagePlanningError(
            "No supported parent pair found; Sweepy requires two owned parents or one owned plus one rental"
        )
    supported.sort(
        key=lambda row: (
            -float(row.get("score") or 0.0),
            int(row.get("rank") or 999999),
        )
    )
    return copy.deepcopy(supported[0])


def _row_id(row: Any) -> int:
    if not isinstance(row, dict):
        return 0
    return int(
        row.get("instance_id")
        or row.get("trained_chara_id")
        or row.get("id")
        or 0
    )


def _find_parent(session: dict[str, Any], reference: dict[str, Any]) -> dict[str, Any]:
    parent_id = int(reference.get("id") or 0)
    source = _source(reference)
    key = "parents" if source == "owned" else "friendVeterans"
    rows = session.get(key) if isinstance(session.get(key), list) else []
    for row in rows:
        if isinstance(row, dict) and _row_id(row) == parent_id:
            resolved = copy.deepcopy(row)
            resolved.setdefault("instance_id", parent_id)
            resolved.setdefault("trained_chara_id", parent_id)
            return resolved
    raise LineagePlanningError(
        f"Recommended {source or 'unknown'} parent {parent_id} is not available in current session"
    )


def resolve_lineage_selection(
    session: dict[str, Any],
    setup: dict[str, Any],
) -> dict[str, Any]:
    selection = session.get("selection") if isinstance(session.get("selection"), dict) else {}
    for required in ("trainee", "deck", "friend"):
        if not isinstance(selection.get(required), dict) or not selection.get(required):
            raise LineagePlanningError(
                f"Current Sweepy selection has no {required}; configure it before campaign planning"
            )

    references = [setup.get("parent1"), setup.get("parent2")]
    if not all(isinstance(item, dict) for item in references):
        raise LineagePlanningError("Inheritance recommendation has incomplete parent references")
    resolved = [_find_parent(session, item) for item in references]
    if sum(1 for row in resolved if row.get("viewer_id")) > 1:
        raise LineagePlanningError("Sweepy Career supports at most one rental parent")

    updated_selection = copy.deepcopy(selection)
    updated_selection["veterans"] = resolved
    summary_parents = []
    for reference, row in zip(references, resolved):
        summary_parents.append(
            {
                "trained_chara_id": _row_id(row),
                "name": str(row.get("name") or reference.get("name") or ""),
                "source": _source(reference),
            }
        )

    return {
        "selection": updated_selection,
        "summary": {
            "score": float(setup.get("score") or 0.0),
            "rank": int(setup.get("rank") or 0),
            "compat_total": int(setup.get("compat_total") or 0),
            "compat_tier": str(setup.get("compat_tier") or ""),
            "race_score": int(setup.get("race_score") or 0),
            "parents": summary_parents,
            "spark_hits": copy.deepcopy(setup.get("spark_hits") or []),
        },
        "setup": copy.deepcopy(setup),
    }
