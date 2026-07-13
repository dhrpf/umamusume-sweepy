from career_bot.races import RacePlanner
from career_bot.scenarios.ura import UraStrategy


def state(turn, vital=36):
    return {"data": {
        "chara_info": {"turn": turn, "vital": vital, "max_vital": 100, "fans": 9999},
        "home_info": {"command_info_array": [
            {"command_type": 1, "command_id": 101, "is_enable": 1},
            {"command_type": 4, "command_id": 401, "is_enable": 1},
            {"command_type": 7, "command_id": 701, "is_enable": 1},
        ]},
        "race_condition_array": [{"program_id": 5}, {"program_id": 16}],
        "race_history": [],
    }}


def test_planned_race_beats_low_vital_rest():
    planner = RacePlanner("/nonexistent")
    planner.program = {5: {"name": "Victoria Mile", "race_instance_id": 100801}}
    decision = UraStrategy(planner).next_decision(state(57), {"extra_race_list": [5]})

    assert decision.action == "race"
    assert decision.payload["program_id"] == 5


def test_generic_alt_race_is_not_selected_after_first_win():
    planner = RacePlanner("/nonexistent")
    planner.program = {
        4001: {"name": "Random Open Race", "race_instance_id": 400001, "ground": 1, "distance": 1600},
    }
    current = state(20, vital=80)
    current["data"]["chara_info"].update({
        "fans": 5000,
        "proper_ground_turf": 7,
        "proper_distance_mile": 7,
    })
    current["data"]["race_condition_array"] = [{"program_id": 4001}]
    current["data"]["race_history"] = [
        {"turn": 12, "program_id": 1070, "result_rank": 1},
    ]
    current["data"]["home_info"]["command_info_array"][0].update({
        "params_inc_dec_info_array": [{"target_type": 1, "value": 20}],
        "failure_rate": 0,
    })

    decision = UraStrategy(planner).next_decision(current, {"extra_race_list": []})

    assert decision.action == "command"
    assert decision.payload["command_id"] == 101


def test_fan_building_race_beats_imminent_target_skip():
    planner = RacePlanner("/nonexistent")
    planner.meta = {
        11: {"turn": 23, "program_id": 1001},
    }
    planner.program = {
        1001: {"name": "Planned G1", "race_instance_id": 100001, "ground": 1, "distance": 1600},
        4001: {"name": "Eligible Open", "race_instance_id": 400001, "ground": 1, "distance": 1600},
    }
    current = state(23)
    current["data"]["chara_info"].update({
        "fans": 652,
        "proper_ground_turf": 7,
        "proper_distance_mile": 7,
        "target_chara_race_info_array": [{"target_turn": 24, "is_cleared": False}],
    })
    current["data"]["race_condition_array"] = [
        {"program_id": 1001},
        {"program_id": 4001},
    ]

    decision = UraStrategy(planner).next_decision(
        current,
        {"extra_race_list": [11]},
    )

    assert decision.action == "race"
    assert decision.payload["program_id"] == 4001


def test_lost_debut_forces_best_aptitude_maiden_race():
    planner = RacePlanner("/nonexistent")
    planner.program = {
        298: {"name": "Junior Maiden Race", "race_instance_id": 904050, "ground": 2, "distance": 1150},
        946: {"name": "Junior Maiden Race", "race_instance_id": 904060, "ground": 1, "distance": 1200},
        951: {"name": "Junior Maiden Race", "race_instance_id": 904100, "ground": 1, "distance": 1800},
    }
    current = state(13)
    current["data"]["chara_info"].update({
        "fans": 652,
        "proper_ground_turf": 7,
        "proper_ground_dirt": 6,
        "proper_distance_short": 3,
        "proper_distance_mile": 7,
        "proper_distance_middle": 7,
        "proper_distance_long": 7,
    })
    current["data"]["race_condition_array"] = [
        {"program_id": 298},
        {"program_id": 946},
        {"program_id": 951},
    ]

    strategy = UraStrategy(planner)
    strategy.record_race_result(1070, 2)
    decision = strategy.next_decision(current, {"extra_race_list": []})

    assert decision.action == "race"
    assert decision.payload["program_id"] == 951
    assert "maiden" in decision.reason.lower()


def test_resume_after_lost_debut_reconstructs_maiden_gate_from_history():
    planner = RacePlanner("/nonexistent")
    planner.program = {
        951: {"name": "Junior Maiden Race", "race_instance_id": 904100, "ground": 1, "distance": 1800},
    }
    current = state(13)
    current["data"]["chara_info"].update({
        "fans": 652,
        "proper_ground_turf": 7,
        "proper_distance_mile": 7,
    })
    current["data"]["race_history"] = [
        {"turn": 12, "program_id": 1070, "result_rank": 2},
    ]
    current["data"]["race_condition_array"] = [{"program_id": 951}]

    decision = UraStrategy(planner).next_decision(current, {"extra_race_list": []})

    assert decision.action == "race"
    assert decision.payload["program_id"] == 951


def test_maiden_gate_stops_after_first_win():
    planner = RacePlanner("/nonexistent")
    planner.meta = {11: {"turn": 14, "program_id": 1001}}
    planner.program = {
        951: {"name": "Junior Maiden Race", "race_instance_id": 904100, "ground": 1, "distance": 1800},
        1001: {"name": "Planned G1", "race_instance_id": 100001, "ground": 1, "distance": 1600},
    }
    current = state(14)
    current["data"]["chara_info"].update({
        "fans": 1400,
        "proper_ground_turf": 7,
        "proper_distance_mile": 7,
    })
    current["data"]["race_condition_array"] = [
        {"program_id": 951},
        {"program_id": 1001},
    ]

    strategy = UraStrategy(planner)
    strategy.record_race_result(1070, 2)
    strategy.record_race_result(951, 1)
    decision = strategy.next_decision(current, {"extra_race_list": [11]})

    assert decision.action == "race"
    assert decision.payload["program_id"] == 1001
