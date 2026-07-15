from career_bot.campaigns.models import CampaignSparkTarget, SparkCategory
from career_bot.campaigns.parent_evaluator import evaluate_candidate_spark_targets
from career_bot.campaigns.targets import evaluate_spark_targets, spark_key


def test_spark_key_normalizes_strings_and_enum_like_values():
    assert spark_key(" BLUE ", " Stamina ") == ("blue", "stamina")
    assert spark_key(SparkCategory.PINK, " Long ") == ("pink", "long")


def test_required_blue_and_pink_targets_gate_required_completion():
    targets = [
        {"category": " BLUE ", "name": " Stamina ", "minimum_stars": 9},
        {"category": "pink", "name": "Long", "minimum_stars": 6},
        {
            "category": "pink",
            "name": "Medium",
            "minimum_stars": 3,
            "priority": "preferred",
        },
    ]
    totals = {
        ("blue", "stamina"): 9,
        ("pink", "long"): 6,
        ("pink", "medium"): 2,
    }

    result = evaluate_spark_targets(targets, totals)

    assert result["required_complete"] is True
    assert result["preferred_complete"] is False
    assert result["required_progress"] == 1.0
    assert result["preferred_progress"] == 2 / 3
    assert result["rows"] == [
        {
            "category": "blue",
            "name": "stamina",
            "minimum_stars": 9,
            "priority": "required",
            "actual_stars": 9,
            "ratio": 1.0,
            "matched": True,
        },
        {
            "category": "pink",
            "name": "long",
            "minimum_stars": 6,
            "priority": "required",
            "actual_stars": 6,
            "ratio": 1.0,
            "matched": True,
        },
        {
            "category": "pink",
            "name": "medium",
            "minimum_stars": 3,
            "priority": "preferred",
            "actual_stars": 2,
            "ratio": 2 / 3,
            "matched": False,
        },
    ]


def test_required_and_preferred_progress_are_capped_and_missing_totals_are_zero():
    result = evaluate_spark_targets(
        [
            CampaignSparkTarget(category="blue", name="Stamina", minimum_stars=9),
            {
                "category": "pink",
                "name": "Long",
                "minimum_stars": 6,
                "priority": "preferred",
            },
            {
                "category": "pink",
                "name": "Medium",
                "minimum_stars": 3,
                "priority": "preferred",
            },
        ],
        {
            ("BLUE", " STAMINA "): 12,
            ("pink", "long"): 9,
        },
    )

    assert result["required_complete"] is True
    assert result["preferred_complete"] is False
    assert result["required_progress"] == 1.0
    assert result["preferred_progress"] == 0.5
    assert [row["actual_stars"] for row in result["rows"]] == [12, 9, 0]
    assert [row["ratio"] for row in result["rows"]] == [1.0, 1.0, 0.0]


def test_duplicate_normalized_total_keys_use_max_without_double_counting():
    result = evaluate_spark_targets(
        [{"category": "blue", "name": "stamina", "minimum_stars": 9}],
        {
            ("blue", " stamina "): 5,
            ("BLUE", "stamina"): 4,
        },
    )

    assert result["rows"][0]["actual_stars"] == 5
    assert result["rows"][0]["ratio"] == 5 / 9

    result = evaluate_spark_targets(
        [{"category": "blue", "name": "stamina", "minimum_stars": 9}],
        {
            ("BLUE", "stamina"): 4,
            ("blue", " stamina "): 5,
        },
    )

    assert result["rows"][0]["actual_stars"] == 5
    assert result["rows"][0]["ratio"] == 5 / 9

    result = evaluate_spark_targets(
        [{"category": "blue", "name": "stamina", "minimum_stars": 9}],
        {("BLUE", "stamina"): -3},
    )

    assert result["rows"][0]["actual_stars"] == 0
    assert result["rows"][0]["ratio"] == 0.0


def test_empty_target_groups_report_complete_progress():
    result = evaluate_spark_targets(
        [
            {
                "category": "pink",
                "name": "Medium",
                "minimum_stars": 3,
                "priority": "preferred",
            }
        ],
        {},
    )

    assert result["required_complete"] is True
    assert result["preferred_complete"] is False
    assert result["required_progress"] == 1.0
    assert result["preferred_progress"] == 0.0

    result = evaluate_spark_targets([], {})

    assert result["required_complete"] is True
    assert result["preferred_complete"] is True
    assert result["required_progress"] == 1.0
    assert result["preferred_progress"] == 1.0


def test_parent_evaluator_adapter_reuses_normalized_target_progress():
    result = evaluate_candidate_spark_targets(
        [
            {"category": "blue", "name": "Stamina", "minimum_stars": 9},
            {
                "category": "pink",
                "name": "Medium",
                "minimum_stars": 3,
                "priority": "preferred",
            },
        ],
        {
            "spark_totals": {
                (" BLUE ", " Stamina "): 10,
                ("PINK", "Medium"): 1,
            }
        },
    )

    assert result["required_complete"] is True
    assert result["preferred_complete"] is False
    assert result["required_progress"] == 1.0
    assert result["preferred_progress"] == 1 / 3
