import pytest

from career_bot.campaigns.models import DeckSelectionPolicy, TraineeSelectionPolicy
from career_bot.campaigns.run_setup import (
    RunSetupSelectionError,
    resolve_deck,
    trainee_candidates,
)


def session_fixture():
    return {
        "selection": {
            "trainee": {"id": 100601, "name": "Oguri Cap"},
            "deck": {
                "id": 9,
                "name": "Current Deck",
                "cards": [{"id": 9001, "type": "Speed", "limit_break_count": 0}],
            },
        },
        "umas": [
            {"id": 100601, "name": "Oguri Cap"},
            {"id": 100602, "name": "Oguri Cap"},
            {"id": 100301, "name": "Mejiro Ryan"},
        ],
        "decks": [
            {
                "id": 1,
                "name": "Speed Deck",
                "cards": [
                    {"id": 101, "type": "Speed", "limit_break_count": 4},
                    {"id": 102, "type": "Speed", "limit_break_count": 3},
                    {"id": 103, "type": "Power", "limit_break_count": 4},
                ],
            },
            {
                "id": 2,
                "name": "Stamina Deck",
                "cards": [
                    {"id": 201, "type": "Stamina", "limit_break_count": 2},
                    {"id": 202, "type": "Stamina", "limit_break_count": 2},
                    {"id": 203, "type": "Stamina", "limit_break_count": 1},
                ],
            },
            {
                "id": 3,
                "name": "Maxed Stamina",
                "cards": [
                    {"id": 301, "type": "Stamina", "limit_break_count": 4},
                    {"id": 302, "type": "Stamina", "limit_break_count": 4},
                    {"id": 303, "type": "Stamina", "limit_break_count": 4},
                ],
            },
        ],
    }


def test_current_trainee_policy_uses_existing_selection():
    candidates = trainee_candidates(
        session_fixture(),
        TraineeSelectionPolicy(mode="current"),
    )

    assert candidates == [{"id": 100601, "name": "Oguri Cap"}]


def test_named_trainee_policy_returns_all_matching_owned_variants_for_later_affinity_ranking():
    candidates = trainee_candidates(
        session_fixture(),
        TraineeSelectionPolicy(mode="named", name="oguri"),
    )

    assert [row["id"] for row in candidates] == [100601, 100602]


def test_named_trainee_card_id_is_exact_and_must_be_owned():
    session = session_fixture()

    assert trainee_candidates(
        session,
        TraineeSelectionPolicy(mode="named", card_id=100602),
    ) == [{"id": 100602, "name": "Oguri Cap"}]

    with pytest.raises(RunSetupSelectionError, match="not owned"):
        trainee_candidates(
            session,
            TraineeSelectionPolicy(mode="named", card_id=999999),
        )


def test_auto_trainee_policy_returns_all_owned_cards_in_stable_card_id_order():
    candidates = trainee_candidates(
        session_fixture(),
        TraineeSelectionPolicy(mode="auto"),
    )

    assert [row["id"] for row in candidates] == [100301, 100601, 100602]


def test_trainee_resolution_rejects_same_character_as_selected_friend_support():
    session = session_fixture()
    session["umas"].append({"id": 100701, "name": "Super Creek"})
    session["selection"]["friend"] = {
        "viewer_id": 90001,
        "support_card_id": 999,
        "support_name": "Super Creek",
    }

    automatic = trainee_candidates(
        session,
        TraineeSelectionPolicy(mode="auto"),
    )

    assert 100701 not in [row["id"] for row in automatic]
    with pytest.raises(RunSetupSelectionError, match="same character as selected friend support"):
        trainee_candidates(
            session,
            TraineeSelectionPolicy(mode="named", name="Super Creek"),
        )


def test_auto_deck_prefers_matching_stat_count_then_limit_break_total():
    selected = resolve_deck(
        session_fixture(),
        DeckSelectionPolicy(mode="auto"),
        preferred_stats=["stamina"],
    )

    assert selected["id"] == 3
    assert selected["name"] == "Maxed Stamina"


def test_auto_deck_avoids_selected_friend_support_conflicts():
    session = session_fixture()
    session["selection"]["friend"] = {
        "viewer_id": 90001,
        "support_card_id": 301,
        "support_name": "Super Creek",
    }

    selected = resolve_deck(
        session,
        DeckSelectionPolicy(mode="auto"),
        preferred_stats=["stamina"],
    )

    assert selected["id"] == 2


def test_auto_deck_maps_wisdom_to_wit_and_uses_deck_id_for_final_tie_break():
    session = session_fixture()
    session["decks"] = [
        {"id": 8, "name": "Wit B", "cards": [{"id": 1, "type": "Wit", "limit_break_count": 4}]},
        {"id": 7, "name": "Wit A", "cards": [{"id": 2, "type": "Wit", "limit_break_count": 4}]},
    ]

    selected = resolve_deck(
        session,
        DeckSelectionPolicy(mode="auto"),
        preferred_stats=["wisdom"],
    )

    assert selected["id"] == 7


def test_named_deck_supports_exact_id_or_unique_case_insensitive_substring():
    session = session_fixture()

    by_id = resolve_deck(
        session,
        DeckSelectionPolicy(mode="named", deck_id=2),
        preferred_stats=["stamina"],
    )
    by_name = resolve_deck(
        session,
        DeckSelectionPolicy(mode="named", name="maxed"),
        preferred_stats=["stamina"],
    )

    assert by_id["name"] == "Stamina Deck"
    assert by_name["id"] == 3


def test_missing_or_ambiguous_named_selection_fails_with_actionable_error():
    session = session_fixture()
    session["decks"].append({"id": 4, "name": "Stamina Experimental", "cards": [{"id": 401}]})

    with pytest.raises(RunSetupSelectionError, match="No owned trainee"):
        trainee_candidates(
            session,
            TraineeSelectionPolicy(mode="named", name="Rice Shower"),
        )

    with pytest.raises(RunSetupSelectionError, match="Multiple decks"):
        resolve_deck(
            session,
            DeckSelectionPolicy(mode="named", name="stamina"),
            preferred_stats=["stamina"],
        )
