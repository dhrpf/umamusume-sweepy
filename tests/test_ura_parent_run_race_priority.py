from career_bot.races import RacePlanner
from career_bot.scenarios.ura import UraStrategy


def state(turn, gain):
    return {"data": {
        "chara_info": {"turn": turn, "vital": 80, "max_vital": 100, "fans": 9999},
        "home_info": {"command_info_array": [
            {"command_type": 1, "command_id": 101, "is_enable": 1, "params_inc_dec_info_array": [{"target_type": 1, "effect_value": gain}]},
            {"command_type": 4, "command_id": 401, "is_enable": 1},
        ]},
        "race_condition_array": [{"program_id": 5}],
        "race_history": [],
    }}


def planner():
    p = RacePlanner("/nonexistent")
    p.program = {5: {"name": "Victoria Mile", "race_instance_id": 100801}}
    return p


def test_parent_run_skips_optional_race_when_training_gain_over_30():
    decision = UraStrategy(planner()).next_decision(state(57, 31), {"extra_race_list": [5], "parent_run": True})
    assert decision.action == "command"


def test_parent_run_runs_mandatory_race_even_when_training_gain_over_30():
    decision = UraStrategy(planner()).next_decision(state(57, 31), {
        "extra_race_list": [5],
        "mandatory_race_list": [5],
        "parent_run": True,
    })
    assert decision.action == "race"
    assert decision.payload["program_id"] == 5


def test_route_target_wins_same_turn_mandatory_race_conflict():
    race_planner = RacePlanner("/nonexistent")
    race_planner.program = {
        165: {"name": "Japanese Oaks", "race_instance_id": 100901},
        166: {"name": "Tokyo Yushun (Japanese Derby)", "race_instance_id": 101001},
    }
    race_planner.objective_resolver.routes = {
        1: {
            "objectives": [
                {
                    "id": 3,
                    "target_type": 1,
                    "sort_id": 3,
                    "turn": 34,
                    "condition_type": 1,
                    "condition_id": 166,
                    "condition_value_1": 5,
                }
            ]
        }
    }
    current = state(34, 31)
    current["data"]["chara_info"].update({
        "route_id": 1,
        "route_race_id_array": [3],
    })
    current["data"]["race_condition_array"] = [
        {"program_id": 165},
        {"program_id": 166},
    ]

    decision = UraStrategy(race_planner).next_decision(current, {
        "mandatory_race_list": [165, 166],
        "parent_run": True,
        "objective_gate_enabled": False,
    })

    assert decision.action == "race"
    assert decision.payload["program_id"] == 166
