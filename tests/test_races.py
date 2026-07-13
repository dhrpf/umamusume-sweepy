import json

from career_bot.races import RacePlanner


def _planner(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "race_map.json").write_text(
        json.dumps(
            {
                "meta": {
                    "11": {"turn": 12, "program_id": 1001},
                    "12": {"turn": 13, "program_id": 1002},
                },
                "program": {
                    "1001": {"name": "G1 Race", "race_instance_id": "100001", "ground": 1, "distance": 1600},
                    "1002": {"name": "Later Race", "race_instance_id": "100002", "ground": 1, "distance": 1600},
                    "2002": {"name": "G2 Race", "race_instance_id": "200002", "ground": 1, "distance": 1600},
                    "4001": {"name": "Open Race", "race_instance_id": "400001", "ground": 1, "distance": 1600},
                    "9001": {"name": "Twinkle Star Climax Race 2", "race_instance_id": "920055", "ground": 1, "distance": 1800},
                    "9002": {"name": "Junior Maiden Race", "race_instance_id": "902622", "ground": 1, "distance": 1600},
                },
                "instance": {"500": [1001, 2002]},
            }
        ),
        encoding="utf-8",
    )
    return RacePlanner(tmp_path)


def _state(turn=12, available=(1001,), race_enabled=True, scenario_id=1, fans=1000):
    return {
        "data": {
            "chara_info": {
                "turn": turn,
                "scenario_id": scenario_id,
                "fans": fans,
                "proper_ground_turf": 6,
                "proper_distance_mile": 6,
            },
            "home_info": {
                "command_info_array": [
                    {"command_type": 4, "command_id": 401, "is_enable": int(race_enabled)}
                ]
            },
            "race_condition_array": [{"program_id": pid} for pid in available],
        }
    }


def test_wanted_programs_resolves_meta_for_current_turn_only(tmp_path):
    planner = _planner(tmp_path)

    assert planner.wanted_programs({"extra_race_list": [11, 12, 500]}, turn=12) == [1001, 2002]


def test_forced_program_prefers_g1_when_only_race_command_available(tmp_path):
    planner = _planner(tmp_path)
    state = _state(available=(2002, 1001))

    assert planner.forced_program(state) == 1001


def test_rejected_program_is_removed_from_wanted_available(tmp_path):
    planner = _planner(tmp_path)
    state = _state(available=(1001,))
    preset = {"extra_race_list": [11]}

    assert planner.choose(state, preset) == 1001
    planner.reject(12, 1001)

    assert planner.choose(state, preset) == 0


def test_choose_falls_back_when_planned_g1_fan_requirement_is_not_met(tmp_path):
    planner = _planner(tmp_path)
    state = _state(available=(1001, 4001), fans=652)

    assert planner.choose(state, {"extra_race_list": [11]}) == 4001


def test_choose_builds_fans_before_next_turn_planned_g1(tmp_path):
    planner = _planner(tmp_path)
    state = _state(turn=12, available=(4001,), fans=652)

    assert planner.choose(state, {"extra_race_list": [12]}) == 4001


def test_fallback_candidates_exclude_ineligible_and_rejected_races(tmp_path):
    planner = _planner(tmp_path)
    state = _state(available=(1001, 2002, 4001), fans=652)
    planner.reject(12, 2002)

    assert planner.fallback_candidates(state, exclude={1001}) == [4001]


def test_fallback_candidates_require_enabled_race_command(tmp_path):
    planner = _planner(tmp_path)
    state = _state(available=(4001,), race_enabled=False)

    assert planner.fallback_candidates(state) == []


def test_fallback_candidates_exclude_internal_scenario_variants(tmp_path):
    planner = _planner(tmp_path)
    state = _state(available=(9001, 4001))

    assert planner.fallback_candidates(state) == [4001]


def test_fallback_candidates_exclude_maiden_after_first_win(tmp_path):
    planner = _planner(tmp_path)
    state = _state(turn=20, available=(9002, 4001))
    state["data"]["race_history"] = [
        {"turn": 12, "program_id": 1001, "result_rank": 1}
    ]

    assert planner.fallback_candidates(state) == [4001]
