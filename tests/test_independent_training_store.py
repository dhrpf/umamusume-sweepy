import os

import pytest

from career_bot.independent_training.models import RunState
from career_bot.independent_training.store import (
    IndependentTrainingStore,
    InvalidRunTransition,
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
