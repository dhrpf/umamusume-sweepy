import json

import pytest

import sweepy_mcp


class FakeGateway:
    def __init__(self):
        self.calls = []
        self.responses = {}

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        return self.responses.get((method, path), {"success": True})


class FakeAccountRegistry:
    def __init__(self, gateways):
        self.gateways = dict(gateways)

    def list_accounts(self):
        return [
            {"name": name, "port": 10000 + index, "enabled": True}
            for index, name in enumerate(self.gateways, 1)
        ]

    def resolve(self, account=""):
        if not account:
            if len(self.gateways) != 1:
                raise ValueError("account is required")
            account = next(iter(self.gateways))
        if account not in self.gateways:
            raise ValueError(f"Unknown Sweepy account: {account}")
        return account, self.gateways[account]


class FakeSupervisor:
    def __init__(self):
        self.calls = []

    def status(self, account):
        self.calls.append(("status", account))
        return {
            "account": account,
            "port": 1617,
            "process": {"managed": True, "running": True, "pid": 4321},
            "api": {"reachable": True, "logged_in": True},
        }

    def tail_logs(self, account, *, lines=100, max_bytes=65536):
        self.calls.append(("tail_logs", account, lines, max_bytes))
        return {"success": True, "account": account, "lines": ["ready"]}

    def launch(self, account):
        self.calls.append(("launch", account))
        return {"success": True, "account": account, "already_running": False}

    def stop(self, account, *, timeout_seconds=10, force=False):
        self.calls.append(("stop", account, timeout_seconds, force))
        return {"success": True, "account": account, "stopped": True, "forced": force}

    def restart(self, account, *, timeout_seconds=10, force=False):
        self.calls.append(("restart", account, timeout_seconds, force))
        return {"success": True, "account": account, "restarted": True}

    def wait_until_ready(self, account, *, timeout_seconds=30, require_login=False):
        self.calls.append(("wait_until_ready", account, timeout_seconds, require_login))
        return {"success": True, "account": account, "ready": True}


def sample_session():
    return {
        "success": True,
        "account": {
            "tp": {"current": 70, "max": 100},
            "carrots": {"free": 500, "paid": 0, "total": 500},
            "gold": 123456,
            "clocks": 4,
            "career": None,
            "sid": "should-not-leak",
        },
        "selection": {
            "deck": {
                "id": 3,
                "name": "Speed Deck",
                "cards": [{"id": 301}, {"id": 302}, {"id": 303}, {"id": 304}, {"id": 305}],
            },
            "trainee": {"id": 100101, "name": "Test Uma"},
            "friend": {
                "viewer_id": 999999,
                "support_card_id": 401,
                "support_name": "Friend Support",
            },
            "veterans": [
                {"instance_id": 7001, "name": "Parent A", "rank_score": 12000},
                {"instance_id": 7002, "name": "Parent B", "rank_score": 11000},
            ],
        },
        "parents": [
            {"instance_id": 7001, "name": "Parent A", "rank_score": 12000},
            {"instance_id": 7002, "name": "Parent B", "rank_score": 11000},
        ],
        "umas": [{"id": 100101}],
        "supports": [{"id": 301}],
        "decks": [{"id": 3}],
        "friends": [{"viewer_id": 999999}],
        "auth_key": "should-not-leak",
    }


def test_redact_sensitive_fields_recursively():
    value = {
        "sid": "secret-sid",
        "nested": {
            "steam_session_ticket": "ticket",
            "safe": 123,
            "rows": [{"auth_key": "key", "name": "ok"}],
        },
    }

    assert sweepy_mcp.redact_sensitive(value) == {
        "sid": "<redacted>",
        "nested": {
            "steam_session_ticket": "<redacted>",
            "safe": 123,
            "rows": [{"auth_key": "<redacted>", "name": "ok"}],
        },
    }


def test_compact_state_keeps_operational_data_without_credentials():
    state = sweepy_mcp.compact_session(sample_session())

    assert state["logged_in"] is True
    assert state["account"]["tp"] == {"current": 70, "max": 100}
    assert state["counts"] == {
        "umas": 1,
        "supports": 1,
        "decks": 1,
        "friends": 1,
        "veterans": 2,
    }
    assert state["selection"]["deck"] == {"id": 3, "name": "Speed Deck"}
    assert state["selection"]["friend"] == {
        "support_card_id": 401,
        "support_name": "Friend Support",
    }
    assert state["recommended_veterans"][0]["trained_chara_id"] == 7001
    rendered = repr(state)
    assert "should-not-leak" not in rendered
    assert "viewer_id" not in rendered


def test_run_dailies_requires_confirmation(monkeypatch):
    gateway = FakeGateway()
    monkeypatch.setattr(
        sweepy_mcp,
        "account_registry",
        FakeAccountRegistry({"alpha": gateway}),
    )

    result = sweepy_mcp.run_dailies(
        account="alpha",
        team_trials=True,
        daily_races=False,
        legend_races=False,
        daily_shop=False,
        confirm=False,
    )

    assert result["success"] is False
    assert result["requires_confirmation"] is True
    assert gateway.calls == []


def test_run_dailies_uses_selected_or_recommended_veteran(monkeypatch):
    gateway = FakeGateway()
    gateway.responses[("GET", "/api/session")] = sample_session()
    monkeypatch.setattr(
        sweepy_mcp,
        "account_registry",
        FakeAccountRegistry({"alpha": gateway}),
    )

    result = sweepy_mcp.run_dailies(
        account="alpha",
        team_trials=False,
        daily_races=True,
        legend_races=False,
        daily_shop=False,
        trained_chara_id=0,
        confirm=True,
    )

    assert result["success"] is True
    assert gateway.calls[-1] == (
        "POST",
        "/api/dailies/run",
        {
            "team_trials": False,
            "daily_races": True,
            "legend_races": False,
            "daily_shop": False,
            "trained_chara_id": 7001,
            "opponent_strength": 1,
            "legend_race_id": 0,
        },
    )


def test_build_career_payload_matches_current_ui_selection():
    preset = {
        "name": "Test Preset",
        "scenario_id": 4,
        "run_delay_min_min": 5,
        "run_delay_max_min": 15,
        "tp_mode": "wait",
    }

    payload = sweepy_mcp.build_career_payload(
        sample_session(),
        preset,
        max_steps=1234,
        burn_clocks=True,
        dev_mode=True,
    )

    assert payload == {
        "card_id": 100101,
        "support_card_ids": [301, 302, 303, 304, 305],
        "friend_viewer_id": 999999,
        "friend_card_id": 401,
        "parent_id_1": 7001,
        "parent_id_2": 7002,
        "rental_viewer_id": 0,
        "rental_trained_chara_id": 0,
        "deck_id": 3,
        "scenario_id": 4,
        "use_tp": 30,
        "difficulty_id": 0,
        "difficulty": 0,
        "is_boost": 0,
        "boost_story_event_id": 0,
        "preset_name": "Test Preset",
        "max_steps": 1234,
        "burn_clocks": True,
        "dev_mode": True,
        "run_delay_min_min": 5,
        "run_delay_max_min": 15,
        "tp_mode": "wait",
    }


def test_build_career_payload_fails_when_selection_is_incomplete():
    session = sample_session()
    session["selection"]["friend"] = None

    with pytest.raises(ValueError, match="friend support"):
        sweepy_mcp.build_career_payload(
            session,
            {"name": "Preset", "scenario_id": 4},
            max_steps=100,
            burn_clocks=False,
            dev_mode=False,
        )


def test_account_registry_reads_enabled_accounts_and_routes_by_name(tmp_path):
    accounts = tmp_path / "accounts.json"
    accounts.write_text(
        json.dumps(
            [
                {"name": "alpha", "port": 1616, "enabled": True},
                {"name": "beta", "port": 1617, "enabled": True},
                {"name": "disabled", "port": 1618, "enabled": False},
            ]
        ),
        encoding="utf-8",
    )
    registry = sweepy_mcp.SweepyAccountRegistry(accounts_path=accounts)

    assert registry.list_accounts() == [
        {"name": "alpha", "port": 1616, "enabled": True},
        {"name": "beta", "port": 1617, "enabled": True},
    ]
    name, gateway = registry.resolve("beta")
    assert name == "beta"
    assert gateway.base_url == "http://127.0.0.1:1617"


def test_account_registry_requires_explicit_name_when_multiple_accounts(tmp_path):
    accounts = tmp_path / "accounts.json"
    accounts.write_text(
        json.dumps(
            [
                {"name": "alpha", "port": 1616},
                {"name": "beta", "port": 1617},
            ]
        ),
        encoding="utf-8",
    )
    registry = sweepy_mcp.SweepyAccountRegistry(accounts_path=accounts)

    with pytest.raises(ValueError, match="account is required"):
        registry.resolve("")


def test_get_bot_state_routes_to_requested_account(monkeypatch):
    alpha = FakeGateway()
    beta = FakeGateway()
    for gateway in (alpha, beta):
        gateway.responses[("GET", "/api/session")] = sample_session()
        gateway.responses[("GET", "/api/career/runner")] = {
            "success": True,
            "runner": {"running": False},
        }
        gateway.responses[("GET", "/api/dailies/status")] = {
            "success": True,
            "status": {"running": False},
        }
        gateway.responses[("GET", "/api/settings/turn-delay")] = {
            "min": 0.2,
            "max": 0.5,
        }
    monkeypatch.setattr(
        sweepy_mcp,
        "account_registry",
        FakeAccountRegistry({"alpha": alpha, "beta": beta}),
    )

    result = sweepy_mcp.get_bot_state(account="beta")

    assert result["success"] is True
    assert result["account"] == "beta"
    assert alpha.calls == []
    assert beta.calls == [
        ("GET", "/api/session", None),
        ("GET", "/api/career/runner", None),
        ("GET", "/api/dailies/status", None),
        ("GET", "/api/settings/turn-delay", None),
    ]


def test_get_account_runtime_and_logs_route_to_supervisor(monkeypatch):
    gateway = FakeGateway()
    supervisor = FakeSupervisor()
    monkeypatch.setattr(
        sweepy_mcp,
        "account_registry",
        FakeAccountRegistry({"alpha": gateway, "beta": FakeGateway()}),
    )
    monkeypatch.setattr(sweepy_mcp, "supervisor", supervisor)

    runtime = sweepy_mcp.get_account_runtime(account="alpha")
    logs = sweepy_mcp.get_bot_logs(account="alpha", lines=25)

    assert runtime["success"] is True
    assert runtime["runtime"]["account"] == "alpha"
    assert logs == {"success": True, "account": "alpha", "lines": ["ready"]}
    assert supervisor.calls == [
        ("status", "alpha"),
        ("tail_logs", "alpha", 25, 65536),
    ]


def test_launch_bot_requires_confirmation_and_targets_exact_account(monkeypatch):
    supervisor = FakeSupervisor()
    monkeypatch.setattr(
        sweepy_mcp,
        "account_registry",
        FakeAccountRegistry({"alpha": FakeGateway(), "beta": FakeGateway()}),
    )
    monkeypatch.setattr(sweepy_mcp, "supervisor", supervisor)

    preview = sweepy_mcp.launch_bot(account="beta", confirm=False)
    started = sweepy_mcp.launch_bot(account="beta", confirm=True)

    assert preview["requires_confirmation"] is True
    assert preview["details"] == {"account": "beta"}
    assert started["success"] is True
    assert started["account"] == "beta"
    assert supervisor.calls == [("launch", "beta")]


def test_stop_and_restart_bot_require_confirmation_including_force(monkeypatch):
    supervisor = FakeSupervisor()
    monkeypatch.setattr(
        sweepy_mcp,
        "account_registry",
        FakeAccountRegistry({"alpha": FakeGateway()}),
    )
    monkeypatch.setattr(sweepy_mcp, "supervisor", supervisor)

    stop_preview = sweepy_mcp.stop_bot(
        account="alpha",
        force=True,
        timeout_seconds=7,
        confirm=False,
    )
    restart_preview = sweepy_mcp.restart_bot(
        account="alpha",
        force=False,
        timeout_seconds=8,
        confirm=False,
    )

    assert stop_preview["details"] == {
        "account": "alpha",
        "force": True,
        "timeout_seconds": 7.0,
    }
    assert restart_preview["details"] == {
        "account": "alpha",
        "force": False,
        "timeout_seconds": 8.0,
    }
    assert supervisor.calls == []

    stopped = sweepy_mcp.stop_bot(
        account="alpha",
        force=True,
        timeout_seconds=7,
        confirm=True,
    )
    restarted = sweepy_mcp.restart_bot(
        account="alpha",
        force=False,
        timeout_seconds=8,
        confirm=True,
    )

    assert stopped["forced"] is True
    assert restarted["restarted"] is True
    assert supervisor.calls == [
        ("stop", "alpha", 7.0, True),
        ("restart", "alpha", 8.0, False),
    ]


def test_wait_until_ready_routes_read_only_probe(monkeypatch):
    supervisor = FakeSupervisor()
    monkeypatch.setattr(
        sweepy_mcp,
        "account_registry",
        FakeAccountRegistry({"alpha": FakeGateway()}),
    )
    monkeypatch.setattr(sweepy_mcp, "supervisor", supervisor)

    result = sweepy_mcp.wait_until_ready(
        account="alpha",
        timeout_seconds=12,
        require_login=True,
    )

    assert result["ready"] is True
    assert supervisor.calls == [("wait_until_ready", "alpha", 12.0, True)]


def test_registered_mcp_tools_are_intentional_and_small():
    names = {tool.name for tool in sweepy_mcp.mcp._tool_manager.list_tools()}

    assert names == {
        "list_accounts",
        "get_bot_state",
        "list_career_presets",
        "get_legend_races",
        "run_dailies",
        "stop_dailies",
        "run_career",
        "stop_career",
        "refresh_account",
        "refill_tp",
        "set_turn_delay",
        "get_account_runtime",
        "get_bot_logs",
        "launch_bot",
        "stop_bot",
        "restart_bot",
        "wait_until_ready",
        "get_recent_operations",
        "get_cached_account_snapshot",
        "list_cached_veterans",
        "get_legacy_spark_rules",
        "scan_cached_legacy_loops",
        "preview_shared_g1_agenda",
        "preview_parent_campaign",
        "create_parent_campaign",
        "list_parent_campaigns",
        "get_parent_campaign",
        "get_parent_campaign_summary",
        "start_parent_campaign",
        "advance_parent_campaign",
        "pause_parent_campaign",
        "resume_parent_campaign",
        "cancel_parent_campaign",
        "list_parent_candidates",
        "select_parent_candidate",
        "prepare_parent_campaign_run",
        "run_parent_campaign_career",
        "collect_parent_campaign_result",
    }
