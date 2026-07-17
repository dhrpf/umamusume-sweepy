from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
from career_bot.campaigns.store import CampaignError, CampaignNotFound, InvalidTransition

def valid_web_spec():
    return {
        "account": "acct01",
        "goal": {
            "purpose": "parent",
            "target_factors": [{"name": "stamina", "minimum_stars": 2, "scope": "lineage"}],
        },
        "strategy": {"preset_name": "parent", "maximum_runs": 20, "maximum_runtime_hours": 4},
        "final_uma": {"card_id": 100101},
        "spark_targets": [{"category": "blue", "name": "stamina", "minimum_stars": 9}],
        "loop_members": [
            {"chara_id": 1, "deck_id": 1},
            {"chara_id": 2, "deck_id": 2},
            {"chara_id": 3, "deck_id": 3},
            {"chara_id": 4, "deck_id": 4},
        ],
    }


class FakeCampaignService:
    def __init__(self):
        self.calls = []
        self.error = None

    def _call(self, method, *args, **kwargs):
        self.calls.append((method, args, kwargs))
        if self.error:
            raise self.error
        return {"method": method}

    def list_campaigns(self, account):
        return self._call("list_campaigns", account)

    def recommend_final_parents(self, request):
        return self._call("recommend_final_parents", request)

    def recommend_loops(self, request):
        return self._call("recommend_loops", request)

    def create_campaign(self, spec):
        return self._call("create_campaign", spec)

    def get_campaign(self, campaign_id):
        return self._call("get_campaign", campaign_id)

    def activate(self, campaign_id):
        return self._call("activate", campaign_id)

    def pause(self, campaign_id):
        return self._call("pause", campaign_id)

    def resume(self, campaign_id):
        return self._call("resume", campaign_id)

    def prepare_next_run(self, campaign_id):
        return self._call("prepare_next_run", campaign_id)

    def approve_run(self, campaign_id, selection_override=None):
        return self._call("approve_run", campaign_id, selection_override)

    def select_candidate(self, campaign_id, candidate_id):
        return self._call("select_candidate", campaign_id, candidate_id)

    def continue_for_preferred(self, campaign_id):
        return self._call("continue_for_preferred", campaign_id)

    def cancel(self, campaign_id, reason=""):
        return self._call("cancel", campaign_id, reason)


@pytest.fixture
def fake_campaign_service(monkeypatch):
    service = FakeCampaignService()
    monkeypatch.setattr(main, "campaign_service", service)
    return service


@pytest.fixture
def client():
    return TestClient(main.app)


@pytest.mark.parametrize(
    ("method", "path", "json_body", "expected"),
    [
        ("get", "/api/campaigns?account=acct01", None, ("list_campaigns", ("acct01",), {})),
        ("post", "/api/campaigns/recommend-final-parents", {"final_uma_card_id": 100101, "limit": 2}, ("recommend_final_parents", ({"account": None, "final_uma_card_id": 100101, "spark_targets": [], "limit": 2},), {})),
        ("post", "/api/campaigns/recommend-loop", {"final_uma_card_id": 100101, "final_parent_chara_id": 1004, "limit": 3, "pinned_chara_ids": [1, 2]}, ("recommend_loops", ({"account": None, "final_uma_card_id": 100101, "spark_targets": [], "limit": 3, "pinned_chara_ids": [1, 2], "final_parent_chara_id": 1004},), {})),
        ("get", "/api/campaigns/cmp1", None, ("get_campaign", ("cmp1",), {})),
        ("post", "/api/campaigns/cmp1/activate", None, ("activate", ("cmp1",), {})),
        ("post", "/api/campaigns/cmp1/pause", None, ("pause", ("cmp1",), {})),
        ("post", "/api/campaigns/cmp1/resume", None, ("resume", ("cmp1",), {})),
        ("post", "/api/campaigns/cmp1/prepare-next-run", None, ("prepare_next_run", ("cmp1",), {})),
        ("post", "/api/campaigns/cmp1/approve-run", {"selection_override": {"race_overrides": [1]}}, ("approve_run", ("cmp1", {"race_overrides": [1]}), {})),
        ("post", "/api/campaigns/cmp1/select-candidate", {"candidate_id": "candidate-1"}, ("select_candidate", ("cmp1", "candidate-1"), {})),
        ("post", "/api/campaigns/cmp1/continue-preferred", None, ("continue_for_preferred", ("cmp1",), {})),
        ("post", "/api/campaigns/cmp1/cancel", {"reason": "user"}, ("cancel", ("cmp1", "user"), {})),
    ],
)
def test_campaign_routes_delegate(client, fake_campaign_service, monkeypatch, method, path, json_body, expected):
    monkeypatch.setattr(main, "active_account", {"name": "acct01"})
    response = client.request(method, path, json=json_body)

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert fake_campaign_service.calls[-1] == expected


def test_campaign_advance_route_runs_lifecycle_reconciliation(client, monkeypatch):
    monkeypatch.setattr(
        main,
        "_campaign_advance",
        lambda campaign_id: {"campaign": {"campaign_id": campaign_id, "state": "SELECTING_LINEAGE"}},
    )

    response = client.post("/api/campaigns/cmp1/advance")

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "result": {"campaign": {"campaign_id": "cmp1", "state": "SELECTING_LINEAGE"}},
    }

def test_campaign_create_delegates_to_service(client, fake_campaign_service):
    response = client.post("/api/campaigns", json={"spec": valid_web_spec()})

    assert response.status_code == 200
    assert response.json()["success"] is True
    method, args, kwargs = fake_campaign_service.calls[-1]
    assert method == "create_campaign"
    assert args[0].model_dump(mode="json") == main.ParentCampaignSpec.model_validate(valid_web_spec()).model_dump(mode="json")
    assert kwargs == {}


def test_campaign_list_uses_current_account_when_omitted(client, fake_campaign_service, monkeypatch):
    monkeypatch.setattr(main, "active_account", {"name": "acct-current"})

    response = client.get("/api/campaigns")

    assert response.status_code == 200
    assert fake_campaign_service.calls[-1] == ("list_campaigns", ("acct-current",), {})
    assert response.json()["account"] == "acct-current"


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (CampaignError("conflict"), 409),
        (InvalidTransition("invalid state"), 409),
        (CampaignNotFound("missing"), 404),
        (ValueError("invalid request"), 422),
    ],
)
def test_campaign_known_errors_are_mapped(client, fake_campaign_service, error, status_code):
    fake_campaign_service.error = error

    response = client.post("/api/campaigns", json={"spec": valid_web_spec()})

    assert response.status_code == status_code
    assert response.json() == {"detail": str(error)}


def test_campaign_unexpected_errors_propagate(client, fake_campaign_service):
    fake_campaign_service.error = RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        client.get("/api/campaigns/cmp1")

@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"final_uma_card_id": 0},
        {"final_uma_card_id": 100101, "limit": 0},
        {"final_uma_card_id": 100101, "mdb_path": "/tmp/master.mdb"},
        {"final_uma_card_id": 100101, "factor_map": {}},
        {"final_uma_card_id": 100101, "pinned_chara_ids": [0]},
        {"final_uma_card_id": 100101, "final_parent_chara_id": 0, "pinned_chara_ids": []},
        {"final_uma_card_id": 100101, "spark_targets": [{"category": "blue", "name": "", "minimum_stars": 0}]},
        {"account": "bad account", "final_uma_card_id": 100101},
    ],
)
def test_campaign_recommendation_rejects_malformed_or_extra_fields(client, fake_campaign_service, payload):
    route = "/api/campaigns/recommend-loop" if "pinned_chara_ids" in payload else "/api/campaigns/recommend-final-parents"

    response = client.post(route, json=payload)

    assert response.status_code == 422
    assert fake_campaign_service.calls == []

def test_campaign_runtime_snapshot_uses_nested_runner_contract(monkeypatch):
    class FakeDailiesRunner:
        running = True

    monkeypatch.setattr(main, "active_account", {"name": "acct01", "career": {"active": True}})
    monkeypatch.setattr(main, "active_dashboard_data", {"umas": []})
    monkeypatch.setattr(main, "active_client", object())
    monkeypatch.setattr(main.career_runner, "snapshot", lambda: {"running": True, "finished": False})
    monkeypatch.setattr(main, "dailies_runner", FakeDailiesRunner())

    snapshot = main._campaign_runtime_snapshot("acct01")

    assert snapshot["runtime"] == {"api_reachable": True, "logged_in": True}
    assert snapshot["bot_state"] == {
        "session": {"logged_in": True},
        "career_runner": {"running": True, "finished": False},
        "dailies": {"running": True},
    }

def test_campaign_runtime_snapshot_rejects_active_account_mismatch(monkeypatch):
    monkeypatch.setattr(main, "active_account", {"name": "acct01"})
    monkeypatch.setattr(main, "active_dashboard_data", {})

    with pytest.raises(ValueError, match="acct02.*acct01"):
        main._campaign_runtime_snapshot("acct02")

def test_campaign_start_rejects_active_account_mismatch(monkeypatch):
    monkeypatch.setattr(main, "active_account", {"name": "acct01"})

    with pytest.raises(ValueError, match="acct02.*acct01"):
        main._campaign_start_career({"account": "acct02"})

def _stub_campaign_runtime_launch(monkeypatch):
    class FakeCareerRunner:
        def start(self, *_args, **_kwargs):
            return None

        def snapshot(self):
            return {"running": True}

    monkeypatch.setattr(main, "apply_career_result", lambda _result: ({"career": {"active": True}}, {}))
    monkeypatch.setattr(main, "apply_deck_type_counts", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "_apply_preset_turn_delay", lambda _preset: None)
    monkeypatch.setattr(main, "career_runner", FakeCareerRunner())


def test_campaign_start_propagates_friend_and_races(monkeypatch):
    captured = []
    _stub_campaign_runtime_launch(monkeypatch)
    monkeypatch.setattr(main, "active_account", {"name": "acct01"})
    monkeypatch.setattr(main, "active_client", object())
    monkeypatch.setattr(main, "active_dashboard_data", {"umas": [{"id": 100101}], "decks": [{"id": 3, "cards": [{"id": value} for value in [1, 2, 3, 4, 5]]}]})
    monkeypatch.setattr(
        main,
        "start_career_from_request",
        lambda request: captured.append(request) or {"success": True, "result": {"started": True}},
    )

    result = main._campaign_start_career({
        "account": "acct01",
        "deck_id": 3,
        "trainee_chara_id": 1001,
        "legacy_slots": [{"trained_chara_id": 11}, {"trained_chara_id": 22}],
        "friend_support": {"viewer_id": 33, "support_card_id": 44},
        "race_overrides": {"mandatory_race_list": [7], "extra_race_list": [8]},
        "preset": {
            "name": "parent",
            "friend_viewer_id": 99,
            "friend_card_id": 100,
            "parent_run": True,
        },
    })

    request = captured[0]
    assert result["success"] is True
    assert request.friend_viewer_id == 33
    assert request.friend_card_id == 44
    assert request.support_card_ids == [1, 2, 3, 4, 5]
    assert request.deck_id == 3
    assert request.preset_overrides["mandatory_race_list"] == [7]
    assert request.preset_overrides["extra_race_list"] == [8]
    assert request.preset_overrides["parent_run"] is True


def test_campaign_advance_auto_prepares_and_starts_selecting_lineage(monkeypatch):
    calls = []
    campaign = {
        "campaign_id": "cmp1",
        "account": "acct01",
        "state": "SELECTING_LINEAGE",
        "next_action": "prepare_next_run",
        "context": {},
    }

    class FakeStore:
        def get(self, _campaign_id):
            return dict(campaign)

    class FakeCampaignRunner:
        def reconcile(self, *_args, **_kwargs):
            raise AssertionError("selecting lineage must prepare before runtime reconciliation")

    class FakeCampaignService:
        def prepare_next_run(self, campaign_id):
            calls.append(("prepare", campaign_id))
            campaign.update({
                "state": "SELECTING_LINEAGE",
                "next_action": "start_career",
                "context": {
                    "prepared_run": {"account": "acct01", "campaign_id": "cmp1"},
                    "review_required": False,
                },
            })
            return {"campaign": dict(campaign), "prepared_run": campaign["context"]["prepared_run"]}

        def approve_run(self, campaign_id):
            calls.append(("approve", campaign_id))
            campaign.update({"state": "RUNNING_CAREER", "next_action": "monitor_career"})
            return {"runner": {"running": True}}

    monkeypatch.setattr(main, "campaign_store", FakeStore())
    monkeypatch.setattr(main, "campaign_runner", FakeCampaignRunner())
    monkeypatch.setattr(main, "campaign_service", FakeCampaignService())
    monkeypatch.setattr(
        main,
        "_campaign_runtime_snapshot",
        lambda _account: {
            "current_career": None,
            "runtime": {"api_reachable": True, "logged_in": True},
            "bot_state": {"career_runner": {"running": False}},
        },
    )

    result = main._campaign_advance("cmp1")

    assert calls == [("prepare", "cmp1"), ("approve", "cmp1")]
    assert result["campaign"]["state"] == "RUNNING_CAREER"
    assert result["campaign"]["next_action"] == "monitor_career"


def test_campaign_advance_restarts_matching_active_career_before_collecting(monkeypatch):
    calls = {}
    prepared = {
        "account": "acct01",
        "campaign_id": "cmp1",
        "trainee_chara_id": 1001,
        "deck_id": 4,
        "legacy_slots": [
            {"trained_chara_id": 11},
            {"trained_chara_id": 12},
        ],
    }
    campaign = {
        "campaign_id": "cmp1",
        "account": "acct01",
        "state": "RUNNING_CAREER",
        "context": {"prepared_run": prepared},
    }

    class FakeStore:
        def get(self, _campaign_id):
            return dict(campaign)

        def transition(self, campaign_id, state, **kwargs):
            calls["transition"] = (campaign_id, state, kwargs)
            return {**campaign, "state": getattr(state, "value", state), **kwargs}

    class FakeCampaignRunner:
        def reconcile(self, *_args, **_kwargs):
            raise AssertionError("active career must be resumed before result reconciliation")

    class FakeCampaignService:
        def start_career(self, request):
            calls["start"] = request
            return {"success": True, "runner": {"running": True}}

        def record_completed_veteran(self, *_args, **_kwargs):
            raise AssertionError("active career is not a completed result")

    monkeypatch.setattr(main, "campaign_store", FakeStore())
    monkeypatch.setattr(main, "campaign_runner", FakeCampaignRunner())
    monkeypatch.setattr(main, "campaign_service", FakeCampaignService())
    monkeypatch.setattr(
        main,
        "_campaign_runtime_snapshot",
        lambda _account: {
            "current_career": {
                "active": True,
                "trainee_chara_id": 1001,
                "deck_id": 4,
                "parent_id_1": 11,
                "parent_id_2": 12,
                "account": "acct01",
                "campaign_id": "cmp1",
            },
            "runtime": {"api_reachable": True, "logged_in": True},
            "bot_state": {"career_runner": {"running": False}},
        },
    )

    result = main._campaign_advance("cmp1")

    assert calls["start"] == prepared
    assert result["campaign"]["state"] == "RUNNING_CAREER"
    assert result["campaign"]["next_action"] == "monitor_career"


def test_campaign_advance_refreshes_finished_runner_and_resumes_live_career(monkeypatch):
    calls = {}
    prepared = {
        "account": "acct01",
        "campaign_id": "cmp1",
        "trainee_chara_id": 1001,
        "deck_id": 4,
        "legacy_slots": [
            {"trained_chara_id": 11},
            {"trained_chara_id": 12},
        ],
    }
    campaign = {
        "campaign_id": "cmp1",
        "account": "acct01",
        "state": "EVALUATING_RESULT",
        "next_action": "evaluate_result",
        "context": {"prepared_run": prepared},
    }

    class FakeStore:
        def get(self, _campaign_id):
            return dict(campaign)

        def transition(self, campaign_id, state, **kwargs):
            calls["transition"] = (campaign_id, state, kwargs)
            return {**campaign, "state": getattr(state, "value", state), **kwargs}

    class FakeCampaignRunner:
        def reconcile(self, *_args, **_kwargs):
            raise AssertionError("live career must be resumed before result collection")

    class FakeCampaignService:
        def start_career(self, request):
            calls["start"] = request
            return {"success": True, "runner": {"running": True}}

        def reconcile_runtime(self, *_args, **_kwargs):
            raise AssertionError("matching live career must not be treated as mismatch")

    live_career = {
        "active": True,
        "trainee_chara_id": 1001,
        "deck_id": 4,
        "parent_id_1": 11,
        "parent_id_2": 12,
        "account": "acct01",
        "campaign_id": "cmp1",
    }
    initial_snapshot = {
        "current_career": dict(live_career),
        "runtime": {"api_reachable": True, "logged_in": True},
        "bot_state": {"career_runner": {"running": False, "finished": True}},
    }
    refreshed_snapshot = {
        "current_career": dict(live_career),
        "runtime": {"api_reachable": True, "logged_in": True},
        "bot_state": {"career_runner": {"running": False, "finished": True}},
    }
    monkeypatch.setattr(main, "campaign_store", FakeStore())
    monkeypatch.setattr(main, "campaign_runner", FakeCampaignRunner())
    monkeypatch.setattr(main, "campaign_service", FakeCampaignService())
    monkeypatch.setattr(main, "_campaign_runtime_snapshot", lambda _account: initial_snapshot)
    monkeypatch.setattr(main, "_refresh_campaign_runtime_snapshot", lambda _account: refreshed_snapshot)

    result = main._campaign_advance("cmp1")

    assert calls["start"] == prepared
    assert calls["transition"][0:2] == ("cmp1", "RUNNING_CAREER")
    assert result["campaign"]["state"] == "RUNNING_CAREER"
    assert result["campaign"]["next_action"] == "monitor_career"


def test_campaign_advance_collects_result_after_runner_finishes(monkeypatch):
    calls = {}
    campaign = {
        "campaign_id": "cmp1",
        "account": "acct01",
        "state": "RUNNING_CAREER",
        "spec": {},
        "context": {},
    }

    class FakeStore:
        def get(self, campaign_id):
            assert campaign_id == "cmp1"
            return dict(campaign)

        def update_context(self, campaign_id, updates):
            calls["context"] = updates
            return {**campaign, "state": "SELECTING_LINEAGE", "context": updates}

    class FakeCampaignRunner:
        def reconcile(self, campaign_id, *, runtime, bot_state):
            calls["reconcile"] = (campaign_id, runtime, bot_state)
            campaign["state"] = "EVALUATING_RESULT"
            return dict(campaign)

    class FakeCampaignService:
        def start_career(self, _request):
            raise AssertionError("finished runner must not resume a stale cached career")

        def record_completed_veteran(self, campaign_id, candidate, pairings):
            calls["record"] = (campaign_id, candidate, pairings)
            campaign["state"] = "SELECTING_LINEAGE"
            return {
                "campaign": dict(campaign),
                "candidate": {"trained_chara_id": 12},
                "decision": "reject",
            }

    initial_snapshot = {
        "current_career": {
            "active": True,
            "trainee_chara_id": 1001,
            "deck_id": 4,
            "parent_id_1": 11,
            "parent_id_2": 12,
            "account": "acct01",
            "campaign_id": "cmp1",
        },
        "runtime": {"api_reachable": True, "logged_in": True},
        "bot_state": {"career_runner": {"running": False, "finished": True}},
    }
    refreshed_snapshot = {"owned_candidates": [{"trained_chara_id": 12}]}
    monkeypatch.setattr(main, "campaign_store", FakeStore())
    monkeypatch.setattr(main, "campaign_runner", FakeCampaignRunner())
    monkeypatch.setattr(main, "campaign_service", FakeCampaignService())
    monkeypatch.setattr(main, "_campaign_runtime_snapshot", lambda account: initial_snapshot)
    monkeypatch.setattr(main, "_refresh_campaign_runtime_snapshot", lambda account: refreshed_snapshot)
    monkeypatch.setattr(
        main,
        "_campaign_completed_result",
        lambda current, snapshot: (
            {"trained_chara_id": 12, "candidate_id": "veteran-12"},
            [{"trained_chara_id": 11}],
            [10, 11, 12],
        ),
    )

    result = main._campaign_advance("cmp1")

    assert calls["reconcile"] == (
        "cmp1",
        initial_snapshot["runtime"],
        initial_snapshot["bot_state"],
    )
    assert calls["record"] == (
        "cmp1",
        {"trained_chara_id": 12, "candidate_id": "veteran-12"},
        [{"trained_chara_id": 11}],
    )
    assert calls["context"]["baseline_parent_ids"] == [10, 11, 12]
    assert calls["context"]["run_start"] is None
    assert result["campaign"]["state"] == "SELECTING_LINEAGE"


def test_campaign_completed_result_uses_new_matching_trainee_and_lineage_sparks():
    campaign = {
        "campaign_id": "cmp1",
        "account": "acct01",
        "spec": {
            "final_parent": {"trained_chara_id": 11},
        },
        "context": {
            "baseline_parent_ids": [10, 11],
            "prepared_run": {"trainee_chara_id": 1001},
        },
    }
    snapshot = {
        "owned_candidates": [
            {"trained_chara_id": 10, "card_id": 101401},
            {"trained_chara_id": 11, "card_id": 101401, "win_saddle_id_array": []},
            {
                "trained_chara_id": 12,
                "card_id": 100101,
                "rank_score": 3517,
                "create_time": "2026-07-16 11:05:12",
                "win_saddle_id_array": [1],
                "succession_chara_array": [],
            },
            {"trained_chara_id": 13, "card_id": 101801},
        ],
        "display_by_id": {
            12: {
                "instance_id": 12,
                "name": "Special Week",
                "tree": {
                    "self": {
                        "factors": [
                            {"factor_id": 302, "category": "stat", "name": "Power", "stars": 2},
                            {"factor_id": 10010101, "category": "unique", "name": "Shooting Star", "stars": 1},
                            {"factor_id": 2003302, "category": "skill", "name": "Homestretch Haste", "stars": 2},
                            {"factor_id": 3007401, "category": "race", "name": "Japan Cup", "stars": 1},
                        ]
                    },
                    "p1": {"factors": [{"factor_id": 303, "category": "stat", "name": "Power", "stars": 3}]},
                    "p2": {"factors": [{"factor_id": 301, "category": "stat", "name": "Power", "stars": 1}]},
                    "gp1": {"factors": [{"factor_id": 2302, "category": "aptitude", "name": "Long", "stars": 2}]},
                },
            }
        },
    }

    candidate, pairings, parent_ids = main._campaign_completed_result(campaign, snapshot)

    assert candidate["candidate_id"] == "veteran-12"
    assert candidate["trained_chara_id"] == 12
    assert candidate["name"] == "Special Week"
    assert candidate["spark_totals"] == {
        ("blue", "power"): 6,
        ("pink", "long"): 2,
    }
    assert candidate["factor_tree"] == snapshot["display_by_id"][12]["tree"]
    assert pairings == [{
        "trained_chara_id": 11,
        "card_id": 101401,
        "win_saddle_id_array": [],
        "rental": False,
    }]
    assert parent_ids == [10, 11, 12, 13]


def test_campaign_start_applies_result_and_launches_career_runner(monkeypatch):
    calls = {}

    class FakeCareerRunner:
        def start(self, client, preset, initial_result, max_steps, *, burn_clocks, dev_mode):
            calls["runner"] = {
                "client": client,
                "preset": preset,
                "initial_result": initial_result,
                "max_steps": max_steps,
                "burn_clocks": burn_clocks,
                "dev_mode": dev_mode,
            }

        def snapshot(self):
            return {"running": True}

    client = object()
    start_result = {"data": {"chara_info": {"card_id": 100101, "turn": 1, "scenario_id": 2}}}
    monkeypatch.setattr(main, "active_account", {"name": "acct01"})
    monkeypatch.setattr(main, "active_client", client)
    monkeypatch.setattr(
        main,
        "active_dashboard_data",
        {"umas": [{"id": 100101}], "decks": [{"id": 3, "cards": [{"id": value} for value in [1, 2, 3, 4, 5]]}]},
    )
    monkeypatch.setattr(
        main,
        "start_career_from_request",
        lambda _request: {"success": True, "result": start_result},
    )
    def fake_apply_career_result(result):
        calls["applied_result"] = result
        return {"career": {"active": True}}, result["data"]["chara_info"]

    monkeypatch.setattr(main, "apply_career_result", fake_apply_career_result)
    monkeypatch.setattr(
        main,
        "apply_deck_type_counts",
        lambda preset, **kwargs: calls.setdefault("deck_meta", (preset, kwargs)),
    )
    monkeypatch.setattr(main, "_apply_preset_turn_delay", lambda preset: calls.setdefault("delay_preset", preset))
    monkeypatch.setattr(main, "career_runner", FakeCareerRunner())

    result = main._campaign_start_career({
        "account": "acct01",
        "deck_id": 3,
        "trainee_chara_id": 1001,
        "legacy_slots": [{"trained_chara_id": 11}, {"trained_chara_id": 22}],
        "friend_support": {"viewer_id": 33, "support_card_id": 44},
        "preset": {"name": "parent", "scenario_id": 2, "burn_clocks": True},
    })

    assert calls["applied_result"] == start_result
    assert calls["runner"] == {
        "client": client,
        "preset": {"name": "parent", "scenario_id": 2, "burn_clocks": True, "extra_race_list": []},
        "initial_result": start_result,
        "max_steps": 2500,
        "burn_clocks": True,
        "dev_mode": False,
    }
    assert result["success"] is True
    assert result["runner"]["running"] is True
    assert result["account"]["career"] == {
        "active": True,
        "trainee_chara_id": 1001,
        "deck_id": 3,
        "parent_id_1": 11,
        "parent_id_2": 22,
    }


def test_campaign_start_resumes_matching_active_career_without_starting_another(monkeypatch):
    calls = {}

    class FakeClient:
        def load_career(self, *, scenario_id):
            calls["load_scenario"] = scenario_id
            return {"data": {"chara_info": {"card_id": 100101, "turn": 1, "scenario_id": 2}}}

    _stub_campaign_runtime_launch(monkeypatch)
    monkeypatch.setattr(
        main,
        "active_account",
        {
            "name": "acct01",
            "career": {
                "active": True,
                "card_id": "100101",
                "deck_id": 3,
                "parent_id_1": 11,
                "parent_id_2": 22,
            },
        },
    )
    monkeypatch.setattr(main, "active_client", FakeClient())
    monkeypatch.setattr(
        main,
        "active_dashboard_data",
        {"umas": [{"id": 100101}], "decks": [{"id": 3, "cards": [{"id": value} for value in [1, 2, 3, 4, 5]]}]},
    )
    monkeypatch.setattr(
        main,
        "start_career_from_request",
        lambda _request: (_ for _ in ()).throw(AssertionError("must not start another career")),
    )

    result = main._campaign_start_career({
        "account": "acct01",
        "campaign_id": "cmp1",
        "deck_id": 3,
        "trainee_chara_id": 1001,
        "legacy_slots": [{"trained_chara_id": 11}, {"trained_chara_id": 22}],
        "friend_support": {"viewer_id": 33, "support_card_id": 44},
        "preset": {"name": "parent", "scenario_id": 2},
    })

    assert calls["load_scenario"] == 2
    assert result["success"] is True


def test_campaign_start_recovers_redacted_friend_viewer_id_from_runtime_cache(monkeypatch):
    captured = []
    _stub_campaign_runtime_launch(monkeypatch)
    monkeypatch.setattr(main, "active_account", {"name": "acct01"})
    monkeypatch.setattr(main, "active_client", object())
    monkeypatch.setattr(
        main,
        "active_dashboard_data",
        {
            "umas": [{"id": 100101, "name": "Special Week"}],
            "decks": [{"id": 3, "cards": [{"id": value} for value in [1, 2, 3, 4, 5]]}],
            "friends": [
                {
                    "viewer_id": 777,
                    "support_card_id": 44,
                    "support_name": "Super Creek",
                    "limit_break_count": 4,
                    "exp": 100,
                    "favorite_flag": 1,
                    "friend_state": 2,
                }
            ],
        },
    )
    monkeypatch.setattr(
        main,
        "start_career_from_request",
        lambda request: captured.append(request) or {"success": True, "result": {"started": True}},
    )

    result = main._campaign_start_career({
        "account": "acct01",
        "deck_id": 3,
        "trainee_chara_id": 1001,
        "legacy_slots": [{"trained_chara_id": 11}, {"trained_chara_id": 22}],
        "friend_support": {
            "viewer_id": "<redacted>",
            "support_card_id": 44,
            "support_name": "Super Creek",
        },
        "preset": {"name": "parent"},
    })

    assert result["success"] is True
    assert captured[0].friend_viewer_id == 777
    assert captured[0].friend_card_id == 44


def test_campaign_start_reports_unavailable_redacted_friend_support(monkeypatch):
    monkeypatch.setattr(main, "active_account", {"name": "acct01"})
    monkeypatch.setattr(main, "active_client", object())
    monkeypatch.setattr(
        main,
        "active_dashboard_data",
        {
            "umas": [{"id": 100101, "name": "Special Week"}],
            "decks": [{"id": 3, "cards": [{"id": value} for value in [1, 2, 3, 4, 5]]}],
            "friends": [],
        },
    )

    with pytest.raises(ValueError, match="Friend support 44 is no longer available"):
        main._campaign_start_career({
            "account": "acct01",
            "deck_id": 3,
            "trainee_chara_id": 1001,
            "legacy_slots": [{"trained_chara_id": 11}, {"trained_chara_id": 22}],
            "friend_support": {
                "viewer_id": "<redacted>",
                "support_card_id": 44,
                "support_name": "Super Creek",
            },
            "preset": {"name": "parent"},
        })

def test_campaign_planner_includes_rentals_without_duplicate_trained_ids(monkeypatch):
    monkeypatch.setattr(
        main,
        "_campaign_runtime_snapshot",
        lambda _account: {
            "owned_chara_ids": {1001},
            "owned_candidates": [{"trained_chara_id": 1, "card_id": 100101}],
            "rental_candidates": [
                {"trained_chara_id": 1, "card_id": 100199},
                {"trained_chara_id": 2, "card_id": 100201},
            ],
            "display_by_id": {},
        },
    )
    monkeypatch.setattr(main, "_campaign_master_mdb_path", lambda: "/tmp/master.mdb")
    monkeypatch.setattr(main, "_campaign_race_rows", lambda: [])
    monkeypatch.setattr(main.affinity_calc, "_load_g1_saddles", lambda _path: set())

    planner = main._campaign_planner_factory({"final_uma_card_id": 100101})

    assert [row["trained_chara_id"] for row in planner.veteran_records] == [1, 2]
    assert planner.veteran_records[0]["card_id"] == 100101


@pytest.mark.parametrize(
    ("route", "filename", "content_type"),
    [
        ("/campaigns", "campaigns.html", "text/html"),
        ("/campaigns.js", "campaigns.js", "application/javascript"),
        ("/campaigns.css", "campaigns.css", "text/css"),
    ],
)
def test_campaign_page_and_assets_resolve(client, monkeypatch, tmp_path, route, filename, content_type):
    public = tmp_path / "public"
    public.mkdir()
    (public / filename).write_text("test", encoding="utf-8")
    monkeypatch.setattr(main, "base_dir", Path(tmp_path))

    response = client.get(route)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["content-type"].startswith(content_type)
