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
