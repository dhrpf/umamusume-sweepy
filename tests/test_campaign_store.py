import pytest

from career_bot.campaigns.models import CampaignState, ParentCampaignSpec
from career_bot.campaigns.store import BudgetExceeded, CampaignStore, InvalidTransition


class FakeClock:
    def __init__(self, value=1000.0):
        self.value = float(value)

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += float(seconds)


def sample_spec(account="alpha"):
    return ParentCampaignSpec(
        account=account,
        goal={
            "surface_targets": ["turf"],
            "distance_targets": ["medium"],
        },
        strategy={
            "preset_name": "MANT Parent",
            "maximum_runs": 3,
            "maximum_carats": 0,
            "maximum_clocks": 1,
            "maximum_runtime_hours": 12,
        },
    )


def test_campaign_create_and_reopen_are_durable(tmp_path):
    database = tmp_path / "campaigns.sqlite3"
    store = CampaignStore(database)

    created = store.create(sample_spec(), campaign_id="campaign-1")
    reopened = CampaignStore(database).get("campaign-1")

    assert created["state"] == CampaignState.DRAFT.value
    assert reopened["account"] == "alpha"
    assert reopened["spec"]["goal"]["distance_targets"] == ["medium"]
    assert reopened["usage"] == {"runs": 0, "carats": 0, "clocks": 0}


def test_valid_transitions_are_recorded_and_invalid_transition_is_rejected(tmp_path):
    store = CampaignStore(tmp_path / "campaigns.sqlite3")
    store.create(sample_spec(), campaign_id="campaign-1")

    ready = store.transition(
        "campaign-1",
        CampaignState.READY,
        next_action="inspect_runtime",
    )
    starting = store.transition("campaign-1", CampaignState.STARTING_BOT)

    assert ready["next_action"] == "inspect_runtime"
    assert starting["state"] == CampaignState.STARTING_BOT.value
    assert [row["event_type"] for row in store.recent_events("campaign-1", limit=10)][:3] == [
        "state_changed",
        "state_changed",
        "campaign_created",
    ]

    with pytest.raises(InvalidTransition):
        store.transition("campaign-1", CampaignState.COMPLETED)


def test_pause_and_resume_return_to_previous_state(tmp_path):
    store = CampaignStore(tmp_path / "campaigns.sqlite3")
    store.create(sample_spec(), campaign_id="campaign-1")
    store.transition("campaign-1", CampaignState.READY)
    store.transition("campaign-1", CampaignState.STARTING_BOT)
    store.transition("campaign-1", CampaignState.WAITING_FOR_LOGIN)

    paused = store.pause("campaign-1")
    resumed = store.resume("campaign-1")

    assert paused["state"] == CampaignState.PAUSED.value
    assert paused["paused_from_state"] == CampaignState.WAITING_FOR_LOGIN.value
    assert resumed["state"] == CampaignState.WAITING_FOR_LOGIN.value
    assert resumed["paused_from_state"] == ""


def test_usage_enforces_run_carrot_clock_and_runtime_budgets(tmp_path):
    clock = FakeClock()
    store = CampaignStore(tmp_path / "campaigns.sqlite3", clock=clock)
    store.create(sample_spec(), campaign_id="campaign-1")

    updated = store.add_usage("campaign-1", runs=2, clocks=1)
    assert updated["usage"] == {"runs": 2, "carats": 0, "clocks": 1}

    with pytest.raises(BudgetExceeded, match="maximum_runs"):
        store.add_usage("campaign-1", runs=2)
    with pytest.raises(BudgetExceeded, match="maximum_clocks"):
        store.add_usage("campaign-1", clocks=1)
    with pytest.raises(BudgetExceeded, match="maximum_carats"):
        store.add_usage("campaign-1", carats=1)

    clock.advance(12 * 60 * 60 + 1)
    with pytest.raises(BudgetExceeded, match="maximum_runtime_hours"):
        store.assert_within_budget("campaign-1")


def test_candidates_are_ranked_and_selected_durably(tmp_path):
    store = CampaignStore(tmp_path / "campaigns.sqlite3")
    store.create(sample_spec(), campaign_id="campaign-1")

    low = store.add_candidate(
        "campaign-1",
        trained_chara_id=1001,
        name="Candidate Low",
        score=65.5,
        evaluation={"accepted": False, "reasons": ["medium matched"]},
        candidate_id="candidate-low",
    )
    high = store.add_candidate(
        "campaign-1",
        trained_chara_id=1002,
        name="Candidate High",
        score=91.0,
        evaluation={"accepted": True, "reasons": ["all targets matched"]},
        candidate_id="candidate-high",
    )

    rows = store.list_candidates("campaign-1")
    selected = store.select_candidate("campaign-1", "candidate-high")

    assert [row["candidate_id"] for row in rows] == ["candidate-high", "candidate-low"]
    assert high["accepted"] is True
    assert low["accepted"] is False
    assert selected["selected"] is True
    assert store.get("campaign-1")["selected_candidate_id"] == "candidate-high"


def test_campaign_context_is_merged_and_survives_reopen(tmp_path):
    database = tmp_path / "campaigns.sqlite3"
    store = CampaignStore(database)
    store.create(sample_spec(), campaign_id="campaign-1")

    first = store.update_context(
        "campaign-1",
        {
            "lineage": {"score": 150, "parents": [7001, 8001]},
            "generation": 1,
        },
    )
    second = store.update_context(
        "campaign-1",
        {"lineage": {"compat_total": 155}},
    )
    reopened = CampaignStore(database).get("campaign-1")

    assert first["context"]["generation"] == 1
    assert second["context"] == {
        "generation": 1,
        "lineage": {
            "score": 150,
            "parents": [7001, 8001],
            "compat_total": 155,
        },
    }
    assert reopened["context"] == second["context"]


def test_campaign_listing_is_account_scoped(tmp_path):
    store = CampaignStore(tmp_path / "campaigns.sqlite3")
    store.create(sample_spec("alpha"), campaign_id="alpha-1")
    store.create(sample_spec("beta"), campaign_id="beta-1")

    rows = store.list(account="alpha")

    assert [row["campaign_id"] for row in rows] == ["alpha-1"]
