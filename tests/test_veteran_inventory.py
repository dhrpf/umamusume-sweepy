from career_bot.campaigns.legacy.veteran_inventory import (
    find_veterans,
    summarize_veteran,
)


FACTOR_MAP = {
    "301": {"name": "Power", "stars": 1, "category": "stat"},
    "302": {"name": "Power", "stars": 2, "category": "stat"},
    "303": {"name": "Power", "stars": 3, "category": "stat"},
    "1002301": {"name": "Arima Kinen", "stars": 1, "category": "race"},
    "1002302": {"name": "Arima Kinen", "stars": 2, "category": "race"},
}


def record_without_power_factor():
    return {
        "trained_chara_id": 1001,
        "card_id": 100101,
        "rank": 17,
        "rank_score": 17000,
        "power": 1200,
        "factor_info_array": [
            {"factor_id": 1002301, "level": 0},
            {"factor_id": 1002302, "level": 0},
        ],
        "succession_chara_array": [
            {
                "position_id": 10,
                "card_id": 100201,
                "factor_info_array": [{"factor_id": 1002301, "level": 0}],
            },
            {
                "position_id": 20,
                "card_id": 100301,
                "factor_info_array": [{"factor_id": 1002302, "level": 0}],
            },
        ],
    }


def record_with_power_nine_star():
    return {
        "trained_chara_id": 1002,
        "card_id": 100401,
        "rank": 13,
        "rank_score": 11000,
        "power": 700,
        "factor_info_array": [{"factor_id": 303, "level": 0}],
        "succession_chara_array": [
            {
                "position_id": 10,
                "card_id": 100501,
                "factor_info_array": [{"factor_id": 303, "level": 0}],
            },
            {
                "position_id": 20,
                "card_id": 100601,
                "factor_info_array": [{"factor_id": 303, "level": 0}],
            },
            {
                "position_id": 11,
                "card_id": 100701,
                "factor_info_array": [{"factor_id": 302, "level": 0}],
            },
        ],
    }


def test_final_power_stat_and_race_sparks_do_not_imply_power_nine_star():
    summary = summarize_veteran(
        record_without_power_factor(),
        factor_map=FACTOR_MAP,
        display={"name": "Synthetic Veteran A"},
    )

    assert summary["final_stats"]["power"] == 1200
    assert summary["self_blue_factors"] == {}
    assert summary["direct_lineage_blue_totals"].get("Power", 0) == 0
    assert summary["legacy_tags"] == []
    assert summary["factor_tree"]["self"]["white_race"] == [
        {"factor_id": 1002301, "name": "Arima Kinen", "stars": 1, "category": "race"},
        {"factor_id": 1002302, "name": "Arima Kinen", "stars": 2, "category": "race"},
    ]


def test_power_nine_star_is_self_plus_two_direct_parent_blue_factors():
    summary = summarize_veteran(
        record_with_power_nine_star(),
        factor_map=FACTOR_MAP,
        display={"name": "Synthetic Veteran B"},
    )

    assert summary["self_blue_factors"] == {"Power": 3}
    assert summary["direct_parent_blue_factors"] == {
        "parent1": {"Power": 3},
        "parent2": {"Power": 3},
    }
    assert summary["direct_lineage_blue_totals"] == {"Power": 9}
    assert summary["full_lineage_blue_totals"] == {"Power": 11}
    assert summary["legacy_tags"] == ["Power 9★"]


def test_find_veterans_filters_using_decoded_direct_lineage_blue_stars():
    result = find_veterans(
        [record_without_power_factor(), record_with_power_nine_star()],
        factor_map=FACTOR_MAP,
        display_by_id={
            1001: {"name": "Synthetic Veteran A"},
            1002: {"name": "Synthetic Veteran B"},
        },
        blue_factor="power",
        minimum_lineage_stars=9,
        scope="direct_lineage",
    )

    assert result["query"] == {
        "blue_factor": "Power",
        "minimum_lineage_stars": 9,
        "scope": "direct_lineage",
        "definition": "self + direct parent 1 + direct parent 2",
    }
    assert result["match_count"] == 1
    assert result["matches"][0]["trained_chara_id"] == 1002
    assert result["matches"][0]["matched_blue_stars"] == 9
