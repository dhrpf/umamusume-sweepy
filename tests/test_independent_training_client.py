import pytest

from uma_api.client import UmaClient


def setup_payload():
    return {
        "card_id": 100101,
        "support_card_ids": [30001, 30002, 30003, 30004, 30005],
        "friend_viewer_id": 70001,
        "friend_card_id": 30006,
        "parent_id_1": 101,
        "parent_id_2": 202,
        "rental_viewer_id": 0,
        "rental_trained_chara_id": 0,
        "scenario_id": 3,
        "deck_id": 1,
        "running_style": 1,
        "difficulty_id": 0,
        "difficulty": 0,
        "is_boost": 0,
        "boost_story_event_id": 0,
        "training_policy_ground_type": 1,
        "training_policy_param_rate_set_id": 1,
        "priority_skill_array": [
            {"priority": 1, "skill_id": 100011},
        ],
        "race_array": [{"year": 2, "program_id": 301}],
        "use_tp": 30,
    }


def test_idle_start_uses_capture_shape():
    client = object.__new__(UmaClient)
    calls = []
    client.call = (
        lambda endpoint, payload=None, **kwargs: calls.append(
            (endpoint, payload, kwargs)
        )
        or {"data": {}}
    )

    client.start_independent_training(
        setup=setup_payload(),
        tp_info={
            "current_tp": 30,
            "max_tp": 100,
            "max_recovery_time": 0,
        },
        current_money=500,
        succession_rank_point=10,
    )

    endpoint, payload, _ = calls[0]
    assert endpoint == "idle_single_mode/start"
    common = payload["single_mode_start_request_common"]
    assert common["start_chara"]["running_style"] == 1
    assert common["start_chara"]["boost_factor_research_event_id"] == 0
    assert common["start_chara"]["training_challenge_mode"] == 0
    assert payload["start_info"]["priority_skill_array"][0] == {
        "priority": 1,
        "skill_id": 100011,
    }
    assert payload["start_info"]["race_array"] == [
        {"year": 2, "program_id": 301}
    ]


def test_independent_factor_lottery_routes_to_grand_live():
    client = object.__new__(UmaClient)
    client.current_scenario_id = 3
    assert client._scenario_endpoint(
        "single_mode_free/factor_lottery"
    ) == "single_mode_live/factor_lottery"


@pytest.mark.parametrize(
    ("method", "args", "endpoint", "payload", "kwargs"),
    [
        (
            "pre_start_independent_training",
            (3,),
            "idle_single_mode/pre_start",
            {"scenario_id": 3},
            {},
        ),
        (
            "independent_training_status",
            (),
            "idle_single_mode/status",
            {},
            {},
        ),
        (
            "end_independent_training",
            (),
            "idle_single_mode/end",
            {},
            {},
        ),
        (
            "select_independent_factors",
            (78,),
            "single_mode_free/factor_select",
            {"current_turn": 78},
            {},
        ),
        (
            "reroll_independent_factors",
            (
                1,
                {
                    "current_tp": 30,
                    "max_tp": 100,
                    "max_recovery_time": 0,
                },
            ),
            "single_mode_free/factor_lottery",
            {
                "lottery_count": 1,
                "tp_info": {
                    "current_tp": 30,
                    "max_tp": 100,
                    "max_recovery_time": 0,
                },
                "use_tp": 30,
            },
            {"retry_205": 0},
        ),
        (
            "finish_independent_training",
            (78, 2),
            "single_mode_free/finish",
            {"factor_lottery_id": 2, "current_turn": 78},
            {},
        ),
    ],
)
def test_independent_wrapper_payloads(
    method,
    args,
    endpoint,
    payload,
    kwargs,
):
    client = object.__new__(UmaClient)
    calls = []
    client.call = (
        lambda ep, body=None, **options: calls.append(
            (ep, body, options)
        )
        or {}
    )
    getattr(client, method)(*args)
    assert calls == [(endpoint, payload, kwargs)]
