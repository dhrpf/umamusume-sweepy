import main


def test_apply_runtime_preset_overrides_keeps_base_preset_name_and_replaces_campaign_runtime_fields():
    base = {
        "name": "top_UG_PC_oguri",
        "scenario_id": 1,
        "scenario": 1,
        "parent_run": False,
        "tp_mode": "carat",
        "extra_race_list": [629, 630, 646],
        "mandatory_race_list": [999],
        "learn_skill_threshold": 720,
    }

    merged = main.apply_runtime_preset_overrides(
        base,
        {
            "scenario_id": 4,
            "scenario": 4,
            "parent_run": True,
            "tp_mode": "wait",
            "extra_race_list": [200073, 300076],
            "mandatory_race_list": [],
            "not_allowed": "ignored",
        },
    )

    assert merged["name"] == "top_UG_PC_oguri"
    assert merged["scenario_id"] == 4
    assert merged["scenario"] == 4
    assert merged["parent_run"] is True
    assert merged["tp_mode"] == "wait"
    assert merged["extra_race_list"] == [200073, 300076]
    assert merged["mandatory_race_list"] == []
    assert merged["learn_skill_threshold"] == 720
    assert "not_allowed" not in merged
    assert base["scenario_id"] == 1
    assert base["extra_race_list"] == [629, 630, 646]
