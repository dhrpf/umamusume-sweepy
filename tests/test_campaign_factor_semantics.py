from career_bot.campaigns.factor_semantics import (
    direct_lineage_spark_totals,
    parent_pair_targets,
    ready_parent_targets,
    self_spark_totals,
)


def test_self_totals_ignore_parents_and_grandparents():
    tree = {
        "self": {"factors": [{"category": "stat", "name": "Power", "stars": 2}]},
        "p1": {"factors": [{"category": "stat", "name": "Power", "stars": 3}]},
        "p2": {"factors": [{"category": "stat", "name": "Power", "stars": 3}]},
        "gp1": {"factors": [{"category": "stat", "name": "Power", "stars": 3}]},
    }

    assert self_spark_totals(tree) == {("blue", "power"): 2}


def test_direct_lineage_totals_include_self_and_direct_parents_only():
    tree = {
        "self": {"factors": [{"category": "stat", "name": "Power", "stars": 2}]},
        "p1": {"factors": [{"category": "stat", "name": "Power", "stars": 3}]},
        "p2": {"factors": [{"category": "stat", "name": "Power", "stars": 3}]},
        "gp1": {"factors": [{"category": "stat", "name": "Power", "stars": 3}]},
        "gp2": {"factors": [{"category": "aptitude", "name": "Long", "stars": 2}]},
    }

    assert direct_lineage_spark_totals(tree) == {("blue", "power"): 8}


def test_direct_lineage_supports_parent_aliases_and_bucket_style_nodes():
    tree = {
        "self": {
            "blue": [{"name": "Power", "stars": 3}],
            "pink": [{"name": "Long", "stars": 1}],
        },
        "parent1": {
            "blue": [{"name": "Power", "stars": 3}],
            "pink": [{"name": "Long", "stars": 2}],
        },
        "parent2": {
            "blue": [{"name": "Power", "stars": 2}],
        },
        "gp1": {
            "blue": [{"name": "Power", "stars": 3}],
            "pink": [{"name": "Long", "stars": 3}],
        },
    }

    assert self_spark_totals(tree) == {
        ("blue", "power"): 3,
        ("pink", "long"): 1,
    }
    assert direct_lineage_spark_totals(tree) == {
        ("blue", "power"): 8,
        ("pink", "long"): 3,
    }


def test_ready_parent_target_for_nine_star_goal_requires_three_self_stars():
    targets = [
        {"category": "blue", "name": "power", "minimum_stars": 9, "priority": "required"}
    ]

    assert ready_parent_targets(targets) == [
        {"category": "blue", "name": "power", "minimum_stars": 3, "priority": "required"}
    ]


def test_parent_pair_target_reserves_final_self_share():
    targets = [
        {"category": "blue", "name": "power", "minimum_stars": 9, "priority": "required"},
        {"category": "pink", "name": "long", "minimum_stars": 6, "priority": "preferred"},
    ]

    assert parent_pair_targets(targets) == [
        {"category": "blue", "name": "power", "minimum_stars": 6, "priority": "required"},
        {"category": "pink", "name": "long", "minimum_stars": 4, "priority": "preferred"},
    ]
