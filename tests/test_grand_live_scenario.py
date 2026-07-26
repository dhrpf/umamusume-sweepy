import copy

import pytest

from career_bot.runner import STRATEGIES
from career_bot.scenarios.grand_live import GrandLiveStrategy


REFERENCE = {
    "11001": {
        "square_type": 1,
        "name": "Steps",
        "reward": "Speed +5",
        "grants_sp": False,
        "token_cost": {"Dance": 10},
        "adds_song_live_id": None,
    }
}


def _state(
    *,
    turn=24,
    playing_state=1,
    career_state=1,
    offered=(),
    events=(),
    finish=False,
):
    data = {
        "chara_info": {
            "turn": turn,
            "state": career_state,
            "playing_state": playing_state,
            "vital": 80,
            "max_vital": 100,
            "speed": 100,
            "stamina": 100,
            "power": 100,
            "guts": 100,
            "wiz": 100,
            "evaluation_info_array": [],
        },
        "home_info": {
            "command_info_array": [{
                "command_type": 7,
                "command_id": 701,
                "is_enable": 1,
            }],
            "race_program_info_array": [],
        },
        "unchecked_event_array": list(events),
        "live_data_set": {
            "next_square_info_array": [
                {"square_id": square_id}
                for square_id in offered
            ],
            "live_performance_info": {
                "dance": 100,
                "max_dance": 200,
            },
            "next_live_id_array": [],
            "command_info_array": [],
        },
    }
    if finish:
        data["single_mode_finish_common"] = {}
    return {"data": data}


def test_strategy_is_registered_and_accepts_live_states():
    assert STRATEGIES[3] is GrandLiveStrategy
    assert GrandLiveStrategy.scenario_id == 3
    assert GrandLiveStrategy.api_prefix == "single_mode_live"
    assert GrandLiveStrategy.allowed_playing_states == frozenset({
        1, 2, 3, 4, 5, 10,
    })
    assert GrandLiveStrategy.calls_race_reward_on_resume is False


def test_mcts_is_disabled():
    strategy = GrandLiveStrategy(square_reference=REFERENCE)

    assert strategy._ensure_mcts({"use_mcts": True}) is None


def test_state_10_buys_lesson_before_live():
    strategy = GrandLiveStrategy(square_reference=REFERENCE)

    decision = strategy.next_decision(
        _state(playing_state=10, offered=[11001]),
        {"scenario_id": 3},
    )

    assert decision.action == "lessons"
    assert decision.payload == {"current_turn": 24, "square_id": 11001}


@pytest.mark.parametrize("turn", [24, 36, 48, 60, 72])
def test_each_server_live_window_dispatches_once(turn):
    strategy = GrandLiveStrategy(square_reference=REFERENCE)
    state = _state(turn=turn, playing_state=10)

    assert strategy.next_decision(state, {"scenario_id": 3}).action == "live_perform"

    state["data"]["chara_info"]["playing_state"] = 1
    assert strategy.next_decision(state, {"scenario_id": 3}).action != "live_perform"


def test_state_5_event_is_drained_not_finished():
    strategy = GrandLiveStrategy(square_reference=REFERENCE)
    event = {"event_id": 9001, "chara_id": 1001, "choice_array": []}

    decision = strategy.next_decision(
        _state(playing_state=5, events=[event]),
        {"scenario_id": 3},
    )

    assert decision.action == "event"


def test_state_5_polls_then_falls_through_without_race_progress():
    strategy = GrandLiveStrategy(square_reference=REFERENCE)
    state = _state(playing_state=5)

    actions = [
        strategy.next_decision(state, {"scenario_id": 3}).action
        for _ in range(strategy.PS5_POLL_LIMIT + 1)
    ]

    assert actions[:strategy.PS5_POLL_LIMIT] == ["state_poll"] * 3
    assert actions[-1] not in {"finish", "race_progress", "state_poll"}


def test_state_5_poll_counter_resets_on_new_turn():
    strategy = GrandLiveStrategy(square_reference=REFERENCE)
    first = _state(turn=24, playing_state=5)
    later = _state(turn=25, playing_state=5)

    for _ in range(strategy.PS5_POLL_LIMIT):
        strategy.next_decision(first, {"scenario_id": 3})

    assert strategy.next_decision(later, {"scenario_id": 3}).action == "state_poll"


def test_real_finish_still_finishes():
    strategy = GrandLiveStrategy(square_reference=REFERENCE)

    assert strategy.next_decision(
        _state(playing_state=5, finish=True),
        {"scenario_id": 3},
    ).action == "finish"
    assert strategy.next_decision(
        _state(playing_state=5, career_state=3),
        {"scenario_id": 3},
    ).action == "finish"


def test_live_training_bonus_uses_only_supplemental_gains_and_tokens():
    strategy = GrandLiveStrategy(square_reference=REFERENCE)
    home = {
        "command_type": 1,
        "command_id": 101,
        "params_inc_dec_info_array": [
            {"target_type": 1, "value": 5},
        ],
    }
    strategy._live_cmd_map[(1, 101)] = {
        "command_type": 1,
        "command_id": 101,
        "params_inc_dec_info_array": [
            {"target_type": 1, "value": 10},
            {"target_type": 6, "value": 3},
        ],
        "performance_value_array": [
            {"performance_type": 1, "value": 4},
            {"performance_type": 2, "value": 6},
        ],
    }

    bonus, reasons, detail = strategy._training_score_bonus(
        home,
        {},
        {"performance_training_weight": 0.6},
        12,
    )

    assert bonus == pytest.approx((8 + 10) * 0.6)
    assert reasons
    assert detail == {
        "live_supplemental_gain": 8.0,
        "live_performance_gain": 10.0,
        "live_training_weight": 0.6,
        "live_bonus": 10.8,
    }


def test_concert_members_are_removed_from_bond_scoring():
    strategy = GrandLiveStrategy(square_reference=REFERENCE)
    state = _state()
    state["data"]["home_info"]["command_info_array"] = [{
        "command_type": 1,
        "command_id": 101,
        "training_partner_array": [10, {"partner_id": 1000}, 11],
    }]

    sanitized = strategy._state_for_ura(state)
    partners = sanitized["data"]["home_info"]["command_info_array"][0][
        "training_partner_array"
    ]

    assert partners == [10, 11]
    assert state["data"]["home_info"]["command_info_array"][0][
        "training_partner_array"
    ] != partners
