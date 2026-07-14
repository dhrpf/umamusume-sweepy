from career_bot.campaigns.friend_support import (
    candidate_id_for_friend,
    find_friend_support_candidates,
    resolve_friend_support_candidate,
)


def friend(
    viewer_id,
    support_card_id,
    *,
    name="Super Creek",
    support_type="Stamina",
    lb=4,
    exp=100,
    favorite=0,
    friend_state=1,
):
    return {
        "viewer_id": viewer_id,
        "support_card_id": support_card_id,
        "support_name": name,
        "type": support_type,
        "rarity": "SSR",
        "limit_break_count": lb,
        "exp": exp,
        "favorite_flag": favorite,
        "friend_state": friend_state,
    }


def selection():
    return {
        "deck": {
            "id": 4,
            "name": "Deck 4",
            "cards": [
                {"id": "30010", "name": "Fine Motion"},
                {"id": "30028", "name": "Kitasan Black"},
            ],
        },
        "trainee": {"id": "100601", "name": "Oguri Cap"},
        "friend": None,
        "veterans": [{"instance_id": 101}, {"instance_id": 202}],
        "preset": "parent-preset",
    }


def test_find_support_requires_exact_lb_and_prefers_best_owner_for_same_card():
    rows = [
        friend(10, 30111, lb=3, exp=9999, favorite=1, friend_state=2),
        friend(20, 30111, lb=4, exp=100, favorite=0, friend_state=1),
        friend(30, 30111, lb=4, exp=90, favorite=1, friend_state=2),
    ]

    result = find_friend_support_candidates(
        rows,
        selection(),
        name="Super Creek",
        limit_break=4,
    )

    assert result["match_count"] == 2
    assert result["unique_card_count"] == 1
    assert result["requires_user_choice"] is False
    assert result["recommended_candidate_id"] == candidate_id_for_friend(rows[2])
    assert all(row["limit_break_count"] == 4 for row in result["matches"])
    assert all("viewer_id" not in row for row in result["matches"])


def test_find_support_requires_choice_for_multiple_card_variants():
    rows = [
        friend(10, 30111, support_type="Stamina"),
        friend(20, 30999, support_type="Wit"),
    ]

    result = find_friend_support_candidates(
        rows,
        selection(),
        name="Super Creek",
        limit_break=4,
    )

    assert result["match_count"] == 2
    assert result["unique_card_count"] == 2
    assert result["requires_user_choice"] is True
    assert result["recommended_candidate_id"] is None

    stamina = find_friend_support_candidates(
        rows,
        selection(),
        name="Super Creek",
        support_type="Stamina",
        limit_break=4,
    )
    assert stamina["requires_user_choice"] is False
    assert stamina["matches"][0]["support_card_id"] == 30111


def test_deck_and_trainee_conflicts_are_returned_not_silently_selected():
    rows = [
        friend(10, 30028, name="Kitasan Black", support_type="Speed"),
        friend(20, 30123, name="Oguri Cap", support_type="Power"),
    ]

    deck_conflict = find_friend_support_candidates(
        rows,
        selection(),
        name="Kitasan Black",
        limit_break=4,
    )
    trainee_conflict = find_friend_support_candidates(
        rows,
        selection(),
        name="Oguri Cap",
        limit_break=4,
    )

    assert deck_conflict["selectable_count"] == 0
    assert deck_conflict["matches"][0]["selectable"] is False
    assert "already_in_deck" in deck_conflict["matches"][0]["conflicts"]
    assert trainee_conflict["selectable_count"] == 0
    assert "same_character_as_trainee" in trainee_conflict["matches"][0]["conflicts"]


def test_resolve_candidate_returns_private_selection_row_only_for_current_match():
    row = friend(10, 30111)
    candidate_id = candidate_id_for_friend(row)

    resolved = resolve_friend_support_candidate(
        [row],
        selection(),
        candidate_id=candidate_id,
    )

    assert resolved["selection_row"] == row
    assert resolved["public"]["candidate_id"] == candidate_id
    assert "viewer_id" not in resolved["public"]
