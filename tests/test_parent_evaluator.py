from career_bot.campaigns.models import ParentGoal
from career_bot.campaigns.parent_evaluator import evaluate_parent_candidate


def medium_turf_goal():
    return ParentGoal(
        surface_targets=["turf"],
        distance_targets=["medium"],
        minimum_rank="S",
        preferred_stats=["speed", "stamina"],
    )


def test_matching_medium_turf_candidate_is_accepted_with_explanations():
    result = evaluate_parent_candidate(
        medium_turf_goal(),
        {
            "trained_chara_id": 1001,
            "name": "Strong Parent",
            "rank": "S+",
            "stats": {"speed": 1200, "stamina": 1000, "power": 900},
            "aptitudes": {"turf": "A", "medium": "S"},
            "lineage_factors": [
                {"name": "turf", "stars": 2},
                {"name": "medium", "stars": 3},
            ],
            "candidate_factors": [{"name": "speed", "stars": 3}],
            "compatibility_score": 88,
            "race_history_score": 75,
        },
    )

    assert result["accepted"] is True
    assert result["score"] >= 80
    assert result["decision"] == "accept"
    assert result["matched_targets"] == ["turf:lineage", "medium:lineage"]
    assert any("rank" in reason.lower() for reason in result["reasons"])
    assert result["weaknesses"] == []


def test_missing_required_lineage_factor_rejects_candidate():
    result = evaluate_parent_candidate(
        medium_turf_goal(),
        {
            "trained_chara_id": 1002,
            "rank": "S",
            "stats": {"speed": 1200, "stamina": 1200},
            "aptitudes": {"turf": "A", "medium": "A"},
            "lineage_factors": [{"name": "medium", "stars": 2}],
            "candidate_factors": [{"name": "turf", "stars": 3}],
            "compatibility_score": 100,
            "race_history_score": 100,
        },
    )

    assert result["accepted"] is False
    assert result["decision"] == "reject"
    assert result["missing_targets"] == ["turf:lineage"]
    assert any("turf" in weakness.lower() for weakness in result["weaknesses"])


def test_candidate_factor_does_not_satisfy_lineage_requirement():
    goal = ParentGoal(
        surface_targets=["turf"],
        distance_targets=["medium"],
        target_factors=[
            {"name": "speed", "minimum_stars": 3, "scope": "candidate"},
            {"name": "medium", "minimum_stars": 2, "scope": "lineage"},
        ],
    )
    result = evaluate_parent_candidate(
        goal,
        {
            "rank": "S",
            "candidate_factors": [
                {"name": "speed", "stars": 3},
                {"name": "medium", "stars": 3},
            ],
            "lineage_factors": [],
        },
    )

    assert result["matched_targets"] == ["speed:candidate"]
    assert result["missing_targets"] == ["medium:lineage"]
    assert result["accepted"] is False


def test_rank_below_minimum_is_a_hard_rejection():
    result = evaluate_parent_candidate(
        medium_turf_goal(),
        {
            "rank": "A+",
            "lineage_factors": [
                {"name": "turf", "stars": 3},
                {"name": "medium", "stars": 3},
            ],
        },
    )

    assert result["accepted"] is False
    assert any("minimum rank" in weakness.lower() for weakness in result["weaknesses"])


def test_baseline_delta_marks_close_candidate_as_ambiguous():
    result = evaluate_parent_candidate(
        medium_turf_goal(),
        {
            "rank": "S",
            "stats": {"speed": 950, "stamina": 900},
            "aptitudes": {"turf": "A", "medium": "A"},
            "lineage_factors": [
                {"name": "turf", "stars": 2},
                {"name": "medium", "stars": 2},
            ],
            "compatibility_score": 70,
            "race_history_score": 60,
        },
        baseline_score=80,
    )

    assert result["accepted"] is True
    assert -5 <= result["baseline_delta"] <= 5
    assert result["decision"] == "ambiguous"
