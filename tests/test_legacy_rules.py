from career_bot.campaigns.legacy.rules import (
    DEFAULT_SPARK_RULESET,
    blue_stat_effect,
    compatibility_tier,
    estimate_initial_blue_stats,
)


def test_compatibility_circle_thresholds():
    assert compatibility_tier(49)["name"] == "triangle"
    assert compatibility_tier(50)["name"] == "single_circle"
    assert compatibility_tier(150)["name"] == "single_circle"
    assert compatibility_tier(151) == {
        "symbol": "◎",
        "name": "double_circle",
        "minimum": 151,
        "total": 151,
    }


def test_blue_spark_effects_and_two_nine_star_parent_stack():
    assert blue_stat_effect(1) == 5
    assert blue_stat_effect(2) == 12
    assert blue_stat_effect(3) == 21
    factors = [
        {"category": "blue", "name": "speed", "stars": 3},
        {"category": "stat", "name": "stamina", "stars": 3},
        {"category": "blue", "name": "power", "stars": 3},
        {"category": "blue", "name": "speed", "stars": 3},
        {"category": "stat", "name": "stamina", "stars": 3},
        {"category": "blue", "name": "power", "stars": 3},
        {"category": "aptitude", "name": "medium", "stars": 3},
    ]
    assert estimate_initial_blue_stats(factors) == 126


def test_spark_rules_keep_affinity_and_three_star_roll_separate():
    assert DEFAULT_SPARK_RULESET["blue"]["three_star_stat_target"] == 1100
    assert DEFAULT_SPARK_RULESET["white_race"]["shared_g1_is_affinity_progress"] is True
    assert DEFAULT_SPARK_RULESET["white_skill"]["exclude_unique"] is True
