from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from sweepy_jobs import sanitize_for_storage

from .models import RunState, TpMode


class RunNotFound(LookupError):
    pass


class InvalidRunTransition(RuntimeError):
    pass


class RunVersionConflict(RuntimeError):
    pass


class PresetNotFound(LookupError):
    pass


_TERMINAL_STATES = {
    RunState.COMPLETED,
    RunState.FAILED,
    RunState.CANCELLED,
}
_ACTIVE_STATES = {
    RunState.STARTING,
    RunState.RUNNING,
    RunState.COLLECTING,
    RunState.FINALIZING,
    RunState.NEEDS_ATTENTION,
}
_TRANSITIONS = {
    RunState.QUEUED: {
        RunState.STARTING,
        RunState.CANCELLED,
        RunState.FAILED,
    },
    RunState.STARTING: {
        RunState.RUNNING,
        RunState.FAILED,
        RunState.NEEDS_ATTENTION,
    },
    RunState.RUNNING: {
        RunState.COLLECTING,
        RunState.FAILED,
        RunState.NEEDS_ATTENTION,
    },
    RunState.COLLECTING: {
        RunState.FINALIZING,
        RunState.NEEDS_ATTENTION,
    },
    RunState.FINALIZING: {
        RunState.COMPLETED,
        RunState.NEEDS_ATTENTION,
    },
    RunState.NEEDS_ATTENTION: {
        RunState.STARTING,
        RunState.RUNNING,
        RunState.COLLECTING,
        RunState.FINALIZING,
        RunState.FAILED,
        RunState.COMPLETED,
    },
    RunState.COMPLETED: set(),
    RunState.FAILED: set(),
    RunState.CANCELLED: set(),
}
_COLUMN_UPDATES = {
    "server_start_time": "server_start_time",
    "server_end_time": "server_end_time",
    "start_attempted": "start_attempted",
    "collection_attempted": "collection_attempted",
    "finalization": "finalization_json",
    "factor_lottery_attempted": "factor_lottery_attempted",
    "factor_candidates": "factor_candidates_json",
    "selected_lottery_id": "selected_lottery_id",
    "finish_attempted": "finish_attempted",
    "result": "result_json",
    "error": "error_text",
    "error_text": "error_text",
    "next_action": "next_action",
}
_JSON_UPDATE_KEYS = {
    "finalization",
    "factor_candidates",
    "result",
}
_BOOL_UPDATE_KEYS = {
    "start_attempted",
    "collection_attempted",
    "factor_lottery_attempted",
    "finish_attempted",
}


def _private_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _safe_value(value: Any) -> Any:
    def redact_viewer_ids(item: Any) -> Any:
        if isinstance(item, dict):
            return {
                str(key): (
                    "<redacted>"
                    if str(key).casefold().endswith("viewer_id")
                    else redact_viewer_ids(child)
                )
                for key, child in item.items()
            }
        if isinstance(item, (list, tuple)):
            return [redact_viewer_ids(child) for child in item]
        return item

    return sanitize_for_storage(redact_viewer_ids(value))


def _safe_json(value: Any) -> str:
    return _private_json(_safe_value(value))


def _load_json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _deep_merge(current: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    result = dict(current)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class IndependentTrainingStore:
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
        os.chmod(self.database_path, 0o600)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path,
            timeout=5.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS independent_runs (
                    run_id TEXT PRIMARY KEY,
                    account TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    setup_json TEXT NOT NULL,
                    tp_mode TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    server_start_time REAL,
                    server_end_time REAL,
                    start_attempted INTEGER NOT NULL DEFAULT 0,
                    collection_attempted INTEGER NOT NULL DEFAULT 0,
                    finalization_json TEXT NOT NULL DEFAULT '{}',
                    factor_lottery_attempted INTEGER NOT NULL DEFAULT 0,
                    factor_candidates_json TEXT NOT NULL DEFAULT '[]',
                    selected_lottery_id INTEGER,
                    finish_attempted INTEGER NOT NULL DEFAULT 0,
                    result_json TEXT NOT NULL DEFAULT '{}',
                    error_text TEXT NOT NULL DEFAULT '',
                    next_action TEXT NOT NULL DEFAULT ''
                );
                CREATE UNIQUE INDEX IF NOT EXISTS independent_runs_account_position
                ON independent_runs(account, position);
                CREATE INDEX IF NOT EXISTS independent_runs_account_state
                ON independent_runs(account, state, position);

                CREATE TABLE IF NOT EXISTS independent_controls (
                    account TEXT PRIMARY KEY,
                    stop_after_current INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS independent_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account TEXT NOT NULL,
                    run_id TEXT,
                    event_type TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    data_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS independent_events_account_created
                ON independent_events(account, created_at DESC, event_id DESC);

                CREATE TABLE IF NOT EXISTS independent_training_presets (
                    account TEXT NOT NULL,
                    name TEXT NOT NULL COLLATE NOCASE,
                    setup_json TEXT NOT NULL,
                    count INTEGER NOT NULL,
                    tp_mode TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (account, name)
                );
                CREATE INDEX IF NOT EXISTS independent_training_presets_account_updated
                ON independent_training_presets(account, updated_at DESC, name ASC);
                """
            )
        finally:
            connection.close()

    @staticmethod
    def _run_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "run_id": row["run_id"],
            "account": row["account"],
            "position": int(row["position"]),
            "state": row["state"],
            "version": int(row["version"]),
            "setup": _load_json(row["setup_json"], {}),
            "tp_mode": row["tp_mode"],
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
            "server_start_time": (
                float(row["server_start_time"])
                if row["server_start_time"] is not None
                else None
            ),
            "server_end_time": (
                float(row["server_end_time"])
                if row["server_end_time"] is not None
                else None
            ),
            "start_attempted": bool(row["start_attempted"]),
            "collection_attempted": bool(row["collection_attempted"]),
            "finalization": _load_json(row["finalization_json"], {}),
            "factor_lottery_attempted": bool(
                row["factor_lottery_attempted"]
            ),
            "factor_candidates": _load_json(
                row["factor_candidates_json"], []
            ),
            "selected_lottery_id": (
                int(row["selected_lottery_id"])
                if row["selected_lottery_id"] is not None
                else None
            ),
            "finish_attempted": bool(row["finish_attempted"]),
            "result": _load_json(row["result_json"], {}),
            "error": row["error_text"] or "",
            "next_action": row["next_action"] or "",
        }

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "event_id": int(row["event_id"]),
            "account": row["account"],
            "run_id": row["run_id"],
            "event_type": row["event_type"],
            "created_at": float(row["created_at"]),
            "data": _load_json(row["data_json"], {}),
        }

    @staticmethod
    def _preset_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "account": row["account"],
            "name": row["name"],
            "setup": _load_json(row["setup_json"], {}),
            "count": int(row["count"]),
            "tp_mode": row["tp_mode"],
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
        }

    @staticmethod
    def _normalize_account(account: str) -> str:
        normalized = str(account or "").strip()
        if not normalized:
            raise ValueError("account is required")
        return normalized

    @staticmethod
    def _normalize_preset_name(name: str) -> str:
        normalized = str(name or "").strip()
        if not normalized:
            raise ValueError("preset name is required")
        if len(normalized) > 80:
            raise ValueError("preset name must be at most 80 characters")
        return normalized

    @staticmethod
    def _rollback(connection: sqlite3.Connection) -> None:
        if connection.in_transaction:
            connection.execute("ROLLBACK")

    def enqueue(
        self,
        account: str,
        setup: dict[str, Any],
        *,
        count: int,
        tp_mode: str | TpMode,
    ) -> list[dict[str, Any]]:
        account = self._normalize_account(account)
        resolved_count = int(count)
        if resolved_count < 1 or resolved_count > 100:
            raise ValueError("count must be between 1 and 100")
        resolved_tp_mode = TpMode(tp_mode).value
        setup_json = _private_json(setup)
        now = float(self.clock())
        run_ids: list[str] = []

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT COALESCE(MAX(position), 0) AS position "
                "FROM independent_runs WHERE account=?",
                (account,),
            ).fetchone()
            position = int(row["position"])
            for index in range(resolved_count):
                run_id = str(uuid.uuid4())
                connection.execute(
                    "INSERT INTO independent_runs "
                    "(run_id, account, position, state, version, setup_json, "
                    "tp_mode, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)",
                    (
                        run_id,
                        account,
                        position + index + 1,
                        RunState.QUEUED.value,
                        setup_json,
                        resolved_tp_mode,
                        now,
                        now,
                    ),
                )
                run_ids.append(run_id)
            connection.execute("COMMIT")
        except Exception:
            self._rollback(connection)
            raise
        finally:
            connection.close()
        return [self.get(run_id) for run_id in run_ids]

    def adopt_server_run(
        self,
        account: str,
        setup: dict[str, Any],
        *,
        server_start_time: float,
        server_end_time: float,
        tp_mode: str | TpMode = TpMode.WAIT,
    ) -> dict[str, Any]:
        """Record a server-side run Sweepy never enqueued locally.

        The game only allows one idle single mode career at a time, so an
        orphan left over from a crashed session blocks every queued run with
        an error 102 on ``idle_single_mode/start``.  Adopting it inserts an
        already-RUNNING record whose setup mirrors the server, letting the
        normal collect/finalize path drain it.
        """
        account = self._normalize_account(account)
        resolved_tp_mode = TpMode(tp_mode).value
        now = float(self.clock())
        run_id = str(uuid.uuid4())
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            placeholders = ",".join("?" for _ in _ACTIVE_STATES)
            active = connection.execute(
                f"SELECT run_id FROM independent_runs WHERE account=? "
                f"AND state IN ({placeholders}) LIMIT 1",
                (account, *(state.value for state in _ACTIVE_STATES)),
            ).fetchone()
            if active is not None:
                raise InvalidRunTransition(
                    "Account already tracks an active Independent Training run"
                )
            row = connection.execute(
                "SELECT COALESCE(MAX(position), 0) AS position "
                "FROM independent_runs WHERE account=?",
                (account,),
            ).fetchone()
            connection.execute(
                "INSERT INTO independent_runs "
                "(run_id, account, position, state, version, setup_json, "
                "tp_mode, created_at, updated_at, server_start_time, "
                "server_end_time, start_attempted) "
                "VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, 1)",
                (
                    run_id,
                    account,
                    int(row["position"]) + 1,
                    RunState.RUNNING.value,
                    _private_json(setup),
                    resolved_tp_mode,
                    now,
                    now,
                    float(server_start_time),
                    float(server_end_time),
                ),
            )
            connection.execute("COMMIT")
        except Exception:
            self._rollback(connection)
            raise
        finally:
            connection.close()
        return self.get(run_id)

    def save_preset(
        self,
        account: str,
        name: str,
        setup: dict[str, Any],
        *,
        count: int,
        tp_mode: str | TpMode,
    ) -> dict[str, Any]:
        account = self._normalize_account(account)
        name = self._normalize_preset_name(name)
        resolved_count = int(count)
        if resolved_count < 1 or resolved_count > 100:
            raise ValueError("count must be between 1 and 100")
        resolved_tp_mode = TpMode(tp_mode).value
        now = float(self.clock())
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO independent_training_presets "
                "(account, name, setup_json, count, tp_mode, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(account, name) DO UPDATE SET "
                "name=excluded.name, setup_json=excluded.setup_json, "
                "count=excluded.count, tp_mode=excluded.tp_mode, "
                "updated_at=excluded.updated_at",
                (
                    account,
                    name,
                    _private_json(setup),
                    resolved_count,
                    resolved_tp_mode,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM independent_training_presets "
                "WHERE account=? AND name=?",
                (account, name),
            ).fetchone()
            connection.execute("COMMIT")
            return self._preset_from_row(row)
        except Exception:
            self._rollback(connection)
            raise
        finally:
            connection.close()

    def get_preset(self, account: str, name: str) -> dict[str, Any]:
        account = self._normalize_account(account)
        name = self._normalize_preset_name(name)
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM independent_training_presets "
                "WHERE account=? AND name=?",
                (account, name),
            ).fetchone()
            if row is None:
                raise PresetNotFound(
                    f"Independent Training preset not found: {name}"
                )
            return self._preset_from_row(row)
        finally:
            connection.close()

    def list_presets(self, account: str) -> list[dict[str, Any]]:
        account = self._normalize_account(account)
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM independent_training_presets WHERE account=? "
                "ORDER BY updated_at DESC, name ASC",
                (account,),
            ).fetchall()
            return [self._preset_from_row(row) for row in rows]
        finally:
            connection.close()

    def delete_preset(self, account: str, name: str) -> bool:
        account = self._normalize_account(account)
        name = self._normalize_preset_name(name)
        connection = self._connect()
        try:
            result = connection.execute(
                "DELETE FROM independent_training_presets WHERE account=? AND name=?",
                (account, name),
            )
            return result.rowcount > 0
        finally:
            connection.close()

    def get(self, run_id: str) -> dict[str, Any]:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM independent_runs WHERE run_id=?",
                (str(run_id),),
            ).fetchone()
            if row is None:
                raise RunNotFound(f"Independent run not found: {run_id}")
            return self._run_from_row(row)
        finally:
            connection.close()

    def list_runs(
        self,
        account: str,
        *,
        include_terminal: bool = True,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        account = self._normalize_account(account)
        resolved_limit = max(1, min(int(limit), 1000))
        params: list[Any] = [account]
        where = "account=?"
        if not include_terminal:
            placeholders = ",".join("?" for _ in _TERMINAL_STATES)
            where += f" AND state NOT IN ({placeholders})"
            params.extend(state.value for state in _TERMINAL_STATES)
        params.append(resolved_limit)
        connection = self._connect()
        try:
            rows = connection.execute(
                f"SELECT * FROM independent_runs WHERE {where} "
                "ORDER BY position ASC LIMIT ?",
                params,
            ).fetchall()
            return [self._run_from_row(row) for row in rows]
        finally:
            connection.close()

    def list_status_runs(
        self,
        account: str,
        *,
        completed_limit: int = 10,
    ) -> list[dict[str, Any]]:
        account = self._normalize_account(account)
        resolved_completed_limit = max(0, min(int(completed_limit), 100))
        terminal_states = tuple(state.value for state in _TERMINAL_STATES)
        terminal_placeholders = ",".join("?" for _ in terminal_states)
        connection = self._connect()
        try:
            rows = connection.execute(
                "WITH recent_completed AS ("
                "SELECT run_id FROM independent_runs "
                "WHERE account=? AND state=? "
                "ORDER BY position DESC LIMIT ?"
                ") "
                "SELECT * FROM independent_runs WHERE account=? AND ("
                f"state NOT IN ({terminal_placeholders}) "
                "OR run_id IN (SELECT run_id FROM recent_completed)"
                ") ORDER BY position ASC",
                (
                    account,
                    RunState.COMPLETED.value,
                    resolved_completed_limit,
                    account,
                    *terminal_states,
                ),
            ).fetchall()
            return [self._run_from_row(row) for row in rows]
        finally:
            connection.close()

    def active_run(self, account: str) -> dict[str, Any] | None:
        account = self._normalize_account(account)
        placeholders = ",".join("?" for _ in _ACTIVE_STATES)
        connection = self._connect()
        try:
            row = connection.execute(
                f"SELECT * FROM independent_runs WHERE account=? "
                f"AND state IN ({placeholders}) ORDER BY position ASC LIMIT 1",
                (account, *(state.value for state in _ACTIVE_STATES)),
            ).fetchone()
            return self._run_from_row(row) if row is not None else None
        finally:
            connection.close()

    def mark_stale_unconfirmed_starts(
        self,
        account: str,
        *,
        stale_after_seconds: float = 60,
    ) -> int:
        """Stop presenting abandoned local starts as active server runs."""
        account = self._normalize_account(account)
        cutoff = float(self.clock()) - max(0.0, float(stale_after_seconds))
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            result = connection.execute(
                "UPDATE independent_runs SET state=?, error_text=?, "
                "next_action=?, "
                "version=version+1, updated_at=? WHERE account=? "
                "AND state=? AND start_attempted=1 "
                "AND (server_start_time IS NULL OR server_start_time<=0) "
                "AND (server_end_time IS NULL OR server_end_time<=0) "
                "AND updated_at<=?",
                (
                    RunState.NEEDS_ATTENTION.value,
                    "unconfirmed start was abandoned; idle status was not queried",
                    "reconcile",
                    float(self.clock()),
                    account,
                    RunState.STARTING.value,
                    cutoff,
                ),
            )
            connection.execute("COMMIT")
            return int(result.rowcount)
        except Exception:
            self._rollback(connection)
            raise
        finally:
            connection.close()

    def claim_next(self, account: str) -> dict[str, Any] | None:
        account = self._normalize_account(account)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            placeholders = ",".join("?" for _ in _ACTIVE_STATES)
            active = connection.execute(
                f"SELECT * FROM independent_runs WHERE account=? "
                f"AND state IN ({placeholders}) ORDER BY position ASC LIMIT 1",
                (account, *(state.value for state in _ACTIVE_STATES)),
            ).fetchone()
            if active is not None:
                connection.execute("COMMIT")
                return self._run_from_row(active)
            row = connection.execute(
                "SELECT * FROM independent_runs WHERE account=? AND state=? "
                "ORDER BY position ASC LIMIT 1",
                (account, RunState.QUEUED.value),
            ).fetchone()
            if row is None:
                connection.execute("COMMIT")
                return None
            now = float(self.clock())
            connection.execute(
                "UPDATE independent_runs SET state=?, version=version+1, "
                "updated_at=? WHERE run_id=? AND version=?",
                (
                    RunState.STARTING.value,
                    now,
                    row["run_id"],
                    int(row["version"]),
                ),
            )
            updated = connection.execute(
                "SELECT * FROM independent_runs WHERE run_id=?",
                (row["run_id"],),
            ).fetchone()
            connection.execute("COMMIT")
            return self._run_from_row(updated)
        except Exception:
            self._rollback(connection)
            raise
        finally:
            connection.close()

    def transition(
        self,
        run_id: str,
        target: RunState | str,
        *,
        expected_version: int,
        **updates: Any,
    ) -> dict[str, Any]:
        target_state = RunState(target)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM independent_runs WHERE run_id=?",
                (str(run_id),),
            ).fetchone()
            if row is None:
                raise RunNotFound(f"Independent run not found: {run_id}")
            if int(row["version"]) != int(expected_version):
                raise RunVersionConflict(
                    f"Run {run_id} version changed from {expected_version}"
                )
            current = RunState(row["state"])
            if target_state not in _TRANSITIONS[current]:
                raise InvalidRunTransition(
                    f"Cannot transition {current.value} to {target_state.value}"
                )

            assignments = ["state=?", "version=version+1", "updated_at=?"]
            values: list[Any] = [
                target_state.value,
                float(self.clock()),
            ]
            for key, value in updates.items():
                column = _COLUMN_UPDATES.get(key)
                if column is None:
                    raise ValueError(f"Unsupported run update: {key}")
                if key in _JSON_UPDATE_KEYS:
                    value = _safe_json(value)
                elif key in _BOOL_UPDATE_KEYS:
                    value = int(bool(value))
                elif key in {"error", "error_text", "next_action"}:
                    value = str(_safe_value(value) or "")
                assignments.append(f"{column}=?")
                values.append(value)
            values.extend((str(run_id), int(expected_version)))
            cursor = connection.execute(
                f"UPDATE independent_runs SET {', '.join(assignments)} "
                "WHERE run_id=? AND version=?",
                values,
            )
            if cursor.rowcount != 1:
                raise RunVersionConflict(
                    f"Run {run_id} version changed from {expected_version}"
                )
            updated = connection.execute(
                "SELECT * FROM independent_runs WHERE run_id=?",
                (str(run_id),),
            ).fetchone()
            connection.execute("COMMIT")
            return self._run_from_row(updated)
        except Exception:
            self._rollback(connection)
            raise
        finally:
            connection.close()

    def _mark_flag(
        self,
        run_id: str,
        expected_version: int,
        column: str,
    ) -> dict[str, Any]:
        now = float(self.clock())
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                f"UPDATE independent_runs SET {column}=1, "
                "version=version+1, updated_at=? "
                f"WHERE run_id=? AND version=? AND {column}=0",
                (now, str(run_id), int(expected_version)),
            )
            if cursor.rowcount != 1:
                row = connection.execute(
                    "SELECT run_id FROM independent_runs WHERE run_id=?",
                    (str(run_id),),
                ).fetchone()
                if row is None:
                    raise RunNotFound(
                        f"Independent run not found: {run_id}"
                    )
                raise RunVersionConflict(
                    f"Run {run_id} marker or version changed"
                )
            updated = connection.execute(
                "SELECT * FROM independent_runs WHERE run_id=?",
                (str(run_id),),
            ).fetchone()
            connection.execute("COMMIT")
            return self._run_from_row(updated)
        except Exception:
            self._rollback(connection)
            raise
        finally:
            connection.close()

    def mark_start_attempted(
        self, run_id: str, expected_version: int
    ) -> dict[str, Any]:
        return self._mark_flag(run_id, expected_version, "start_attempted")

    def mark_collection_attempted(
        self, run_id: str, expected_version: int
    ) -> dict[str, Any]:
        return self._mark_flag(
            run_id, expected_version, "collection_attempted"
        )

    def mark_factor_lottery_attempted(
        self, run_id: str, expected_version: int
    ) -> dict[str, Any]:
        return self._mark_flag(
            run_id, expected_version, "factor_lottery_attempted"
        )

    def mark_finish_attempted(
        self, run_id: str, expected_version: int
    ) -> dict[str, Any]:
        return self._mark_flag(run_id, expected_version, "finish_attempted")

    def update_finalization(
        self,
        run_id: str,
        expected_version: int,
        progress: dict[str, Any],
    ) -> dict[str, Any]:
        current = self.get(run_id)
        merged = _deep_merge(current["finalization"], progress)
        return self._update_columns(
            run_id,
            expected_version,
            {"finalization_json": _safe_json(merged)},
        )

    def save_factor_candidates(
        self,
        run_id: str,
        expected_version: int,
        candidates: list[dict[str, Any]],
        selected_lottery_id: int | None = None,
    ) -> dict[str, Any]:
        columns: dict[str, Any] = {
            "factor_candidates_json": _safe_json(candidates)
        }
        if selected_lottery_id is not None:
            columns["selected_lottery_id"] = int(selected_lottery_id)
        return self._update_columns(run_id, expected_version, columns)

    def save_result(
        self,
        run_id: str,
        expected_version: int,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        return self._update_columns(
            run_id,
            expected_version,
            {"result_json": _safe_json(result)},
        )

    def _update_columns(
        self,
        run_id: str,
        expected_version: int,
        columns: dict[str, Any],
    ) -> dict[str, Any]:
        if not columns:
            return self.get(run_id)
        assignments = [
            *(f"{column}=?" for column in columns),
            "version=version+1",
            "updated_at=?",
        ]
        values = [
            *columns.values(),
            float(self.clock()),
            str(run_id),
            int(expected_version),
        ]
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                f"UPDATE independent_runs SET {', '.join(assignments)} "
                "WHERE run_id=? AND version=?",
                values,
            )
            if cursor.rowcount != 1:
                row = connection.execute(
                    "SELECT run_id FROM independent_runs WHERE run_id=?",
                    (str(run_id),),
                ).fetchone()
                if row is None:
                    raise RunNotFound(
                        f"Independent run not found: {run_id}"
                    )
                raise RunVersionConflict(
                    f"Run {run_id} version changed from {expected_version}"
                )
            updated = connection.execute(
                "SELECT * FROM independent_runs WHERE run_id=?",
                (str(run_id),),
            ).fetchone()
            connection.execute("COMMIT")
            return self._run_from_row(updated)
        except Exception:
            self._rollback(connection)
            raise
        finally:
            connection.close()

    def cancel_queued(self, run_id: str) -> dict[str, Any]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM independent_runs WHERE run_id=?",
                (str(run_id),),
            ).fetchone()
            if row is None:
                raise RunNotFound(f"Independent run not found: {run_id}")
            if row["state"] != RunState.QUEUED.value:
                raise InvalidRunTransition(
                    "Only queued Independent Training runs can be cancelled"
                )
            connection.execute(
                "UPDATE independent_runs SET state=?, version=version+1, "
                "updated_at=? WHERE run_id=?",
                (
                    RunState.CANCELLED.value,
                    float(self.clock()),
                    str(run_id),
                ),
            )
            updated = connection.execute(
                "SELECT * FROM independent_runs WHERE run_id=?",
                (str(run_id),),
            ).fetchone()
            connection.execute("COMMIT")
            return self._run_from_row(updated)
        except Exception:
            self._rollback(connection)
            raise
        finally:
            connection.close()

    def discard(self, run_id: str, *, reason: str = "") -> dict[str, Any]:
        """Force a stuck run into FAILED so the queue can move on.

        Reconciliation cannot always resolve an ambiguous server state (an
        error 102 on ``idle_single_mode/start`` leaves the run parked in
        NEEDS_ATTENTION forever).  Discarding drops only the local record;
        the server side, if any, is untouched.
        """
        message = str(reason).strip() or "discarded from dashboard"
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM independent_runs WHERE run_id=?",
                (str(run_id),),
            ).fetchone()
            if row is None:
                raise RunNotFound(f"Independent run not found: {run_id}")
            if row["state"] in {state.value for state in _TERMINAL_STATES}:
                raise InvalidRunTransition(
                    "Independent run already reached a terminal state: "
                    f"{row['state']}"
                )
            connection.execute(
                "UPDATE independent_runs SET state=?, error_text=?, "
                "next_action=?, version=version+1, updated_at=? "
                "WHERE run_id=?",
                (
                    RunState.FAILED.value,
                    message,
                    "",
                    float(self.clock()),
                    str(run_id),
                ),
            )
            updated = connection.execute(
                "SELECT * FROM independent_runs WHERE run_id=?",
                (str(run_id),),
            ).fetchone()
            connection.execute("COMMIT")
            return self._run_from_row(updated)
        except Exception:
            self._rollback(connection)
            raise
        finally:
            connection.close()

    def set_stop_after_current(
        self, account: str, value: bool
    ) -> dict[str, Any]:
        account = self._normalize_account(account)
        now = float(self.clock())
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO independent_controls "
                "(account, stop_after_current, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(account) DO UPDATE SET "
                "stop_after_current=excluded.stop_after_current, "
                "updated_at=excluded.updated_at",
                (account, int(bool(value)), now),
            )
            connection.execute("COMMIT")
        except Exception:
            self._rollback(connection)
            raise
        finally:
            connection.close()
        return self.get_control(account)

    def get_control(self, account: str) -> dict[str, Any]:
        account = self._normalize_account(account)
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM independent_controls WHERE account=?",
                (account,),
            ).fetchone()
            if row is None:
                return {
                    "account": account,
                    "stop_after_current": False,
                    "updated_at": None,
                }
            return {
                "account": account,
                "stop_after_current": bool(row["stop_after_current"]),
                "updated_at": float(row["updated_at"]),
            }
        finally:
            connection.close()

    def append_event(
        self,
        account: str,
        event_type: str,
        data: dict[str, Any],
        *,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        account = self._normalize_account(account)
        normalized_type = str(event_type or "").strip()
        if not normalized_type:
            raise ValueError("event_type is required")
        connection = self._connect()
        try:
            cursor = connection.execute(
                "INSERT INTO independent_events "
                "(account, run_id, event_type, created_at, data_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    account,
                    str(run_id) if run_id is not None else None,
                    normalized_type,
                    float(self.clock()),
                    _safe_json(data),
                ),
            )
            row = connection.execute(
                "SELECT * FROM independent_events WHERE event_id=?",
                (int(cursor.lastrowid),),
            ).fetchone()
            return self._event_from_row(row)
        finally:
            connection.close()

    def list_events(
        self,
        account: str,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        account = self._normalize_account(account)
        resolved_limit = max(1, min(int(limit), 500))
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM independent_events WHERE account=? "
                "ORDER BY created_at DESC, event_id DESC LIMIT ?",
                (account, resolved_limit),
            ).fetchall()
            return [self._event_from_row(row) for row in rows]
        finally:
            connection.close()
