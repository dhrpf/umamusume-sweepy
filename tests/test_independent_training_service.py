import json

import pytest

from career_bot.independent_training.service import (
    IndependentTrainingService,
    WorkflowConflict,
)
from career_bot.independent_training.store import (
    IndependentTrainingStore,
    RunNotFound,
)
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
        "friend_supports": [
            {
                "viewer_id": 70001,
                "support_card_id": 6,
                "support_name": "Friend Support",
            }
        ],
        "decks": [
            {
                "id": 1,
                "name": "Dirt Deck",
                "cards": [
                    {
                        "id": str(value),
                        "name": f"Support {value}",
                        "type": "Speed",
                        "rarity": 3,
                        "limit_break_count": 4,
                    }
                    for value in range(1, 6)
                ],
            }
        ],
        "saved_race_agendas": [
            {"name": "Classic dirt", "race_array": [{"year": 2, "program_id": 301}]}
        ],
    }


class FakeRunner:
    def __init__(self):
        self.started = []
        self.woken = False
        self.reconciled = []
        self.load_index_match = False
        self.completed_retry = False
        self.collection_retry = False
        self.collection_retry_calls = []
        self.finish_retry = False
        self.start_retry = False
        self.setup_retry = False
        self.finalization_retry = False
        self.state = {"state": "IDLE"}
        self.server_run = None
        self.adopted = []

    def start(self, account):
        self.started.append(account)
        self.state = {"state": "RUNNING", "account": account}
        return dict(self.state)

    def wake(self):
        self.woken = True

    def describe_server_run(self, account):
        return dict(self.server_run) if self.server_run else None

    def adopt_server_run(self, account):
        if not self.server_run:
            return None
        self.adopted.append(account)
        return {
            "run_id": "adopted-run",
            "account": account,
            "state": "RUNNING",
            "setup": {"card_id": self.server_run["card_id"]},
            "position": 99,
        }

    def reconcile_load_index(self, account):
        self.reconciled.append(account)
        return self.load_index_match

    def retry_completed_reconciliation(self, account):
        return self.completed_retry

    def retry_collection_reconciliation(self, account):
        self.collection_retry_calls.append(account)
        return self.collection_retry

    def retry_finish_reconciliation(self, account):
        return self.finish_retry

    def retry_start_reconciliation(self, account):
        return self.start_retry

    def retry_setup_reconciliation(self, account):
        return self.setup_retry

    def retry_finalization_reconciliation(self, account):
        return self.finalization_retry

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
            "detected_tp_cost": 15,
            "tp_cost_source": "campaign",
            "tp_cost_error": "",
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


def test_enqueue_rejects_friend_viewer_and_card_pair_not_in_dashboard_session(
    service,
):
    payload = setup_payload()
    payload["friend_viewer_id"] = 79999

    with pytest.raises(ValueError, match="friend support"):
        service.enqueue(payload, count=1, tp_mode="wait")


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


def test_status_marks_interrupted_start_without_server_window_attention(
    service,
    store,
):
    run = service.enqueue(setup_payload(), count=1, tp_mode="wait")["runs"][0]
    starting = store.claim_next("acct01")
    store.mark_start_attempted(run["run_id"], starting["version"])
    updated_at = store.get(run["run_id"])["updated_at"]
    store.clock = lambda: updated_at + 61

    status = service.status()

    assert status["runs"][0]["state"] == "NEEDS_ATTENTION"
    assert "unconfirmed" in status["runs"][0]["error"]
    assert status["runs"][0]["next_action"] == "reconcile"


def test_status_starts_runner_after_load_index_confirms_active_run(
    service,
    runner,
    job_store,
):
    runner.load_index_match = True

    service.status()

    assert runner.reconciled == ["acct01"]
    assert runner.started == ["acct01"]
    assert job_store.get_workflow_lease("acct01")["workflow_type"] == (
        "independent_training"
    )


def test_status_resumes_persisted_confirmed_running_run(
    service,
    store,
    runner,
    job_store,
):
    run = service.enqueue(setup_payload(), count=1, tp_mode="wait")["runs"][0]
    starting = store.claim_next("acct01")
    started = store.mark_start_attempted(run["run_id"], starting["version"])
    store.transition(
        run["run_id"],
        "RUNNING",
        expected_version=started["version"],
        server_start_time=100,
        server_end_time=3100,
    )

    service.status()

    assert runner.started == ["acct01"]
    assert job_store.get_workflow_lease("acct01")["workflow_type"] == (
        "independent_training"
    )


def test_reconcile_starts_runner_after_completed_status_retry(
    service,
    runner,
    job_store,
):
    runner.completed_retry = True

    service.reconcile()

    assert runner.started == ["acct01"]
    assert job_store.get_workflow_lease("acct01")["workflow_type"] == (
        "independent_training"
    )


def test_reconcile_starts_runner_after_finish_reconciliation(
    service,
    runner,
    job_store,
):
    runner.finish_retry = True

    service.reconcile()

    assert runner.started == ["acct01"]
    assert job_store.get_workflow_lease("acct01")["workflow_type"] == (
        "independent_training"
    )


def test_reconcile_starts_runner_after_start_reconciliation(
    service,
    runner,
    job_store,
):
    runner.start_retry = True

    service.reconcile()

    assert runner.started == ["acct01"]
    assert job_store.get_workflow_lease("acct01")["workflow_type"] == (
        "independent_training"
    )


def test_bootstrap_loads_saved_agendas_and_redacts_private_ids(service):
    result = service.bootstrap()
    encoded = json.dumps(result)

    assert result["saved_race_agendas"]
    assert result["account"] == "acct01"
    assert result["decks"] == dashboard_payload()["decks"]
    assert result["decks"][0]["cards"][0]["name"] == "Support 1"
    assert result["detected_tp_cost"] == 15
    assert result["tp_cost_source"] == "campaign"
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


def test_heartbeat_reacquires_lapsed_lease_while_run_is_active(
    service,
    store,
    job_store,
    clock,
):
    service.start()
    store.enqueue("acct01", setup_payload(), count=1, tp_mode="wait")
    store.claim_next("acct01")  # moves the queued run into STARTING
    clock["now"] += 121  # lease TTL expired during a long TP-regen sleep

    renewed = service.heartbeat()

    assert renewed["owner"] == "independent-training:acct01"
    assert renewed["expires_at"] > clock["now"]


def test_heartbeat_without_active_run_does_not_reacquire_lease(
    service,
    job_store,
    clock,
):
    service.start()
    clock["now"] += 121  # lease TTL expired while idle

    with pytest.raises(WorkflowConflict):
        service.heartbeat()

    assert job_store.get_workflow_lease("acct01") is None


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


def test_enqueue_rejects_supports_that_do_not_match_saved_deck(service):
    payload = setup_payload()
    payload["support_card_ids"] = [5, 4, 3, 2, 1]

    with pytest.raises(ValueError, match="saved deck"):
        service.enqueue(payload, count=1, tp_mode="wait")


def test_status_omits_raw_private_setup(service):
    service.enqueue(setup_payload(), count=1, tp_mode="wait")

    result = service.status()
    encoded = json.dumps(result)

    assert "setup" not in result["runs"][0]
    assert "friend_viewer_id" not in encoded
    assert "rental_viewer_id" not in encoded
    assert result["runs"][0]["setup_summary"]["card_id"] == 100101


def test_status_keeps_current_queue_after_more_than_200_historical_runs(
    service,
    store,
):
    for _ in range(2):
        historical = store.enqueue(
            "acct01",
            setup_payload(),
            count=100,
            tp_mode="wait",
        )
        for run in historical:
            store.cancel_queued(run["run_id"])

    completed_run = store.enqueue(
        "acct01",
        setup_payload(),
        count=1,
        tp_mode="wait",
    )[0]
    current = store.claim_next("acct01")
    for next_state in ("RUNNING", "COLLECTING", "FINALIZING", "COMPLETED"):
        current = store.transition(
            completed_run["run_id"],
            next_state,
            expected_version=current["version"],
        )
    queued_run = service.enqueue(
        setup_payload(),
        count=1,
        tp_mode="wait",
    )["runs"][0]

    result = service.status()

    assert [run["run_id"] for run in result["runs"]] == [
        completed_run["run_id"],
        queued_run["run_id"],
    ]
    assert [run["state"] for run in result["runs"]] == [
        "COMPLETED",
        "QUEUED",
    ]


def test_named_preset_round_trips_skills_races_and_safe_friend_selection(service):
    payload = setup_payload()
    payload["priority_skill_array"] = [{"priority": 1, "skill_id": 100011}]
    payload["final_skill_ids"] = [100031]
    payload["race_array"] = [{"year": 2, "program_id": 301}]

    service.save_preset("Dirt sprint", payload, count=2, tp_mode="wait")
    result = service.get_preset("Dirt sprint")

    assert result["setup"]["priority_skill_array"] == [
        {"priority": 1, "skill_id": 100011}
    ]
    assert result["setup"]["final_skill_ids"] == [100031]
    assert result["setup"]["race_array"] == [{"year": 2, "program_id": 301}]
    assert result["friend_index"] == 0
    assert "friend_viewer_id" not in json.dumps(result)


def test_named_preset_keeps_other_settings_when_friend_is_unavailable(service):
    service.save_preset("Dirt sprint", setup_payload(), count=2, tp_mode="wait")
    dashboard = dashboard_payload()
    dashboard["friend_supports"] = []
    service.dashboard_provider = lambda: dashboard

    result = service.get_preset("Dirt sprint")

    assert result["setup"]["card_id"] == 100101
    assert result["setup"]["parent_id_1"] == 11
    assert result["friend_index"] is None


def test_discard_drops_stuck_active_run_and_records_event(
    service,
    store,
    runner,
):
    service.enqueue(setup_payload(), count=2, tp_mode="wait")
    claimed = store.claim_next("acct01")
    store.transition(
        claimed["run_id"],
        "NEEDS_ATTENTION",
        expected_version=claimed["version"],
        error="start result is ambiguous: API error 102",
    )

    discarded = service.discard()

    assert discarded["run_id"] == claimed["run_id"]
    assert discarded["state"] == "FAILED"
    assert runner.woken is True
    assert store.active_run("acct01") is None
    event = store.list_events("acct01")[0]
    assert event["event_type"] == "run_discarded"
    assert event["data"]["previous_state"] == "NEEDS_ATTENTION"
    assert store.claim_next("acct01")["position"] == 2


def test_discard_reconciles_confirmed_server_run_before_freeing_queue(
    service,
    store,
    runner,
):
    service.enqueue(setup_payload(), count=2, tp_mode="wait")
    claimed = store.claim_next("acct01")
    started = store.mark_start_attempted(claimed["run_id"], claimed["version"])
    running = store.transition(
        claimed["run_id"],
        "RUNNING",
        expected_version=started["version"],
        server_start_time=10,
        server_end_time=90,
    )
    collecting = store.transition(
        claimed["run_id"],
        "COLLECTING",
        expected_version=running["version"],
    )
    marked = store.mark_collection_attempted(
        claimed["run_id"],
        collecting["version"],
    )
    store.transition(
        claimed["run_id"],
        "NEEDS_ATTENTION",
        expected_version=marked["version"],
        error="collection result is ambiguous: API error 1503 on idle_single_mode/end",
    )
    runner.collection_retry = True

    result = service.discard(claimed["run_id"])

    assert result["state"] == "NEEDS_ATTENTION"
    assert store.active_run("acct01")["run_id"] == claimed["run_id"]
    assert runner.collection_retry_calls == ["acct01"]
    assert runner.started == ["acct01"]
    assert not any(
        event["event_type"] == "run_discarded"
        for event in store.list_events("acct01")
    )


def test_discard_of_rejected_start_adopts_existing_server_run_before_queue_continues(
    service,
    store,
    runner,
):
    service.enqueue(setup_payload(), count=2, tp_mode="wait")
    claimed = store.claim_next("acct01")
    marked = store.mark_start_attempted(claimed["run_id"], claimed["version"])
    store.transition(
        claimed["run_id"],
        "NEEDS_ATTENTION",
        expected_version=marked["version"],
        error="start result is ambiguous: API error 102 on idle_single_mode/start",
    )
    runner.server_run = {
        "card_id": 100999,
        "scenario_id": 3,
        "parent_id_1": 55,
        "parent_id_2": 66,
        "server_start_time": 10,
        "server_end_time": 90,
        "collectable": True,
    }

    result = service.discard(claimed["run_id"])

    assert result["state"] == "FAILED"
    assert runner.adopted == ["acct01"]
    assert runner.started == ["acct01"]
    assert runner.woken is False


def test_discard_requires_an_active_run_of_the_bound_account(service, store):
    with pytest.raises(RunNotFound):
        service.discard()

    other = store.enqueue(
        "acct02", setup_payload(), count=1, tp_mode="wait"
    )[0]
    with pytest.raises(ValueError):
        service.discard(other["run_id"])
    assert store.get(other["run_id"])["state"] == "QUEUED"


def test_dashboard_start_clears_stop_after_current_so_queue_runs(
    service,
    store,
    runner,
):
    service.enqueue(setup_payload(), count=1, tp_mode="wait")
    service.stop_after_current()

    started = service.start(clear_stop=True)

    assert started["accepted"] is True
    assert store.get_control("acct01")["stop_after_current"] is False
    assert runner.started == ["acct01"]


def test_internal_start_keeps_stop_after_current_intent(service, store):
    service.enqueue(setup_payload(), count=1, tp_mode="wait")
    service.stop_after_current()

    service.start()

    assert store.get_control("acct01")["stop_after_current"] is True


def test_status_surfaces_an_untracked_server_career(service, runner):
    runner.server_run = {
        "card_id": 100999,
        "scenario_id": 4,
        "collectable": True,
    }

    assert service.status()["untracked_server_run"] == {
        "card_id": 100999,
        "scenario_id": 4,
        "collectable": True,
    }


def test_adopting_the_untracked_server_career_starts_the_executor(
    service,
    runner,
):
    runner.server_run = {"card_id": 100999, "scenario_id": 4}

    result = service.adopt_server_run()

    assert result["accepted"] is True
    assert result["run"]["run_id"] == "adopted-run"
    assert runner.adopted == ["acct01"]
    assert runner.started == ["acct01"]


def test_adopting_without_a_server_career_is_a_404(service, runner):
    with pytest.raises(RunNotFound):
        service.adopt_server_run()
