from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx


REPO_ROOT = Path(__file__).resolve().parent
ACCOUNTS_FILE = REPO_ROOT / "accounts.json"
METADATA_NAME = "supervisor.json"
LOG_NAME = "supervisor.log"
METADATA_VERSION = 1

_SENSITIVE_LOG_KEYS = (
    "auth_key",
    "authorization",
    "cookie",
    "device_id",
    "ip_address",
    "password",
    "raw_body",
    "refresh_token",
    "session_ticket",
    "sid",
    "steam_id",
    "steam_session_ticket",
    "token",
    "udid",
    "viewer_id",
)
_LOG_SECRET_PATTERN = re.compile(
    r"(?i)(?P<prefix>(?:[\"']?(?:"
    + "|".join(re.escape(key) for key in _SENSITIVE_LOG_KEYS)
    + r")[\"']?)\s*[:=]\s*)(?P<value>\"[^\"]*\"|'[^']*'|[^\s,}\]]+)"
)
_BEARER_PATTERN = re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]+")


def redact_log_line(line: str) -> str:
    def replace(match: re.Match[str]) -> str:
        value = match.group("value")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"\"", "'"}:
            replacement = f"{value[0]}<redacted>{value[-1]}"
        else:
            replacement = "<redacted>"
        return match.group("prefix") + replacement

    return _BEARER_PATTERN.sub(r"\1<redacted>", _LOG_SECRET_PATTERN.sub(replace, line))


def _default_process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _default_read_cmdline(pid: int) -> list[str]:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return []
    return [part.decode("utf-8", errors="replace") for part in raw.split(b"\0") if part]


def _default_api_probe(account: dict[str, Any]) -> dict[str, bool]:
    result = {
        "reachable": False,
        "logged_in": False,
        "career_running": False,
        "dailies_running": False,
    }
    base_url = f"http://127.0.0.1:{int(account['port'])}"
    try:
        with httpx.Client(base_url=base_url, timeout=1.5, trust_env=False) as client:
            session_response = client.get("/api/session")
            session_response.raise_for_status()
            session = session_response.json()
            if not isinstance(session, dict):
                return result
            result["reachable"] = True
            result["logged_in"] = bool(session.get("success"))

            try:
                career_response = client.get("/api/career/runner")
                career_response.raise_for_status()
                career = career_response.json()
                runner = career.get("runner") if isinstance(career, dict) else {}
                result["career_running"] = bool(
                    isinstance(runner, dict) and runner.get("running")
                )
            except (httpx.HTTPError, ValueError):
                pass

            try:
                dailies_response = client.get("/api/dailies/status")
                dailies_response.raise_for_status()
                dailies = dailies_response.json()
                status = dailies.get("status") if isinstance(dailies, dict) else {}
                result["dailies_running"] = bool(
                    (isinstance(dailies, dict) and dailies.get("running"))
                    or (isinstance(status, dict) and status.get("running"))
                )
            except (httpx.HTTPError, ValueError):
                pass
    except (httpx.HTTPError, ValueError):
        pass
    return result


class SweepySupervisor:
    """Own detached per-account launcher processes without arbitrary shell access."""

    def __init__(
        self,
        repo_root: str | Path = REPO_ROOT,
        accounts_file: str | Path = ACCOUNTS_FILE,
        python_executable: str | None = None,
        *,
        popen_factory: Callable[..., Any] = subprocess.Popen,
        api_probe: Callable[[dict[str, Any]], dict[str, bool]] = _default_api_probe,
        process_exists: Callable[[int], bool] = _default_process_exists,
        read_cmdline: Callable[[int], list[str]] = _default_read_cmdline,
        get_process_group: Callable[[int], int] = os.getpgid,
        kill_process_group: Callable[[int, int], None] = os.killpg,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.accounts_file = Path(accounts_file).resolve()
        self.python_executable = python_executable or sys.executable
        self.popen_factory = popen_factory
        self.api_probe = api_probe
        self.process_exists = process_exists
        self.read_cmdline = read_cmdline
        self.get_process_group = get_process_group
        self.kill_process_group = kill_process_group
        self.sleep = sleep
        self.monotonic = monotonic

    @property
    def launcher_path(self) -> Path:
        return self.repo_root / "launcher.py"

    def _accounts(self) -> list[dict[str, Any]]:
        try:
            raw = json.loads(self.accounts_file.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise RuntimeError(f"Sweepy accounts file not found: {self.accounts_file}") from exc
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"Cannot read Sweepy accounts file: {self.accounts_file}") from exc
        if not isinstance(raw, list):
            raise RuntimeError("accounts.json must contain a JSON array")

        accounts: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in raw:
            if not isinstance(row, dict) or not row.get("enabled", True):
                continue
            name = str(row.get("name") or "").strip()
            try:
                port = int(row.get("port") or 0)
            except (TypeError, ValueError):
                port = 0
            if not name or name in {".", ".."} or "/" in name or "\\" in name:
                raise RuntimeError("Each enabled Sweepy account needs a safe non-empty name")
            if port <= 0 or port > 65535:
                raise RuntimeError(f"Sweepy account {name} has an invalid port")
            if name in seen:
                raise RuntimeError(f"Duplicate Sweepy account name: {name}")
            seen.add(name)
            item = dict(row)
            item["name"] = name
            item["port"] = port
            accounts.append(item)
        return accounts

    def account_config(self, account: str) -> dict[str, Any]:
        requested = str(account or "").strip()
        row = next((item for item in self._accounts() if item["name"] == requested), None)
        if row is None:
            available = ", ".join(item["name"] for item in self._accounts()) or "none"
            raise ValueError(
                f"Unknown Sweepy account: {requested or '<empty>'}. Available accounts: {available}"
            )
        return row

    def runtime_dir(self, account: str) -> Path:
        config = self.account_config(account)
        return self.repo_root / "uma_runtime" / config["name"]

    def metadata_path(self, account: str) -> Path:
        return self.runtime_dir(account) / METADATA_NAME

    def log_path(self, account: str) -> Path:
        return self.runtime_dir(account) / LOG_NAME

    def _read_metadata(self, account: str) -> dict[str, Any] | None:
        path = self.metadata_path(account)
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._remove_metadata(account)
            return None
        return value if isinstance(value, dict) else None

    def _write_metadata(self, account: str, metadata: dict[str, Any]) -> None:
        path = self.metadata_path(account)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)

    def _remove_metadata(self, account: str) -> None:
        try:
            self.metadata_path(account).unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass

    def _launcher_cmdline_matches(self, account: str, cmdline: list[str]) -> bool:
        expected = self.launcher_path.resolve()
        for index, value in enumerate(cmdline):
            try:
                candidate = Path(value).resolve()
            except (OSError, ValueError):
                continue
            if candidate == expected:
                return index + 1 < len(cmdline) and cmdline[index + 1] == account
        return False

    def _owned_metadata(self, account: str) -> dict[str, Any] | None:
        metadata = self._read_metadata(account)
        if not metadata:
            return None
        try:
            pid = int(metadata.get("pid") or 0)
            process_group_id = int(metadata.get("process_group_id") or 0)
        except (TypeError, ValueError):
            self._remove_metadata(account)
            return None
        if (
            metadata.get("version") != METADATA_VERSION
            or metadata.get("account") != account
            or pid <= 0
            or process_group_id <= 0
            or not self.process_exists(pid)
            or not self._launcher_cmdline_matches(account, self.read_cmdline(pid))
        ):
            self._remove_metadata(account)
            return None
        try:
            if int(self.get_process_group(pid)) != process_group_id:
                self._remove_metadata(account)
                return None
        except (OSError, ProcessLookupError, PermissionError, ValueError):
            self._remove_metadata(account)
            return None
        return metadata

    def _frida_remote_configured(self, config: dict[str, Any]) -> bool:
        extra_env = config.get("extra_env") if isinstance(config.get("extra_env"), dict) else {}
        return bool(
            extra_env.get("FRIDA_REMOTE")
            or os.environ.get("SWEEPY_FRIDA_REMOTE")
            or os.environ.get("FRIDA_REMOTE")
        )

    def status(self, account: str) -> dict[str, Any]:
        config = self.account_config(account)
        metadata = self._owned_metadata(account)
        api = self.api_probe(config)
        api_status = {
            "reachable": bool(api.get("reachable")),
            "logged_in": bool(api.get("logged_in")),
            "career_running": bool(api.get("career_running")),
            "dailies_running": bool(api.get("dailies_running")),
        }
        return {
            "account": config["name"],
            "port": int(config["port"]),
            "process": {
                "managed": metadata is not None,
                "running": metadata is not None,
                "pid": int(metadata["pid"]) if metadata else None,
                "started_at": metadata.get("started_at") if metadata else None,
            },
            "api": api_status,
            "externally_managed": bool(api_status["reachable"] and metadata is None),
            "frida_remote_configured": self._frida_remote_configured(config),
            "log_path": str(self.log_path(account)),
        }

    def launch(self, account: str) -> dict[str, Any]:
        config = self.account_config(account)
        runtime = self.status(account)
        if runtime["process"]["running"] or runtime["api"]["reachable"]:
            return {
                "success": True,
                "already_running": True,
                "runtime": runtime,
            }

        runtime_dir = self.runtime_dir(account)
        runtime_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.log_path(account)
        environment = os.environ.copy()
        remote = environment.get("SWEEPY_FRIDA_REMOTE")
        if remote and not environment.get("FRIDA_REMOTE"):
            environment["FRIDA_REMOTE"] = remote
        extra_env = config.get("extra_env") if isinstance(config.get("extra_env"), dict) else {}
        environment.update({str(key): str(value) for key, value in extra_env.items()})
        environment["SWEEPY_SUPERVISED"] = "1"

        command = [
            self.python_executable,
            str(self.launcher_path),
            config["name"],
        ]
        log_handle = log_path.open("a", encoding="utf-8", buffering=1)
        os.chmod(log_path, 0o600)
        try:
            process = self.popen_factory(
                command,
                cwd=str(self.repo_root),
                env=environment,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
                close_fds=True,
            )
        finally:
            log_handle.close()

        pid = int(process.pid)
        try:
            process_group_id = int(self.get_process_group(pid))
        except (OSError, ProcessLookupError, PermissionError, ValueError):
            process_group_id = pid
        started_at = datetime.now(timezone.utc).isoformat()
        metadata = {
            "version": METADATA_VERSION,
            "account": config["name"],
            "port": int(config["port"]),
            "pid": pid,
            "process_group_id": process_group_id,
            "started_at": started_at,
            "command": command,
            "log_path": str(log_path),
        }
        self._write_metadata(account, metadata)
        return {
            "success": True,
            "already_running": False,
            "runtime": {
                "account": config["name"],
                "port": int(config["port"]),
                "process": {
                    "managed": True,
                    "running": True,
                    "pid": pid,
                    "started_at": started_at,
                },
                "api": {
                    "reachable": False,
                    "logged_in": False,
                    "career_running": False,
                    "dailies_running": False,
                },
                "externally_managed": False,
                "frida_remote_configured": self._frida_remote_configured(config),
                "log_path": str(log_path),
            },
        }

    def _wait_for_exit(self, pid: int, timeout_seconds: float) -> bool:
        deadline = self.monotonic() + max(0.0, float(timeout_seconds))
        while self.process_exists(pid):
            if self.monotonic() >= deadline:
                return False
            self.sleep(min(0.1, max(0.0, deadline - self.monotonic())))
        return True

    def stop(
        self,
        account: str,
        *,
        timeout_seconds: float = 10,
        force: bool = False,
    ) -> dict[str, Any]:
        self.account_config(account)
        metadata = self._owned_metadata(account)
        if metadata is None:
            runtime = self.status(account)
            return {
                "success": False,
                "stopped": False,
                "forced": False,
                "detail": "Bot process is not managed by Sweepy supervisor",
                "runtime": runtime,
            }

        pid = int(metadata["pid"])
        process_group_id = int(metadata["process_group_id"])
        try:
            self.kill_process_group(process_group_id, signal.SIGTERM)
        except ProcessLookupError:
            self._remove_metadata(account)
            return {
                "success": True,
                "stopped": True,
                "forced": False,
                "runtime": self.status(account),
            }
        except (PermissionError, OSError) as exc:
            return {
                "success": False,
                "stopped": False,
                "forced": False,
                "detail": f"Failed to stop managed bot process: {exc}",
            }

        if self._wait_for_exit(pid, timeout_seconds):
            self._remove_metadata(account)
            return {
                "success": True,
                "stopped": True,
                "forced": False,
                "runtime": self.status(account),
            }

        owned_after_grace = self._owned_metadata(account)
        if owned_after_grace is None:
            return {
                "success": True,
                "stopped": True,
                "forced": False,
                "runtime": self.status(account),
            }
        if not force:
            return {
                "success": False,
                "stopped": False,
                "forced": False,
                "needs_force": True,
                "detail": "Bot did not stop within the grace period",
                "runtime": self.status(account),
            }

        try:
            self.kill_process_group(process_group_id, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except (PermissionError, OSError) as exc:
            return {
                "success": False,
                "stopped": False,
                "forced": False,
                "detail": f"Failed to force-stop managed bot process: {exc}",
            }
        self._wait_for_exit(pid, 2)
        if self.process_exists(pid):
            return {
                "success": False,
                "stopped": False,
                "forced": True,
                "detail": "Managed bot process is still alive after SIGKILL",
            }
        self._remove_metadata(account)
        return {
            "success": True,
            "stopped": True,
            "forced": True,
            "runtime": self.status(account),
        }

    def restart(
        self,
        account: str,
        *,
        timeout_seconds: float = 10,
        force: bool = False,
    ) -> dict[str, Any]:
        runtime = self.status(account)
        if runtime["process"]["running"]:
            stopped = self.stop(
                account,
                timeout_seconds=timeout_seconds,
                force=force,
            )
            if not stopped.get("success"):
                return {
                    "success": False,
                    "detail": stopped.get("detail") or "Failed to stop bot before restart",
                    "stop": stopped,
                }
        elif runtime["api"]["reachable"]:
            return {
                "success": False,
                "detail": "Bot API is reachable but the process is not managed by Sweepy supervisor",
                "runtime": runtime,
            }
        launched = self.launch(account)
        return {
            "success": bool(launched.get("success")),
            "restarted": bool(launched.get("success")),
            "launch": launched,
        }

    def wait_until_ready(
        self,
        account: str,
        *,
        timeout_seconds: float = 30,
        require_login: bool = False,
        poll_interval: float = 0.5,
    ) -> dict[str, Any]:
        timeout_seconds = max(0.0, min(float(timeout_seconds), 300.0))
        poll_interval = max(0.05, min(float(poll_interval), 5.0))
        deadline = self.monotonic() + timeout_seconds
        last_runtime = self.status(account)
        while True:
            ready = bool(last_runtime["api"]["reachable"])
            if require_login:
                ready = ready and bool(last_runtime["api"]["logged_in"])
            if ready:
                return {
                    "success": True,
                    "ready": True,
                    "runtime": last_runtime,
                }
            if self.monotonic() >= deadline:
                return {
                    "success": False,
                    "ready": False,
                    "detail": "Timed out waiting for Sweepy bot readiness",
                    "runtime": last_runtime,
                }
            self.sleep(min(poll_interval, max(0.0, deadline - self.monotonic())))
            last_runtime = self.status(account)

    def tail_logs(
        self,
        account: str,
        *,
        lines: int = 100,
        max_bytes: int = 65536,
    ) -> dict[str, Any]:
        self.account_config(account)
        line_limit = max(1, min(int(lines), 500))
        byte_limit = max(1024, min(int(max_bytes), 1024 * 1024))
        path = self.log_path(account)
        if not path.exists():
            return {
                "success": True,
                "account": account,
                "lines": [],
                "log_path": str(path),
            }
        try:
            with path.open("rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(0, size - byte_limit))
                payload = handle.read(byte_limit)
        except OSError as exc:
            return {
                "success": False,
                "account": account,
                "detail": f"Cannot read supervisor log: {exc}",
                "lines": [],
            }
        rows = payload.decode("utf-8", errors="replace").splitlines()[-line_limit:]
        return {
            "success": True,
            "account": account,
            "lines": [redact_log_line(row) for row in rows],
            "log_path": str(path),
        }
