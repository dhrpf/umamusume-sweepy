import pytest

from career_bot.campaigns.aptitude_planner import (
    evaluate_aptitude_pair,
    generate_aptitude_targets,
)


@pytest.mark.parametrize(
    ("grade", "required", "target"),
    [
        ("C", 1, "B"),
        ("D", 4, "B"),
        ("E", 7, "B"),
        ("F", 10, "B"),
        ("G", 10, "C"),
    ],
)
def test_race_required_aptitude_thresholds(grade, required, target):
    result = generate_aptitude_targets(
        trainee_card_id=100101,
        race_ids=[10],
        race_rows=[
            {"program_id": 10, "terrain": "Dirt", "distance": "Long"},
        ],
        base_aptitudes={"100101": {"dirt": grade, "long": "A"}},
    )

    assert result["targets"] == [
        {
            "aptitude": "dirt",
            "starting_grade": grade,
            "required_red_stars": required,
            "achievable_target_grade": target,
            "supporting_race_ids": [10],
        }
    ]


def test_only_race_required_ground_and_distance_below_b_are_generated():
    result = generate_aptitude_targets(
        trainee_card_id=100101,
        race_ids=[10, 20],
        race_rows=[
            {"program_id": 10, "terrain": "Turf", "distance": "Mile"},
            {"program_id": 20, "terrain": "Dirt", "distance": "Long"},
        ],
        base_aptitudes={
            "100101": {
                "turf": "A",
                "dirt": "D",
                "mile": "B",
                "long": "C",
                "front": "G",
            }
        },
    )

    assert [row["aptitude"] for row in result["targets"]] == ["dirt", "long"]
    assert result["targets"][0]["supporting_race_ids"] == [20]
    assert result["warnings"] == []


def test_missing_base_aptitude_warns_and_omits_target():
    result = generate_aptitude_targets(
        trainee_card_id=100101,
        race_ids=[10],
        race_rows=[{"program_id": 10, "terrain": "Dirt", "distance": "Long"}],
        base_aptitudes={"100101": {"long": "C"}},
    )

    assert [row["aptitude"] for row in result["targets"]] == ["long"]
    assert result["warnings"] == ["Missing base aptitude data for dirt"]


def parent(tree):
    return {"factor_tree": tree, "trained_chara_id": tree.get("id", 0)}


def node(*factors):
    return {"pink": list(factors)}


def factor(name, stars):
    return {"category": "aptitude", "name": name, "stars": stars}


def test_pair_evidence_aggregates_direct_veteran_gp1_and_gp2():
    targets = [
        {
            "aptitude": "long",
            "starting_grade": "D",
            "required_red_stars": 4,
            "achievable_target_grade": "B",
            "supporting_race_ids": [10],
        }
    ]
    result = evaluate_aptitude_pair(
        targets,
        parent(
            {
                "self": node(factor("Long", 1)),
                "parent1": node(factor("Long", 1)),
                "parent2": node(),
            }
        ),
        parent(
            {
                "self": node(factor("Long", 1)),
                "parent1": node(),
                "parent2": node(factor("Long", 1)),
            }
        ),
    )

    assert result["feasible"] is True
    assert result["coverage"] == 1.0
    evidence = result["evidence"]["long"]
    assert evidence["total_stars"] == 4
    assert [(row["parent"], row["source"], row["stars"]) for row in evidence["sources"]] == [
        (1, "direct_veteran", 1),
        (1, "gp1", 1),
        (2, "direct_veteran", 1),
        (2, "gp2", 1),
    ]
    assert result["shortfalls"] == []


def test_missing_or_undecodable_factor_metadata_gets_no_credit_and_exposes_shortfall():
    targets = [
        {
            "aptitude": "dirt",
            "starting_grade": "E",
            "required_red_stars": 7,
            "achievable_target_grade": "B",
            "supporting_race_ids": [20],
        }
    ]
    result = evaluate_aptitude_pair(
        targets,
        parent({"self": {"pink": [{"name": "Unknown factor 1", "stars": 0}]}}),
        parent({}),
    )

    assert result["feasible"] is False
    assert result["coverage"] == 0.0
    assert result["shortfalls"] == [
        {
            "aptitude": "dirt",
            "required_red_stars": 7,
            "actual_red_stars": 0,
            "missing_red_stars": 7,
        }
    ]
