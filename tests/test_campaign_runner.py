import pytest

from career_bot.campaigns.models import CampaignState, ParentCampaignSpec
from career_bot.campaigns.runner import CampaignRunner
from career_bot.campaigns.store import CampaignError, CampaignStore, InvalidTransition


def sample_spec(approval_mode="ambiguity_only", maximum_runs=3, account="alpha"):
    return ParentCampaignSpec(
        account=account,
        goal={
            "surface_targets": ["turf"],
            "distance_targets": ["medium"],
            "minimum_rank": "S",
        },
        strategy={
            "preset_name": "MANT Parent",
            "maximum_runs": maximum_runs,
            "maximum_runtime_hours": 24,
            "approval_mode": approval_mode,
        },
    )


def matching_candidate(score_variant="strong"):
    if score_variant == "ambiguous":
        stats = {"speed": 950, "stamina": 900}
        compatibility = 70
        race = 60
    else:
        stats = {"speed": 1200, "stamina": 1100}
        compatibility = 90
        race = 80
    return {
        "trained_chara_id": 1001,
        "name": "Medium Turf Candidate",
        "rank": "S",
        "stats": stats,
        "aptitudes": {"turf": "A", "medium": "A"},
        "lineage_factors": [
            {"name": "turf", "stars": 2},
            {"name": "medium", "stars": 2},
        ],
        "compatibility_score": compatibility,
        "race_history_score": race,
    }


def test_start_routes_campaign_through_bot_readiness_states(tmp_path):
    store = CampaignStore(tmp_path / "campaigns.sqlite3")
    store.create(sample_spec(), campaign_id="campaign-1")
    runner = CampaignRunner(store)

    stopped = runner.start(
        "campaign-1",
        runtime={"api_reachable": False, "logged_in": False},
        bot_state={},
    )
    assert stopped["state"] == CampaignState.STARTING_BOT.value
    assert stopped["next_action"] == "launch_bot"

    waiting = runner.reconcile(
        "campaign-1",
        runtime={"api_reachable": True, "logged_in": False},
        bot_state={},
    )
    assert waiting["state"] == CampaignState.WAITING_FOR_LOGIN.value
    assert waiting["next_action"] == "wait_for_login"

    ready = runner.reconcile(
        "campaign-1",
        runtime={"api_reachable": True, "logged_in": True},
        bot_state={"session": {"logged_in": True}},
    )
    assert ready["state"] == CampaignState.SELECTING_LINEAGE.value
    assert ready["next_action"] == "select_lineage"


def test_begin_run_consumes_budget_and_finished_runner_moves_to_evaluation(tmp_path):
    store = CampaignStore(tmp_path / "campaigns.sqlite3")
    store.create(sample_spec(), campaign_id="campaign-1")
    runner = CampaignRunner(store)
    runner.start(
        "campaign-1",
        runtime={"api_reachable": True, "logged_in": True},
        bot_state={"session": {"logged_in": True}},
    )

    running = runner.begin_run("campaign-1")
    evaluating = runner.reconcile(
        "campaign-1",
        runtime={"api_reachable": True, "logged_in": True},
        bot_state={"career_runner": {"running": False, "finished": True}},
    )

    assert running["state"] == CampaignState.RUNNING_CAREER.value
    assert running["usage"]["runs"] == 1
    assert evaluating["state"] == CampaignState.EVALUATING_RESULT.value
    assert evaluating["next_action"] == "evaluate_result"


def test_accepted_candidate_is_selected_and_completes_campaign(tmp_path):
    store = CampaignStore(tmp_path / "campaigns.sqlite3")
    store.create(sample_spec(), campaign_id="campaign-1")
    runner = CampaignRunner(store)
    runner.start(
        "campaign-1",
        runtime={"api_reachable": True, "logged_in": True},
        bot_state={"session": {"logged_in": True}},
    )
    runner.begin_run("campaign-1")
    runner.reconcile(
        "campaign-1",
        runtime={"api_reachable": True, "logged_in": True},
        bot_state={"career_runner": {"running": False, "finished": True}},
    )

    result = runner.record_candidate("campaign-1", matching_candidate())

    assert result["campaign"]["state"] == CampaignState.COMPLETED.value
    assert result["evaluation"]["accepted"] is True
    assert result["candidate"]["selected"] is True
    assert result["campaign"]["selected_candidate_id"] == result["candidate"]["candidate_id"]


def test_ambiguous_candidate_requires_user_input(tmp_path):
    store = CampaignStore(tmp_path / "campaigns.sqlite3")
    store.create(sample_spec(), campaign_id="campaign-1")
    runner = CampaignRunner(store)
    runner.start(
        "campaign-1",
        runtime={"api_reachable": True, "logged_in": True},
        bot_state={"session": {"logged_in": True}},
    )
    runner.begin_run("campaign-1")
    runner.reconcile(
        "campaign-1",
        runtime={"api_reachable": True, "logged_in": True},
        bot_state={"career_runner": {"running": False, "finished": True}},
    )
    store.add_candidate(
        "campaign-1",
        trained_chara_id=999,
        name="Current Baseline",
        score=80,
        evaluation={"accepted": True},
        candidate_id="baseline",
    )

    result = runner.record_candidate(
        "campaign-1",
        matching_candidate("ambiguous"),
        baseline_score=80,
    )

    assert result["evaluation"]["decision"] == "ambiguous"
    assert result["campaign"]["state"] == CampaignState.NEEDS_USER_INPUT.value
    assert result["campaign"]["next_action"] == "select_candidate"


def test_rejected_last_run_fails_when_run_budget_is_exhausted(tmp_path):
    store = CampaignStore(tmp_path / "campaigns.sqlite3")
    store.create(sample_spec(maximum_runs=1), campaign_id="campaign-1")
    runner = CampaignRunner(store)
    runner.start(
        "campaign-1",
        runtime={"api_reachable": True, "logged_in": True},
        bot_state={"session": {"logged_in": True}},
    )
    runner.begin_run("campaign-1")
    runner.reconcile(
        "campaign-1",
        runtime={"api_reachable": True, "logged_in": True},
        bot_state={"career_runner": {"running": False, "finished": True}},
    )

    result = runner.record_candidate(
        "campaign-1",
        {
            "trained_chara_id": 1002,
            "rank": "A",
            "lineage_factors": [],
        },
    )

    assert result["evaluation"]["accepted"] is False
    assert result["campaign"]["state"] == CampaignState.FAILED.value
    assert "maximum_runs" in result["campaign"]["error"]


def test_require_user_input_persists_pending_review_before_transition(tmp_path):
    database = tmp_path / "campaigns.sqlite3"
    store = CampaignStore(database)
    store.create(sample_spec(), campaign_id="campaign-1")
    runner = CampaignRunner(store)
    runner.start(
        "campaign-1",
        runtime={"api_reachable": True, "logged_in": True},
        bot_state={"session": {"logged_in": True}},
    )

    updated = runner.require_user_input(
        "campaign-1",
        "review_lineage",
        {"kind": "pre_run", "parents": [7001, 8001]},
    )
    reopened = CampaignStore(database).get("campaign-1")

    assert updated["state"] == CampaignState.NEEDS_USER_INPUT.value
    assert updated["next_action"] == "review_lineage"
    assert reopened["context"]["pending_review"] == {
        "kind": "pre_run",
        "parents": [7001, 8001],
    }


def test_require_user_input_rolls_back_review_when_transition_fails(tmp_path):
    store = CampaignStore(tmp_path / "campaigns.sqlite3")
    store.create(sample_spec(), campaign_id="campaign-1")
    runner = CampaignRunner(store)

    with pytest.raises(InvalidTransition):
        runner.require_user_input(
            "campaign-1",
            "review_lineage",
            {"kind": "pre_run"},
        )

    assert "pending_review" not in store.get("campaign-1")["context"]


def test_repeated_require_user_input_updates_review_and_next_action(tmp_path):
    store = CampaignStore(tmp_path / "campaigns.sqlite3")
    store.create(sample_spec(), campaign_id="campaign-1")
    runner = CampaignRunner(store)
    runner.start(
        "campaign-1",
        runtime={"api_reachable": True, "logged_in": True},
        bot_state={"session": {"logged_in": True}},
    )
    runner.require_user_input(
        "campaign-1",
        "review_lineage",
        {"kind": "lineage"},
    )

    updated = runner.require_user_input(
        "campaign-1",
        "review_support",
        {"kind": "support"},
    )

    assert updated["next_action"] == "review_support"
    assert updated["error"] == ""
    assert updated["context"]["pending_review"] == {"kind": "support"}
    assert store.recent_events("campaign-1")[0]["event_type"] == "state_updated"


def test_continue_for_preferred_requires_completed_campaign(tmp_path):
    store = CampaignStore(tmp_path / "campaigns.sqlite3")
    store.create(sample_spec(), campaign_id="campaign-1")
    runner = CampaignRunner(store)

    with pytest.raises(InvalidTransition, match="COMPLETED"):
        runner.continue_for_preferred("campaign-1")


def test_continue_for_preferred_reopens_completed_campaign(tmp_path):
    store = CampaignStore(tmp_path / "campaigns.sqlite3")
    store.create(sample_spec(), campaign_id="campaign-1")
    runner = CampaignRunner(store)
    runner.start(
        "campaign-1",
        runtime={"api_reachable": True, "logged_in": True},
        bot_state={"session": {"logged_in": True}},
    )
    runner.begin_run("campaign-1")
    runner.reconcile(
        "campaign-1",
        runtime={"api_reachable": True, "logged_in": True},
        bot_state={"career_runner": {"running": False, "finished": True}},
    )
    runner.require_user_input(
        "campaign-1",
        "review_result",
        {"kind": "post_run"},
    )
    store.transition("campaign-1", CampaignState.COMPLETED)

    reopened = runner.continue_for_preferred("campaign-1")

    assert reopened["state"] == CampaignState.SELECTING_LINEAGE.value
    assert reopened["next_action"] == "prepare_next_run"
    assert reopened["context"] == {
        "required_target_achieved": True,
        "pending_review": None,
        "continue_preferred": True,
    }


def test_continue_for_preferred_conflict_leaves_completed_context_untouched(tmp_path):
    store = CampaignStore(tmp_path / "campaigns.sqlite3")
    store.create(sample_spec(), campaign_id="completed")
    store.create(sample_spec(), campaign_id="active")
    for state in (
        CampaignState.READY,
        CampaignState.STARTING_BOT,
        CampaignState.SELECTING_LINEAGE,
        CampaignState.RUNNING_CAREER,
        CampaignState.EVALUATING_RESULT,
        CampaignState.COMPLETED,
    ):
        store.transition("completed", state)
    store.update_context(
        "completed",
        {"pending_review": {"kind": "keep"}, "continue_preferred": False},
    )
    store.transition("active", CampaignState.READY)
    store.transition("active", CampaignState.STARTING_BOT)
    runner = CampaignRunner(store)

    with pytest.raises(CampaignError, match="active campaign"):
        runner.continue_for_preferred("completed")

    unchanged = store.get("completed")
    assert unchanged["state"] == CampaignState.COMPLETED.value
    assert unchanged["context"] == {
        "pending_review": {"kind": "keep"},
        "continue_preferred": False,
    }
