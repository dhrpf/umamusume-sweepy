import json
import os
import signal
import sys
import time
from pathlib import Path

import pytest

from sweepy_supervisor import SweepySupervisor


def write_accounts(path: Path):
    path.write_text(
        json.dumps(
            [
                {
                    "name": "acct1",
                    "port": 1616,
                    "extra_env": {"FRIDA_REMOTE": "127.0.0.1:27042"},
                },
                {"name": "acct2", "port": 1617},
            ]
        ),
        encoding="utf-8",
    )


class FakeProcess:
    def __init__(self, pid=4321):
        self.pid = pid


class Clock:
    def __init__(self):
        self.value = 0.0

    def monotonic(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


def make_supervisor(tmp_path, **overrides):
    accounts = tmp_path / "accounts.json"
    write_accounts(accounts)
    defaults = {
        "repo_root": tmp_path,
        "accounts_file": accounts,
        "python_executable": "/test/python",
        "api_probe": lambda account: {
            "reachable": False,
            "logged_in": False,
            "career_running": False,
            "dailies_running": False,
        },
        "process_exists": lambda pid: False,
        "read_cmdline": lambda pid: [],
        "get_process_group": lambda pid: pid,
        "kill_process_group": lambda pgid, sig: None,
        "sleep": lambda seconds: None,
        "monotonic": lambda: 0.0,
    }
    defaults.update(overrides)
    return SweepySupervisor(**defaults)


def test_unknown_account_is_rejected(tmp_path):
    supervisor = make_supervisor(tmp_path)

    with pytest.raises(ValueError, match="Unknown Sweepy account"):
        supervisor.status("missing")


def test_status_removes_stale_metadata_without_signaling(tmp_path):
    supervisor = make_supervisor(tmp_path)
    runtime_dir = tmp_path / "uma_runtime" / "acct1"
    runtime_dir.mkdir(parents=True)
    metadata_path = runtime_dir / "supervisor.json"
    metadata_path.write_text(
        json.dumps(
            {
                "version": 1,
                "account": "acct1",
                "pid": 555,
                "process_group_id": 555,
                "started_at": "2026-07-14T00:00:00+00:00",
                "command": ["/test/python", str(tmp_path / "launcher.py"), "acct1"],
            }
        ),
        encoding="utf-8",
    )

    status = supervisor.status("acct1")

    assert status["process"] == {
        "managed": False,
        "running": False,
        "pid": None,
        "started_at": None,
    }
    assert status["api"]["reachable"] is False
    assert not metadata_path.exists()


def test_launch_starts_detached_launcher_and_writes_safe_metadata(tmp_path):
    calls = []

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return FakeProcess(4321)

    supervisor = make_supervisor(tmp_path, popen_factory=fake_popen)

    result = supervisor.launch("acct1")

    assert result["success"] is True
    assert result["already_running"] is False
    command, kwargs = calls[0]
    assert command == ["/test/python", str(tmp_path / "launcher.py"), "acct1"]
    assert kwargs["cwd"] == str(tmp_path)
    assert kwargs["start_new_session"] is True
    assert kwargs["stderr"] == -2
    assert kwargs["env"]["FRIDA_REMOTE"] == "127.0.0.1:27042"
    assert kwargs["env"]["SWEEPY_SUPERVISED"] == "1"

    metadata_path = tmp_path / "uma_runtime" / "acct1" / "supervisor.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["pid"] == 4321
    assert metadata["process_group_id"] == 4321
    assert metadata["account"] == "acct1"
    rendered = json.dumps(metadata)
    assert "FRIDA_REMOTE" not in rendered
    assert "auth" not in rendered.lower()


def test_launch_does_not_duplicate_an_externally_running_api(tmp_path):
    calls = []
    supervisor = make_supervisor(
        tmp_path,
        popen_factory=lambda *args, **kwargs: calls.append((args, kwargs)),
        api_probe=lambda account: {
            "reachable": True,
            "logged_in": True,
            "career_running": False,
            "dailies_running": False,
        },
    )

    result = supervisor.launch("acct1")

    assert result["success"] is True
    assert result["already_running"] is True
    assert result["runtime"]["process"]["managed"] is False
    assert result["runtime"]["api"]["reachable"] is True
    assert calls == []


def test_stop_signals_only_an_owned_launcher_process_group(tmp_path):
    alive = {4321: True}
    signals = []
    launcher_path = str(tmp_path / "launcher.py")

    def process_exists(pid):
        return alive.get(pid, False)

    def killpg(pgid, sig):
        signals.append((pgid, sig))
        if sig == signal.SIGTERM:
            alive[4321] = False

    supervisor = make_supervisor(
        tmp_path,
        process_exists=process_exists,
        read_cmdline=lambda pid: ["/test/python", launcher_path, "acct1"],
        get_process_group=lambda pid: 4321,
        kill_process_group=killpg,
    )
    supervisor._write_metadata(
        "acct1",
        {
            "version": 1,
            "account": "acct1",
            "pid": 4321,
            "process_group_id": 4321,
            "started_at": "2026-07-14T00:00:00+00:00",
            "command": ["/test/python", launcher_path, "acct1"],
        },
    )

    result = supervisor.stop("acct1", timeout_seconds=1)

    assert result["success"] is True
    assert result["stopped"] is True
    assert signals == [(4321, signal.SIGTERM)]
    assert not supervisor.metadata_path("acct1").exists()


def test_stop_refuses_to_signal_reused_or_unowned_pid(tmp_path):
    signals = []
    supervisor = make_supervisor(
        tmp_path,
        process_exists=lambda pid: True,
        read_cmdline=lambda pid: ["/usr/bin/python", "/other/program.py"],
        get_process_group=lambda pid: pid,
        kill_process_group=lambda pgid, sig: signals.append((pgid, sig)),
    )
    supervisor._write_metadata(
        "acct1",
        {
            "version": 1,
            "account": "acct1",
            "pid": 4321,
            "process_group_id": 4321,
            "started_at": "2026-07-14T00:00:00+00:00",
            "command": ["/test/python", str(tmp_path / "launcher.py"), "acct1"],
        },
    )

    result = supervisor.stop("acct1")

    assert result["success"] is False
    assert "not managed" in result["detail"].lower()
    assert signals == []
    assert not supervisor.metadata_path("acct1").exists()


def test_force_stop_escalates_after_grace_period(tmp_path):
    alive = {4321: True}
    signals = []
    clock = Clock()
    launcher_path = str(tmp_path / "launcher.py")

    def killpg(pgid, sig):
        signals.append((pgid, sig))
        if sig == signal.SIGKILL:
            alive[4321] = False

    supervisor = make_supervisor(
        tmp_path,
        process_exists=lambda pid: alive.get(pid, False),
        read_cmdline=lambda pid: ["/test/python", launcher_path, "acct1"],
        get_process_group=lambda pid: 4321,
        kill_process_group=killpg,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    supervisor._write_metadata(
        "acct1",
        {
            "version": 1,
            "account": "acct1",
            "pid": 4321,
            "process_group_id": 4321,
            "started_at": "2026-07-14T00:00:00+00:00",
            "command": ["/test/python", launcher_path, "acct1"],
        },
    )

    result = supervisor.stop("acct1", timeout_seconds=1, force=True)

    assert result["success"] is True
    assert result["forced"] is True
    assert signals == [(4321, signal.SIGTERM), (4321, signal.SIGKILL)]


def test_tail_logs_caps_lines_and_redacts_sensitive_values(tmp_path):
    supervisor = make_supervisor(tmp_path)
    log_path = supervisor.log_path("acct1")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        "first\n"
        'sid="secret-sid" viewer_id=1234567890123\n'
        'steam_session_ticket: very-secret-ticket\n'
        "last\n",
        encoding="utf-8",
    )

    result = supervisor.tail_logs("acct1", lines=3)

    assert result["success"] is True
    assert result["lines"] == [
        'sid="<redacted>" viewer_id=<redacted>',
        "steam_session_ticket: <redacted>",
        "last",
    ]
    assert "secret-sid" not in repr(result)
    assert "very-secret-ticket" not in repr(result)


def test_detached_launcher_process_can_be_started_logged_and_stopped(tmp_path):
    accounts = tmp_path / "accounts.json"
    accounts.write_text(
        json.dumps([{"name": "acct1", "port": 1616}]),
        encoding="utf-8",
    )
    (tmp_path / "launcher.py").write_text(
        "import signal, sys, time\n"
        "running = True\n"
        "def stop(*_args):\n"
        "    global running\n"
        "    running = False\n"
        "signal.signal(signal.SIGTERM, stop)\n"
        "print('DUMMY_READY', flush=True)\n"
        "while running:\n"
        "    time.sleep(0.05)\n"
        "print('DUMMY_STOPPED', flush=True)\n",
        encoding="utf-8",
    )
    supervisor = SweepySupervisor(
        repo_root=tmp_path,
        accounts_file=accounts,
        python_executable=sys.executable,
        api_probe=lambda account: {
            "reachable": False,
            "logged_in": False,
            "career_running": False,
            "dailies_running": False,
        },
    )

    launched = supervisor.launch("acct1")
    try:
        assert launched["success"] is True
        deadline = time.monotonic() + 3
        logs = {"lines": []}
        while time.monotonic() < deadline:
            logs = supervisor.tail_logs("acct1", lines=20)
            if "DUMMY_READY" in logs["lines"]:
                break
            time.sleep(0.05)
        assert "DUMMY_READY" in logs["lines"]
        assert supervisor.status("acct1")["process"]["running"] is True

        stopped = supervisor.stop("acct1", timeout_seconds=3)
        assert stopped["success"] is True
        assert stopped["stopped"] is True
        assert supervisor.status("acct1")["process"]["running"] is False
    finally:
        if supervisor.status("acct1")["process"]["running"]:
            supervisor.stop("acct1", timeout_seconds=0.2, force=True)


def test_wait_until_ready_polls_without_mutating_game_state(tmp_path):
    clock = Clock()
    probes = iter(
        [
            {
                "reachable": False,
                "logged_in": False,
                "career_running": False,
                "dailies_running": False,
            },
            {
                "reachable": True,
                "logged_in": False,
                "career_running": False,
                "dailies_running": False,
            },
            {
                "reachable": True,
                "logged_in": True,
                "career_running": False,
                "dailies_running": False,
            },
        ]
    )
    supervisor = make_supervisor(
        tmp_path,
        api_probe=lambda account: next(probes),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )

    result = supervisor.wait_until_ready(
        "acct1",
        timeout_seconds=5,
        require_login=True,
        poll_interval=1,
    )

    assert result["success"] is True
    assert result["ready"] is True
    assert result["runtime"]["api"]["logged_in"] is True
    assert clock.value == 2
