import json

from career_bot.master_data import synthesize_career_objectives


def test_synthesize_career_objectives_groups_and_sorts_route_rows(tmp_path):
    (tmp_path / "data").mkdir()
    master_data = {
        "tables": {
            "single_mode_route": [
                {
                    "id": 2,
                    "scenario_id": 0,
                    "chara_id": 1006,
                    "race_set_id": 1006,
                    "condition_set_id": 0,
                    "priority": 0,
                }
            ],
            "single_mode_route_race": [
                {
                    "id": 16,
                    "race_set_id": 1006,
                    "scenario_group_id": 100,
                    "target_type": 1,
                    "sort_id": 6,
                    "turn": 60,
                    "race_type": 0,
                    "condition_type": 2,
                    "condition_id": 100,
                    "condition_value_1": 3,
                    "condition_value_2": 2,
                    "determine_race": 0,
                    "determine_race_flag": 0,
                },
                {
                    "id": 15,
                    "race_set_id": 1006,
                    "scenario_group_id": 100,
                    "target_type": 1,
                    "sort_id": 5,
                    "turn": 48,
                    "race_type": 0,
                    "condition_type": 1,
                    "condition_id": 81,
                    "condition_value_1": 3,
                    "condition_value_2": 0,
                    "determine_race": 0,
                    "determine_race_flag": 0,
                },
            ],
        },
        "text": {},
    }

    result = synthesize_career_objectives(tmp_path, master_data)
    generated = json.loads(
        (tmp_path / "data" / "career_objectives.json").read_text(encoding="utf-8")
    )
    route = generated["routes"]["2"]

    assert result == {"file": "career_objectives.json", "routes": 1}
    assert route["scenario_id"] == 0
    assert route["chara_id"] == 1006
    assert [row["id"] for row in route["objectives"]] == [15, 16]
    assert route["objectives"][1]["condition_type"] == 2
    assert route["objectives"][1]["condition_value_2"] == 2


def test_synthesize_career_objectives_preserves_existing_when_tables_missing(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    path = data_dir / "career_objectives.json"
    path.write_text(json.dumps({"routes": {"2": {"objectives": []}}}), encoding="utf-8")

    result = synthesize_career_objectives(tmp_path, {"tables": {}, "text": {}})

    assert result["preserved_existing"] is True
    assert result["routes"] == 1
    assert json.loads(path.read_text(encoding="utf-8"))["routes"] == {
        "2": {"objectives": []}
    }
