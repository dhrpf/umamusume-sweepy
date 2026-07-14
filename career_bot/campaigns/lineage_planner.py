from __future__ import annotations

import copy
from typing import Any

from career_bot.affinity import card_to_chara_id

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
            "distance": goal.distance_targets[0] if goal.distance_targets else "",
            "surface": goal.surface_targets[0] if goal.surface_targets else "",
            "target_factors": [
                row.model_dump(mode="json") for row in goal.target_factors
            ],
        },
        "limit": max(1, min(int(limit), 50)),
    }


def _source(parent: Any) -> str:
    if not isinstance(parent, dict):
        return ""
    source = str(parent.get("source") or "").strip().lower()
    return source if source in {"owned", "veteran"} else ""


def _reference_id(reference: Any) -> int:
    if not isinstance(reference, dict):
        return 0
    try:
        return int(
            reference.get("id")
            or reference.get("instance_id")
            or reference.get("trained_chara_id")
            or 0
        )
    except (TypeError, ValueError):
        return 0


def _session_reference_row(
    session: dict[str, Any] | None,
    reference: Any,
) -> dict[str, Any] | None:
    if not isinstance(session, dict) or not isinstance(reference, dict):
        return None
    source = _source(reference)
    key = "parents" if source == "owned" else "friendVeterans"
    wanted = _reference_id(reference)
    rows = session.get(key) if isinstance(session.get(key), list) else []
    for row in rows:
        if isinstance(row, dict) and _row_id(row) == wanted:
            return row
    return None


def _reference_base_chara_id(
    reference: Any,
    session: dict[str, Any] | None = None,
) -> int:
    if not isinstance(reference, dict):
        return 0
    try:
        explicit = int(reference.get("base_chara_id") or 0)
    except (TypeError, ValueError):
        explicit = 0
    if explicit > 0:
        return explicit
    try:
        card_id = int(reference.get("card_id") or 0)
    except (TypeError, ValueError):
        card_id = 0
    if card_id <= 0:
        resolved = _session_reference_row(session, reference)
        try:
            card_id = int((resolved or {}).get("card_id") or 0)
        except (TypeError, ValueError):
            card_id = 0
    return card_to_chara_id(card_id) if card_id > 0 else 0


def _self_factor_stars(row: dict[str, Any] | None, name: str) -> int:
    if not isinstance(row, dict):
        return 0
    tree = row.get("tree") if isinstance(row.get("tree"), dict) else {}
    self_node = tree.get("self") if isinstance(tree.get("self"), dict) else {}
    factors = self_node.get("factors") if isinstance(self_node.get("factors"), list) else row.get("factors")
    result = 0
    for factor in factors or []:
        if not isinstance(factor, dict):
            continue
        factor_name = str(factor.get("name") or factor.get("factor_name") or "").strip().casefold()
        category = str(factor.get("category") or "").strip().casefold()
        if factor_name != name.strip().casefold() or category not in {"", "stat"}:
            continue
        try:
            result = max(result, int(factor.get("stars") or factor.get("star") or 0))
        except (TypeError, ValueError):
            continue
    return result


def _direct_lineage_target_evidence(
    references: list[dict[str, Any]],
    session: dict[str, Any] | None,
    target_factors: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], bool]:
    evidence: list[dict[str, Any]] = []
    feasible = True
    for target in target_factors or []:
        if not isinstance(target, dict) or not bool(target.get("required", True)):
            continue
        if str(target.get("scope") or "lineage").strip().lower() != "lineage":
            continue
        if str(target.get("aggregation") or "sum").strip().lower() != "sum":
            continue
        if str(target.get("lineage_depth") or "direct").strip().lower() != "direct":
            continue
        name = str(target.get("name") or "").strip().lower()
        minimum = int(target.get("minimum_stars") or 0)
        if not name or minimum <= 0:
            continue
        rows = [_session_reference_row(session, reference) for reference in references]
        parent_stars = [_self_factor_stars(row, name) for row in rows]
        maximum_total = sum(parent_stars) + 3
        item = {
            "name": name,
            "required_stars": minimum,
            "parent1_stars": parent_stars[0],
            "parent2_stars": parent_stars[1],
            "maximum_candidate_stars": 3,
            "maximum_total_stars": maximum_total,
            "feasible": maximum_total >= minimum,
        }
        evidence.append(item)
        feasible = feasible and bool(item["feasible"])
    return evidence, feasible


def choose_lineage_setup(
    response: dict[str, Any],
    *,
    target_card_id: int = 0,
    session: dict[str, Any] | None = None,
    target_factors: list[dict[str, Any]] | None = None,
    ranking: str = "score",
) -> dict[str, Any]:
    if not isinstance(response, dict) or not response.get("success"):
        detail = response.get("detail") if isinstance(response, dict) else "invalid response"
        raise LineagePlanningError(f"Inheritance recommendation failed: {detail}")
    rows = response.get("results") if isinstance(response.get("results"), list) else []
    try:
        target_base = int(response.get("target_base_chara_id") or 0)
    except (TypeError, ValueError):
        target_base = 0
    if target_base <= 0:
        try:
            normalized_target_card_id = int(target_card_id or 0)
        except (TypeError, ValueError):
            normalized_target_card_id = 0
        target_base = (
            card_to_chara_id(normalized_target_card_id)
            if normalized_target_card_id > 0
            else 0
        )
    supported = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        references = [row.get("parent1"), row.get("parent2")]
        sources = [_source(reference) for reference in references]
        if any(not source for source in sources):
            continue
        if sources.count("veteran") > 1:
            continue
        if row.get("target_factor_feasible") is False:
            continue
        bases = [_reference_base_chara_id(reference, session) for reference in references]
        if target_base and target_base in bases:
            continue
        if bases[0] and bases[0] == bases[1]:
            continue
        evidence, feasible = _direct_lineage_target_evidence(
            references,
            session,
            target_factors,
        )
        if not feasible:
            continue
        candidate = copy.deepcopy(row)
        if evidence:
            candidate["target_factor_evidence"] = evidence
        supported.append(candidate)
    if not supported:
        raise LineagePlanningError(
            "No supported parent pair found; Sweepy requires two owned parents or one owned plus one rental"
        )
    normalized_ranking = str(ranking or "score").strip().lower()
    if normalized_ranking not in {"score", "affinity"}:
        raise LineagePlanningError("ranking must be score or affinity")
    if normalized_ranking == "affinity":
        supported.sort(
            key=lambda row: (
                -int(row.get("compat_total") or 0),
                -float(row.get("score") or 0.0),
                int(row.get("rank") or 999999),
            )
        )
    else:
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
            "target_factor_evidence": copy.deepcopy(
                setup.get("target_factor_evidence") or []
            ),
        },
        "setup": copy.deepcopy(setup),
    }
