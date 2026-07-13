import json

import pytest

from career_bot.objectives import CareerObjectiveResolver


def _write_objectives(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    (data_dir / "career_objectives.json").write_text(
        json.dumps({
            "routes": {
                "2": {
                    "route_id": 2,
                    "scenario_id": 0,
                    "chara_id": 1006,
                    "race_set_id": 1006,
                    "objectives": [
                        {
                            "id": 15,
                            "scenario_group_id": 100,
                            "target_type": 1,
                            "sort_id": 5,
                            "turn": 48,
                            "race_type": 0,
                            "condition_type": 1,
                            "condition_id": 81,
                            "condition_value_1": 3,
                            "condition_value_2": 0,
                        },
                        {
                            "id": 16,
                            "scenario_group_id": 100,
                            "target_type": 1,
                            "sort_id": 6,
                            "turn": 60,
                            "race_type": 0,
                            "condition_type": 2,
                            "condition_id": 100,
                            "condition_value_1": 3,
                            "condition_value_2": 2,
                        },
                        {
                            "id": 17,
                            "scenario_group_id": 100,
                            "target_type": 1,
                            "sort_id": 7,
                            "turn": 68,
                            "race_type": 0,
                            "condition_type": 1,
                            "condition_id": 76,
                            "condition_value_1": 1,
                            "condition_value_2": 0,
                        },
                        {
                            "id": 19,
                            "scenario_group_id": 701,
                            "target_type": 3,
                            "sort_id": 9,
                            "turn": 74,
                            "race_type": 1,
                            "condition_type": 1,
                            "condition_id": 10001,
                            "condition_value_1": 1,
                            "condition_value_2": 0,
                        },
                    ],
                }
            }
        }),
        encoding="utf-8",
    )


def _programs():
    return {
        81: {"name": "Arima Kinen", "grade": 100, "race_instance_id": 100101},
        76: {"name": "Tenno Sho Autumn", "grade": 100, "race_instance_id": 100201},
        3: {"name": "Osaka Hai", "grade": 100, "race_instance_id": 100301},
        4: {"name": "Tenno Sho Spring", "grade": 100, "race_instance_id": 100601},
        5: {"name": "Victoria Mile", "grade": 100, "race_instance_id": 100801},
        73: {"name": "Yasuda Kinen", "grade": 100, "race_instance_id": 101101},
    }


def _state(turn, history=(), scenario_id=1, fans=100000):
    return {
        "data": {
            "chara_info": {
                "turn": turn,
                "scenario_id": scenario_id,
                "route_id": 2,
                "route_race_id_array": [15, 16, 17, 19],
                "fans": fans,
            },
            "race_history": list(history),
        }
    }


@pytest.mark.parametrize("scenario_id", [1, 2])
def test_oguri_senior_g1_progress_is_shared_by_ura_and_unity(tmp_path, scenario_id):
    _write_objectives(tmp_path)
    resolver = CareerObjectiveResolver(tmp_path, _programs())
    history = [
        {"turn": 44, "program_id": 76, "result_rank": 1},
        {"turn": 48, "program_id": 81, "result_rank": 1},
    ]

    status = resolver.current_status(_state(53, history, scenario_id=scenario_id))
    assert status.objective_id == 16
    assert status.progress == 0
    assert status.required == 2
    assert status.window_start_turn == 49

    history.append({"turn": 54, "program_id": 3, "result_rank": 1})
    status = resolver.current_status(_state(54, history, scenario_id=scenario_id))
    assert status.progress == 1

    history.append({"turn": 56, "program_id": 4, "result_rank": 6})
    status = resolver.current_status(_state(56, history, scenario_id=scenario_id))
    assert status.progress == 1

    history.append({"turn": 57, "program_id": 5, "result_rank": 1})
    statuses = resolver.statuses(_state(57, history, scenario_id=scenario_id))
    g1_status = next(row for row in statuses if row.objective_id == 16)
    assert g1_status.progress == 2
    assert g1_status.completed is True
    assert resolver.current_status(_state(57, history, scenario_id=scenario_id)).objective_id == 17


def test_specific_race_objective_uses_its_own_turn_window(tmp_path):
    _write_objectives(tmp_path)
    resolver = CareerObjectiveResolver(tmp_path, _programs())
    history = [
        {"turn": 48, "program_id": 81, "result_rank": 1},
        {"turn": 54, "program_id": 3, "result_rank": 1},
        {"turn": 57, "program_id": 5, "result_rank": 1},
        {"turn": 68, "program_id": 76, "result_rank": 1},
    ]

    statuses = resolver.statuses(_state(68, history))
    senior_g1 = next(row for row in statuses if row.objective_id == 16)
    tenno = next(row for row in statuses if row.objective_id == 17)

    assert senior_g1.completed is True
    assert tenno.completed is True
    assert tenno.window_start_turn == 61


def test_cached_result_is_merged_without_double_counting(tmp_path):
    _write_objectives(tmp_path)
    resolver = CareerObjectiveResolver(tmp_path, _programs())
    history = [
        {"turn": 48, "program_id": 81, "result_rank": 1},
        {"turn": 54, "program_id": 3, "result_rank": 1},
    ]
    cached = {
        (54, 3): {"turn": 54, "program_id": 3, "result_rank": 1},
        (57, 5): {"turn": 57, "program_id": 5, "result_rank": 1},
    }

    statuses = resolver.statuses(_state(57, history), cached_results=cached)
    status = next(row for row in statuses if row.objective_id == 16)

    assert status.progress == 2
    assert len(status.qualifying_results) == 2


def test_missing_history_does_not_pin_resolver_to_expired_objective(tmp_path):
    _write_objectives(tmp_path)
    resolver = CareerObjectiveResolver(tmp_path, _programs())

    status = resolver.current_status(_state(54, history=[]))

    assert status.objective_id == 16
    assert status.window_start_turn == 49


def test_scenario_final_targets_are_not_character_objectives(tmp_path):
    _write_objectives(tmp_path)
    resolver = CareerObjectiveResolver(tmp_path, _programs())

    ids = [row.objective_id for row in resolver.route_objectives(_state(53))]

    assert ids == [15, 16, 17]
