import json

import pytest

from career_bot.races import RacePlanner
from career_bot.scenarios.unity import UnityStrategy
from career_bot.scenarios.ura import UraStrategy


def _planner(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
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
                    ],
                }
            }
        }),
        encoding="utf-8",
    )
    (data_dir / "race_map.json").write_text(
        json.dumps({
            "meta": {
                "300003": {"program_id": 3, "turn": 54, "name": "Osaka Hai"},
                "300004": {"program_id": 4, "turn": 56, "name": "Tenno Sho Spring"},
                "300005": {"program_id": 5, "turn": 57, "name": "Victoria Mile"},
                "300073": {"program_id": 73, "turn": 59, "name": "Yasuda Kinen"},
            },
            "program": {
                "3": {
                    "name": "Osaka Hai",
                    "race_instance_id": 100301,
                    "grade": 100,
                    "ground": 1,
                    "distance": 2000
                },
                "4": {
                    "name": "Tenno Sho Spring",
                    "race_instance_id": 100601,
                    "grade": 100,
                    "ground": 1,
                    "distance": 3200
                },
                "5": {
                    "name": "Victoria Mile",
                    "race_instance_id": 100801,
                    "grade": 100,
                    "ground": 1,
                    "distance": 1600
                },
                "73": {
                    "name": "Yasuda Kinen",
                    "race_instance_id": 101101,
                    "grade": 100,
                    "ground": 1,
                    "distance": 1600
                },
                "81": {
                    "name": "Arima Kinen",
                    "race_instance_id": 101201,
                    "grade": 100,
                    "ground": 1,
                    "distance": 2500
                }
            },
            "instance": {}
        }),
        encoding="utf-8",
    )
    return RacePlanner(tmp_path)


def _state(turn, available, history=(), scenario_id=1, stamina=354, playing_state=1):
    return {
        "data": {
            "chara_info": {
                "turn": turn,
                "scenario_id": scenario_id,
                "route_id": 2,
                "route_race_id_array": [15, 16],
                "playing_state": playing_state,
                "state": 0,
                "vital": 80,
                "max_vital": 100,
                "motivation": 5,
                "fans": 100000,
                "stamina": stamina,
                "proper_ground_turf": 7,
                "proper_ground_dirt": 6,
                "proper_distance_short": 5,
                "proper_distance_mile": 7,
                "proper_distance_middle": 8,
                "proper_distance_long": 7,
            },
            "home_info": {
                "command_info_array": [
                    {
                        "command_type": 1,
                        "command_id": 101,
                        "is_enable": 1,
                        "failure_rate": 0,
                        "params_inc_dec_info_array": [
                            {"target_type": 1, "value": 80}
                        ],
                    },
                    {"command_type": 4, "command_id": 401, "is_enable": 1},
                    {"command_type": 7, "command_id": 701, "is_enable": 1},
                ]
            },
            "race_condition_array": [{"program_id": pid} for pid in available],
            "race_history": list(history),
        }
    }


def _classic_arima():
    return {"turn": 48, "program_id": 81, "result_rank": 1}


@pytest.mark.parametrize("scenario_id", [1, 2])
def test_shared_gate_selects_osaka_hai_for_oguri(tmp_path, scenario_id):
    planner = _planner(tmp_path)
    state = _state(54, [3], history=[_classic_arima()], scenario_id=scenario_id)

    decision = planner.objective_candidate(state, {}, best_training_gain=80)

    assert decision.program_id == 3
    assert "progress=0/2" in decision.reason


def test_gate_skips_risky_tenno_spring_when_safe_g1s_remain(tmp_path):
    planner = _planner(tmp_path)
    planner.record_race_result(54, 3, 1)
    state = _state(56, [4], history=[_classic_arima()], stamina=354)

    decision = planner.objective_candidate(state, {}, best_training_gain=20)

    assert decision is None
    observation = planner.last_objective_observation
    assert observation["objective"]["progress"] == 1
    assert observation["objective"]["safe_future_opportunities"] == 2


def test_gate_selects_victoria_mile_to_finish_objective(tmp_path):
    planner = _planner(tmp_path)
    planner.record_race_result(54, 3, 1)
    state = _state(57, [5], history=[_classic_arima()], stamina=354)

    decision = planner.objective_candidate(state, {}, best_training_gain=80)

    assert decision.program_id == 5
    assert decision.forced is True
    assert "progress=1/2" in decision.reason


def test_gate_stops_after_objective_is_complete(tmp_path):
    planner = _planner(tmp_path)
    planner.record_race_result(54, 3, 1)
    planner.record_race_result(57, 5, 1)
    state = _state(59, [73], history=[_classic_arima()], stamina=354)

    assert planner.objective_candidate(state, {}, best_training_gain=0) is None


@pytest.mark.parametrize("strategy_cls,scenario_id", [(UraStrategy, 1), (UnityStrategy, 2)])
def test_strategy_uses_shared_objective_gate_before_optional_races(
    tmp_path, strategy_cls, scenario_id
):
    planner = _planner(tmp_path)
    state = _state(54, [3, 73], history=[_classic_arima()], scenario_id=scenario_id)
    strategy = strategy_cls(planner)

    decision = strategy.next_decision(
        state,
        {"scenario_id": scenario_id, "extra_race_list": [73]},
    )

    assert decision.action == "race"
    assert decision.payload["program_id"] == 3
    assert "objective 16" in decision.reason


def test_upcoming_arima_adds_stamina_readiness_context(tmp_path):
    planner = _planner(tmp_path)
    state = _state(43, [], stamina=259)

    context = planner.objective_training_context(state, {})

    assert context["objective_id"] == 15
    assert context["program_id"] == 81
    assert context["turns_left"] == 5
    assert context["stamina_floor"] == 350
    assert context["stamina_deficit"] == 91


def test_arima_readiness_bonus_can_prioritize_stamina_training(tmp_path):
    planner = _planner(tmp_path)
    state = _state(43, [], stamina=259)
    chara = state["data"]["chara_info"]
    chara.update({
        "speed": 849,
        "power": 551,
        "guts": 151,
        "wiz": 359,
        "evaluation_info_array": [],
    })
    commands = [
        {
            "command_type": 1,
            "command_id": 101,
            "is_enable": 1,
            "failure_rate": 0,
            "training_partner_array": [1, 2, 3],
            "params_inc_dec_info_array": [
                {"target_type": 1, "value": 30},
                {"target_type": 3, "value": 13},
                {"target_type": 30, "value": 7},
            ],
        },
        {
            "command_type": 1,
            "command_id": 102,
            "is_enable": 1,
            "failure_rate": 0,
            "training_partner_array": [1, 2],
            "params_inc_dec_info_array": [
                {"target_type": 2, "value": 15},
                {"target_type": 3, "value": 12},
                {"target_type": 30, "value": 6},
            ],
        },
    ]
    context = planner.objective_training_context(state, {})

    best, _ = UraStrategy(planner)._best_training(
        commands,
        {},
        chara,
        43,
        False,
        False,
        objective_context=context,
    )

    assert best["command_id"] == 102
    assert best["_decision_detail"]["objective_readiness_bonus"] > 100
    assert "Arima Kinen" in " ".join(best["_decision_detail"]["reasons"])


def test_forced_target_race_requests_pre_race_skill_purchase(tmp_path):
    planner = _planner(tmp_path)
    state = _state(48, [81], stamina=350)
    state["data"]["chara_info"]["target_chara_race_info_array"] = [
        {"program_id": 81, "target_turn": 48, "is_cleared": False}
    ]
    state["data"]["home_info"]["race_program_info_array"] = [
        {"program_id": 81, "name": "Arima Kinen"}
    ]

    decision = UraStrategy(planner).next_decision(state, {})

    assert decision.action == "race"
    assert decision.payload["program_id"] == 81
    assert decision.payload["_buy_skills_before_race"] is True


def test_unity_team_race_state_stays_above_objective_gate(tmp_path):
    planner = _planner(tmp_path)
    state = _state(
        54,
        [3],
        history=[_classic_arima()],
        scenario_id=2,
        playing_state=7,
    )

    decision = UnityStrategy(planner).next_decision(state, {"scenario_id": 2})

    assert decision.action == "team_race"
    assert decision.payload["phase"] == "full"


def test_observe_mode_does_not_change_decision(tmp_path):
    planner = _planner(tmp_path)
    state = _state(54, [3], history=[_classic_arima()])

    decision = planner.objective_candidate(
        state,
        {"objective_gate_mode": "observe"},
        best_training_gain=80,
    )

    assert decision is None
    assert planner.last_objective_observation["objective"]["id"] == 16


def _fan_planner(tmp_path):
    root = tmp_path / "fan_goal"
    data_dir = root / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "career_objectives.json").write_text(
        json.dumps({
            "routes": {
                "2": {
                    "route_id": 2,
                    "scenario_id": 0,
                    "chara_id": 1006,
                    "race_set_id": 1006,
                    "objectives": [{
                        "id": 12,
                        "scenario_group_id": 100,
                        "target_type": 1,
                        "sort_id": 2,
                        "turn": 24,
                        "race_type": 0,
                        "condition_type": 3,
                        "condition_id": 0,
                        "condition_value_1": 3000,
                        "condition_value_2": 0,
                    }],
                }
            }
        }),
        encoding="utf-8",
    )
    (data_dir / "race_map.json").write_text(
        json.dumps({
            "meta": {
                "100625": {
                    "program_id": 625,
                    "turn": 24,
                    "name": "Hopeful Stakes",
                }
            },
            "program": {
                "625": {
                    "name": "Hopeful Stakes",
                    "race_instance_id": 102401,
                    "grade": 100,
                    "ground": 1,
                    "distance": 2000,
                },
                "633": {
                    "name": "Artemis Stakes",
                    "race_instance_id": 302001,
                    "grade": 300,
                    "ground": 1,
                    "distance": 1600,
                },
            },
            "instance": {},
        }),
        encoding="utf-8",
    )
    return RacePlanner(root)


def _fan_state(turn, available):
    return {
        "data": {
            "chara_info": {
                "turn": turn,
                "scenario_id": 1,
                "route_id": 2,
                "route_race_id_array": [12],
                "playing_state": 1,
                "state": 0,
                "vital": 80,
                "max_vital": 100,
                "motivation": 5,
                "fans": 1587,
                "stamina": 180,
                "proper_ground_turf": 7,
                "proper_distance_mile": 7,
                "proper_distance_middle": 7,
            },
            "home_info": {
                "command_info_array": [
                    {"command_type": 1, "command_id": 101, "is_enable": 1},
                    {"command_type": 4, "command_id": 401, "is_enable": 1},
                    {"command_type": 7, "command_id": 701, "is_enable": 1},
                ]
            },
            "race_condition_array": [{"program_id": pid} for pid in available],
            "race_history": [
                {"turn": 12, "program_id": 1070, "result_rank": 1}
            ],
        }
    }


def test_fan_goal_waits_for_planned_hopeful_stakes(tmp_path):
    planner = _fan_planner(tmp_path)
    state = _fan_state(20, [633])

    decision = planner.objective_candidate(
        state,
        {"extra_race_list": [100625]},
        best_training_gain=20,
    )

    assert decision is None
    planned = planner.last_objective_observation["objective"]["planned_fan_race"]
    assert planned["program_id"] == 625
    assert planned["turn"] == 24


def test_fan_goal_uses_planned_hopeful_on_deadline(tmp_path):
    planner = _fan_planner(tmp_path)
    state = _fan_state(24, [625])

    decision = planner.objective_candidate(
        state,
        {"extra_race_list": [100625]},
        best_training_gain=80,
    )

    assert decision.program_id == 625
    assert decision.forced is True
    assert "using planned Hopeful Stakes" in decision.reason
