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
        ("post", "/api/campaigns/recommend-loop", {"final_uma_card_id": 100101, "limit": 3, "pinned_chara_ids": [1, 2]}, ("recommend_loops", ({"account": None, "final_uma_card_id": 100101, "spark_targets": [], "limit": 3, "pinned_chara_ids": [1, 2]},), {})),
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
def test_campaign_routes_delegate(client, fake_campaign_service, method, path, json_body, expected):
    response = client.request(method, path, json=json_body)

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert fake_campaign_service.calls[-1] == expected

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
    monkeypatch.setattr(main, "active_account", {"name": "acct01", "career": {"active": True}})
    monkeypatch.setattr(main, "active_dashboard_data", {"umas": []})
    monkeypatch.setattr(main, "active_client", object())
    monkeypatch.setattr(main.career_runner, "snapshot", lambda: {"running": True})
    monkeypatch.setattr(main.dailies_runner, "running", True)

    snapshot = main._campaign_runtime_snapshot("acct01")

    assert snapshot["runtime"] == {"api_reachable": True, "logged_in": True}
    assert snapshot["bot_state"] == {
        "session": {"logged_in": True},
        "career_runner": {"running": True},
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

def test_campaign_start_propagates_friend_and_races(monkeypatch):
    captured = []
    monkeypatch.setattr(main, "active_account", {"name": "acct01"})
    monkeypatch.setattr(main, "active_client", object())
    monkeypatch.setattr(main, "active_dashboard_data", {"umas": [{"id": 100101}]})
    monkeypatch.setattr(
        main,
        "start_career_from_request",
        lambda request: captured.append(request) or {"success": True, "result": {"started": True}},
    )

    result = main._campaign_start_career({
        "account": "acct01",
        "trainee_chara_id": 1001,
        "legacy_slots": [{"trained_chara_id": 11}, {"trained_chara_id": 22}],
        "friend_support": {"viewer_id": 33, "support_card_id": 44},
        "race_overrides": {"mandatory_race_list": [7], "extra_race_list": [8]},
        "preset": {
            "name": "parent",
            "support_card_ids": [1, 2, 3, 4, 5],
            "friend_viewer_id": 99,
            "friend_card_id": 100,
            "parent_run": True,
        },
    })

    request = captured[0]
    assert result["success"] is True
    assert request.friend_viewer_id == 33
    assert request.friend_card_id == 44
    assert request.preset_overrides["mandatory_race_list"] == [7]
    assert request.preset_overrides["extra_race_list"] == [8]
    assert request.preset_overrides["parent_run"] is True

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
