from career_bot.campaigns.final_setup import (
    MIN_FINAL_AFFINITY,
    evaluate_final_setup,
    rank_final_parent_candidates,
)


def test_affinity_exactly_150_passes_final_gate():
    result = evaluate_final_setup(
        True,
        [{"key": "owned-a", "affinity": MIN_FINAL_AFFINITY, "rental": False}],
        allow_rental=False,
    )

    assert result["status"] == "READY"
    assert result["best_affinity"] == 150
    assert result["best_pairing"]["key"] == "owned-a"


def test_below_150_stays_in_progress():
    result = evaluate_final_setup(
        True,
        [{"key": "owned-a", "affinity": 149, "rental": False}],
        allow_rental=False,
    )

    assert result["status"] == "IN_PROGRESS"
    assert result["best_affinity"] == 149
    assert result["best_pairing"]["key"] == "owned-a"


def test_required_incomplete_never_passes_even_with_high_affinity():
    result = evaluate_final_setup(
        False,
        [{"key": "owned-a", "affinity": 220, "rental": False}],
        allow_rental=False,
    )

    assert result["status"] == "IN_PROGRESS"
    assert result["best_affinity"] == 220


def test_rental_only_pairing_is_filtered_when_rental_disabled():
    result = evaluate_final_setup(
        True,
        [{"key": "rental-a", "affinity": 180, "rental": True}],
        allow_rental=False,
    )

    assert result == {
        "status": "IN_PROGRESS",
        "best_affinity": 0,
        "best_pairing": None,
    }


def test_rental_pairing_reports_rental_status_when_enabled():
    result = evaluate_final_setup(
        True,
        [{"key": "rental-a", "affinity": 180, "rental": True}],
        allow_rental=True,
    )

    assert result["status"] == "READY_WITH_RENTAL"
    assert result["best_affinity"] == 180
    assert result["best_pairing"]["key"] == "rental-a"


def test_owned_pairing_wins_equal_affinity_tie_over_rental():
    result = evaluate_final_setup(
        True,
        [
            {"key": "rental-a", "affinity": 180, "rental": True},
            {"key": "owned-a", "affinity": 180, "rental": False},
        ],
        allow_rental=True,
    )

    assert result["status"] == "READY"
    assert result["best_pairing"]["key"] == "owned-a"


def test_passing_owned_pairing_wins_over_higher_affinity_rental():
    result = evaluate_final_setup(
        True,
        [
            {"key": "rental-a", "affinity": 220, "rental": True},
            {"key": "owned-a", "affinity": 150, "rental": False},
        ],
        allow_rental=True,
    )

    assert result["status"] == "READY"
    assert result["best_affinity"] == 150
    assert result["best_pairing"]["key"] == "owned-a"


def test_pairing_same_key_affinity_tie_is_independent_of_input_order():
    pairings = [
        {"key": "owned-a", "affinity": 150, "variant": "z"},
        {"key": "owned-a", "affinity": 150, "variant": "a"},
    ]

    forward = evaluate_final_setup(True, pairings, allow_rental=False)
    reversed_result = evaluate_final_setup(
        True,
        list(reversed(pairings)),
        allow_rental=False,
    )

    assert forward["best_pairing"] == reversed_result["best_pairing"]
    assert forward["best_pairing"]["variant"] == "a"


def test_no_pairings_returns_empty_in_progress_result():
    assert evaluate_final_setup(True, [], allow_rental=True) == {
        "status": "IN_PROGRESS",
        "best_affinity": 0,
        "best_pairing": None,
    }


def test_existing_near_complete_veteran_beats_theoretical_candidate():
    ranked = rank_final_parent_candidates(
        [
            {
                "key": "future-perfect",
                "required_progress": 1.0,
                "preferred_progress": 1.0,
                "best_affinity": 200,
                "existing": False,
                "effort": 1.0,
            },
            {
                "key": "owned-veteran",
                "required_progress": 0.95,
                "preferred_progress": 0.9,
                "best_affinity": 190,
                "existing": True,
                "effort": 0.0,
            },
        ]
    )

    assert [row["key"] for row in ranked] == ["owned-veteran", "future-perfect"]
    assert ranked[0]["score"] > ranked[1]["score"]


def test_rank_ties_use_key_string_deterministically():
    ranked = rank_final_parent_candidates(
        [
            {"key": "b", "required_progress": 0.5},
            {"key": "a", "required_progress": 0.5},
        ]
    )

    assert [row["key"] for row in ranked] == ["a", "b"]


def test_rank_same_key_score_tie_is_independent_of_input_order():
    rows = [
        {"key": "same", "required_progress": 0.5, "variant": "z"},
        {"key": "same", "required_progress": 0.5, "variant": "a"},
    ]

    forward = rank_final_parent_candidates(rows)
    reversed_result = rank_final_parent_candidates(list(reversed(rows)))

    assert forward == reversed_result
    assert [row["variant"] for row in forward] == ["a", "z"]
