import json

from uma_api import client as client_module


def bare_client():
    client = object.__new__(client_module.UmaClient)
    client.viewer_id = 123
    client.device_id = "device"
    client.device_name = "device-name"
    client.graphics_device = "gpu"
    client.ip_address = "127.0.0.1"
    client.platform_os = "Windows"
    client.locale = "JPN"
    client.steam_id = "steam"
    client.steam_ticket = "ticket"
    client.current_scenario_id = 2
    client._last_raw_call_ts = 0
    client.sid = bytes(16)
    client.udid_str = "0" * 32
    client.auth_key_hex = ""
    client.app_ver = "1"
    client.res_ver = "1"
    return client


def capture_request_payload(monkeypatch, endpoint):
    captured = {"jitter": [-100, 100]}
    client = bare_client()
    response = type("Response", (), {"status_code": 200, "text": "response"})()

    monkeypatch.setattr(client_module, "pack", lambda *_args: b"body")
    monkeypatch.setattr(
        client_module,
        "unpack",
        lambda *_args: {"data_headers": {"result_code": 1}, "data": {}},
    )
    monkeypatch.setattr(client_module.time, "time", lambda: 1000)
    monkeypatch.setattr(client_module, "dna_sleep", lambda *_args: None)
    monkeypatch.setattr(
        client_module,
        "dna_randint",
        lambda low, high: captured["jitter"].pop(0),
    )
    client.session = type(
        "Session",
        (),
        {"post": lambda *_args, **_kwargs: response},
    )()
    client.api_log = lambda direction, ep, data, req_id=None: (
        captured.setdefault("request", (direction, ep, data))
        if direction == "REQ"
        else None
    )

    client.call(endpoint, {"start_chara": {}})

    return captured["request"]


def test_team_start_sends_captured_button_info(monkeypatch):
    direction, endpoint, data = capture_request_payload(
        monkeypatch,
        "single_mode_free/start",
    )

    assert direction == "REQ"
    assert endpoint == "single_mode_team/start"
    button = json.loads(data["payload"]["button_info"])
    assert button == {
        "ViewerId": 123,
        "DeviceId": 4,
        "ScenarioId": 0,
        "ClickPosX": 9401548,
        "ClickPosY": 1397685,
        "ClickServerTime": 1000,
        "LogType": 6,
    }


def test_non_start_keeps_empty_button_info(monkeypatch):
    _direction, endpoint, data = capture_request_payload(
        monkeypatch,
        "single_mode_free/load",
    )

    assert endpoint == "single_mode_team/load"
    assert data["payload"]["button_info"] == ""
