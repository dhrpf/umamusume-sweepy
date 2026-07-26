import pytest

from career_bot.independent_training.finalizer import NeedsAttention
from career_bot.independent_training.runner import IndependentTrainingRunner
from career_bot.independent_training.store import IndependentTrainingStore


def setup_payload():
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
        "priority_skill_array": [],
        "race_array": [],
        "factor_reroll": {"enabled": False, "targets": []},
        "use_tp": 30,
    }


def progress(*, card_id=100101, start=100, end=100):
    return {
        "card_id": card_id,
        "parent_id_1": 11,
        "parent_id_2": 22,
        "scenario_id": 3,
        "support_card_ids": [1, 2, 3, 4, 5],
        "start_time": start,
        "end_time": end,
    }


def status_response(value=None):
    return {"data": {"progress_info": value or {}}}


def end_response():
    return {
        "data": {
            "end_info": {
                "chara_info": {
                    "turn": 78,
                    "skill_point": 500,
                    "speed": 1100,
                    "stamina": 700,
                    "power": 900,
                    "guts": 500,
                    "wiz": 800,
                    "skill_array": [],
                    "skill_tips_array": [],
                }
            },
            "tp_info": {
                "current_tp": 30,
                "max_tp": 100,
                "max_recovery_time": 0,
            },
        }
    }


class FakeClient:
    def __init__(self):
        self.calls = []
        self.status_results = [status_response()]
        self.start_result = status_response(progress())
        self.end_result = end_response()
        self.raise_at = ""

    @property
    def start_calls(self):
        return self.calls.count("start")

    @property
    def end_calls(self):
        return self.calls.count("end")

    def independent_training_status(self):
        self.calls.append("status")
        if len(self.status_results) > 1:
            return self.status_results.pop(0)
        return self.status_results[0]

    def pre_start_independent_training(self, scenario_id):
        self.calls.append("pre_start")
        return {"data": {}}

    def start_independent_training(self, **kwargs):
        self.calls.append("start")
        if self.raise_at == "start":
            raise RuntimeError("connection lost after start")
        return self.start_result

    def end_independent_training(self):
        self.calls.append("end")
        if self.raise_at == "end":
            raise RuntimeError("connection lost after end")
        return self.end_result


class FakeFinalizer:
    def __init__(self, client):
        self.client = client

    def run(self, run):
        self.client.calls.append("finalize")
        if self.client.raise_at == "finalize":
            raise NeedsAttention("finish result is ambiguous")
        return {
            "trained_chara_id": 77,
            "current_turn": 78,
            "selected_lottery_id": 1,
        }


@pytest.fixture
def store(tmp_path):
    return IndependentTrainingStore(tmp_path / "independent.sqlite3")


@pytest.fixture
def account_state():
    return {
        "tp_info": {
            "current_tp": 60,
            "max_tp": 100,
            "max_recovery_time": 0,
        },
        "current_money": 500,
        "succession_rank_point": 10,
    }


@pytest.fixture
def harness(store, account_state):
    client = FakeClient()
    recover_calls = []
    refresh_calls = []

    def recover_tp(account):
        recover_calls.append(account)
        account_state["tp_info"]["current_tp"] = 30
        return True

    runner = IndependentTrainingRunner(
        store,
        client_provider=lambda account: client,
        finalizer_provider=lambda account: FakeFinalizer(client),
        account_state_provider=lambda account: account_state,
        refresh_account=lambda account: refresh_calls.append(account),
        recover_tp=recover_tp,
        clock=lambda: 100,
    )
    return runner, client, recover_calls, refresh_calls


def enqueue(store, *, count=1, tp_mode="wait"):
    return store.enqueue(
        "acct01",
        setup_payload(),
        count=count,
        tp_mode=tp_mode,
    )


def test_one_run_completes_full_lifecycle(store, harness):
    runner, client, _, refresh_calls = harness
    run = enqueue(store)[0]
    client.status_results = [
        status_response(),
        status_response(progress()),
    ]

    runner.run_once("acct01")

    assert store.get(run["run_id"])["state"] == "COMPLETED"
    assert client.calls == [
        "status",
        "pre_start",
        "start",
        "status",
        "end",
        "finalize",
    ]
    assert refresh_calls == ["acct01"]


def test_restart_after_start_attempt_reconciles_without_duplicate_start(
    store,
    harness,
):
    runner, client, _, _ = harness
    run = enqueue(store)[0]
    marked = store.mark_start_attempted(run["run_id"], run["version"])
    client.status_results = [status_response(progress(end=3100))]

    runner.run_once("acct01")

    assert client.start_calls == 0
    resumed = store.get(marked["run_id"])
    assert resumed["state"] == "RUNNING"
    assert resumed["server_start_time"] == 100
    assert resumed["server_end_time"] == 3100


def test_status_mismatch_needs_attention_and_does_not_start(store, harness):
    runner, client, _, _ = harness
    run = enqueue(store)[0]
    store.mark_start_attempted(run["run_id"], run["version"])
    client.status_results = [status_response(progress(card_id=999, end=3100))]

    runner.run_once("acct01")

    assert store.get(run["run_id"])["state"] == "NEEDS_ATTENTION"
    assert client.start_calls == 0


def test_stop_after_current_collects_active_but_leaves_next_queued(
    store,
    harness,
):
    runner, client, _, _ = harness
    first, second = enqueue(store, count=2)
    store.claim_next("acct01")
    store.set_stop_after_current("acct01", True)
    client.status_results = [
        status_response(),
        status_response(progress()),
    ]

    runner.run_once("acct01")

    assert store.get(first["run_id"])["state"] == "COMPLETED"
    assert store.get(second["run_id"])["state"] == "QUEUED"
    assert runner.snapshot()["state"] == "STOPPED"


def test_two_snapshots_run_without_second_approval(store, harness):
    runner, client, _, _ = harness
    first, second = enqueue(store, count=2)
    client.status_results = [
        status_response(),
        status_response(progress()),
        status_response(),
        status_response(progress(start=100, end=100)),
    ]

    runner.run_once("acct01")
    runner.run_once("acct01")

    assert [
        store.get(row["run_id"])["state"] for row in (first, second)
    ] == ["COMPLETED", "COMPLETED"]
    assert client.start_calls == 2


@pytest.mark.parametrize(
    ("tp_mode", "expected_state", "refill_count"),
    [
        ("wait", "WAITING_FOR_TP", 0),
        ("stop", "STOPPED", 0),
        ("carat", "RUNNING", 1),
    ],
)
def test_tp_policy_is_explicit(
    store,
    harness,
    account_state,
    tp_mode,
    expected_state,
    refill_count,
):
    runner, client, recover_calls, _ = harness
    enqueue(store, tp_mode=tp_mode)
    account_state["tp_info"]["current_tp"] = 0
    client.status_results = [status_response()]
    if tp_mode == "carat":
        client.start_result = status_response(progress(end=3100))

    runner.run_once("acct01")

    assert runner.snapshot()["state"] == expected_state
    assert len(recover_calls) == refill_count
    if tp_mode != "carat":
        assert client.start_calls == 0


@pytest.mark.parametrize("phase", ["start", "end", "finalize"])
def test_ambiguous_mutation_needs_attention(store, harness, phase):
    runner, client, _, _ = harness
    run = enqueue(store)[0]
    client.raise_at = phase
    client.status_results = [
        status_response(),
        status_response(progress()),
    ]

    runner.run_once("acct01")

    assert store.get(run["run_id"])["state"] == "NEEDS_ATTENTION"


def test_collection_marker_prevents_duplicate_end_after_restart(
    store,
    harness,
):
    runner, client, _, _ = harness
    run = enqueue(store)[0]
    starting = store.claim_next("acct01")
    started = store.mark_start_attempted(
        run["run_id"],
        starting["version"],
    )
    running = store.transition(
        run["run_id"],
        "RUNNING",
        expected_version=started["version"],
        server_start_time=100,
        server_end_time=100,
    )
    collecting = store.transition(
        run["run_id"],
        "COLLECTING",
        expected_version=running["version"],
    )
    store.mark_collection_attempted(
        run["run_id"],
        collecting["version"],
    )
    client.status_results = [status_response(progress())]

    runner.run_once("acct01")

    assert client.end_calls == 0
    assert store.get(run["run_id"])["state"] == "NEEDS_ATTENTION"
