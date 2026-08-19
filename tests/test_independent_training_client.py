import json

import pytest

from uma_api import client as client_module
from uma_api.client import StateRecoveryError, UmaClient


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


def run_idle_start(monkeypatch, setup=None):
    """Drive start_independent_training and return the start payload."""
    client = object.__new__(UmaClient)
    calls = []
    client.call = (
        lambda endpoint, payload=None, **kwargs: calls.append(
            (endpoint, payload, kwargs)
        )
        or {"data": {}}
    )
    monkeypatch.setattr("uma_api.client.dna_sleep", lambda *args: None)

    client.start_independent_training(
        setup=setup or setup_payload(),
        tp_info={
            "current_tp": 30,
            "max_tp": 100,
            "max_recovery_time": 0,
        },
        current_money=500,
        succession_rank_point=10,
    )
    return calls[1][1]


def test_idle_start_uses_capture_shape(monkeypatch):
    monkeypatch.delenv("UMA_TRAINING_EVENT", raising=False)
    client = object.__new__(UmaClient)
    calls = []
    sleep_calls = []
    client.call = (
        lambda endpoint, payload=None, **kwargs: calls.append(
            (endpoint, payload, kwargs)
        )
        or {"data": {}}
    )
    monkeypatch.setattr(
        "uma_api.client.dna_sleep",
        lambda *args: sleep_calls.append(args),
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

    assert calls[0] == (
        "idle_single_mode/pre_start",
        {"scenario_id": 3},
        {},
    )
    endpoint, payload, _ = calls[1]
    assert endpoint == "idle_single_mode/start"
    common = payload["single_mode_start_request_common"]
    assert common["start_chara"]["running_style"] == 1
    assert common["start_chara"]["boost_factor_research_event_id"] == 0
    assert common["start_chara"]["is_play_training_challenge"] is False
    assert common["start_chara"]["training_challenge_mode"] == 0
    assert common["start_chara"]["rental_succession_trained_chara"] == {
        "viewer_id": 0,
        "trained_chara_id": 0,
        "is_circle_member": False,
        "is_event_rental": False,
    }
    assert payload["start_info"]["priority_skill_array"][0] == {
        "priority": 1,
        "skill_id": 100011,
    }
    assert payload["start_info"]["race_array"] == [
        {"year": 2, "program_id": 301}
    ]
    assert sleep_calls == []


@pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", "on"])
def test_idle_start_opts_into_training_event_via_env(monkeypatch, value):
    monkeypatch.setenv("UMA_TRAINING_EVENT", value)

    start_chara = run_idle_start(monkeypatch)["single_mode_start_request_common"][
        "start_chara"
    ]

    assert start_chara["is_play_training_challenge"] is True
    assert start_chara["training_challenge_mode"] == 1


@pytest.mark.parametrize("value", ["", "false", "0", "off", "no"])
def test_idle_start_skips_training_event_when_env_falsy(monkeypatch, value):
    monkeypatch.setenv("UMA_TRAINING_EVENT", value)

    start_chara = run_idle_start(monkeypatch)["single_mode_start_request_common"][
        "start_chara"
    ]

    assert start_chara["is_play_training_challenge"] is False
    assert start_chara["training_challenge_mode"] == 0


def test_idle_start_setup_overrides_training_event_env(monkeypatch):
    monkeypatch.setenv("UMA_TRAINING_EVENT", "true")
    setup = setup_payload()
    setup["is_play_training_challenge"] = False

    start_chara = run_idle_start(monkeypatch, setup)[
        "single_mode_start_request_common"
    ]["start_chara"]

    assert start_chara["is_play_training_challenge"] is False
    assert start_chara["training_challenge_mode"] == 0


def test_idle_start_setup_can_pick_training_challenge_mode(monkeypatch):
    monkeypatch.delenv("UMA_TRAINING_EVENT", raising=False)
    setup = setup_payload()
    setup["is_play_training_challenge"] = True
    setup["training_challenge_mode"] = 2

    start_chara = run_idle_start(monkeypatch, setup)[
        "single_mode_start_request_common"
    ]["start_chara"]

    assert start_chara["is_play_training_challenge"] is True
    assert start_chara["training_challenge_mode"] == 2


def test_idle_start_uses_pre_start_server_priority_order(monkeypatch):
    client = object.__new__(UmaClient)
    calls = []
    server_priority_skills = [
        {"priority": 1, "skill_id": 201601},
        {"priority": 2, "skill_id": 201591},
        {"priority": 3, "skill_id": 201701},
        {"priority": 4, "skill_id": 202332},
    ]

    def call(endpoint, payload=None, **kwargs):
        calls.append((endpoint, payload, kwargs))
        if endpoint == "idle_single_mode/pre_start":
            return {
                "data": {
                    "last_idle_single_mode_start_info": {
                        "priority_skill_array": server_priority_skills,
                    },
                },
            }
        return {"data": {}}

    client.call = call
    monkeypatch.setattr("uma_api.client.dna_sleep", lambda *_args: None)

    client.pre_start_independent_training(3)
    client.start_independent_training(
        setup=setup_payload(),
        tp_info={},
        current_money=0,
        succession_rank_point=0,
        prepared=True,
    )

    start_payload = next(
        payload
        for endpoint, payload, _ in calls
        if endpoint == "idle_single_mode/start"
    )
    assert (
        start_payload["start_info"]["priority_skill_array"]
        == server_priority_skills
    )


def test_idle_start_adds_capture_button_info_to_wire_payload(monkeypatch):
    client = object.__new__(UmaClient)
    client.viewer_id = 123
    client.device_id = "device"
    client.device_name = "device-name"
    client.graphics_device = "gpu"
    client.ip_address = "127.0.0.1"
    client.platform_os = "Windows"
    client.locale = "JPN"
    client.steam_id = "steam"
    client.steam_ticket = "ticket"
    client.current_scenario_id = 3
    client._last_raw_call_ts = 0
    client.sid = bytes(16)
    client.udid_str = "0" * 32
    client.auth_key_hex = ""
    client.app_ver = "1"
    client.res_ver = "1"
    client.api_log = lambda *_args, **_kwargs: None
    client.tp_info = {}
    client.coin_info = {}
    client.item_map = {}
    response = type("Response", (), {"status_code": 200, "text": "response"})()
    client.session = type(
        "Session",
        (),
        {"post": lambda *_args, **_kwargs: response},
    )()
    packed_payloads = []

    def capture_pack(_sid, _udid, _auth, payload, _udid_str):
        packed_payloads.append(dict(payload))
        return b"body"

    monkeypatch.setattr(client_module, "pack", capture_pack)
    monkeypatch.setattr(
        client_module,
        "unpack",
        lambda *_args: {
            "data_headers": {"result_code": 1},
            "data": {},
        },
    )
    monkeypatch.setattr(client_module, "dna_sleep", lambda *_args: None)

    client.call(
        "idle_single_mode/start",
        {"single_mode_start_request_common": {}},
    )

    assert packed_payloads[0]["button_info"]
    button_info = json.loads(packed_payloads[0]["button_info"])
    assert button_info == {
        "ViewerId": 123,
        "DeviceId": 4,
        "ScenarioId": 0,
        "ClickPosX": button_info["ClickPosX"],
        "ClickPosY": button_info["ClickPosY"],
        "ClickServerTime": button_info["ClickServerTime"],
        "LogType": 7,
    }


def test_idle_start_reprepares_before_retrying_205(monkeypatch):
    client = object.__new__(UmaClient)
    calls = []
    start_results = iter([
        Exception("API error 205 on idle_single_mode/start"),
        {"data": {}},
    ])

    def call(endpoint, payload=None, **kwargs):
        calls.append((endpoint, payload, kwargs))
        if endpoint == "idle_single_mode/start":
            result = next(start_results)
            if isinstance(result, Exception):
                raise result
            return result
        return {"data": {}}

    client.call = call
    monkeypatch.setattr("uma_api.client.dna_sleep", lambda *_args: None)

    client.start_independent_training(
        setup=setup_payload(),
        tp_info={},
        current_money=0,
        succession_rank_point=0,
    )

    assert [endpoint for endpoint, _, _ in calls] == [
        "idle_single_mode/pre_start",
        "idle_single_mode/start",
        "idle_single_mode/pre_start",
        "idle_single_mode/start",
    ]
    assert calls[1][2] == {"retry_205": 0, "retry_208": 0, "retry_501": 0}


def test_idle_start_reprepares_after_501_relogin(monkeypatch):
    client = object.__new__(UmaClient)
    calls = []
    refreshed = []
    start_results = iter([
        StateRecoveryError("API error 501 on idle_single_mode/start"),
        {"data": {}},
    ])

    def call(endpoint, payload=None, **kwargs):
        calls.append((endpoint, payload, kwargs))
        if endpoint == "idle_single_mode/start":
            result = next(start_results)
            if isinstance(result, Exception):
                raise result
            return result
        return {"data": {}}

    client.call = call
    client._refresh_ticket_and_login = lambda: refreshed.append(True)
    monkeypatch.setattr("uma_api.client.dna_sleep", lambda *_args: None)

    client.start_independent_training(
        setup=setup_payload(),
        tp_info={},
        current_money=0,
        succession_rank_point=0,
    )

    assert refreshed == [True]
    assert [endpoint for endpoint, _, _ in calls] == [
        "idle_single_mode/pre_start",
        "idle_single_mode/start",
        "pre_single_mode/index",
        "idle_single_mode/pre_start",
        "idle_single_mode/start",
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
            "check_independent_training_progress_log",
            (),
            "idle_single_mode/check_progress_log",
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
            {
                "factor_lottery_id": 2,
                "current_turn": 78,
                "is_force_delete": False,
            },
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
