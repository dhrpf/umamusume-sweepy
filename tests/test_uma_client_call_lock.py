import threading

import pytest

from uma_api import client as client_module


def _bare_client():
    client = object.__new__(client_module.UmaClient)
    client._call_lock = threading.RLock()
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
    return client


def test_call_serializes_the_complete_api_transaction():
    client = _bare_client()
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()
    results = []
    errors = []

    def unlocked(endpoint, *args, **kwargs):
        if endpoint == "first":
            first_entered.set()
            release_first.wait(1)
        else:
            second_entered.set()
        return endpoint

    client._call_unlocked = unlocked

    def invoke(endpoint):
        try:
            results.append(client.call(endpoint))
        except Exception as exc:
            errors.append(exc)

    first = threading.Thread(target=invoke, args=("first",))
    second = threading.Thread(target=invoke, args=("second",))
    first.start()
    assert first_entered.wait(1)
    second.start()

    assert not second_entered.wait(0.05)
    release_first.set()
    first.join(1)
    second.join(1)

    assert errors == []
    assert results == ["first", "second"]
    assert second_entered.is_set()


def test_successful_response_retains_authoritative_server_time(monkeypatch):
    client = _bare_client()
    response = type("Response", (), {"status_code": 200, "text": "response"})()
    client.session = type(
        "Session",
        (),
        {"post": lambda *_args, **_kwargs: response},
    )()

    monkeypatch.setattr(client_module, "pack", lambda *_args: b"body")
    monkeypatch.setattr(
        client_module,
        "unpack",
        lambda *_args: {
            "data_headers": {"result_code": 1, "servertime": 123456},
            "data": {},
        },
    )
    monkeypatch.setattr(client_module, "dna_sleep", lambda *_args: None)

    client.call("idle_single_mode/status")

    assert client.last_server_time == 123456


def test_error_response_does_not_replace_live_viewer_id(monkeypatch):
    client = _bare_client()
    response = type("Response", (), {"status_code": 200, "text": "response"})()
    client.session = type(
        "Session",
        (),
        {"post": lambda *_args, **_kwargs: response},
    )()

    monkeypatch.setattr(client_module, "pack", lambda *_args: b"body")
    monkeypatch.setattr(
        client_module,
        "unpack",
        lambda *_args: {
            "data_headers": {"result_code": 205, "viewer_id": 456},
            "data": {},
        },
    )
    monkeypatch.setattr(client_module, "dna_sleep", lambda *_args: None)

    with pytest.raises(Exception, match="API error 205"):
        client.call("idle_single_mode/start", retry_205=0)

    assert client.viewer_id == 123


def test_501_adopts_live_viewer_even_when_transport_retry_is_disabled(
    monkeypatch,
):
    client = _bare_client()
    client._cfg = {"viewer_id": 123}
    response = type("Response", (), {"status_code": 200, "text": "response"})()
    client.session = type(
        "Session",
        (),
        {"post": lambda *_args, **_kwargs: response},
    )()

    monkeypatch.setattr(client_module, "pack", lambda *_args: b"body")
    monkeypatch.setattr(
        client_module,
        "unpack",
        lambda *_args: {
            "data_headers": {"result_code": 501, "viewer_id": 456},
            "data": {},
        },
    )
    monkeypatch.setattr(client_module, "dna_sleep", lambda *_args: None)

    with pytest.raises(client_module.StateRecoveryError, match="501"):
        client.call("idle_single_mode/start", retry_501=0)

    assert client.viewer_id == 456
    assert client._cfg["viewer_id"] == 456


def test_scenario_id_detected_from_nested_end_info_chara_info(monkeypatch):
    """idle_single_mode/result and idle_single_mode/end nest chara_info under
    end_info rather than at the top level of data — the scenario_id autodetect
    must look there too, or single_mode_free/* never remaps to
    single_mode_live/* for these scenarios and gain_skills/factor_select hit
    the wrong endpoint."""
    client = _bare_client()
    client.current_scenario_id = None
    response = type("Response", (), {"status_code": 200, "text": "response"})()
    client.session = type(
        "Session",
        (),
        {"post": lambda *_args, **_kwargs: response},
    )()

    monkeypatch.setattr(client_module, "pack", lambda *_args: b"body")
    monkeypatch.setattr(
        client_module,
        "unpack",
        lambda *_args: {
            "data_headers": {"result_code": 1, "sid": "ab"},
            "data": {"end_info": {"chara_info": {"scenario_id": 3}}},
        },
    )
    monkeypatch.setattr(client_module, "dna_sleep", lambda *_args: None)

    client.call("idle_single_mode/result")

    assert client.current_scenario_id == 3


def test_generic_error_chains_sid_forward_since_server_echoes_no_sid(
    monkeypatch,
):
    client = _bare_client()
    client.sid = bytes.fromhex("11" * 16)
    stale_sid = client.sid
    response = type("Response", (), {"status_code": 200, "text": "response"})()
    client.session = type(
        "Session",
        (),
        {"post": lambda *_args, **_kwargs: response},
    )()

    monkeypatch.setattr(client_module, "pack", lambda *_args: b"body")
    monkeypatch.setattr(
        client_module,
        "unpack",
        lambda *_args: {
            "data_headers": {"result_code": 217, "sid": ""},
            "data": {},
        },
    )
    monkeypatch.setattr(client_module, "dna_sleep", lambda *_args: None)

    with pytest.raises(Exception, match="API error 217"):
        client.call("single_mode_free/gain_skills", retry_205=0)

    assert client.sid != stale_sid
    assert client.sid == client_module.next_sid(stale_sid.hex())


def test_709_adopts_live_viewer_and_regenerates_sid(monkeypatch):
    client = _bare_client()
    regen_calls = []
    client.regen_sid = lambda: regen_calls.append(client.viewer_id)
    response = type("Response", (), {"status_code": 200, "text": "response"})()
    client.session = type(
        "Session",
        (),
        {"post": lambda *_args, **_kwargs: response},
    )()

    monkeypatch.setattr(client_module, "pack", lambda *_args: b"body")
    monkeypatch.setattr(
        client_module,
        "unpack",
        lambda *_args: {
            "data_headers": {"result_code": 709, "viewer_id": 456},
            "data": {},
        },
    )
    monkeypatch.setattr(client_module, "dna_sleep", lambda *_args: None)

    with pytest.raises(Exception, match="709"):
        client.call("idle_single_mode/status")

    assert client.viewer_id == 456
    assert regen_calls == [456]
