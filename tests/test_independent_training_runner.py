import pytest

from career_bot.independent_training.finalizer import NeedsAttention
from career_bot.independent_training.runner import IndependentTrainingRunner
from career_bot.independent_training.store import IndependentTrainingStore
from career_bot.independent_training.tp_cost import (
    TpCostResolution,
    TpCostResolutionError,
)


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
        self.current_scenario_id = None
        self.calls = []
        self.status_results = [status_response()]
        self.start_result = status_response(progress())
        self.end_result = end_response()
        self.result_response = end_response()
        self.raise_at = ""
        self.start_kwargs = []

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

    def pre_single_mode(self):
        self.calls.append("pre_single")
        if self.raise_at == "pre_single_201":
            raise RuntimeError("API error 201 on pre_single_mode/index")
        return {"data": {}}

    def start_independent_training(self, **kwargs):
        self.calls.append("start")
        self.start_kwargs.append(kwargs)
        if self.raise_at == "start":
            raise RuntimeError("connection lost after start")
        return self.start_result

    def end_independent_training(self):
        self.calls.append("end")
        if self.raise_at == "end":
            raise RuntimeError("connection lost after end")
        if self.raise_at == "end_1503":
            raise RuntimeError("API error 1503 on idle_single_mode/end")
        return self.end_result

    def independent_training_result(self):
        self.calls.append("result")
        return self.result_response

    def check_independent_training_progress_log(self):
        self.calls.append("progress_log")
        return {"data": {}}


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
        tp_cost_provider=lambda account: TpCostResolution(30, "base"),
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
    client.status_results = [status_response(progress())]

    runner.run_once("acct01")

    assert store.get(run["run_id"])["state"] == "COMPLETED"
    assert client.calls == [
        "pre_start",
        "start",
        "status",
        "end",
        "progress_log",
        "finalize",
    ]
    assert refresh_calls == ["acct01"]


def test_run_once_sets_client_scenario_id_before_dispatch(store, harness):
    """A fresh client (e.g. after a process restart) defaults current_scenario_id
    to None, which breaks single_mode_free/* -> single_mode_live/* endpoint
    remapping for scenario_id=3 runs (gain_skills/factor_select silently hit
    the wrong endpoint and the server rejects them). run_once must stamp it
    from the run's own setup before any client call, on every dispatch."""
    runner, client, _, _ = harness
    enqueue(store)
    assert client.current_scenario_id is None

    runner.run_once("acct01")

    assert client.current_scenario_id == 3


def test_status_reconciles_runtime_deck_with_friend_support(store, harness):
    runner, client, _, _ = harness
    run = enqueue(store)[0]
    client.status_results = [status_response({
        "start_time": "1970-01-01 00:01:40",
        "end_time": "1970-01-01 00:01:40",
        "chara_info": {
            "card_id": 100101,
            "parent_id_1": 11,
            "parent_id_2": 22,
            "scenario_id": 3,
            "support_card_array": [
                {"support_card_id": card_id, "position": position}
                for position, card_id in enumerate([1, 2, 3, 4, 5, 6], 1)
            ],
        },
    })]

    runner.run_once("acct01")

    assert store.get(run["run_id"])["state"] == "COMPLETED"


def test_new_run_starts_without_idle_status_poll(store, harness):
    runner, client, _, _ = harness
    client.start_result = status_response(progress(end=3100))
    enqueue(store)

    runner.run_once("acct01")

    assert client.calls == ["pre_start", "start"]
    assert runner.snapshot()["state"] == "RUNNING"


def test_new_run_uses_selected_parent_affinity_for_succession_points(
    store,
    harness,
):
    runner, client, _, _ = harness
    provider_calls = []
    runner.succession_rank_point_provider = lambda account, setup: (
        provider_calls.append((account, setup["card_id"])) or 148
    )
    client.start_result = status_response(progress(end=3100))
    enqueue(store)

    runner.run_once("acct01")

    assert provider_calls == [("acct01", 100101)]
    assert client.start_kwargs[0]["succession_rank_point"] == 148


def test_affinity_resolution_failure_stops_before_pre_start(store, harness):
    runner, client, _, _ = harness
    runner.succession_rank_point_provider = lambda _account, _setup: (
        (_ for _ in ()).throw(ValueError("parents unavailable"))
    )
    run = enqueue(store)[0]

    runner.run_once("acct01")

    latest = store.get(run["run_id"])
    assert latest["state"] == "NEEDS_ATTENTION"
    assert latest["start_attempted"] is False
    assert client.calls == []
    assert "parents unavailable" in latest["error"]


def test_known_active_run_waits_without_idle_status_poll(store, harness):
    runner, client, _, _ = harness
    run = enqueue(store)[0]
    starting = store.claim_next("acct01")
    started = store.mark_start_attempted(run["run_id"], starting["version"])
    store.transition(
        run["run_id"],
        "RUNNING",
        expected_version=started["version"],
        server_start_time=100,
        server_end_time=3100,
    )

    runner.run_once("acct01")

    assert client.calls == []
    assert runner.snapshot()["state"] == "RUNNING"


def test_running_record_without_server_window_does_not_probe_idle_status(
    store,
    harness,
):
    runner, client, _, _ = harness
    run = enqueue(store)[0]
    starting = store.claim_next("acct01")
    started = store.mark_start_attempted(run["run_id"], starting["version"])
    store.transition(
        run["run_id"],
        "RUNNING",
        expected_version=started["version"],
        server_start_time=0,
        server_end_time=0,
    )

    runner.run_once("acct01")

    assert client.calls == []
    latest = store.get(run["run_id"])
    assert latest["state"] == "NEEDS_ATTENTION"
    assert "server window" in latest["error"]


def test_restart_after_unconfirmed_start_does_not_probe_idle_status(
    store,
    harness,
):
    runner, client, _, _ = harness
    run = enqueue(store)[0]
    marked = store.mark_start_attempted(run["run_id"], run["version"])

    runner.run_once("acct01")

    assert client.calls == []
    resumed = store.get(marked["run_id"])
    assert resumed["state"] == "NEEDS_ATTENTION"
    assert "unconfirmed" in resumed["error"]


def test_load_index_reconciles_unconfirmed_start_without_idle_status(
    store,
    harness,
):
    runner, client, _, _ = harness
    runner.load_progress_provider = lambda account: {
        "start_time": "1970-01-01T00:01:40+00:00",
        "end_time": "1970-01-01T00:51:40+00:00",
        "single_mode_chara_light": {
            "card_id": 100101,
            "parent_id_1": 11,
            "parent_id_2": 22,
            "scenario_id": 3,
        },
    }
    run = enqueue(store)[0]
    starting = store.claim_next("acct01")
    store.mark_start_attempted(run["run_id"], starting["version"])

    runner.run_once("acct01")

    resumed = store.get(run["run_id"])
    assert client.calls == []
    assert resumed["state"] == "RUNNING"
    assert resumed["server_start_time"] == 100
    assert resumed["server_end_time"] == 3100


def test_load_index_mismatch_does_not_promote_queued_run(store, harness):
    runner, client, _, _ = harness
    runner.load_progress_provider = lambda account: {
        "start_time": "1970-01-01T00:01:40+00:00",
        "end_time": "1970-01-01T00:51:40+00:00",
        "single_mode_chara_light": {"card_id": 999999},
    }
    run = enqueue(store)[0]
    starting = store.claim_next("acct01")
    store.mark_start_attempted(run["run_id"], starting["version"])

    runner.run_once("acct01")

    assert client.calls == []
    assert store.get(run["run_id"])["state"] == "NEEDS_ATTENTION"


def test_reconcile_retries_only_completed_status_mismatch(store, harness):
    runner, client, _, _ = harness
    run = enqueue(store)[0]
    starting = store.claim_next("acct01")
    started = store.mark_start_attempted(run["run_id"], starting["version"])
    running = store.transition(
        run["run_id"],
        "RUNNING",
        expected_version=started["version"],
        server_start_time=100,
        server_end_time=100,
    )
    store.transition(
        run["run_id"],
        "NEEDS_ATTENTION",
        expected_version=running["version"],
        error="completed server run could not be reconciled",
        next_action="reconcile",
    )

    assert runner.retry_completed_reconciliation("acct01") is True
    assert client.calls == []
    resumed = store.get(run["run_id"])
    assert resumed["state"] == "RUNNING"
    assert resumed["error"] == ""


@pytest.mark.parametrize(
    "error",
    [
        "start result is ambiguous: API error 205",
        "unconfirmed start was abandoned; idle status was not queried",
    ],
)
def test_reconcile_retries_unconfirmed_start_when_load_index_has_no_run(
    store,
    harness,
    error,
):
    runner, _, _, refresh_calls = harness
    runner.refresh_account = lambda account: (
        refresh_calls.append(account) or {"data": {}}
    )
    run = enqueue(store)[0]
    starting = store.claim_next("acct01")
    marked = store.mark_start_attempted(run["run_id"], starting["version"])
    attention = store.transition(
        run["run_id"],
        "NEEDS_ATTENTION",
        expected_version=marked["version"],
        error=error,
        next_action="reconcile",
    )

    assert runner.retry_start_reconciliation("acct01") is True

    retried = store.get(attention["run_id"])
    assert refresh_calls == ["acct01"]
    assert retried["state"] == "STARTING"
    assert retried["start_attempted"] is False
    assert retried["error"] == ""
    assert harness[1].calls == ["pre_single"]


def test_reconcile_reauthenticates_expired_pre_single_session(store, harness):
    runner, client, _, _ = harness
    reauth_calls = []
    runner.auth_recovery = lambda account: reauth_calls.append(account) or True
    runner.refresh_account = lambda account: {"data": {}}
    client.raise_at = "pre_single_201"
    run = enqueue(store)[0]
    starting = store.claim_next("acct01")
    marked = store.mark_start_attempted(run["run_id"], starting["version"])
    attention = store.transition(
        run["run_id"],
        "NEEDS_ATTENTION",
        expected_version=marked["version"],
        error="start result is ambiguous: API error 201",
        next_action="reconcile",
    )

    assert runner.retry_start_reconciliation("acct01") is True

    retried = store.get(attention["run_id"])
    assert reauth_calls == ["acct01"]
    assert client.calls == ["pre_single"]
    assert retried["state"] == "STARTING"
    assert retried["start_attempted"] is False


def test_reconcile_reauthenticates_expired_load_index_session(store, harness):
    runner, client, _, _ = harness
    reauth_calls = []
    runner.auth_recovery = lambda account: reauth_calls.append(account) or True
    runner.refresh_account = lambda account: (_ for _ in ()).throw(
        RuntimeError("API error 201 on load/index")
    )
    run = enqueue(store)[0]
    starting = store.claim_next("acct01")
    marked = store.mark_start_attempted(run["run_id"], starting["version"])
    attention = store.transition(
        run["run_id"],
        "NEEDS_ATTENTION",
        expected_version=marked["version"],
        error="start result is ambiguous: API error 201",
        next_action="reconcile",
    )

    assert runner.retry_start_reconciliation("acct01") is True

    retried = store.get(attention["run_id"])
    assert reauth_calls == ["acct01"]
    assert client.calls == []
    assert retried["state"] == "STARTING"
    assert retried["start_attempted"] is False


@pytest.mark.parametrize(
    "error",
    [
        "independent race setup unavailable: unable to resolve objective sort 6",
        "succession affinity unavailable: missing parent card",
    ],
)
def test_retry_setup_reconciliation_resets_to_starting(store, harness, error):
    runner, _, _, _ = harness
    run = enqueue(store)[0]
    starting = store.claim_next("acct01")
    attention = store.transition(
        run["run_id"],
        "NEEDS_ATTENTION",
        expected_version=starting["version"],
        error=error,
        next_action="reconcile",
    )

    assert runner.retry_setup_reconciliation("acct01") is True

    retried = store.get(attention["run_id"])
    assert retried["state"] == "STARTING"
    assert retried["start_attempted"] is False
    assert retried["error"] == ""


def test_reconcile_resumes_ambiguous_start_when_load_index_matches_run(
    store,
    harness,
):
    runner, _, _, refresh_calls = harness
    runner.refresh_account = lambda account: (
        refresh_calls.append(account)
        or {"data": {"idle_single_mode_load_info": progress(end=3100)}}
    )
    run = enqueue(store)[0]
    starting = store.claim_next("acct01")
    marked = store.mark_start_attempted(run["run_id"], starting["version"])
    attention = store.transition(
        run["run_id"],
        "NEEDS_ATTENTION",
        expected_version=marked["version"],
        error="start result is ambiguous: API error 205",
        next_action="reconcile",
    )

    assert runner.retry_start_reconciliation("acct01") is True

    resumed = store.get(attention["run_id"])
    assert refresh_calls == ["acct01"]
    assert resumed["state"] == "RUNNING"
    assert resumed["start_attempted"] is True
    assert resumed["server_end_time"] == 3100


def test_reconcile_finishes_ambiguous_finish_when_load_index_has_no_career(
    store,
    harness,
):
    runner, _, _, refresh_calls = harness
    runner.refresh_account = lambda account: (
        refresh_calls.append(account) or {"data": {}}
    )
    run = enqueue(store)[0]
    starting = store.claim_next("acct01")
    started = store.mark_start_attempted(run["run_id"], starting["version"])
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
    finalizing = store.transition(
        run["run_id"],
        "FINALIZING",
        expected_version=collecting["version"],
        finalization={"chara_info": {"turn": 78}},
        selected_lottery_id=2,
    )
    store.mark_finish_attempted(run["run_id"], finalizing["version"])
    attention = store.transition(
        run["run_id"],
        "NEEDS_ATTENTION",
        expected_version=store.get(run["run_id"])["version"],
        error="finish result is ambiguous",
        next_action="reconcile",
    )

    assert runner.retry_finish_reconciliation("acct01") is True

    completed = store.get(attention["run_id"])
    assert refresh_calls == ["acct01"]
    assert completed["state"] == "COMPLETED"
    assert completed["error"] == ""
    assert completed["result"] == {
        "current_turn": 78,
        "selected_lottery_id": 2,
        "reconciled": True,
    }


def test_reconcile_keeps_ambiguous_finish_when_load_index_has_active_career(
    store,
    harness,
):
    runner, _, _, refresh_calls = harness
    runner.refresh_account = lambda account: (
        refresh_calls.append(account)
        or {"data": {"single_mode_chara_light": {"card_id": 100101}}}
    )
    run = enqueue(store)[0]
    starting = store.claim_next("acct01")
    started = store.mark_start_attempted(run["run_id"], starting["version"])
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
    finalizing = store.transition(
        run["run_id"],
        "FINALIZING",
        expected_version=collecting["version"],
    )
    store.mark_finish_attempted(run["run_id"], finalizing["version"])
    attention = store.transition(
        run["run_id"],
        "NEEDS_ATTENTION",
        expected_version=store.get(run["run_id"])["version"],
        error="finish result is ambiguous",
        next_action="reconcile",
    )

    assert runner.retry_finish_reconciliation("acct01") is False

    assert refresh_calls == ["acct01"]
    assert store.get(attention["run_id"])["state"] == "NEEDS_ATTENTION"


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
    client.status_results = [status_response(progress())]

    runner.run_once("acct01")

    assert store.get(first["run_id"])["state"] == "COMPLETED"
    assert store.get(second["run_id"])["state"] == "QUEUED"
    assert runner.snapshot()["state"] == "STOPPED"


def test_end_1503_reconciles_post_run_result_instead_of_parking(
    store,
    harness,
):
    runner, client, _, _ = harness
    run = enqueue(store)[0]
    client.status_results = [status_response(progress())]
    client.raise_at = "end_1503"

    runner.run_once("acct01")

    assert store.get(run["run_id"])["state"] == "COMPLETED"
    assert client.calls == [
        "pre_start",
        "start",
        "status",
        "end",
        "result",
        "finalize",
    ]
    assert client.start_calls == 1


def test_two_snapshots_run_without_second_approval(store, harness):
    runner, client, _, _ = harness
    first, second = enqueue(store, count=2)
    client.status_results = [
        status_response(progress()),
        status_response(progress(start=100, end=100)),
    ]

    runner.run_once("acct01")
    runner.run_once("acct01")

    assert [
        store.get(row["run_id"])["state"] for row in (first, second)
    ] == ["COMPLETED", "COMPLETED"]
    assert client.start_calls == 2


def test_resolves_tp_cost_at_start_and_sends_it_to_server(
    store,
    account_state,
):
    client = FakeClient()
    client.start_result = status_response(progress(end=3100))
    resolved = []
    runner = IndependentTrainingRunner(
        store,
        client_provider=lambda account: client,
        finalizer_provider=lambda account: FakeFinalizer(client),
        account_state_provider=lambda account: account_state,
        refresh_account=lambda account: None,
        recover_tp=lambda account: False,
        tp_cost_provider=lambda account: (
            resolved.append(account) or TpCostResolution(15, "campaign", (7,))
        ),
        clock=lambda: 100,
    )
    enqueue(store)
    account_state["tp_info"]["current_tp"] = 15

    runner.run_once("acct01")

    assert resolved == ["acct01"]
    assert client.start_kwargs[0]["setup"]["use_tp"] == 15
    assert "use_tp" not in store.list_runs("acct01")[0]["setup"]
    assert runner.snapshot()["detected_tp_cost"] == 15
    assert runner.snapshot()["tp_cost_source"] == "campaign"


def test_start_uses_wire_races_without_mutating_queued_setup(
    store,
    account_state,
):
    client = FakeClient()
    client.start_result = status_response(progress(end=3100))
    wire_races = [{"year": 1, "program_id": 846}]
    provided_setups = []
    runner = IndependentTrainingRunner(
        store,
        client_provider=lambda account: client,
        finalizer_provider=lambda account: FakeFinalizer(client),
        account_state_provider=lambda account: account_state,
        refresh_account=lambda account: None,
        recover_tp=lambda account: False,
        tp_cost_provider=lambda account: TpCostResolution(15, "base"),
        race_array_provider=lambda setup: (
            provided_setups.append(setup) or wire_races
        ),
        clock=lambda: 100,
    )
    run = enqueue(store)[0]
    account_state["tp_info"]["current_tp"] = 15

    runner.run_once("acct01")

    assert provided_setups[0]["card_id"] == 100101
    assert client.start_kwargs[0]["setup"]["race_array"] == wire_races
    assert store.get(run["run_id"])["setup"]["race_array"] == []


def test_race_validation_failure_stops_before_tp_resolution(
    store,
    account_state,
):
    client = FakeClient()
    tp_resolutions = []
    runner = IndependentTrainingRunner(
        store,
        client_provider=lambda account: client,
        finalizer_provider=lambda account: FakeFinalizer(client),
        account_state_provider=lambda account: account_state,
        refresh_account=lambda account: None,
        recover_tp=lambda account: False,
        tp_cost_provider=lambda account: (
            tp_resolutions.append(account)
            or TpCostResolution(15, "base")
        ),
        race_array_provider=lambda setup: (_ for _ in ()).throw(
            ValueError("invalid race setup")
        ),
        clock=lambda: 100,
    )
    run = enqueue(store)[0]

    runner.run_once("acct01")

    latest = store.get(run["run_id"])
    assert latest["state"] == "NEEDS_ATTENTION"
    assert tp_resolutions == []
    assert client.calls == []


def test_each_queued_run_resolves_current_tp_cost(
    store,
    account_state,
):
    client = FakeClient()
    client.status_results = [
        status_response(progress()),
        status_response(progress()),
    ]
    costs = iter((15, 30))
    runner = IndependentTrainingRunner(
        store,
        client_provider=lambda account: client,
        finalizer_provider=lambda account: FakeFinalizer(client),
        account_state_provider=lambda account: account_state,
        refresh_account=lambda account: None,
        recover_tp=lambda account: False,
        tp_cost_provider=lambda account: TpCostResolution(next(costs), "test"),
        clock=lambda: 100,
    )
    enqueue(store, count=2)

    runner.run_once("acct01")
    runner.run_once("acct01")

    assert [row["setup"]["use_tp"] for row in client.start_kwargs] == [15, 30]


def test_tp_cost_resolution_failure_stops_before_mutation(
    store,
    account_state,
):
    client = FakeClient()
    recover_calls = []
    runner = IndependentTrainingRunner(
        store,
        client_provider=lambda account: client,
        finalizer_provider=lambda account: FakeFinalizer(client),
        account_state_provider=lambda account: account_state,
        refresh_account=lambda account: None,
        recover_tp=lambda account: recover_calls.append(account),
        tp_cost_provider=lambda account: (_ for _ in ()).throw(
            TpCostResolutionError("master.mdb unavailable")
        ),
        clock=lambda: 100,
    )
    run = enqueue(store)[0]

    runner.run_once("acct01")

    latest = store.get(run["run_id"])
    assert latest["state"] == "NEEDS_ATTENTION"
    assert latest["start_attempted"] is False
    assert recover_calls == []
    assert client.start_calls == 0
    assert "master.mdb unavailable" in runner.snapshot()["tp_cost_error"]


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


def test_tp_wait_refreshes_stale_cache_before_committing_to_wait(
    store, harness, account_state,
):
    """account_state_provider is a passive local cache — it only updates as a
    side effect of unrelated API calls. Before parking in WAITING_FOR_TP,
    _prepare_tp must force a live refresh_account() so a stale cache (server
    already has enough TP) doesn't cause a needless wait."""
    runner, client, _, refresh_calls = harness
    enqueue(store, tp_mode="wait")
    account_state["tp_info"]["current_tp"] = 0

    def refresh_account(account):
        refresh_calls.append(account)
        account_state["tp_info"]["current_tp"] = 30  # server was already ready

    runner.refresh_account = refresh_account
    client.start_result = status_response(progress(end=3100))

    runner.run_once("acct01")

    assert refresh_calls == ["acct01"]
    assert runner.snapshot()["state"] == "RUNNING"


def test_tp_wait_schedules_next_check_at_regen_eta_not_fixed_poll(
    store, harness, account_state,
):
    """Once still short after a live refresh, the loop should sleep until TP
    is actually expected to regen (10 min/TP) instead of polling a fixed
    30s — the stale cache never updates between polls, so fixed polling was
    just spinning the CPU without ever learning TP had regenerated."""
    from career_bot.delay import compute_regen_wait_seconds

    runner, client, _, _ = harness
    enqueue(store, tp_mode="wait")
    account_state["tp_info"]["current_tp"] = 7
    client.status_results = [status_response()]

    runner.run_once("acct01")

    assert runner.snapshot()["state"] == "WAITING_FOR_TP"
    assert runner._tp_wait_override_sec == compute_regen_wait_seconds(30, 7)


@pytest.mark.parametrize("phase", ["start", "end", "finalize"])
def test_ambiguous_mutation_needs_attention(store, harness, phase):
    runner, client, _, _ = harness
    run = enqueue(store)[0]
    client.raise_at = phase
    client.status_results = [status_response(progress())]

    runner.run_once("acct01")

    assert store.get(run["run_id"])["state"] == "NEEDS_ATTENTION"


def test_lease_is_heartbeated_while_work_exists_and_released_when_idle(
    store,
    account_state,
):
    client = FakeClient()
    client.status_results = [status_response()]
    client.start_result = status_response(progress(end=3100))
    heartbeats = []
    releases = []
    runner = IndependentTrainingRunner(
        store,
        client_provider=lambda account: client,
        finalizer_provider=lambda account: FakeFinalizer(client),
        account_state_provider=lambda account: account_state,
        refresh_account=lambda account: None,
        recover_tp=lambda account: False,
        tp_cost_provider=lambda account: TpCostResolution(30, "base"),
        heartbeat_lease=lambda account: heartbeats.append(account),
        release_lease=lambda account: releases.append(account),
        clock=lambda: 100,
    )
    enqueue(store)

    runner.run_once("acct01")

    assert heartbeats == ["acct01"]
    assert releases == []
    assert runner.snapshot()["state"] == "RUNNING"

    store.transition(
        store.active_run("acct01")["run_id"],
        "FAILED",
        expected_version=store.active_run("acct01")["version"],
    )
    runner.run_once("acct01")

    assert heartbeats == ["acct01", "acct01"]
    assert releases == ["acct01"]


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


def orphan_load_info(*, card_id=100999, end=90):
    return {
        "playing_state": 1,
        "start_time": 10,
        "end_time": end,
        "single_mode_chara_light": {
            "card_id": card_id,
            "scenario_id": 4,
            "succession_trained_chara_id_1": 55,
            "succession_trained_chara_id_2": 66,
        },
    }


def orphan_harness(store, account_state, load_info):
    client = FakeClient()
    runner = IndependentTrainingRunner(
        store,
        client_provider=lambda account: client,
        finalizer_provider=lambda account: FakeFinalizer(client),
        account_state_provider=lambda account: account_state,
        refresh_account=lambda account: None,
        recover_tp=lambda account: True,
        tp_cost_provider=lambda account: TpCostResolution(30, "base"),
        load_progress_provider=lambda account: load_info,
        clock=lambda: 100,
    )
    return runner, client


def test_untracked_server_career_is_described_only_when_no_run_is_active(
    store,
    account_state,
):
    runner, _ = orphan_harness(store, account_state, orphan_load_info())

    summary = runner.describe_server_run("acct01")

    assert summary == {
        "card_id": 100999,
        "scenario_id": 4,
        "parent_id_1": 55,
        "parent_id_2": 66,
        "server_start_time": 10,
        "server_end_time": 90,
        "collectable": True,
    }

    enqueue(store)
    store.claim_next("acct01")
    assert runner.describe_server_run("acct01") is None


def test_adopting_a_server_career_collects_it_and_frees_the_slot(
    store,
    account_state,
):
    load_info = orphan_load_info()
    runner, client = orphan_harness(store, account_state, load_info)
    queued = enqueue(store)[0]

    adopted = runner.adopt_server_run("acct01")

    assert adopted["state"] == "RUNNING"
    assert adopted["setup"]["card_id"] == 100999
    assert adopted["setup"]["adopted_from_server"] is True
    assert store.active_run("acct01")["run_id"] == adopted["run_id"]
    assert store.list_events("acct01")[0]["event_type"] == "server_run_adopted"

    runner.run_once("acct01")

    assert store.get(adopted["run_id"])["state"] == "COMPLETED"
    assert client.calls == ["end", "progress_log", "finalize"]
    assert client.start_calls == 0
    assert store.get(queued["run_id"])["state"] == "QUEUED"


def test_adopting_is_rejected_while_a_local_run_is_active(store, account_state):
    runner, _ = orphan_harness(store, account_state, orphan_load_info())
    enqueue(store)
    store.claim_next("acct01")

    assert runner.adopt_server_run("acct01") is None


def test_adopting_without_a_server_career_returns_nothing(store, account_state):
    runner, _ = orphan_harness(store, account_state, {})

    assert runner.adopt_server_run("acct01") is None


def test_elapsed_window_is_confirmed_from_load_index_without_status_probe(
    store,
    account_state,
):
    load_info = orphan_load_info()
    runner, client = orphan_harness(store, account_state, load_info)
    adopted = runner.adopt_server_run("acct01")

    def explode():
        client.calls.append("status")
        raise RuntimeError("API error 217 on idle_single_mode/status")

    client.independent_training_status = explode

    runner.run_once("acct01")

    assert store.get(adopted["run_id"])["state"] == "COMPLETED"
    assert "status" not in client.calls
    assert client.calls == ["end", "progress_log", "finalize"]


def test_failed_status_probe_parks_the_run_instead_of_raising(store, harness):
    runner, client, _, _ = harness
    run = enqueue(store)[0]
    claimed = store.claim_next("acct01")
    running = store.transition(
        claimed["run_id"],
        "RUNNING",
        expected_version=claimed["version"],
        server_start_time=10,
        server_end_time=90,
    )
    assert running["state"] == "RUNNING"

    def explode():
        raise RuntimeError("API error 217 on idle_single_mode/status")

    client.independent_training_status = explode

    runner.run_once("acct01")

    parked = store.get(run["run_id"])
    assert parked["state"] == "NEEDS_ATTENTION"
    assert parked["error"].startswith("idle status probe failed:")
    assert "217" in parked["error"]
    assert client.end_calls == 0


def test_executor_thread_survives_an_escaping_api_error(store, harness):
    runner, client, _, _ = harness
    run = enqueue(store)[0]
    store.claim_next("acct01")

    def explode(account):
        raise RuntimeError("API error 217 on idle_single_mode/status")

    runner.run_once = explode
    runner._account = "acct01"
    runner.wake_wait = lambda timeout: runner._stop_event.set()
    runner._loop()

    parked = store.get(run["run_id"])
    assert parked["state"] == "NEEDS_ATTENTION"
