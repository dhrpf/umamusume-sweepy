from uma_api.client import UmaClient


CORE_ENDPOINTS = (
    "load",
    "start",
    "exec_command",
    "check_event",
    "race_entry",
    "race_start",
    "race_end",
    "race_out",
    "finish",
    "factor_select",
    "continue",
    "change_running_style",
    "gain_skills",
    "multi_item_use",
    "multi_item_exchange",
    "minigame_end",
)


def test_grand_live_routes_core_endpoints():
    client = UmaClient.__new__(UmaClient)
    client.current_scenario_id = 3

    assert [
        client._scenario_endpoint(f"single_mode_free/{operation}")
        for operation in CORE_ENDPOINTS
    ] == [
        f"single_mode_live/{operation}"
        for operation in CORE_ENDPOINTS
    ]


def test_existing_scenario_routes_are_preserved():
    client = UmaClient.__new__(UmaClient)

    client.current_scenario_id = 1
    assert client._scenario_endpoint("single_mode_free/load") == "single_mode/load"

    client.current_scenario_id = 2
    assert client._scenario_endpoint("single_mode_free/load") == "single_mode_team/load"

    client.current_scenario_id = 4
    assert client._scenario_endpoint("single_mode_free/load") == "single_mode_free/load"

    client.current_scenario_id = 3
    assert client._scenario_endpoint("single_mode_free/reserve_race") == "single_mode_free/reserve_race"
    assert client._scenario_endpoint("trained_chara/load") == "trained_chara/load"


def test_grand_live_square_and_live_payloads(monkeypatch):
    client = UmaClient.__new__(UmaClient)
    calls = []
    monkeypatch.setattr(
        client,
        "call",
        lambda endpoint, payload=None, **kwargs: calls.append((endpoint, payload)) or {"data": {}},
    )

    client.master_square(40123, 24)
    client.live_start(24)

    assert calls == [
        ("single_mode_live/master_square", {"square_id": 40123, "current_turn": 24}),
        ("single_mode_live/live_start", {"current_turn": 24}),
    ]
