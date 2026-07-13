from career_bot.campaigns.models import CampaignState, ParentCampaignSpec
from career_bot.campaigns.runner import CampaignRunner
from career_bot.campaigns.store import CampaignStore
from sweepy_jobs import SweepyJobStore

import sweepy_mcp


class FakeGateway:
    def __init__(self):
        self.calls = []
        self.responses = {
            ("GET", "/api/session"): {"success": True, "account": {}},
            ("GET", "/api/career/runner"): {
                "success": True,
                "runner": {"running": False, "finished": False},
            },
            ("GET", "/api/dailies/status"): {
                "success": True,
                "status": {"running": False, "finished": False},
            },
            ("GET", "/api/settings/turn-delay"): {"min": 0.2, "max": 0.5},
        }

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if method == "POST" and path == "/api/selection" and isinstance(payload, dict):
            session = self.responses.setdefault(("GET", "/api/session"), {"success": True})
            session["selection"] = payload.get("selection")
        return self.responses.get((method, path), {"success": True})


class FakeRegistry:
    def __init__(self, gateway):
        self.gateway = gateway

    def list_accounts(self):
        return [{"name": "alpha", "port": 1617, "enabled": True}]

    def resolve(self, account=""):
        if account not in {"", "alpha"}:
            raise ValueError(f"Unknown Sweepy account: {account}")
        return "alpha", self.gateway


class FakeSupervisor:
    def __init__(self, *, api_reachable=False, logged_in=False):
        self.api_reachable = api_reachable
        self.logged_in = logged_in

    def status(self, account):
        return {
            "account": account,
            "api_reachable": self.api_reachable,
            "logged_in": self.logged_in,
        }


def campaign_spec():
    return ParentCampaignSpec(
        account="alpha",
        goal={
            "surface_targets": ["turf"],
            "distance_targets": ["medium"],
            "minimum_rank": "S",
        },
        strategy={
            "preset_name": "MANT Parent",
            "maximum_runs": 20,
            "maximum_runtime_hours": 24,
        },
    )


def configure(monkeypatch, tmp_path, *, api_reachable=False, logged_in=False):
    gateway = FakeGateway()
    campaign_store = CampaignStore(tmp_path / "campaigns.sqlite3")
    job_store = SweepyJobStore(tmp_path / "control-plane.sqlite3")
    monkeypatch.setattr(sweepy_mcp, "account_registry", FakeRegistry(gateway))
    monkeypatch.setattr(
        sweepy_mcp,
        "supervisor",
        FakeSupervisor(api_reachable=api_reachable, logged_in=logged_in),
    )
    monkeypatch.setattr(sweepy_mcp, "campaign_store", campaign_store)
    monkeypatch.setattr(sweepy_mcp, "campaign_runner", CampaignRunner(campaign_store))
    monkeypatch.setattr(sweepy_mcp, "job_store", job_store)
    return gateway, campaign_store, job_store


def test_preview_parent_campaign_returns_normalized_goal_and_budget(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path)

    result = sweepy_mcp.preview_parent_campaign(spec=campaign_spec())

    assert result["success"] is True
    assert result["account"] == "alpha"
    assert result["spec"]["goal"]["surface_targets"] == ["turf"]
    assert result["spec"]["goal"]["target_factors"] == [
        {"name": "turf", "minimum_stars": 2, "scope": "lineage", "required": True},
        {"name": "medium", "minimum_stars": 2, "scope": "lineage", "required": True},
    ]
    assert result["budget"]["maximum_runs"] == 20


def test_create_campaign_is_idempotent(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path)

    first = sweepy_mcp.create_parent_campaign(
        spec=campaign_spec(),
        confirm=True,
        operation_id="discord-campaign-create",
    )
    replay = sweepy_mcp.create_parent_campaign(
        spec=campaign_spec(),
        confirm=True,
        operation_id="discord-campaign-create",
    )

    assert first["success"] is True
    assert first["campaign"]["state"] == CampaignState.DRAFT.value
    assert replay["replayed"] is True
    assert replay["campaign"]["campaign_id"] == first["campaign"]["campaign_id"]


def test_start_campaign_acquires_campaign_lease_and_requests_bot_launch(monkeypatch, tmp_path):
    _, campaign_store, job_store = configure(monkeypatch, tmp_path, api_reachable=False)
    campaign = campaign_store.create(campaign_spec(), campaign_id="campaign-1")

    result = sweepy_mcp.start_parent_campaign(
        campaign_id=campaign["campaign_id"],
        confirm=True,
        operation_id="discord-campaign-start",
    )

    assert result["success"] is True
    assert result["campaign"]["state"] == CampaignState.STARTING_BOT.value
    assert result["campaign"]["next_action"] == "launch_bot"
    lease = job_store.get_workflow_lease("alpha")
    assert lease["workflow_type"] == "campaign"
    assert lease["owner"] == "operation:discord-campaign-start"


def test_advance_campaign_moves_to_lineage_selection_after_login(monkeypatch, tmp_path):
    _, campaign_store, _ = configure(monkeypatch, tmp_path, api_reachable=False)
    campaign_store.create(campaign_spec(), campaign_id="campaign-1")
    sweepy_mcp.start_parent_campaign(
        campaign_id="campaign-1",
        confirm=True,
        operation_id="start-1",
    )
    monkeypatch.setattr(
        sweepy_mcp,
        "supervisor",
        FakeSupervisor(api_reachable=True, logged_in=True),
    )

    result = sweepy_mcp.advance_parent_campaign(
        campaign_id="campaign-1",
        operation_id="advance-1",
    )

    assert result["success"] is True
    assert result["campaign"]["state"] == CampaignState.SELECTING_LINEAGE.value
    assert result["campaign"]["next_action"] == "select_lineage"


def test_pause_releases_lease_and_resume_reacquires_it(monkeypatch, tmp_path):
    _, campaign_store, job_store = configure(monkeypatch, tmp_path, api_reachable=False)
    campaign_store.create(campaign_spec(), campaign_id="campaign-1")
    sweepy_mcp.start_parent_campaign(
        campaign_id="campaign-1",
        confirm=True,
        operation_id="start-1",
    )

    paused = sweepy_mcp.pause_parent_campaign(
        campaign_id="campaign-1",
        confirm=True,
        operation_id="pause-1",
    )
    assert paused["campaign"]["state"] == CampaignState.PAUSED.value
    assert job_store.get_workflow_lease("alpha") is None

    resumed = sweepy_mcp.resume_parent_campaign(
        campaign_id="campaign-1",
        confirm=True,
        operation_id="resume-1",
    )
    assert resumed["campaign"]["state"] == CampaignState.STARTING_BOT.value
    assert job_store.get_workflow_lease("alpha")["workflow_type"] == "campaign"


def test_get_campaign_includes_events_and_candidates(monkeypatch, tmp_path):
    _, campaign_store, _ = configure(monkeypatch, tmp_path)
    campaign_store.create(campaign_spec(), campaign_id="campaign-1")
    campaign_store.add_candidate(
        "campaign-1",
        trained_chara_id=1001,
        name="Candidate",
        score=88.5,
        evaluation={"accepted": True, "decision": "accept"},
        candidate_id="candidate-1",
    )

    result = sweepy_mcp.get_parent_campaign(campaign_id="campaign-1")

    assert result["success"] is True
    assert result["campaign"]["campaign_id"] == "campaign-1"
    assert result["events"][0]["event_type"] == "campaign_created"
    assert result["candidates"][0]["candidate_id"] == "candidate-1"


def full_campaign_session():
    return {
        "success": True,
        "account": {"tp": {"current": 100, "max": 100}, "career": None},
        "selection": {
            "trainee": {"id": 100101, "name": "Test Uma"},
            "deck": {
                "id": 3,
                "name": "Parent Deck",
                "cards": [
                    {"id": 301},
                    {"id": 302},
                    {"id": 303},
                    {"id": 304},
                    {"id": 305},
                ],
            },
            "friend": {
                "viewer_id": 90001,
                "support_card_id": 401,
                "support_name": "Friend Support",
            },
            "veterans": [],
        },
        "parents": [
            {"instance_id": 7001, "name": "Owned A", "card_id": 1101},
            {"instance_id": 7002, "name": "Owned B", "card_id": 1102},
        ],
        "friendVeterans": [
            {
                "instance_id": 8001,
                "trained_chara_id": 8001,
                "viewer_id": 99001,
                "name": "Rental A",
                "card_id": 1201,
            }
        ],
    }


def prepare_running_campaign(monkeypatch, tmp_path):
    gateway, store, jobs = configure(
        monkeypatch,
        tmp_path,
        api_reachable=True,
        logged_in=True,
    )
    gateway.responses[("GET", "/api/session")] = full_campaign_session()
    gateway.responses[("GET", "/api/presets")] = {
        "success": True,
        "presets": [
            {
                "name": "MANT Parent",
                "scenario_id": 4,
                "tp_mode": "wait",
                "run_delay_min_min": 0,
                "run_delay_max_min": 0,
            }
        ],
    }
    gateway.responses[("POST", "/api/inheritance/recommend")] = {
        "success": True,
        "results": [
            {
                "rank": 1,
                "score": 999,
                "parent1": {"id": 8001, "source": "veteran", "name": "Rental A"},
                "parent2": {"id": 8002, "source": "veteran", "name": "Rental B"},
            },
            {
                "rank": 2,
                "score": 180,
                "parent1": {"id": 7001, "source": "owned", "name": "Owned A"},
                "parent2": {"id": 8001, "source": "veteran", "name": "Rental A"},
                "compat_total": 155,
                "compat_tier": "◎",
                "race_score": 20,
                "spark_hits": [
                    {"name": "Turf", "stars": 2},
                    {"name": "Medium", "stars": 2},
                ],
            },
        ],
    }
    store.create(campaign_spec(), campaign_id="campaign-1")
    sweepy_mcp.start_parent_campaign(
        campaign_id="campaign-1",
        confirm=True,
        operation_id="start-campaign",
    )
    return gateway, store, jobs


def test_prepare_campaign_run_selects_supported_lineage_and_persists_context(
    monkeypatch, tmp_path
):
    gateway, store, _ = prepare_running_campaign(monkeypatch, tmp_path)

    result = sweepy_mcp.prepare_parent_campaign_run(
        campaign_id="campaign-1",
        pool="both",
        confirm=True,
        operation_id="prepare-run-1",
    )

    assert result["success"] is True
    assert result["campaign"]["state"] == CampaignState.SELECTING_LINEAGE.value
    assert result["campaign"]["next_action"] == "start_career"
    assert result["lineage"]["rank"] == 2
    assert result["lineage"]["parents"][0]["trained_chara_id"] == 7001
    assert result["lineage"]["parents"][1]["trained_chara_id"] == 8001
    selection_calls = [
        call for call in gateway.calls if call[:2] == ("POST", "/api/selection")
    ]
    assert len(selection_calls) == 1
    assert selection_calls[0][2]["selection"]["veterans"][1]["viewer_id"] == 99001
    reopened = store.get("campaign-1")
    assert reopened["context"]["lineage"]["summary"]["compat_total"] == 155
    assert reopened["context"]["baseline_parent_ids"] == [7001, 7002]


def test_run_campaign_career_starts_once_and_consumes_one_run(monkeypatch, tmp_path):
    gateway, store, _ = prepare_running_campaign(monkeypatch, tmp_path)
    sweepy_mcp.prepare_parent_campaign_run(
        campaign_id="campaign-1",
        confirm=True,
        operation_id="prepare-run-1",
    )
    gateway.responses[("POST", "/api/career/run")] = {
        "success": True,
        "runner": {"running": True, "preset_name": "MANT Parent"},
    }

    first = sweepy_mcp.run_parent_campaign_career(
        campaign_id="campaign-1",
        confirm=True,
        operation_id="career-run-1",
    )
    replay = sweepy_mcp.run_parent_campaign_career(
        campaign_id="campaign-1",
        confirm=True,
        operation_id="career-run-1",
    )

    assert first["success"] is True
    assert first["campaign"]["state"] == CampaignState.RUNNING_CAREER.value
    assert first["campaign"]["usage"]["runs"] == 1
    assert replay["replayed"] is True
    career_calls = [
        call for call in gateway.calls if call[:2] == ("POST", "/api/career/run")
    ]
    assert len(career_calls) == 1
    payload = career_calls[0][2]
    assert payload["parent_id_1"] == 7001
    assert payload["rental_viewer_id"] == 99001
    assert payload["rental_trained_chara_id"] == 8001
    assert payload["preset_name"] == "MANT Parent"
    assert payload["tp_mode"] == "wait"
    assert store.get("campaign-1")["context"]["active_run"]["operation_id"] == "career-run-1"


def test_collect_campaign_result_evaluates_new_veteran_and_completes(
    monkeypatch, tmp_path
):
    gateway, store, jobs = prepare_running_campaign(monkeypatch, tmp_path)
    sweepy_mcp.prepare_parent_campaign_run(
        campaign_id="campaign-1",
        confirm=True,
        operation_id="prepare-run-1",
    )
    gateway.responses[("POST", "/api/career/run")] = {
        "success": True,
        "runner": {"running": True},
    }
    sweepy_mcp.run_parent_campaign_career(
        campaign_id="campaign-1",
        confirm=True,
        operation_id="career-run-1",
    )
    gateway.responses[("GET", "/api/career/runner")] = {
        "success": True,
        "runner": {"running": False, "finished": True},
    }
    gateway.responses[("POST", "/api/account/refresh")] = {
        "success": True,
        "parents": [
            {"instance_id": 7001, "name": "Owned A"},
            {"instance_id": 7002, "name": "Owned B"},
            {
                "instance_id": 9001,
                "trained_chara_id": 9001,
                "name": "New Medium Turf Parent",
                "rank": 15,
                "rank_score": 15000,
                "stats": {
                    "speed": 1200,
                    "stamina": 1100,
                    "power": 900,
                    "guts": 700,
                    "wisdom": 900,
                },
                "wins": 15,
                "tree": {
                    "self": {
                        "factors": [
                            {"name": "Turf", "stars": 2},
                            {"name": "Medium", "stars": 2},
                        ]
                    },
                    "p1": {"factors": []},
                    "p2": {"factors": []},
                },
            },
        ],
    }

    result = sweepy_mcp.collect_parent_campaign_result(
        campaign_id="campaign-1",
        operation_id="collect-result-1",
    )

    assert result["success"] is True
    assert result["evaluation"]["accepted"] is True
    assert result["campaign"]["state"] == CampaignState.COMPLETED.value
    assert result["candidate"]["trained_chara_id"] == 9001
    assert jobs.get_workflow_lease("alpha") is None
    assert store.get("campaign-1")["selected_candidate_id"]


def test_campaign_summary_is_compact_and_discord_friendly(monkeypatch, tmp_path):
    _, campaign_store, _ = configure(monkeypatch, tmp_path)
    campaign_store.create(campaign_spec(), campaign_id="campaign-1")
    campaign_store.transition("campaign-1", CampaignState.READY)
    campaign_store.add_usage("campaign-1", runs=2)
    campaign_store.add_candidate(
        "campaign-1",
        trained_chara_id=1001,
        name="Best Candidate",
        score=88.5,
        evaluation={
            "accepted": True,
            "decision": "ambiguous",
            "matched_targets": ["turf:lineage", "medium:lineage"],
            "missing_targets": [],
        },
        candidate_id="candidate-1",
    )

    result = sweepy_mcp.get_parent_campaign_summary(campaign_id="campaign-1")

    assert result == {
        "success": True,
        "account": "alpha",
        "campaign_id": "campaign-1",
        "state": CampaignState.READY.value,
        "next_action": "",
        "needs_user_input": False,
        "usage": {"runs": 2, "carats": 0, "clocks": 0},
        "budget": {
            "maximum_runs": 20,
            "maximum_carats": 0,
            "maximum_clocks": 0,
            "maximum_runtime_hours": 24.0,
        },
        "best_candidate": {
            "candidate_id": "candidate-1",
            "trained_chara_id": 1001,
            "name": "Best Candidate",
            "score": 88.5,
            "accepted": True,
            "selected": False,
            "decision": "ambiguous",
            "matched_targets": ["turf:lineage", "medium:lineage"],
            "missing_targets": [],
        },
        "error": "",
    }


def test_cancel_campaign_releases_lease(monkeypatch, tmp_path):
    _, campaign_store, job_store = configure(monkeypatch, tmp_path, api_reachable=False)
    campaign_store.create(campaign_spec(), campaign_id="campaign-1")
    sweepy_mcp.start_parent_campaign(
        campaign_id="campaign-1",
        confirm=True,
        operation_id="start-1",
    )

    result = sweepy_mcp.cancel_parent_campaign(
        campaign_id="campaign-1",
        reason="user requested",
        confirm=True,
        operation_id="cancel-1",
    )

    assert result["campaign"]["state"] == CampaignState.CANCELLED.value
    assert job_store.get_workflow_lease("alpha") is None
