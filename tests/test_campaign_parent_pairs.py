from career_bot.campaigns.parent_pairs import rank_parent_pairs


def factor(name, stars, category="pink"):
    return {"name": name, "stars": stars, "category": "aptitude" if category == "pink" else "stat"}


def veteran(trained_id, card_id, *, long=0, stamina=0, rank_score=0):
    pink = [factor("Long", long)] if long else []
    blue = [factor("Stamina", stamina, "blue")] if stamina else []
    return {
        "trained_chara_id": trained_id,
        "card_id": card_id,
        "rank_score": rank_score,
        "factor_tree": {
            "self": {"pink": pink, "blue": blue},
            "parent1": {"pink": [], "blue": []},
            "parent2": {"pink": [], "blue": []},
        },
    }


def affinity(_trainee, first, second):
    pair = frozenset({first["trained_chara_id"], second["trained_chara_id"]})
    return {"total": {frozenset({1, 2}): 100, frozenset({1, 3}): 300, frozenset({2, 3}): 200}.get(pair, 0)}


def test_pair_specific_affinity_races_can_add_aptitude_requirements_before_ranking():
    candidates = [
        veteran(1, 100201),
        veteran(2, 100301),
        veteran(3, 100401),
    ]

    rows = rank_parent_pairs(
        candidates,
        trainee_card_id=100101,
        aptitude_targets=[],
        aptitude_targets_for_pair=lambda first, second: {
            "targets": [
                {
                    "aptitude": "long",
                    "required_red_stars": 4,
                    "starting_grade": "D",
                    "achievable_target_grade": "B",
                    "supporting_race_ids": [10],
                }
            ] if {first["trained_chara_id"], second["trained_chara_id"]} == {1, 2} else [],
            "warnings": [],
        },
        factor_targets=[],
        affinity_scorer=lambda _trainee, first, second: {
            "total": 999 if {first["trained_chara_id"], second["trained_chara_id"]} == {1, 2} else 100
        },
    )

    assert [row["trained_chara_id"] for row in rows[0]["parents"]] != [1, 2]
    pair_12 = next(row for row in rows if row["trained_chara_id"] == [1, 2])
    assert pair_12["aptitude"]["feasible"] is False
    assert pair_12["aptitude_targets"][0]["supporting_race_ids"] == [10]


def test_fully_feasible_pair_beats_higher_affinity_pair():
    rows = rank_parent_pairs(
        [
            veteran(1, 100201, long=2),
            veteran(2, 100301, long=2),
            veteran(3, 100401, long=0),
        ],
        trainee_card_id=100101,
        aptitude_targets=[
            {
                "aptitude": "long",
                "required_red_stars": 4,
                "starting_grade": "D",
                "achievable_target_grade": "B",
                "supporting_race_ids": [10],
            }
        ],
        factor_targets=[],
        affinity_scorer=affinity,
    )

    assert [row["trained_chara_id"] for row in rows[0]["parents"]] == [1, 2]
    assert rows[0]["aptitude"]["feasible"] is True
    assert rows[0]["projected_displayed_affinity"] == 100


def test_when_no_pair_is_feasible_greatest_required_star_coverage_wins_and_shortfalls_are_exposed():
    rows = rank_parent_pairs(
        [
            veteran(1, 100201, long=2),
            veteran(2, 100301, long=1),
            veteran(3, 100401, long=0),
        ],
        trainee_card_id=100101,
        aptitude_targets=[
            {"aptitude": "long", "required_red_stars": 7, "supporting_race_ids": [10]}
        ],
        factor_targets=[],
        affinity_scorer=affinity,
    )

    assert [row["trained_chara_id"] for row in rows[0]["parents"]] == [1, 2]
    assert rows[0]["aptitude"]["coverage"] == 3 / 7
    assert rows[0]["aptitude"]["shortfalls"][0]["missing_red_stars"] == 4


def test_factor_goal_progress_outranks_affinity_after_aptitude_tie():
    rows = rank_parent_pairs(
        [
            veteran(1, 100201, stamina=3),
            veteran(2, 100301, stamina=3),
            veteran(3, 100401, stamina=0),
        ],
        trainee_card_id=100101,
        aptitude_targets=[],
        factor_targets=[
            {"category": "blue", "name": "stamina", "minimum_stars": 6, "priority": "required"}
        ],
        affinity_scorer=affinity,
    )

    assert [row["trained_chara_id"] for row in rows[0]["parents"]] == [1, 2]
    assert rows[0]["factor_progress"]["required_progress"] == 1.0


def test_projected_affinity_outranks_generic_rank_after_aptitude_and_goal_tie():
    first = veteran(1, 100201, rank_score=99999)
    second = veteran(2, 100301, rank_score=1)
    third = veteran(3, 100401, rank_score=999999)

    rows = rank_parent_pairs(
        [first, second, third],
        trainee_card_id=100101,
        aptitude_targets=[],
        factor_targets=[],
        affinity_scorer=affinity,
    )

    assert [row["trained_chara_id"] for row in rows[0]["parents"]] == [1, 3]
    assert rows[0]["projected_displayed_affinity"] == 300


def test_parent_pair_never_uses_two_rentals():
    rows = rank_parent_pairs(
        [
            {**veteran(1, 100201, rank_score=10), "rental": True},
            {**veteran(2, 100301, rank_score=20), "rental": True},
            veteran(3, 100401, rank_score=1),
        ],
        trainee_card_id=100101,
        aptitude_targets=[],
        factor_targets=[],
        affinity_scorer=lambda *_args: {"total": 100},
    )

    assert rows
    assert all(sum(1 for parent in row["parents"] if parent.get("rental") is True) <= 1 for row in rows)


def test_generic_rank_is_last_tiebreaker():
    rows = rank_parent_pairs(
        [
            veteran(1, 100201, rank_score=10),
            veteran(2, 100301, rank_score=20),
            veteran(3, 100401, rank_score=30),
        ],
        trainee_card_id=100101,
        aptitude_targets=[],
        factor_targets=[],
        affinity_scorer=lambda *_args: {"total": 100},
    )

    assert [row["trained_chara_id"] for row in rows[0]["parents"]] == [2, 3]
    assert rows[0]["rank_score"] == 50
