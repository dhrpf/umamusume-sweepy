import pytest
from fastapi.testclient import TestClient

import main
from career_bot.independent_training.service import WorkflowConflict
from career_bot.independent_training.store import InvalidRunTransition, RunNotFound


def setup_payload():
    return {
        "card_id": 100101,
        "support_card_ids": [1, 2, 3, 4, 5],
        "friend_viewer_id": 70001,
        "friend_card_id": 6,
        "parent_id_1": 11,
        "parent_id_2": 22,
        "scenario_id": 3,
        "deck_id": 1,
        "running_style": 1,
        "training_policy_ground_type": 1,
        "training_policy_param_rate_set_id": 1,
        "priority_skill_array": [],
        "race_array": [],
        "factor_reroll": {"enabled": False, "targets": []},
        "use_tp": 30,
    }


class FakeService:
    def __init__(self):
        self.calls = []
        self.error = None

    def _call(self, method, *args, **kwargs):
        self.calls.append((method, args, kwargs))
        if self.error:
            raise self.error
        return {"method": method}

    def bootstrap(self):
        return self._call("bootstrap")

    def enqueue(self, setup, *, count, tp_mode):
        return self._call(
            "enqueue",
            setup,
            count=count,
            tp_mode=tp_mode,
        )

    def start(self):
        return self._call("start")

    def status(self):
        return self._call("status")

    def stop_after_current(self):
        return self._call("stop_after_current")

    def resume(self):
        return self._call("resume")

    def cancel(self, run_id):
        return self._call("cancel", run_id)

    def reconcile(self):
        return self._call("reconcile")


@pytest.fixture
def fake_service(monkeypatch):
    service = FakeService()
    monkeypatch.setattr(main, "independent_service", service)
    return service


@pytest.fixture
def client():
    return TestClient(main.app)


def test_runtime_directory_binds_independent_account(monkeypatch):
    monkeypatch.setenv("UMA_RUNTIME_DIR", "/runtime/accounts/acct-runtime")
    monkeypatch.setattr(main, "active_account", {"name": "other-account"})

    assert main._independent_account() == "acct-runtime"


def test_enqueue_uses_bound_account_and_accepts_no_account_parameter(
    client,
    fake_service,
):
    body = {
        "setup": setup_payload(),
        "count": 2,
        "tp_mode": "wait",
    }

    response = client.post("/api/independent-training/runs", json=body)

    assert response.status_code == 200
    assert b"account" not in response.request.content
    assert fake_service.calls[-1][0] == "enqueue"
    assert fake_service.calls[-1][2] == {
        "count": 2,
        "tp_mode": "wait",
    }


@pytest.mark.parametrize(
    "route",
    [
        "/api/independent-training/start",
        "/api/independent-training/resume",
        "/api/independent-training/reconcile",
    ],
)
def test_async_commands_return_202(client, fake_service, route):
    response = client.post(route)

    assert response.status_code == 202


@pytest.mark.parametrize(
    ("method", "route", "expected_call"),
    [
        ("get", "/api/independent-training/bootstrap", "bootstrap"),
        ("get", "/api/independent-training/status", "status"),
        (
            "post",
            "/api/independent-training/stop-after-current",
            "stop_after_current",
        ),
        ("delete", "/api/independent-training/runs/run-1", "cancel"),
    ],
)
def test_routes_delegate_to_service(
    client,
    fake_service,
    method,
    route,
    expected_call,
):
    response = client.request(method, route)

    assert response.status_code == 200
    assert fake_service.calls[-1][0] == expected_call


def test_workflow_conflict_returns_409(client, fake_service):
    fake_service.error = WorkflowConflict("active campaign lease")

    response = client.post("/api/independent-training/start")

    assert response.status_code == 409
    assert "campaign" in response.json()["detail"]


def test_unknown_run_returns_404(client, fake_service):
    fake_service.error = RunNotFound("missing")

    response = client.delete("/api/independent-training/runs/missing")

    assert response.status_code == 404


def test_run_state_conflict_returns_409(client, fake_service):
    fake_service.error = InvalidRunTransition("run already started")

    response = client.delete("/api/independent-training/runs/run-1")

    assert response.status_code == 409
    assert "already started" in response.json()["detail"]


def test_invalid_setup_is_rejected_before_service_call(client, fake_service):
    body = {
        "setup": {**setup_payload(), "support_card_ids": [1, 2]},
        "count": 1,
        "tp_mode": "wait",
    }

    response = client.post("/api/independent-training/runs", json=body)

    assert response.status_code == 422
    assert fake_service.calls == []


@pytest.mark.parametrize(
    ("route", "body"),
    [
        ("/api/campaigns/cmp1/activate", None),
        ("/api/campaigns/cmp1/advance", None),
        (
            "/api/career/start",
            {
                "card_id": 100101,
                "support_card_ids": [1, 2, 3, 4, 5],
                "friend_viewer_id": 70001,
                "friend_card_id": 6,
                "parent_id_1": 11,
                "parent_id_2": 22,
            },
        ),
        ("/api/career/run", {}),
        ("/api/dailies/run", {}),
    ],
)
def test_other_workflows_are_blocked_by_independent_training_lease(
    client,
    fake_service,
    monkeypatch,
    route,
    body,
):
    class JobStore:
        def get_workflow_lease(self, account):
            return {
                "account": account,
                "workflow_type": "independent_training",
                "owner": "independent-training:acct01",
            }

    monkeypatch.setattr(main, "workflow_job_store", JobStore())
    monkeypatch.setattr(main, "active_account", {"name": "acct01"})

    response = client.post(route, json=body)

    assert response.status_code == 409
    assert "Independent Training" in response.json()["detail"]


def test_runner_snapshot_blocks_other_workflow_after_lease_expiry(
    client,
    fake_service,
    monkeypatch,
):
    class JobStore:
        def get_workflow_lease(self, account):
            return None

    class Runner:
        def snapshot(self):
            return {"state": "RUNNING", "account": "acct01"}

    monkeypatch.setattr(main, "workflow_job_store", JobStore())
    monkeypatch.setattr(main, "independent_runner", Runner())
    monkeypatch.setattr(main, "active_account", {"name": "acct01"})

    response = client.post("/api/campaigns/cmp1/activate")

    assert response.status_code == 409
    assert "Independent Training" in response.json()["detail"]
