from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable


SENSITIVE_KEYS = {
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
}

MAX_JSON_BYTES = 64 * 1024


class LeaseConflict(RuntimeError):
    pass


class OperationConflict(RuntimeError):
    pass


def sanitize_for_storage(value: Any, key: str = "", depth: int = 0) -> Any:
    if key.lower() in SENSITIVE_KEYS:
        return "<redacted>"
    if depth >= 12:
        return "<max-depth>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= 4096 else value[:4096] + "…<truncated>"
    if isinstance(value, dict):
        items = list(value.items())[:250]
        result = {
            str(child_key): sanitize_for_storage(child_value, str(child_key), depth + 1)
            for child_key, child_value in items
        }
        if len(value) > len(items):
            result["<truncated_keys>"] = len(value) - len(items)
        return result
    if isinstance(value, (list, tuple, set, frozenset)):
        rows = list(value)
        result = [sanitize_for_storage(item, key, depth + 1) for item in rows[:250]]
        if len(rows) > len(result):
            result.append({"<truncated_items>": len(rows) - len(result)})
        return result
    return sanitize_for_storage(repr(value), key, depth + 1)


def _json_dumps(value: Any) -> str:
    safe = sanitize_for_storage(value)
    encoded = json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) <= MAX_JSON_BYTES:
        return encoded

    summary: dict[str, Any] = {"truncated": True, "type": type(safe).__name__}
    if isinstance(safe, dict):
        for field in ("success", "detail", "account", "action", "status"):
            if field in safe:
                summary[field] = safe[field]
    return json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_loads(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _arguments_hash(arguments_json: str) -> str:
    return hashlib.sha256(arguments_json.encode("utf-8")).hexdigest()


class SweepyJobStore:
    def __init__(
        self,
        database_path: str | Path,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock or time.time
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path,
            timeout=5.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS workflow_leases (
                    account TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    workflow_type TEXT NOT NULL,
                    heartbeat_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS mutation_locks (
                    account TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    acquired_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS operations (
                    operation_id TEXT PRIMARY KEY,
                    account TEXT NOT NULL,
                    action TEXT NOT NULL,
                    arguments_hash TEXT NOT NULL,
                    arguments_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    completed_at REAL,
                    result_json TEXT,
                    error_text TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_operations_account_started
                ON operations(account, started_at DESC);

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    operation_id TEXT,
                    created_at REAL NOT NULL,
                    data_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_events_account_created
                ON events(account, created_at DESC, id DESC);
                """
            )
        finally:
            connection.close()

    @staticmethod
    def _validate_identity(account: str, owner: str) -> tuple[str, str]:
        account = str(account or "").strip()
        owner = str(owner or "").strip()
        if not account:
            raise ValueError("account is required")
        if not owner:
            raise ValueError("owner is required")
        return account, owner

    @staticmethod
    def _validate_ttl(ttl_seconds: float) -> float:
        ttl = float(ttl_seconds)
        if ttl <= 0:
            raise ValueError("ttl_seconds must be positive")
        return ttl

    @staticmethod
    def _lease_from_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "account": row["account"],
            "owner": row["owner"],
            "workflow_type": row["workflow_type"],
            "heartbeat_at": float(row["heartbeat_at"]),
            "expires_at": float(row["expires_at"]),
            "metadata": _json_loads(row["metadata_json"]) or {},
        }

    def acquire_workflow_lease(
        self,
        account: str,
        *,
        owner: str,
        workflow_type: str,
        ttl_seconds: float,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        account, owner = self._validate_identity(account, owner)
        workflow_type = str(workflow_type or "").strip()
        if not workflow_type:
            raise ValueError("workflow_type is required")
        ttl = self._validate_ttl(ttl_seconds)
        now = float(self.clock())
        expires_at = now + ttl
        metadata_json = _json_dumps(metadata or {})

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM workflow_leases WHERE account=?",
                (account,),
            ).fetchone()
            if row is not None and float(row["expires_at"]) > now:
                if row["owner"] == owner and row["workflow_type"] == workflow_type:
                    connection.execute(
                        "UPDATE workflow_leases SET heartbeat_at=?, expires_at=?, metadata_json=? "
                        "WHERE account=?",
                        (now, expires_at, metadata_json, account),
                    )
                    connection.execute("COMMIT")
                    return {
                        "account": account,
                        "owner": owner,
                        "workflow_type": workflow_type,
                        "heartbeat_at": now,
                        "expires_at": expires_at,
                        "metadata": _json_loads(metadata_json) or {},
                    }
                raise LeaseConflict(
                    f"Account {account} already has active {row['workflow_type']} lease "
                    f"owned by {row['owner']}"
                )

            connection.execute("DELETE FROM workflow_leases WHERE account=?", (account,))
            connection.execute(
                "INSERT INTO workflow_leases "
                "(account, owner, workflow_type, heartbeat_at, expires_at, metadata_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (account, owner, workflow_type, now, expires_at, metadata_json),
            )
            connection.execute("COMMIT")
            return {
                "account": account,
                "owner": owner,
                "workflow_type": workflow_type,
                "heartbeat_at": now,
                "expires_at": expires_at,
                "metadata": _json_loads(metadata_json) or {},
            }
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def heartbeat_workflow_lease(
        self,
        account: str,
        *,
        owner: str,
        ttl_seconds: float,
    ) -> dict[str, Any]:
        account, owner = self._validate_identity(account, owner)
        ttl = self._validate_ttl(ttl_seconds)
        now = float(self.clock())
        expires_at = now + ttl
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM workflow_leases WHERE account=?",
                (account,),
            ).fetchone()
            if row is None or float(row["expires_at"]) <= now:
                connection.execute("DELETE FROM workflow_leases WHERE account=?", (account,))
                raise LeaseConflict(f"Account {account} has no active workflow lease")
            if row["owner"] != owner:
                raise LeaseConflict(
                    f"Account {account} workflow lease is owned by {row['owner']}"
                )
            connection.execute(
                "UPDATE workflow_leases SET heartbeat_at=?, expires_at=? WHERE account=?",
                (now, expires_at, account),
            )
            connection.execute("COMMIT")
            result = self._lease_from_row(row) or {}
            result.update(heartbeat_at=now, expires_at=expires_at)
            return result
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def get_workflow_lease(self, account: str) -> dict[str, Any] | None:
        account = str(account or "").strip()
        if not account:
            raise ValueError("account is required")
        now = float(self.clock())
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM workflow_leases WHERE account=?",
                (account,),
            ).fetchone()
            if row is not None and float(row["expires_at"]) <= now:
                connection.execute("DELETE FROM workflow_leases WHERE account=?", (account,))
                row = None
            connection.execute("COMMIT")
            return self._lease_from_row(row)
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def release_workflow_lease(
        self,
        account: str,
        *,
        owner: str | None = None,
        workflow_type: str | None = None,
    ) -> bool:
        account = str(account or "").strip()
        if not account:
            raise ValueError("account is required")
        clauses = ["account=?"]
        values: list[Any] = [account]
        if owner is not None:
            clauses.append("owner=?")
            values.append(str(owner))
        if workflow_type is not None:
            clauses.append("workflow_type=?")
            values.append(str(workflow_type))
        connection = self._connect()
        try:
            cursor = connection.execute(
                f"DELETE FROM workflow_leases WHERE {' AND '.join(clauses)}",
                values,
            )
            return cursor.rowcount > 0
        finally:
            connection.close()

    def acquire_mutation_lock(
        self,
        account: str,
        *,
        owner: str,
        ttl_seconds: float,
    ) -> dict[str, Any]:
        account, owner = self._validate_identity(account, owner)
        ttl = self._validate_ttl(ttl_seconds)
        now = float(self.clock())
        expires_at = now + ttl
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM mutation_locks WHERE account=?",
                (account,),
            ).fetchone()
            if row is not None and float(row["expires_at"]) > now:
                if row["owner"] == owner:
                    connection.execute(
                        "UPDATE mutation_locks SET expires_at=? WHERE account=?",
                        (expires_at, account),
                    )
                    connection.execute("COMMIT")
                    return {
                        "account": account,
                        "owner": owner,
                        "acquired_at": float(row["acquired_at"]),
                        "expires_at": expires_at,
                    }
                raise LeaseConflict(
                    f"Account {account} already has a mutation lock owned by {row['owner']}"
                )
            connection.execute("DELETE FROM mutation_locks WHERE account=?", (account,))
            connection.execute(
                "INSERT INTO mutation_locks (account, owner, acquired_at, expires_at) "
                "VALUES (?, ?, ?, ?)",
                (account, owner, now, expires_at),
            )
            connection.execute("COMMIT")
            return {
                "account": account,
                "owner": owner,
                "acquired_at": now,
                "expires_at": expires_at,
            }
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def release_mutation_lock(self, account: str, *, owner: str | None = None) -> bool:
        account = str(account or "").strip()
        if not account:
            raise ValueError("account is required")
        connection = self._connect()
        try:
            if owner is None:
                cursor = connection.execute(
                    "DELETE FROM mutation_locks WHERE account=?",
                    (account,),
                )
            else:
                cursor = connection.execute(
                    "DELETE FROM mutation_locks WHERE account=? AND owner=?",
                    (account, str(owner)),
                )
            return cursor.rowcount > 0
        finally:
            connection.close()

    @staticmethod
    def _operation_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "operation_id": row["operation_id"],
            "account": row["account"],
            "action": row["action"],
            "arguments": _json_loads(row["arguments_json"]) or {},
            "status": row["status"],
            "started_at": float(row["started_at"]),
            "updated_at": float(row["updated_at"]),
            "completed_at": (
                float(row["completed_at"]) if row["completed_at"] is not None else None
            ),
            "result": _json_loads(row["result_json"]),
            "error": row["error_text"] or "",
        }

    def begin_operation(
        self,
        *,
        operation_id: str,
        account: str,
        action: str,
        arguments: dict[str, Any] | None,
    ) -> dict[str, Any]:
        operation_id = str(operation_id or "").strip()
        account = str(account or "").strip()
        action = str(action or "").strip()
        if not operation_id:
            raise ValueError("operation_id is required")
        if not account:
            raise ValueError("account is required")
        if not action:
            raise ValueError("action is required")

        arguments_json = _json_dumps(arguments or {})
        digest = _arguments_hash(arguments_json)
        now = float(self.clock())
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM operations WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if row is not None:
                if row["account"] != account or row["action"] != action:
                    raise OperationConflict(
                        f"Operation ID {operation_id} was already used for a different account or action"
                    )
                if row["arguments_hash"] != digest:
                    raise OperationConflict(
                        f"Operation ID {operation_id} was already used with different arguments"
                    )
                connection.execute("COMMIT")
                return {"created": False, "operation": self._operation_from_row(row)}

            connection.execute(
                "INSERT INTO operations "
                "(operation_id, account, action, arguments_hash, arguments_json, status, "
                "started_at, updated_at) VALUES (?, ?, ?, ?, ?, 'in_progress', ?, ?)",
                (operation_id, account, action, digest, arguments_json, now, now),
            )
            connection.execute(
                "INSERT INTO events (account, event_type, operation_id, created_at, data_json) "
                "VALUES (?, 'operation_started', ?, ?, ?)",
                (account, operation_id, now, _json_dumps({"action": action})),
            )
            row = connection.execute(
                "SELECT * FROM operations WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            connection.execute("COMMIT")
            return {"created": True, "operation": self._operation_from_row(row)}
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def _finish_operation(
        self,
        operation_id: str,
        *,
        status: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        operation_id = str(operation_id or "").strip()
        if status not in {"completed", "failed"}:
            raise ValueError("invalid terminal operation status")
        now = float(self.clock())
        result_json = _json_dumps(result)
        error_text = ""
        safe_result = _json_loads(result_json)
        if status == "failed" and isinstance(safe_result, dict):
            error_text = str(safe_result.get("detail") or safe_result.get("error") or "")[:4096]

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM operations WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown operation ID: {operation_id}")
            if row["status"] in {"completed", "failed"}:
                connection.execute("COMMIT")
                return self._operation_from_row(row)
            connection.execute(
                "UPDATE operations SET status=?, updated_at=?, completed_at=?, "
                "result_json=?, error_text=? WHERE operation_id=?",
                (status, now, now, result_json, error_text, operation_id),
            )
            connection.execute(
                "INSERT INTO events (account, event_type, operation_id, created_at, data_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    row["account"],
                    f"operation_{status}",
                    operation_id,
                    now,
                    _json_dumps({"action": row["action"]}),
                ),
            )
            updated = connection.execute(
                "SELECT * FROM operations WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            connection.execute("COMMIT")
            return self._operation_from_row(updated)
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def complete_operation(
        self,
        operation_id: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        return self._finish_operation(operation_id, status="completed", result=result)

    def fail_operation(
        self,
        operation_id: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        return self._finish_operation(operation_id, status="failed", result=result)

    def recent_operations(self, account: str, *, limit: int = 20) -> list[dict[str, Any]]:
        account = str(account or "").strip()
        if not account:
            raise ValueError("account is required")
        limit = max(1, min(int(limit), 100))
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM operations WHERE account=? "
                "ORDER BY started_at DESC, operation_id DESC LIMIT ?",
                (account, limit),
            ).fetchall()
            return [self._operation_from_row(row) for row in rows]
        finally:
            connection.close()

    def record_event(
        self,
        account: str,
        event_type: str,
        data: dict[str, Any] | None = None,
        *,
        operation_id: str | None = None,
    ) -> dict[str, Any]:
        account = str(account or "").strip()
        event_type = str(event_type or "").strip()
        if not account or not event_type:
            raise ValueError("account and event_type are required")
        now = float(self.clock())
        data_json = _json_dumps(data or {})
        connection = self._connect()
        try:
            cursor = connection.execute(
                "INSERT INTO events (account, event_type, operation_id, created_at, data_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (account, event_type, operation_id, now, data_json),
            )
            return {
                "id": int(cursor.lastrowid),
                "account": account,
                "event_type": event_type,
                "operation_id": operation_id,
                "created_at": now,
                "data": _json_loads(data_json) or {},
            }
        finally:
            connection.close()

    def recent_events(self, account: str, *, limit: int = 50) -> list[dict[str, Any]]:
        account = str(account or "").strip()
        if not account:
            raise ValueError("account is required")
        limit = max(1, min(int(limit), 200))
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM events WHERE account=? "
                "ORDER BY created_at DESC, id DESC LIMIT ?",
                (account, limit),
            ).fetchall()
            return [
                {
                    "id": int(row["id"]),
                    "account": row["account"],
                    "event_type": row["event_type"],
                    "operation_id": row["operation_id"],
                    "created_at": float(row["created_at"]),
                    "data": _json_loads(row["data_json"]) or {},
                }
                for row in rows
            ]
        finally:
            connection.close()
