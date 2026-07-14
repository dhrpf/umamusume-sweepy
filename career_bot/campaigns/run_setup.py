from __future__ import annotations

import copy
from typing import Any

from .friend_support import normalize_support_name
from .models import (
    DeckSelectionMode,
    DeckSelectionPolicy,
    TraineeSelectionMode,
    TraineeSelectionPolicy,
)


class RunSetupSelectionError(RuntimeError):
    pass


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _normalized(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _rows(session: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = session.get(key)
    if not isinstance(value, list):
        return []
    return [copy.deepcopy(row) for row in value if isinstance(row, dict)]


def _public_trainee(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": _int(row.get("id") or row.get("card_id")),
        "name": str(row.get("name") or ""),
    }


def _selected_friend(session: dict[str, Any]) -> dict[str, Any]:
    selection = session.get("selection") if isinstance(session.get("selection"), dict) else {}
    friend = selection.get("friend") if isinstance(selection.get("friend"), dict) else {}
    return friend


def _trainee_conflicts_with_friend(
    trainee: dict[str, Any],
    friend: dict[str, Any],
) -> bool:
    friend_name = normalize_support_name(friend.get("support_name"))
    trainee_name = normalize_support_name(trainee.get("name"))
    return bool(friend_name and trainee_name and friend_name == trainee_name)


def _deck_conflicts_with_friend(
    deck: dict[str, Any],
    friend: dict[str, Any],
) -> bool:
    friend_card_id = _int(friend.get("support_card_id"))
    friend_name = normalize_support_name(friend.get("support_name"))
    cards = deck.get("cards") if isinstance(deck.get("cards"), list) else []
    for card in cards:
        if not isinstance(card, dict):
            continue
        if friend_card_id > 0 and _int(card.get("id") or card.get("support_card_id")) == friend_card_id:
            return True
        card_name = normalize_support_name(card.get("name"))
        if friend_name and card_name and friend_name == card_name:
            return True
    return False


def trainee_candidates(
    session: dict[str, Any],
    policy: TraineeSelectionPolicy,
) -> list[dict[str, Any]]:
    selection = session.get("selection") if isinstance(session.get("selection"), dict) else {}
    friend = _selected_friend(session)
    if policy.mode is TraineeSelectionMode.CURRENT:
        current = selection.get("trainee") if isinstance(selection.get("trainee"), dict) else {}
        trainee = _public_trainee(current)
        if trainee["id"] <= 0:
            raise RunSetupSelectionError(
                "Current trainee selection is empty; use trainee.mode=named or auto for a headless campaign"
            )
        if _trainee_conflicts_with_friend(trainee, friend):
            raise RunSetupSelectionError(
                "Current trainee is the same character as selected friend support"
            )
        return [trainee]

    owned = [_public_trainee(row) for row in _rows(session, "umas")]
    owned = [row for row in owned if row["id"] > 0]
    owned.sort(key=lambda row: row["id"])

    if policy.mode is TraineeSelectionMode.AUTO:
        if not owned:
            raise RunSetupSelectionError("Account has no owned trainees")
        selectable = [
            row for row in owned if not _trainee_conflicts_with_friend(row, friend)
        ]
        if not selectable:
            raise RunSetupSelectionError(
                "No owned trainee is compatible with the selected friend support"
            )
        return selectable

    if policy.card_id > 0:
        exact = [row for row in owned if row["id"] == policy.card_id]
        if not exact:
            raise RunSetupSelectionError(f"Requested trainee card {policy.card_id} is not owned")
        return exact

    wanted = _normalized(policy.name)
    exact_name = [row for row in owned if _normalized(row["name"]) == wanted]
    matches = exact_name or [row for row in owned if wanted in _normalized(row["name"])]
    if not matches:
        raise RunSetupSelectionError(f"No owned trainee matches: {policy.name}")
    selectable = [row for row in matches if not _trainee_conflicts_with_friend(row, friend)]
    if not selectable:
        raise RunSetupSelectionError(
            "Requested trainee is the same character as selected friend support"
        )
    return selectable


def _preferred_support_types(preferred_stats: list[str]) -> set[str]:
    result = set()
    for stat in preferred_stats:
        normalized = _normalized(stat)
        if normalized == "wisdom":
            result.add("wit")
        elif normalized:
            result.add(normalized)
    return result


def _deck_score(deck: dict[str, Any], preferred_types: set[str]) -> tuple[int, int, int]:
    cards = deck.get("cards") if isinstance(deck.get("cards"), list) else []
    matching = 0
    limit_break_total = 0
    for card in cards:
        if not isinstance(card, dict):
            continue
        if _normalized(card.get("type")) in preferred_types:
            matching += 1
        limit_break_total += _int(card.get("limit_break_count"))
    return matching, limit_break_total, -_int(deck.get("id") or deck.get("deck_id"))


def resolve_deck(
    session: dict[str, Any],
    policy: DeckSelectionPolicy,
    *,
    preferred_stats: list[str],
) -> dict[str, Any]:
    selection = session.get("selection") if isinstance(session.get("selection"), dict) else {}
    friend = _selected_friend(session)
    if policy.mode is DeckSelectionMode.CURRENT:
        current = selection.get("deck") if isinstance(selection.get("deck"), dict) else {}
        if _int(current.get("id") or current.get("deck_id")) <= 0 or not current.get("cards"):
            raise RunSetupSelectionError(
                "Current deck selection is empty; use deck.mode=named or auto for a headless campaign"
            )
        if _deck_conflicts_with_friend(current, friend):
            raise RunSetupSelectionError(
                "Current deck conflicts with selected friend support"
            )
        return copy.deepcopy(current)

    decks = _rows(session, "decks")
    decks = [
        row
        for row in decks
        if _int(row.get("id") or row.get("deck_id")) > 0 and row.get("cards")
    ]
    if not decks:
        raise RunSetupSelectionError("Account has no usable support decks")

    if policy.mode is DeckSelectionMode.AUTO:
        selectable = [row for row in decks if not _deck_conflicts_with_friend(row, friend)]
        if not selectable:
            raise RunSetupSelectionError(
                "No support deck is compatible with the selected friend support"
            )
        preferred_types = _preferred_support_types(preferred_stats)
        return max(selectable, key=lambda row: _deck_score(row, preferred_types))

    if policy.deck_id > 0:
        matches = [
            row
            for row in decks
            if _int(row.get("id") or row.get("deck_id")) == policy.deck_id
        ]
    else:
        wanted = _normalized(policy.name)
        exact = [row for row in decks if _normalized(row.get("name")) == wanted]
        matches = exact or [row for row in decks if wanted in _normalized(row.get("name"))]

    if not matches:
        raise RunSetupSelectionError(
            f"No support deck matches: {policy.name or policy.deck_id}"
        )
    if len(matches) > 1:
        names = ", ".join(str(row.get("name") or row.get("id")) for row in matches[:5])
        raise RunSetupSelectionError(f"Multiple decks match '{policy.name}': {names}")
    if _deck_conflicts_with_friend(matches[0], friend):
        raise RunSetupSelectionError(
            "Requested support deck conflicts with selected friend support"
        )
    return matches[0]
