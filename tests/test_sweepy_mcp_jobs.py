import sweepy_mcp
from sweepy_jobs import SweepyJobStore


class FakeGateway:
    def __init__(self):
        self.calls = []
        self.responses = {}

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        return self.responses.get((method, path), {"success": True})


class FakeRegistry:
    def __init__(self, gateways):
        self.gateways = dict(gateways)

    def list_accounts(self):
        return [
            {"name": name, "port": 1600 + index, "enabled": True}
            for index, name in enumerate(self.gateways, 1)
        ]

    def resolve(self, account=""):
        if account not in self.gateways:
            raise ValueError(f"Unknown Sweepy account: {account}")
        return account, self.gateways[account]


class FakeSupervisor:
    def __init__(self):
        self.calls = []

    def launch(self, account):
        self.calls.append(("launch", account))
        return {"success": True, "account": account, "managed": True}

    def stop(self, account, timeout_seconds=10, force=False):
        self.calls.append(("stop", account, timeout_seconds, force))
        return {"success": True, "account": account, "stopped": True}

    def restart(self, account, timeout_seconds=10, force=False):
        self.calls.append(("restart", account, timeout_seconds, force))
        return {"success": True, "account": account, "restarted": True}


def configure(monkeypatch, tmp_path, gateways, supervisor=None):
    store = SweepyJobStore(tmp_path / "control-plane.sqlite3")
    monkeypatch.setattr(sweepy_mcp, "job_store", store)
    monkeypatch.setattr(sweepy_mcp, "account_registry", FakeRegistry(gateways))
    if supervisor is not None:
        monkeypatch.setattr(sweepy_mcp, "supervisor", supervisor)
    return store


def test_confirmation_preview_returns_reusable_operation_id(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path, {"alpha": FakeGateway()})

    preview = sweepy_mcp.run_dailies(
        account="alpha",
        team_trials=True,
        confirm=False,
    )

    assert preview["requires_confirmation"] is True
    assert preview["operation_id"]
    assert preview["details"]["account"] == "alpha"
    assert preview["instruction"].endswith("confirm=true after user approval.")


def test_same_operation_id_replays_dailies_without_second_api_call(monkeypatch, tmp_path):
    gateway = FakeGateway()
    store = configure(monkeypatch, tmp_path, {"alpha": gateway})

    first = sweepy_mcp.run_dailies(
        account="alpha",
        team_trials=False,
        daily_shop=True,
        confirm=True,
        operation_id="discord-100",
    )
    replay = sweepy_mcp.run_dailies(
        account="alpha",
        team_trials=False,
        daily_shop=True,
        confirm=True,
        operation_id="discord-100",
    )

    posts = [call for call in gateway.calls if call[:2] == ("POST", "/api/dailies/run")]
    assert len(posts) == 1
    assert first["success"] is True
    assert first["operation_id"] == "discord-100"
    assert replay["success"] is True
    assert replay["replayed"] is True
    assert replay["operation_id"] == "discord-100"
    assert store.get_workflow_lease("alpha")["workflow_type"] == "dailies"


def test_operation_id_with_changed_arguments_is_rejected(monkeypatch, tmp_path):
    gateway = FakeGateway()
    configure(monkeypatch, tmp_path, {"alpha": gateway})

    first = sweepy_mcp.run_dailies(
        account="alpha",
        team_trials=True,
        confirm=True,
        operation_id="discord-101",
    )
    changed = sweepy_mcp.run_dailies(
        account="alpha",
        team_trials=False,
        daily_shop=True,
        confirm=True,
        operation_id="discord-101",
    )

    assert first["success"] is True
    assert changed["success"] is False
    assert "different arguments" in changed["detail"]
    posts = [call for call in gateway.calls if call[:2] == ("POST", "/api/dailies/run")]
    assert len(posts) == 1


def test_workflow_lease_blocks_same_account_but_not_other_account(monkeypatch, tmp_path):
    alpha = FakeGateway()
    beta = FakeGateway()
    store = configure(monkeypatch, tmp_path, {"alpha": alpha, "beta": beta})
    store.acquire_workflow_lease(
        "alpha",
        owner="operation:career-existing",
        workflow_type="career",
        ttl_seconds=3600,
    )

    blocked = sweepy_mcp.run_dailies(
        account="alpha",
        team_trials=True,
        confirm=True,
        operation_id="discord-102",
    )
    allowed = sweepy_mcp.run_dailies(
        account="beta",
        team_trials=True,
        confirm=True,
        operation_id="discord-103",
    )

    assert blocked["success"] is False
    assert "active career lease" in blocked["detail"]
    assert not any(call[:2] == ("POST", "/api/dailies/run") for call in alpha.calls)
    assert allowed["success"] is True
    assert any(call[:2] == ("POST", "/api/dailies/run") for call in beta.calls)


def test_stop_dailies_releases_workflow_lease_and_is_idempotent(monkeypatch, tmp_path):
    gateway = FakeGateway()
    store = configure(monkeypatch, tmp_path, {"alpha": gateway})
    store.acquire_workflow_lease(
        "alpha",
        owner="operation:run",
        workflow_type="dailies",
        ttl_seconds=3600,
    )

    first = sweepy_mcp.stop_dailies(account="alpha", operation_id="discord-104")
    replay = sweepy_mcp.stop_dailies(account="alpha", operation_id="discord-104")

    posts = [call for call in gateway.calls if call[:2] == ("POST", "/api/dailies/stop")]
    assert len(posts) == 1
    assert first["success"] is True
    assert replay["replayed"] is True
    assert store.get_workflow_lease("alpha") is None


def test_lifecycle_operation_is_idempotent(monkeypatch, tmp_path):
    gateway = FakeGateway()
    supervisor = FakeSupervisor()
    configure(monkeypatch, tmp_path, {"alpha": gateway}, supervisor=supervisor)

    first = sweepy_mcp.launch_bot(
        account="alpha",
        confirm=True,
        operation_id="discord-105",
    )
    replay = sweepy_mcp.launch_bot(
        account="alpha",
        confirm=True,
        operation_id="discord-105",
    )

    assert first["success"] is True
    assert replay["replayed"] is True
    assert supervisor.calls == [("launch", "alpha")]


def test_get_bot_state_reconciles_finished_and_external_workflows(monkeypatch, tmp_path):
    gateway = FakeGateway()
    gateway.responses[("GET", "/api/session")] = {"success": True, "account": {}}
    gateway.responses[("GET", "/api/career/runner")] = {
        "success": True,
        "runner": {"running": False},
    }
    gateway.responses[("GET", "/api/dailies/status")] = {
        "success": True,
        "status": {"running": False},
    }
    gateway.responses[("GET", "/api/settings/turn-delay")] = {"min": 0.2, "max": 0.5}
    store = configure(monkeypatch, tmp_path, {"alpha": gateway})
    store.acquire_workflow_lease(
        "alpha",
        owner="operation:old",
        workflow_type="career",
        ttl_seconds=3600,
    )

    idle = sweepy_mcp.get_bot_state(account="alpha")
    assert idle["success"] is True
    assert idle["workflow_lease"] is None
    assert store.get_workflow_lease("alpha") is None

    gateway.responses[("GET", "/api/dailies/status")] = {
        "success": True,
        "status": {"running": True, "task": "Daily Shop"},
    }
    active = sweepy_mcp.get_bot_state(account="alpha")

    assert active["workflow_lease"]["workflow_type"] == "dailies"
    assert active["workflow_lease"]["owner"].startswith("external:")


def test_recent_operations_tool_is_account_scoped(monkeypatch, tmp_path):
    store = configure(
        monkeypatch,
        tmp_path,
        {"alpha": FakeGateway(), "beta": FakeGateway()},
    )
    store.begin_operation(
        operation_id="alpha-op",
        account="alpha",
        action="launch_bot",
        arguments={},
    )
    store.complete_operation("alpha-op", {"success": True})
    store.begin_operation(
        operation_id="beta-op",
        account="beta",
        action="launch_bot",
        arguments={},
    )
    store.complete_operation("beta-op", {"success": True})

    result = sweepy_mcp.get_recent_operations(account="alpha", limit=10)

    assert result["success"] is True
    assert result["account"] == "alpha"
    assert [row["operation_id"] for row in result["operations"]] == ["alpha-op"]
