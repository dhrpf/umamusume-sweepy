import json

import pytest

from sweepy_jobs import LeaseConflict, OperationConflict, SweepyJobStore


class FakeClock:
    def __init__(self, value=1000.0):
        self.value = float(value)

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += float(seconds)


def test_workflow_lease_conflicts_per_account_but_not_across_accounts(tmp_path):
    store = SweepyJobStore(tmp_path / "jobs.sqlite3")
    first = store.acquire_workflow_lease(
        "alpha", owner="operation:one", workflow_type="career", ttl_seconds=300
    )
    other = store.acquire_workflow_lease(
        "beta", owner="operation:two", workflow_type="dailies", ttl_seconds=300
    )

    assert first["workflow_type"] == "career"
    assert other["account"] == "beta"
    with pytest.raises(LeaseConflict, match="alpha"):
        store.acquire_workflow_lease(
            "alpha", owner="operation:three", workflow_type="dailies", ttl_seconds=300
        )


def test_stale_workflow_lease_is_recoverable(tmp_path):
    clock = FakeClock()
    store = SweepyJobStore(tmp_path / "jobs.sqlite3", clock=clock)
    store.acquire_workflow_lease(
        "alpha", owner="operation:old", workflow_type="career", ttl_seconds=10
    )
    clock.advance(11)

    replacement = store.acquire_workflow_lease(
        "alpha", owner="operation:new", workflow_type="dailies", ttl_seconds=20
    )

    assert replacement["owner"] == "operation:new"
    assert store.get_workflow_lease("alpha")["workflow_type"] == "dailies"


def test_workflow_heartbeat_and_owner_safe_release(tmp_path):
    clock = FakeClock()
    store = SweepyJobStore(tmp_path / "jobs.sqlite3", clock=clock)
    original = store.acquire_workflow_lease(
        "alpha", owner="operation:one", workflow_type="career", ttl_seconds=10
    )
    clock.advance(5)

    refreshed = store.heartbeat_workflow_lease(
        "alpha", owner="operation:one", ttl_seconds=30
    )

    assert refreshed["expires_at"] > original["expires_at"]
    assert store.release_workflow_lease("alpha", owner="wrong-owner") is False
    assert store.release_workflow_lease("alpha", owner="operation:one") is True
    assert store.get_workflow_lease("alpha") is None


def test_mutation_lock_serializes_same_account_only(tmp_path):
    store = SweepyJobStore(tmp_path / "jobs.sqlite3")
    store.acquire_mutation_lock("alpha", owner="operation:one", ttl_seconds=30)
    store.acquire_mutation_lock("beta", owner="operation:two", ttl_seconds=30)

    with pytest.raises(LeaseConflict, match="alpha"):
        store.acquire_mutation_lock("alpha", owner="operation:three", ttl_seconds=30)

    assert store.release_mutation_lock("alpha", owner="wrong") is False
    assert store.release_mutation_lock("alpha", owner="operation:one") is True
    store.acquire_mutation_lock("alpha", owner="operation:three", ttl_seconds=30)


def test_completed_operation_replays_without_second_execution(tmp_path):
    store = SweepyJobStore(tmp_path / "jobs.sqlite3")
    started = store.begin_operation(
        operation_id="discord-message-1",
        account="alpha",
        action="run_dailies",
        arguments={"daily_shop": True},
    )
    assert started["created"] is True

    store.complete_operation(
        "discord-message-1", {"success": True, "status": {"running": True}}
    )
    replay = store.begin_operation(
        operation_id="discord-message-1",
        account="alpha",
        action="run_dailies",
        arguments={"daily_shop": True},
    )

    assert replay["created"] is False
    assert replay["operation"]["status"] == "completed"
    assert replay["operation"]["result"]["success"] is True


def test_operation_id_reuse_with_different_input_is_rejected(tmp_path):
    store = SweepyJobStore(tmp_path / "jobs.sqlite3")
    store.begin_operation(
        operation_id="same-id",
        account="alpha",
        action="run_dailies",
        arguments={"daily_shop": True},
    )

    with pytest.raises(OperationConflict, match="different arguments"):
        store.begin_operation(
            operation_id="same-id",
            account="alpha",
            action="run_dailies",
            arguments={"daily_shop": False},
        )
    with pytest.raises(OperationConflict, match="different account or action"):
        store.begin_operation(
            operation_id="same-id",
            account="beta",
            action="run_dailies",
            arguments={"daily_shop": True},
        )


def test_failed_operation_is_durable_and_replayed(tmp_path):
    database = tmp_path / "jobs.sqlite3"
    store = SweepyJobStore(database)
    store.begin_operation(
        operation_id="failed-id", account="alpha", action="launch_bot", arguments={}
    )
    store.fail_operation(
        "failed-id", {"success": False, "detail": "port occupied"}
    )

    replay = SweepyJobStore(database).begin_operation(
        operation_id="failed-id", account="alpha", action="launch_bot", arguments={}
    )

    assert replay["created"] is False
    assert replay["operation"]["status"] == "failed"
    assert replay["operation"]["result"]["detail"] == "port occupied"


def test_operation_storage_redacts_sensitive_fields(tmp_path):
    store = SweepyJobStore(tmp_path / "jobs.sqlite3")
    store.begin_operation(
        operation_id="safe-id",
        account="alpha",
        action="test_action",
        arguments={
            "safe": "visible",
            "sid": "placeholder",
            "viewer_id": "placeholder-id",
        },
    )
    store.complete_operation(
        "safe-id",
        {"success": True, "auth_key": "placeholder", "rows": [{"name": "ok"}]},
    )

    recent = store.recent_operations("alpha", limit=10)
    rendered = json.dumps(recent)

    assert recent[0]["arguments"]["safe"] == "visible"
    assert recent[0]["arguments"]["sid"] == "<redacted>"
    assert recent[0]["arguments"]["viewer_id"] == "<redacted>"
    assert recent[0]["result"]["auth_key"] == "<redacted>"
    assert "placeholder" not in rendered


def test_recorded_events_are_account_scoped(tmp_path):
    store = SweepyJobStore(tmp_path / "jobs.sqlite3")
    store.record_event("alpha", "bot_started", {"pid": 123})
    store.record_event("beta", "bot_started", {"pid": 456})
    store.record_event("alpha", "career_started", {"preset": "Medium Parent"})

    events = store.recent_events("alpha", limit=10)

    assert [row["event_type"] for row in events] == [
        "career_started",
        "bot_started",
    ]
    assert all(row["account"] == "alpha" for row in events)
