from career_bot.campaigns.preset_policy import (
    build_campaign_base_preset,
    build_step_overrides,
)


def test_base_preset_preserves_manual_deck_choice():
    preset = build_campaign_base_preset(
        name="Campaign / A",
        running_style=3,
        scenario_id=4,
        spark_targets=[],
        core_races=[],
        optional_races=[],
    )

    assert "deck_id" not in preset
    assert "deck" not in preset


def test_base_preset_emphasizes_supported_blue_target_stats():
    preset = build_campaign_base_preset(
        name="Campaign / Stats",
        running_style=2,
        scenario_id=4,
        spark_targets=[
            {"category": "blue", "name": "speed"},
            {"category": "blue", "name": "stamina"},
            {"category": "blue", "name": "power"},
            {"category": "blue", "name": "guts"},
            {"category": "blue", "name": "wisdom"},
        ],
        core_races=[10],
        optional_races=[20],
    )

    for stat in ("speed", "stamina", "power", "guts", "wisdom"):
        assert preset[f"expect_{stat}"] >= 1100


def test_base_preset_maps_wit_to_wisdom():
    preset = build_campaign_base_preset(
        name="Campaign / Wit",
        running_style=1,
        scenario_id=1,
        spark_targets=[{"category": "blue", "name": "wit"}],
        core_races=[],
        optional_races=[],
    )

    assert preset["expect_wisdom"] >= 1100
    assert "expect_wit" not in preset


def test_base_preset_ignores_pink_and_unsupported_targets():
    preset = build_campaign_base_preset(
        name="Campaign / Ignore",
        running_style=1,
        scenario_id=1,
        spark_targets=[
            {"category": "pink", "name": "speed"},
            {"category": "blue", "name": "turf"},
            {"category": "green", "name": "stamina"},
        ],
        core_races=[],
        optional_races=[],
    )

    assert not any(key.startswith("expect_") for key in preset)


def test_builders_copy_inputs_without_mutation():
    spark_targets = [{"category": "blue", "name": "speed"}]
    core_races = [1, 2]
    optional_races = [3]

    preset = build_campaign_base_preset(
        name="Campaign / Copy",
        running_style=3,
        scenario_id=4,
        spark_targets=spark_targets,
        core_races=core_races,
        optional_races=optional_races,
    )
    overrides = build_step_overrides(
        core_races=core_races,
        optional_races=optional_races,
    )

    preset["mandatory_race_list"].append(4)
    preset["extra_race_list"].append(5)
    overrides["mandatory_race_list"].append(6)
    overrides["extra_race_list"].append(7)

    assert spark_targets == [{"category": "blue", "name": "speed"}]
    assert core_races == [1, 2]
    assert optional_races == [3]


def test_step_overrides_separate_core_and_optional_races():
    overrides = build_step_overrides(
        core_races=[1, 2],
        optional_races=[3],
        parent_run=False,
    )

    assert overrides == {
        "mandatory_race_list": [1, 2],
        "extra_race_list": [3],
        "parent_run": False,
    }
