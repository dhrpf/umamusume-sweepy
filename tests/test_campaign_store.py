from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from career_bot.campaigns.models import CampaignState, ParentCampaignSpec
from career_bot.campaigns.store import (
    BudgetExceeded,
    CampaignError,
    CampaignStore,
    InvalidTransition,
)


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


def test_only_one_campaign_per_account_can_enter_active_execution(tmp_path):
    store = CampaignStore(tmp_path / "campaigns.sqlite3")
    store.create(sample_spec("alpha"), campaign_id="alpha-1")
    store.create(sample_spec("alpha"), campaign_id="alpha-2")
    store.create(sample_spec("beta"), campaign_id="beta-1")
    for campaign_id in ("alpha-1", "alpha-2", "beta-1"):
        store.transition(campaign_id, CampaignState.READY)

    store.transition("alpha-1", CampaignState.STARTING_BOT)

    with pytest.raises(CampaignError, match="active campaign"):
        store.transition("alpha-2", CampaignState.STARTING_BOT)

    beta = store.transition("beta-1", CampaignState.STARTING_BOT)
    assert beta["state"] == CampaignState.STARTING_BOT.value
    assert store.get("alpha-2")["state"] == CampaignState.READY.value

    store.pause("alpha-1")
    store.transition("alpha-2", CampaignState.STARTING_BOT)
    with pytest.raises(CampaignError, match="active campaign"):
        store.resume("alpha-1")


def test_reopen_completed_is_explicit_and_preserves_terminal_transition_rules(tmp_path):
    store = CampaignStore(tmp_path / "campaigns.sqlite3")
    store.create(sample_spec(), campaign_id="campaign-1")
    store.transition("campaign-1", CampaignState.READY)
    store.transition("campaign-1", CampaignState.STARTING_BOT)
    store.transition("campaign-1", CampaignState.SELECTING_LINEAGE)
    store.transition("campaign-1", CampaignState.RUNNING_CAREER)
    store.transition("campaign-1", CampaignState.EVALUATING_RESULT)
    completed = store.transition("campaign-1", CampaignState.COMPLETED)

    with pytest.raises(InvalidTransition):
        store.transition("campaign-1", CampaignState.SELECTING_LINEAGE)

    reopened = store.reopen_completed(
        "campaign-1",
        next_action="prepare_next_run",
    )

    assert completed["ended_at"] is not None
    assert reopened["state"] == CampaignState.SELECTING_LINEAGE.value
    assert reopened["next_action"] == "prepare_next_run"
    assert reopened["ended_at"] is None
    assert reopened["error"] == ""
    assert store.recent_events("campaign-1")[0]["event_type"] == "campaign_reopened"


def test_transition_context_rolls_back_when_transition_is_invalid(tmp_path):
    store = CampaignStore(tmp_path / "campaigns.sqlite3")
    store.create(sample_spec(), campaign_id="campaign-1")
    store.update_context("campaign-1", {"pending_review": {"kind": "original"}})

    with pytest.raises(InvalidTransition):
        store.transition(
            "campaign-1",
            CampaignState.COMPLETED,
            context_updates={"pending_review": {"kind": "replacement"}},
        )

    campaign = store.get("campaign-1")
    assert campaign["state"] == CampaignState.DRAFT.value
    assert campaign["context"]["pending_review"] == {"kind": "original"}


def test_two_store_instances_cannot_activate_same_account_concurrently(tmp_path):
    database = tmp_path / "campaigns.sqlite3"
    first = CampaignStore(database)
    second = CampaignStore(database)
    first.create(sample_spec(), campaign_id="campaign-1")
    first.create(sample_spec(), campaign_id="campaign-2")
    first.transition("campaign-1", CampaignState.READY)
    first.transition("campaign-2", CampaignState.READY)
    barrier = Barrier(2)

    def activate(store, campaign_id):
        barrier.wait()
        try:
            store.transition(campaign_id, CampaignState.STARTING_BOT)
            return "activated"
        except CampaignError:
            return "blocked"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda args: activate(*args),
                ((first, "campaign-1"), (second, "campaign-2")),
            )
        )

    assert sorted(results) == ["activated", "blocked"]

def _evaluating_campaign(store, campaign_id="campaign-1"):
    store.create(sample_spec(), campaign_id=campaign_id)
    for state in (
        CampaignState.READY,
        CampaignState.STARTING_BOT,
        CampaignState.SELECTING_LINEAGE,
        CampaignState.RUNNING_CAREER,
        CampaignState.EVALUATING_RESULT,
    ):
        store.transition(campaign_id, state)
    return store.get(campaign_id)


def test_public_append_event_is_append_only(tmp_path):
    store = CampaignStore(tmp_path / "campaigns.sqlite3")
    store.create(sample_spec(), campaign_id="campaign-1")
    store.append_event("campaign-1", "automatic_legacy_replacement", {"role": "parent1"})
    store.append_event("campaign-1", "automatic_legacy_replacement", {"role": "parent2"})
    events = [row for row in store.recent_events("campaign-1") if row["event_type"] == "automatic_legacy_replacement"]
    assert [row["data"]["role"] for row in events] == ["parent2", "parent1"]


def test_prepared_run_reservation_is_atomic_and_failed_start_can_retry(tmp_path):
    store = CampaignStore(tmp_path / "campaigns.sqlite3")
    store.create(sample_spec(), campaign_id="campaign-1")
    barrier = Barrier(2)

    def reserve():
        barrier.wait()
        return store.reserve_prepared_run_start(
            "campaign-1", "operation-1", prepared_run={"campaign_id": "campaign-1"}
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _value: reserve(), range(2)))

    assert sorted(row["acquired"] for row in results) == [False, True]
    store.finish_prepared_run_start(
        "campaign-1", "operation-1", status="FAILED", error="gateway failed"
    )
    retry = store.reserve_prepared_run_start("campaign-1", "operation-1")
    assert retry["acquired"] is True
    started = store.finish_prepared_run_start(
        "campaign-1", "operation-1", status="STARTED", result={"job_id": "job-1"}
    )
    replay = store.reserve_prepared_run_start("campaign-1", "operation-1")
    assert started["result"] == {"job_id": "job-1"}
    assert replay == {"acquired": False, "run_start": started}


def test_candidate_result_transaction_replays_without_duplicate_and_selects_completion(tmp_path):
    store = CampaignStore(tmp_path / "campaigns.sqlite3")
    campaign = _evaluating_campaign(store)
    kwargs = {
        "candidate_id": "result-1",
        "trained_chara_id": 501,
        "name": "Veteran",
        "score": 1150,
        "evaluation": {"accepted": True, "final_setup": {"status": "READY"}},
        "select": True,
        "state": CampaignState.COMPLETED,
        "next_action": "",
        "context_updates": {"pending_review": None, "review_required": False},
        "expected_version": campaign["version"],
    }
    first = store.persist_candidate_result("campaign-1", **kwargs)
    second = store.persist_candidate_result("campaign-1", **kwargs)
    assert first["replayed"] is False
    assert second["replayed"] is True
    assert len(store.list_candidates("campaign-1")) == 1
    assert store.get("campaign-1")["selected_candidate_id"] == "result-1"
    assert first["candidate"]["selected"] is True


def test_candidate_selection_transaction_uses_requested_outcome(tmp_path):
    store = CampaignStore(tmp_path / "campaigns.sqlite3")
    campaign = _evaluating_campaign(store)
    stored = store.persist_candidate_result(
        "campaign-1",
        candidate_id="tradeoff-1",
        trained_chara_id=501,
        name="Tradeoff",
        score=900,
        evaluation={"accepted": False, "final_setup": {"status": "IN_PROGRESS"}},
        select=False,
        state=CampaignState.NEEDS_USER_INPUT,
        next_action="select_candidate",
        context_updates={"pending_review": {"kind": "candidate_tradeoff"}},
        expected_version=campaign["version"],
    )
    result = store.apply_candidate_selection(
        "campaign-1",
        stored["candidate"]["candidate_id"],
        state=CampaignState.SELECTING_LINEAGE,
        next_action="prepare_next_run",
        context_updates={"pending_review": None, "review_required": False},
    )
    assert result["candidate"]["selected"] is True
    assert result["campaign"]["state"] == CampaignState.SELECTING_LINEAGE.value
    assert result["campaign"]["context"]["pending_review"] is None
