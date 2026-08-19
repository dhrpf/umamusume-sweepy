import os

import pytest

from career_bot.independent_training.models import RunState
from career_bot.independent_training.store import (
    IndependentTrainingStore,
    InvalidRunTransition,
    RunNotFound,
    RunVersionConflict,
)


def minimal_setup():
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
        "factor_reroll": {"enabled": False, "targets": []},
    }


def test_enqueue_persists_ordered_independent_snapshots(tmp_path):
    store = IndependentTrainingStore(tmp_path / "independent.sqlite3")
    runs = store.enqueue(
        "acct01", minimal_setup(), count=2, tp_mode="wait"
    )
    runs[0]["setup"]["card_id"] = 9
    persisted = store.list_runs("acct01")
    assert [row["position"] for row in persisted] == [1, 2]
    assert persisted[0]["setup"]["card_id"] == 100101


def test_transition_requires_expected_version(tmp_path):
    store = IndependentTrainingStore(tmp_path / "independent.sqlite3")
    run = store.enqueue(
        "acct01", minimal_setup(), count=1, tp_mode="wait"
    )[0]
    started = store.transition(
        run["run_id"],
        RunState.STARTING,
        expected_version=run["version"],
    )
    with pytest.raises(RunVersionConflict):
        store.transition(
            run["run_id"],
            RunState.RUNNING,
            expected_version=run["version"],
        )
    assert started["version"] == run["version"] + 1


def test_only_queued_runs_can_be_cancelled(tmp_path):
    store = IndependentTrainingStore(tmp_path / "independent.sqlite3")
    run = store.enqueue(
        "acct01", minimal_setup(), count=1, tp_mode="wait"
    )[0]
    store.transition(
        run["run_id"],
        RunState.STARTING,
        expected_version=run["version"],
    )
    with pytest.raises(InvalidRunTransition):
        store.cancel_queued(run["run_id"])


def test_lottery_attempt_is_atomic_and_idempotent(tmp_path):
    store = IndependentTrainingStore(tmp_path / "independent.sqlite3")
    run = store.enqueue(
        "acct01", minimal_setup(), count=1, tp_mode="wait"
    )[0]
    marked = store.mark_factor_lottery_attempted(
        run["run_id"], run["version"]
    )
    assert marked["factor_lottery_attempted"] is True
    with pytest.raises(RunVersionConflict):
        store.mark_factor_lottery_attempted(
            run["run_id"], run["version"]
        )


def test_events_never_store_viewer_ids(tmp_path):
    store = IndependentTrainingStore(tmp_path / "independent.sqlite3")
    store.append_event(
        "acct01",
        "observed",
        {"viewer_id": 123, "sid": "secret"},
    )
    assert store.list_events("acct01")[0]["data"] == {
        "viewer_id": "<redacted>",
        "sid": "<redacted>",
    }
    assert os.stat(store.database_path).st_mode & 0o077 == 0


def test_named_presets_round_trip_complete_setup_per_account(tmp_path):
    store = IndependentTrainingStore(tmp_path / "independent.sqlite3")
    setup = minimal_setup()
    setup["priority_skill_array"] = [{"priority": 1, "skill_id": 100011}]
    setup["final_skill_ids"] = [100031]
    setup["race_array"] = [{"year": 2, "program_id": 301}]

    created = store.save_preset(
        "acct01", "Dirt sprint", setup, count=2, tp_mode="wait"
    )

    assert created["name"] == "Dirt sprint"
    assert store.list_presets("acct02") == []
    loaded = store.get_preset("acct01", "Dirt sprint")
    assert loaded["setup"]["final_skill_ids"] == [100031]
    assert loaded["setup"]["race_array"] == [{"year": 2, "program_id": 301}]


def test_saving_a_named_preset_replaces_that_account_name_only(tmp_path):
    store = IndependentTrainingStore(tmp_path / "independent.sqlite3")
    store.save_preset(
        "acct01", "Dirt sprint", minimal_setup(), count=1, tp_mode="wait"
    )

    updated = store.save_preset(
        "acct01", "Dirt sprint", minimal_setup(), count=5, tp_mode="stop"
    )

    assert updated["count"] == 5
    assert updated["tp_mode"] == "stop"
    assert len(store.list_presets("acct01")) == 1


def test_discard_forces_stuck_run_into_failed_with_reason(tmp_path):
    store = IndependentTrainingStore(tmp_path / "independent.sqlite3")
    store.enqueue("acct01", minimal_setup(), count=2, tp_mode="wait")
    claimed = store.claim_next("acct01")
    stuck = store.transition(
        claimed["run_id"],
        RunState.NEEDS_ATTENTION,
        expected_version=claimed["version"],
        error="start result is ambiguous: API error 102",
        next_action="reconcile",
    )

    discarded = store.discard(stuck["run_id"], reason="dashboard removal")

    assert discarded["state"] == RunState.FAILED.value
    assert discarded["error"] == "dashboard removal"
    assert discarded["next_action"] == ""
    assert discarded["version"] == stuck["version"] + 1
    assert store.active_run("acct01") is None
    assert store.claim_next("acct01")["position"] == 2


def test_discard_rejects_terminal_runs_and_unknown_ids(tmp_path):
    store = IndependentTrainingStore(tmp_path / "independent.sqlite3")
    run = store.enqueue(
        "acct01", minimal_setup(), count=1, tp_mode="wait"
    )[0]
    store.cancel_queued(run["run_id"])

    with pytest.raises(InvalidRunTransition):
        store.discard(run["run_id"])
    with pytest.raises(RunNotFound):
        store.discard("missing-run")
