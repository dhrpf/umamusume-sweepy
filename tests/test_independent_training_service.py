import json

import pytest

from career_bot.independent_training.service import (
    IndependentTrainingService,
    WorkflowConflict,
)
from career_bot.independent_training.store import IndependentTrainingStore
from sweepy_jobs import SweepyJobStore


def setup_payload():
    return {
        "card_id": 100101,
        "support_card_ids": [1, 2, 3, 4, 5],
        "friend_viewer_id": 70001,
        "friend_card_id": 6,
        "parent_id_1": 11,
        "parent_id_2": 22,
        "rental_viewer_id": 80001,
        "rental_trained_chara_id": 33,
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


def dashboard_payload():
    return {
        "account_label": "Test Account",
        "trainees": [
            {
                "card_id": 100101,
                "base_chara_id": 1001,
                "name": "Trainee",
            }
        ],
        "parents": [
            {
                "trained_chara_id": 11,
                "card_id": 100201,
                "base_chara_id": 1002,
                "name": "Parent A",
            },
            {
                "trained_chara_id": 22,
                "card_id": 100301,
                "base_chara_id": 1003,
                "name": "Parent B",
            },
            {
                "trained_chara_id": 44,
                "card_id": 100102,
                "base_chara_id": 1001,
                "name": "Same trainee",
            },
        ],
        "support_cards": [{"support_card_id": value} for value in range(1, 7)],
        "saved_race_agendas": [
            {"name": "Classic dirt", "race_array": [{"year": 2, "program_id": 301}]}
        ],
    }


class FakeRunner:
    def __init__(self):
        self.started = []
        self.woken = False
        self.state = {"state": "IDLE"}

    def start(self, account):
        self.started.append(account)
        self.state = {"state": "RUNNING", "account": account}
        return dict(self.state)

    def wake(self):
        self.woken = True

    def snapshot(self):
        return dict(self.state)


@pytest.fixture
def clock():
    values = {"now": 100.0}
    return values


@pytest.fixture
def store(tmp_path):
    return IndependentTrainingStore(tmp_path / "independent.sqlite3")


@pytest.fixture
def job_store(tmp_path, clock):
    return SweepyJobStore(
        tmp_path / "jobs.sqlite3",
        clock=lambda: clock["now"],
    )


@pytest.fixture
def runner():
    return FakeRunner()


@pytest.fixture
def service(store, job_store, runner):
    pre_start_calls = []

    def pre_start():
        pre_start_calls.append(True)
        return {
            "reserved_race_info": [{"year": 2, "program_id": 301}],
            "last_idle_single_mode_start_info": {
                "card_id": 100101,
                "friend_viewer_id": 70001,
            },
        }

    instance = IndependentTrainingService(
        store,
        runner,
        job_store,
        account_provider=lambda: "acct01",
        dashboard_provider=dashboard_payload,
        busy_workflow_provider=lambda: None,
        pre_start_provider=pre_start,
        lease_ttl_seconds=120,
    )
    instance.pre_start_calls = pre_start_calls
    instance.dashboard_parent_with_same_base_chara = 44
    return instance


def test_enqueue_validates_dashboard_selection_before_persisting(
    service,
    store,
):
    result = service.enqueue(setup_payload(), count=2, tp_mode="wait")

    assert len(result["runs"]) == 2
    assert all(row["account"] == "acct01" for row in result["runs"])
    assert len(store.list_runs("acct01")) == 2


def test_start_acquires_independent_training_lease(
    service,
    job_store,
    runner,
):
    result = service.start()

    lease = job_store.get_workflow_lease("acct01")
    assert result["accepted"] is True
    assert lease["workflow_type"] == "independent_training"
    assert runner.started == ["acct01"]


def test_existing_campaign_lease_blocks_start(service, job_store):
    job_store.acquire_workflow_lease(
        "acct01",
        owner="campaign:one",
        workflow_type="campaign",
        ttl_seconds=120,
    )

    with pytest.raises(WorkflowConflict, match="campaign"):
        service.start()


def test_busy_runtime_workflow_blocks_start(store, job_store, runner):
    service = IndependentTrainingService(
        store,
        runner,
        job_store,
        account_provider=lambda: "acct01",
        dashboard_provider=dashboard_payload,
        busy_workflow_provider=lambda: "career",
        pre_start_provider=lambda: {},
    )

    with pytest.raises(WorkflowConflict, match="career"):
        service.start()


def test_stop_and_resume_are_persistent(service, store, runner):
    service.stop_after_current()
    assert store.get_control("acct01")["stop_after_current"] is True

    service.resume()

    assert store.get_control("acct01")["stop_after_current"] is False
    assert runner.started == ["acct01"]


def test_bootstrap_loads_saved_agendas_and_redacts_private_ids(service):
    result = service.bootstrap()
    encoded = json.dumps(result)

    assert result["saved_race_agendas"]
    assert result["account"] == "acct01"
    assert "friend_viewer_id" not in encoded
    assert "rental_viewer_id" not in encoded
    assert service.pre_start_calls == [True]


def test_heartbeat_renews_same_owner_and_release_is_owner_safe(
    service,
    job_store,
    clock,
):
    service.start()
    first = job_store.get_workflow_lease("acct01")
    clock["now"] += 30

    renewed = service.heartbeat()

    assert renewed["owner"] == first["owner"]
    assert renewed["expires_at"] > first["expires_at"]
    assert job_store.release_workflow_lease(
        "acct01",
        owner="wrong",
    ) is False
    assert service.release_lease() is True


def test_cancel_and_reconcile_obey_run_state(service, store, runner):
    queued = service.enqueue(
        setup_payload(),
        count=1,
        tp_mode="wait",
    )["runs"][0]
    assert service.cancel(queued["run_id"])["state"] == "CANCELLED"

    attention = store.enqueue(
        "acct01",
        setup_payload(),
        count=1,
        tp_mode="wait",
    )[0]
    starting = store.claim_next("acct01")
    attention = store.transition(
        attention["run_id"],
        "NEEDS_ATTENTION",
        expected_version=starting["version"],
        error="ambiguous",
    )

    result = service.reconcile()

    assert result["accepted"] is True
    assert runner.woken is True
    assert store.get(attention["run_id"])["state"] == "NEEDS_ATTENTION"


def test_enqueue_rejects_trainee_parent_identity_conflict(service):
    payload = setup_payload()
    payload["parent_id_1"] = service.dashboard_parent_with_same_base_chara

    with pytest.raises(ValueError, match="trainee"):
        service.enqueue(payload, count=1, tp_mode="wait")


def test_status_omits_raw_private_setup(service):
    service.enqueue(setup_payload(), count=1, tp_mode="wait")

    result = service.status()
    encoded = json.dumps(result)

    assert "setup" not in result["runs"][0]
    assert "friend_viewer_id" not in encoded
    assert "rental_viewer_id" not in encoded
    assert result["runs"][0]["setup_summary"]["card_id"] == 100101
