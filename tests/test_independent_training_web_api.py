import pytest
from fastapi.testclient import TestClient
from types import SimpleNamespace

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

    def start(self, *, clear_stop=False):
        return self._call("start", clear_stop=clear_stop)

    def status(self):
        return self._call("status")

    def stop_after_current(self):
        return self._call("stop_after_current")

    def resume(self):
        return self._call("resume")

    def cancel(self, run_id):
        return self._call("cancel", run_id)

    def discard(self, run_id, *, reason=""):
        return self._call("discard", run_id, reason=reason)

    def adopt_server_run(self):
        return self._call("adopt_server_run")

    def reconcile(self):
        return self._call("reconcile")

    def list_presets(self):
        return self._call("list_presets")

    def save_preset(self, name, setup, *, count, tp_mode):
        return self._call(
            "save_preset", name, setup, count=count, tp_mode=tp_mode,
        )

    def get_preset(self, name):
        return self._call("get_preset", name)

    def delete_preset(self, name):
        return self._call("delete_preset", name)


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


def test_runtime_directory_is_campaign_fallback_for_unnamed_account(monkeypatch):
    monkeypatch.setenv("UMA_RUNTIME_DIR", "/runtime/accounts/acct-runtime")
    monkeypatch.setattr(main, "active_account", {"tp": {"current": 98}})
    monkeypatch.setattr(main, "active_dashboard_data", {"account": {}})

    assert main._current_campaign_account() == "acct-runtime"
    main._assert_campaign_account("acct-runtime")


def test_named_campaign_account_still_rejects_real_mismatch(monkeypatch):
    monkeypatch.setenv("UMA_RUNTIME_DIR", "/runtime/accounts/acct-runtime")
    monkeypatch.setattr(main, "active_account", {"name": "other-account"})
    monkeypatch.setattr(main, "active_dashboard_data", {})

    with pytest.raises(ValueError, match="acct-runtime.*other-account"):
        main._assert_campaign_account("acct-runtime")


def test_dashboard_provider_exposes_saved_deck_details(monkeypatch):
    deck = {
        "id": 2,
        "name": "Power Deck",
        "cards": [
            {"id": str(value), "name": f"Support {value}"}
            for value in range(1, 6)
        ],
    }
    monkeypatch.setattr(
        main,
        "active_dashboard_data",
        {
            "account": {"name": "acct01"},
            "decks": [deck],
            "friends": [
                {
                    "viewer_id": 70001,
                    "support_card_id": 30006,
                    "support_name": "Friend Support",
                }
            ],
        },
    )
    monkeypatch.setattr(main.preset_store, "read_all", lambda: [])

    result = main._independent_dashboard()

    assert result["decks"] == [deck]
    assert result["friend_supports"] == [
        {
            "viewer_id": 70001,
            "support_card_id": 30006,
            "support_name": "Friend Support",
        }
    ]


def test_independent_dashboard_refreshes_friend_supports_when_not_loaded(
    monkeypatch,
):
    class Client:
        item_map = {}

        def pre_single_mode(self, exclude_viewer_ids=None):
            assert exclude_viewer_ids is None
            return {
                "data": {
                    "summary_user_info_array": [{
                        "viewer_id": 70001,
                        "support_card_id": 30006,
                        "name": "Friend",
                    }],
                }
            }

    monkeypatch.setattr(main, "active_client", Client())
    monkeypatch.setattr(main, "active_account", {"name": "acct01"})
    monkeypatch.setattr(main, "active_dashboard_data", {"umas": []})
    monkeypatch.setattr(main.preset_store, "read_all", lambda: [])

    result = main._independent_dashboard()

    assert result["friend_supports"][0]["support_card_id"] == 30006
    assert main.active_dashboard_data["friendsLoaded"] is True


def test_independent_dashboard_keeps_loading_when_friend_refresh_fails(
    monkeypatch,
):
    class Client:
        item_map = {}

        def pre_single_mode(self, exclude_viewer_ids=None):
            raise RuntimeError("offline")

    monkeypatch.setattr(main, "active_client", Client())
    monkeypatch.setattr(main, "active_account", {"name": "acct01"})
    monkeypatch.setattr(main, "active_dashboard_data", {"umas": []})
    monkeypatch.setattr(main.preset_store, "read_all", lambda: [])

    assert main._independent_dashboard()["friend_supports"] == []


def test_independent_bootstrap_metadata_does_not_pre_start_a_career(
    monkeypatch,
):
    class Client:
        def pre_start_independent_training(self, _scenario_id):
            raise AssertionError("bootstrap must not call pre_start")

    monkeypatch.setattr(main, "active_client", Client())
    monkeypatch.setattr(
        main,
        "_independent_tp_cost",
        lambda _account: SimpleNamespace(cost=30, source="base"),
    )

    metadata = main._independent_pre_start()

    assert metadata == {
        "reserved_race_info": [],
        "last_idle_single_mode_start_info": {},
        "detected_tp_cost": 30,
        "tp_cost_source": "base",
        "tp_cost_error": "",
    }


def test_objective_races_endpoint_returns_owned_trainee_specific_races(
    client,
    monkeypatch,
):
    class Objective:
        deadline_turn = 22
        condition_id = 73

    class Resolver:
        def __init__(self, base_dir, programs):
            assert programs == {73: {"name": "NHK Mile Cup"}}

        def specific_race_objectives(self, chara_id):
            assert chara_id == 1006
            return [Objective()]

    monkeypatch.setattr(
        main,
        "active_dashboard_data",
        {"umas": [{"card_id": 100601, "name": "Taiki Shuttle"}]},
    )
    monkeypatch.setattr(main, "active_account", None)
    monkeypatch.setattr(main.preset_store, "read_all", lambda: [])
    monkeypatch.setattr(main, "race_map", {"program": {"73": {"name": "NHK Mile Cup"}}})
    monkeypatch.setattr(main, "CareerObjectiveResolver", Resolver, raising=False)
    monkeypatch.setattr(main, "_base_chara_id", lambda card_id: 1006)

    response = client.get(
        "/api/independent-training/trainees/100601/objective-races"
    )

    assert response.status_code == 200
    assert response.json() == {
        "card_id": 100601,
        "objective_races": [{
            "turn": 22,
            "program_id": 73,
            "name": "NHK Mile Cup",
        }],
    }


def test_objective_races_endpoint_rejects_unowned_trainee(client, monkeypatch):
    monkeypatch.setattr(main, "active_dashboard_data", {"umas": []})
    monkeypatch.setattr(main, "active_account", None)
    monkeypatch.setattr(main.preset_store, "read_all", lambda: [])

    response = client.get(
        "/api/independent-training/trainees/100601/objective-races"
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Unknown trainee card 100601"


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


def test_named_preset_routes_delegate_to_service(client, fake_service):
    body = {
        "name": "Dirt sprint",
        "setup": setup_payload(),
        "count": 2,
        "tp_mode": "wait",
    }

    assert client.get("/api/independent-training/presets").status_code == 200
    assert client.post("/api/independent-training/presets", json=body).status_code == 200
    assert client.get("/api/independent-training/presets/Dirt%20sprint").status_code == 200
    assert client.delete("/api/independent-training/presets/Dirt%20sprint").status_code == 200
    assert [call[0] for call in fake_service.calls] == [
        "list_presets",
        "save_preset",
        "get_preset",
        "delete_preset",
    ]


@pytest.mark.parametrize(
    "route",
    [
        "/api/independent-training/start",
        "/api/independent-training/resume",
        "/api/independent-training/reconcile",
        "/api/independent-training/adopt-server-run",
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
        (
            "post",
            "/api/independent-training/runs/run-1/discard",
            "discard",
        ),
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


def test_dailies_are_allowed_during_independent_training(
    client,
    fake_service,
    monkeypatch,
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
    monkeypatch.setattr(main, "active_client", object())

    response = client.post("/api/dailies/run", json={})

    assert response.status_code == 200
    assert response.json()["detail"] == "Select at least one daily to run"


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


def test_discard_route_reports_reason_and_state_conflicts(
    client,
    fake_service,
):
    response = client.post("/api/independent-training/runs/run-1/discard")

    assert response.status_code == 200
    assert fake_service.calls[-1] == (
        "discard",
        ("run-1",),
        {"reason": "discarded from dashboard"},
    )

    fake_service.error = InvalidRunTransition("already terminal")
    conflict = client.post("/api/independent-training/runs/run-1/discard")

    assert conflict.status_code == 409


def test_start_route_clears_a_pending_stop_after_current(client, fake_service):
    response = client.post("/api/independent-training/start")

    assert response.status_code == 202
    assert fake_service.calls[-1] == ("start", (), {"clear_stop": True})


def test_adopt_route_delegates_and_reports_missing_server_run(
    client,
    fake_service,
):
    accepted = client.post("/api/independent-training/adopt-server-run")

    assert accepted.status_code == 202
    assert fake_service.calls[-1][0] == "adopt_server_run"

    fake_service.error = RunNotFound("no untracked server career")
    missing = client.post("/api/independent-training/adopt-server-run")

    assert missing.status_code == 404
