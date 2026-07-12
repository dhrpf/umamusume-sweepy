import threading

import pytest

from career_bot.runner import CareerRunner, STRATEGIES
from career_bot.scenarios.unity import UnityStrategy
from career_bot.scenarios.ura import UraStrategy
from uma_api.client import StateRecoveryError, UmaClient


def _training(command_id, target_type, value):
    return {
        "command_type": 1,
        "command_id": command_id,
        "command_group_id": 0,
        "is_enable": 1,
        "failure_rate": 0,
        "params_inc_dec_info_array": [
            {"target_type": target_type, "value": value},
        ],
    }


def _normal_unity_state():
    return {
        "data": {
            "chara_info": {
                "turn": 10,
                "playing_state": 1,
                "state": 0,
                "card_id": 100101,
                "vital": 100,
                "max_vital": 100,
                "motivation": 5,
                "speed": 500,
                "stamina": 500,
                "power": 500,
                "guts": 500,
                "wiz": 500,
                "evaluation_info_array": [],
                "chara_effect_id_array": [],
            },
            "home_info": {
                "command_info_array": [
                    _training(101, 1, 60),
                    _training(102, 2, 25),
                ],
                "race_program_info_array": [],
            },
            "team_data_set": {
                "command_info_array": [
                    {
                        "command_type": 1,
                        "command_id": 102,
                        "sp_soul_event_partner_array": [{"chara_id": 2001}],
                    },
                ],
                "evaluation_info_array": [],
            },
            "race_history": [],
            "race_condition_array": [],
        },
    }


@pytest.mark.parametrize(
    ("playing_state", "phase"),
    [(7, "full"), (8, "end"), (9, "out")],
)
def test_unity_strategy_dispatches_team_race_states(playing_state, phase):
    strategy = UnityStrategy()
    state = {
        "data": {
            "chara_info": {
                "turn": 24,
                "playing_state": playing_state,
            },
        },
    }

    decision = strategy.next_decision(state, {"scenario_id": 2})

    assert decision.action == "team_race"
    assert decision.payload["current_turn"] == 24
    assert decision.payload["phase"] == phase
    assert decision.payload["_strategy"] is strategy


def test_unity_goal_failure_is_marked_as_failed_finish():
    strategy = UnityStrategy()
    state = {
        "data": {
            "chara_info": {
                "turn": 24,
                "state": 2,
                "playing_state": 5,
            },
        },
    }

    decision = strategy.next_decision(state, {"scenario_id": 2})

    assert decision.action == "finish"
    assert decision.payload["career_failed"] is True
    assert "failed" in decision.reason


def test_unity_post_race_playing_state_five_is_not_terminal_without_failed_state():
    strategy = UnityStrategy()
    state = {
        "data": {
            "chara_info": {
                "turn": 12,
                "state": 0,
                "playing_state": 5,
                "vital": 50,
                "max_vital": 100,
                "motivation": 4,
                "speed": 290,
                "stamina": 182,
                "power": 213,
                "guts": 115,
                "wiz": 197,
                "evaluation_info_array": [],
                "chara_effect_id_array": [],
            },
            "home_info": {
                "command_info_array": [_training(101, 1, 30)],
                "race_program_info_array": [],
            },
            "race_history": [],
            "race_condition_array": [],
        },
    }

    decision = strategy.next_decision(state, {"scenario_id": 2})

    assert decision.action != "finish"


def test_unity_pending_event_takes_priority_over_team_race_state():
    strategy = UnityStrategy()
    state = {
        "data": {
            "chara_info": {"turn": 24, "playing_state": 7},
            "unchecked_event_array": [
                {"event_id": 9001, "chara_id": 1001},
            ],
        },
    }

    decision = strategy.next_decision(state, {"scenario_id": 2})

    assert decision.action == "event"
    assert decision.payload["event_id"] == 9001


def test_unity_default_spirit_burst_bonus_can_change_training_choice():
    strategy = UnityStrategy()
    preset = {
        "scenario_id": 2,
        "expect_attribute": [600, 600, 600, 400, 400],
        "unity_config": {
            "unity_training_weight": 0.6,
            "spirit_burst_weight": 5.0,
        },
    }

    decision = strategy.next_decision(_normal_unity_state(), preset)

    assert decision.action == "command"
    assert decision.payload["command_id"] == 102
    assert decision.payload["decision_detail"]["unity_spirit_bursts"] == 1
    assert decision.payload["decision_detail"]["unity_bonus"] == 150.0


def test_summer_camp_uses_server_preview_gain_without_extra_multiplier():
    strategy = UraStrategy()
    command = _training(602, 2, 32)
    command["params_inc_dec_info_array"].extend([
        {"target_type": 4, "value": 19},
        {"target_type": 30, "value": 9},
    ])
    chara = {
        "vital": 85,
        "speed": 650,
        "stamina": 280,
        "power": 480,
        "guts": 230,
        "wiz": 410,
        "evaluation_info_array": [],
    }

    best, _ = strategy._best_training(
        [command],
        {"expect_attribute": [0, 0, 0, 0, 0]},
        chara,
        turn=37,
        is_camp=True,
        pre_camp=False,
    )

    assert best["_decision_detail"]["gain"] == 60.0


def test_9999_expected_stats_use_scenario_targets_instead_of_literal_deficit():
    strategy = UraStrategy()
    command = _training(101, 1, 30)
    chara = {
        "vital": 100,
        "speed": 500,
        "stamina": 500,
        "power": 500,
        "guts": 300,
        "wiz": 500,
        "evaluation_info_array": [],
    }

    best, _ = strategy._best_training(
        [command],
        {"expect_attribute": [9999, 9999, 9999, 9999, 9999]},
        chara,
        turn=10,
        is_camp=False,
        pre_camp=False,
    )

    assert best["_decision_detail"]["target"] == 900
    assert best["_decision_detail"]["deficit"] == 400


def test_unity_scenario_is_registered():
    assert STRATEGIES[2] is UnityStrategy


def test_runner_allows_unity_playing_states_for_unity_strategy():
    runner = CareerRunner.__new__(CareerRunner)
    strategy = UnityStrategy()

    assert runner._blocked_playing_state({"playing_state": 7}, strategy) is False
    assert runner._blocked_playing_state({"playing_state": 8}, strategy) is False
    assert runner._blocked_playing_state({"playing_state": 9}, strategy) is False
    assert runner._blocked_playing_state({"playing_state": 7}) is True


def test_build_unity_team_falls_back_to_round_robin_when_aptitude_is_unknown():
    runner = CareerRunner.__new__(CareerRunner)
    runner._unity_aptitudes = {}
    team_data_set = {
        "evaluation_info_array": [
            {"member_state": 1, "chara_id": 9001},
            {"member_state": 0, "chara_id": 9998},
            {"member_state": 1, "chara_id": 9002},
            {"member_state": 1, "chara_id": 9003},
            {"member_state": 1, "chara_id": 9004},
            {"member_state": 1, "chara_id": 9005},
        ],
    }

    roster = runner._build_unity_team(
        team_data_set,
        {"card_id": 999901},
        {"unity_config": {"default_running_style": 4}},
    )

    assert roster == [
        {"distance_type": 1, "member_id": 1, "chara_id": 9999, "running_style": 4},
        {"distance_type": 2, "member_id": 1, "chara_id": 9001, "running_style": 4},
        {"distance_type": 3, "member_id": 1, "chara_id": 9002, "running_style": 4},
        {"distance_type": 4, "member_id": 1, "chara_id": 9003, "running_style": 4},
        {"distance_type": 5, "member_id": 1, "chara_id": 9004, "running_style": 4},
        {"distance_type": 1, "member_id": 2, "chara_id": 9005, "running_style": 4},
    ]


def test_build_unity_team_assigns_distance_and_style_from_aptitude():
    runner = CareerRunner.__new__(CareerRunner)
    runner._unity_aptitudes = {
        100101: {
            "turf": 7, "dirt": 1,
            "short": 1, "mile": 2, "medium": 5, "long": 7,
            "front": 2, "pace": 7, "late": 4, "end": 1,
        },
        200101: {
            "turf": 7, "dirt": 1,
            "short": 7, "mile": 3, "medium": 1, "long": 1,
            "front": 7, "pace": 3, "late": 2, "end": 1,
        },
    }
    team_data_set = {
        "evaluation_info_array": [
            {"target_id": 1, "member_state": 1, "chara_id": 2001},
        ],
        "team_info": {
            "team_chara_info_array": [
                {"training_partner_id": 1, "rank_score": 3000},
            ],
        },
    }

    roster = runner._build_unity_team(
        team_data_set,
        {"card_id": 100101, "speed": 500, "stamina": 500, "power": 500, "guts": 500, "wiz": 500},
        {"unity_config": {"default_running_style": 4}},
    )

    assert roster == [
        {"distance_type": 1, "member_id": 1, "chara_id": 2001, "running_style": 1},
        {"distance_type": 4, "member_id": 1, "chara_id": 1001, "running_style": 2},
    ]


class _FakeTeamRaceClient:
    def __init__(self, *, analyze_error=None, analyze_team_race_set_id=None, opponents=None):
        self.calls = []
        self.analyze_error = analyze_error
        self.analyze_team_race_set_id = analyze_team_race_set_id
        self.opponents = opponents

    def team_edit(self, roster, current_turn=0):
        self.calls.append(("team_edit", roster, current_turn))
        return {"data": {}}

    def opponent_list(self, current_turn=0):
        self.calls.append(("opponent_list", current_turn))
        opponents = self.opponents
        if opponents is None:
            opponents = [{"team_race_set_id": 777}]
        return {"data": {"opponent_info_array": opponents}}

    def team_race_analyze(self, race_set_id, current_turn=0):
        self.calls.append(("team_race_analyze", race_set_id, current_turn))
        if self.analyze_error:
            raise self.analyze_error
        data = {}
        if self.analyze_team_race_set_id:
            data["team_race_set_id"] = self.analyze_team_race_set_id
        return {"data": data}

    def team_race_start(self, team_race_set_id, current_turn=0):
        self.calls.append(("team_race_start", team_race_set_id, current_turn))
        return {"data": {"chara_info": {"turn": current_turn, "playing_state": 8}}}

    def team_race_end(self, current_turn):
        self.calls.append(("team_race_end", current_turn))
        return {"data": {"chara_info": {"turn": current_turn, "playing_state": 9}}}

    def team_race_out(self, current_turn):
        self.calls.append(("team_race_out", current_turn))
        return {"data": {"chara_info": {"turn": current_turn, "playing_state": 1}}}


def _runner_for_team_race():
    runner = CareerRunner.__new__(CareerRunner)
    runner.lock = threading.RLock()
    runner.stop_requested = False
    runner.status = {"turn": 24, "scenario_id": 2, "log": []}
    runner._team_race_turn = None
    runner._team_race_tries = 0
    return runner


def _team_race_state():
    return {
        "data": {
            "chara_info": {"turn": 24, "playing_state": 7, "card_id": 100101},
            "team_data_set": {
                "evaluation_info_array": [
                    {"member_state": 1, "chara_id": 2001},
                ],
            },
        },
    }


def test_runner_executes_full_unity_team_race_flow():
    runner = _runner_for_team_race()
    client = _FakeTeamRaceClient()

    result = runner._team_race(
        client,
        UnityStrategy(),
        _team_race_state(),
        {"unity_config": {"default_running_style": 1}},
        {"current_turn": 24, "phase": "full"},
    )

    assert [call[0] for call in client.calls] == [
        "team_edit",
        "opponent_list",
        "team_race_analyze",
        "team_race_start",
        "team_race_end",
        "team_race_out",
    ]
    assert result["data"]["chara_info"]["playing_state"] == 1
    assert runner._team_race_tries == 0


def test_runner_uses_analyzed_team_race_set_id_for_start():
    runner = _runner_for_team_race()
    client = _FakeTeamRaceClient(analyze_team_race_set_id=888)

    runner._team_race(
        client,
        UnityStrategy(),
        _team_race_state(),
        {},
        {"current_turn": 24, "phase": "full"},
    )

    start_call = next(call for call in client.calls if call[0] == "team_race_start")
    assert start_call == ("team_race_start", 888, 24)


def test_runner_treats_team_race_analyze_as_best_effort():
    runner = _runner_for_team_race()
    client = _FakeTeamRaceClient(analyze_error=RuntimeError("analyze unavailable"))

    result = runner._team_race(
        client,
        UnityStrategy(),
        _team_race_state(),
        {},
        {"current_turn": 24, "phase": "full"},
    )

    assert result["data"]["chara_info"]["playing_state"] == 1
    assert "team_race_start" in [call[0] for call in client.calls]


def test_runner_rejects_team_race_without_race_set_id():
    runner = _runner_for_team_race()
    client = _FakeTeamRaceClient(opponents=[{}])

    with pytest.raises(StateRecoveryError, match="team_race_set_id"):
        runner._team_race(
            client,
            UnityStrategy(),
            _team_race_state(),
            {},
            {"current_turn": 24, "phase": "full"},
        )


def test_unity_client_methods_use_expected_payloads():
    client = UmaClient.__new__(UmaClient)
    calls = []

    def fake_call(endpoint, payload=None, **kwargs):
        calls.append((endpoint, payload, kwargs))
        return {"endpoint": endpoint, "payload": payload}

    client.call = fake_call

    client.opponent_list(24)
    client.team_edit([{"member_id": 1}], 24)
    client.team_race_analyze(777, 24)
    client.team_race_start(777, 24)
    client.team_race_end(24)
    client.team_race_out(24)

    assert calls == [
        ("single_mode_team/opponent_list", {"current_turn": 24}, {}),
        ("single_mode_team/team_edit", {"team_data_array": [{"member_id": 1}], "current_turn": 24}, {}),
        ("single_mode_team/team_race_analyze", {"race_set_id": 777, "current_turn": 24}, {}),
        ("single_mode_team/team_race_start", {"team_race_set_id": 777, "current_turn": 24}, {}),
        ("single_mode_team/team_race_end", {"current_turn": 24}, {}),
        ("single_mode_team/team_race_out", {"current_turn": 24}, {}),
    ]


def test_load_career_sets_scenario_before_using_canonical_endpoint():
    client = UmaClient.__new__(UmaClient)
    client.current_scenario_id = None
    calls = []

    def fake_call(endpoint, payload=None, **kwargs):
        calls.append((endpoint, payload, client.current_scenario_id))
        return {"data": {}}

    client.call = fake_call

    client.load_career(scenario_id=2)

    assert calls == [("single_mode_free/load", {}, 2)]
