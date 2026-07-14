from __future__ import annotations

import hashlib
import re
from typing import Any


class FriendSupportSelectionError(RuntimeError):
    pass


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def normalize_support_name(value: Any) -> str:
    text = re.sub(r"\([^)]*\)", "", str(value or "").lower())
    return re.sub(r"[^a-z0-9]+", "", text)


def candidate_id_for_friend(friend: dict[str, Any]) -> str:
    viewer_id = _int(friend.get("viewer_id"))
    support_card_id = _int(friend.get("support_card_id"))
    if viewer_id <= 0 or support_card_id <= 0:
        raise FriendSupportSelectionError("Friend support is missing viewer or support card ID")
    digest = hashlib.sha256(f"{viewer_id}:{support_card_id}".encode("utf-8")).hexdigest()
    return f"friend-{digest[:20]}"


def _selection_conflicts(friend: dict[str, Any], selection: dict[str, Any]) -> list[str]:
    conflicts: list[str] = []
    support_card_id = str(_int(friend.get("support_card_id")))
    support_name = normalize_support_name(friend.get("support_name"))

    deck = selection.get("deck") if isinstance(selection.get("deck"), dict) else {}
    cards = deck.get("cards") if isinstance(deck.get("cards"), list) else []
    deck_ids = {str(_int(row.get("id"))) for row in cards if isinstance(row, dict)}
    deck_names = {
        normalize_support_name(row.get("name"))
        for row in cards
        if isinstance(row, dict) and normalize_support_name(row.get("name"))
    }
    if support_card_id in deck_ids or (support_name and support_name in deck_names):
        conflicts.append("already_in_deck")

    trainee = selection.get("trainee") if isinstance(selection.get("trainee"), dict) else {}
    trainee_name = normalize_support_name(trainee.get("name"))
    if support_name and trainee_name and support_name == trainee_name:
        conflicts.append("same_character_as_trainee")
    return conflicts


def _public_candidate(friend: dict[str, Any], selection: dict[str, Any]) -> dict[str, Any]:
    conflicts = _selection_conflicts(friend, selection)
    return {
        "candidate_id": candidate_id_for_friend(friend),
        "support_card_id": _int(friend.get("support_card_id")),
        "support_name": str(friend.get("support_name") or ""),
        "type": str(friend.get("type") or ""),
        "rarity": str(friend.get("rarity") or ""),
        "limit_break_count": _int(friend.get("limit_break_count")),
        "exp": _int(friend.get("exp")),
        "favorite": bool(_int(friend.get("favorite_flag"))),
        "following": _int(friend.get("friend_state")) >= 2,
        "selectable": not conflicts,
        "conflicts": conflicts,
    }


def _matches_query(
    friend: dict[str, Any],
    *,
    name: str,
    support_type: str,
    limit_break: int,
    support_card_id: int,
) -> bool:
    if _int(friend.get("limit_break_count")) != int(limit_break):
        return False
    if support_card_id and _int(friend.get("support_card_id")) != int(support_card_id):
        return False
    if support_type and str(friend.get("type") or "").strip().casefold() != support_type.strip().casefold():
        return False
    query_name = normalize_support_name(name)
    friend_name = normalize_support_name(friend.get("support_name"))
    return not query_name or query_name in friend_name


def _candidate_sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        0 if row.get("selectable") else 1,
        0 if row.get("following") else 1,
        0 if row.get("favorite") else 1,
        -_int(row.get("exp")),
        _int(row.get("support_card_id")),
        str(row.get("candidate_id") or ""),
    )


def find_friend_support_candidates(
    friends: list[dict[str, Any]] | None,
    selection: dict[str, Any] | None,
    *,
    name: str = "",
    support_type: str = "",
    limit_break: int = 4,
    support_card_id: int = 0,
) -> dict[str, Any]:
    normalized_selection = selection if isinstance(selection, dict) else {}
    matched: list[dict[str, Any]] = []
    for friend in friends or []:
        if not isinstance(friend, dict):
            continue
        if not _matches_query(
            friend,
            name=name,
            support_type=support_type,
            limit_break=limit_break,
            support_card_id=support_card_id,
        ):
            continue
        try:
            matched.append(_public_candidate(friend, normalized_selection))
        except FriendSupportSelectionError:
            continue

    matched.sort(key=_candidate_sort_key)
    selectable = [row for row in matched if row.get("selectable")]
    unique_card_ids = {int(row["support_card_id"]) for row in selectable}
    requires_user_choice = len(unique_card_ids) > 1
    recommended = None
    if selectable and not requires_user_choice:
        recommended = str(selectable[0]["candidate_id"])

    return {
        "query": {
            "name": str(name or ""),
            "type": str(support_type or ""),
            "limit_break_count": int(limit_break),
            "support_card_id": int(support_card_id or 0),
        },
        "match_count": len(matched),
        "selectable_count": len(selectable),
        "unique_card_count": len(unique_card_ids),
        "requires_user_choice": requires_user_choice,
        "recommended_candidate_id": recommended,
        "matches": matched,
    }


def resolve_friend_support_candidate(
    friends: list[dict[str, Any]] | None,
    selection: dict[str, Any] | None,
    *,
    candidate_id: str,
) -> dict[str, Any]:
    wanted = str(candidate_id or "").strip()
    if not wanted:
        raise FriendSupportSelectionError("candidate_id is required")
    normalized_selection = selection if isinstance(selection, dict) else {}
    for friend in friends or []:
        if not isinstance(friend, dict):
            continue
        try:
            current_id = candidate_id_for_friend(friend)
        except FriendSupportSelectionError:
            continue
        if current_id != wanted:
            continue
        public = _public_candidate(friend, normalized_selection)
        if not public.get("selectable"):
            conflicts = ", ".join(public.get("conflicts") or []) or "unknown conflict"
            raise FriendSupportSelectionError(f"Friend support is not selectable: {conflicts}")
        return {"selection_row": dict(friend), "public": public}
    raise FriendSupportSelectionError("Friend support candidate is no longer available")
