from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from sweepy_jobs import sanitize_for_storage

from .models import CampaignState, ParentCampaignSpec


class CampaignError(RuntimeError):
    pass


class CampaignNotFound(CampaignError):
    pass


class InvalidTransition(CampaignError):
    pass


class BudgetExceeded(CampaignError):
    pass


TERMINAL_STATES = {
    CampaignState.COMPLETED,
    CampaignState.FAILED,
    CampaignState.CANCELLED,
}

ACTIVE_EXECUTION_STATES = {
    CampaignState.STARTING_BOT,
    CampaignState.WAITING_FOR_LOGIN,
    CampaignState.SELECTING_LINEAGE,
    CampaignState.RUNNING_CAREER,
    CampaignState.EVALUATING_RESULT,
    CampaignState.WAITING_FOR_TP,
    CampaignState.NEEDS_USER_INPUT,
}

# STARTING is a lease, not a permanent replay lock. Five minutes bounds crash recovery.
PREPARED_RUN_START_TIMEOUT_SECONDS = 300.0

ALLOWED_TRANSITIONS: dict[CampaignState, set[CampaignState]] = {
    CampaignState.DRAFT: {CampaignState.READY, CampaignState.CANCELLED},
    CampaignState.READY: {
        CampaignState.STARTING_BOT,
        CampaignState.PAUSED,
        CampaignState.CANCELLED,
        CampaignState.FAILED,
    },
    CampaignState.STARTING_BOT: {
        CampaignState.WAITING_FOR_LOGIN,
        CampaignState.SELECTING_LINEAGE,
        CampaignState.PAUSED,
        CampaignState.CANCELLED,
        CampaignState.FAILED,
    },
    CampaignState.WAITING_FOR_LOGIN: {
        CampaignState.SELECTING_LINEAGE,
        CampaignState.PAUSED,
        CampaignState.CANCELLED,
        CampaignState.FAILED,
    },
    CampaignState.SELECTING_LINEAGE: {
        CampaignState.RUNNING_CAREER,
        CampaignState.NEEDS_USER_INPUT,
        CampaignState.PAUSED,
        CampaignState.CANCELLED,
        CampaignState.FAILED,
    },
    CampaignState.RUNNING_CAREER: {
        CampaignState.EVALUATING_RESULT,
        CampaignState.WAITING_FOR_TP,
        CampaignState.PAUSED,
        CampaignState.CANCELLED,
        CampaignState.FAILED,
    },
    CampaignState.EVALUATING_RESULT: {
        CampaignState.SELECTING_LINEAGE,
        CampaignState.COMPLETED,
        CampaignState.NEEDS_USER_INPUT,
        CampaignState.WAITING_FOR_TP,
        CampaignState.PAUSED,
        CampaignState.CANCELLED,
        CampaignState.FAILED,
    },
    CampaignState.WAITING_FOR_TP: {
        CampaignState.RUNNING_CAREER,
        CampaignState.SELECTING_LINEAGE,
        CampaignState.PAUSED,
        CampaignState.CANCELLED,
        CampaignState.FAILED,
    },
    CampaignState.NEEDS_USER_INPUT: {
        CampaignState.SELECTING_LINEAGE,
        CampaignState.RUNNING_CAREER,
        CampaignState.COMPLETED,
        CampaignState.PAUSED,
        CampaignState.CANCELLED,
        CampaignState.FAILED,
    },
    CampaignState.PAUSED: set(),
    CampaignState.COMPLETED: set(),
    CampaignState.FAILED: set(),
    CampaignState.CANCELLED: set(),
}


def _json_dumps(value: Any) -> str:
    return json.dumps(
        sanitize_for_storage(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _json_loads(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _deep_merge(current: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    result = dict(current)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class CampaignStore:
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
                CREATE TABLE IF NOT EXISTS campaigns (
                    campaign_id TEXT PRIMARY KEY,
                    account TEXT NOT NULL,
                    state TEXT NOT NULL,
                    spec_json TEXT NOT NULL,
                    context_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    started_at REAL,
                    ended_at REAL,
                    paused_from_state TEXT NOT NULL DEFAULT '',
                    next_action TEXT NOT NULL DEFAULT '',
                    error_text TEXT NOT NULL DEFAULT '',
                    run_count INTEGER NOT NULL DEFAULT 0,
                    carats_used INTEGER NOT NULL DEFAULT 0,
                    clocks_used INTEGER NOT NULL DEFAULT 0,
                    selected_candidate_id TEXT NOT NULL DEFAULT '',
                    version INTEGER NOT NULL DEFAULT 1
                );

                CREATE INDEX IF NOT EXISTS idx_campaigns_account_updated
                ON campaigns(account, updated_at DESC);

                CREATE TABLE IF NOT EXISTS campaign_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    campaign_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    data_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(campaign_id) REFERENCES campaigns(campaign_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_campaign_events_created
                ON campaign_events(campaign_id, created_at DESC, id DESC);

                CREATE TABLE IF NOT EXISTS campaign_candidates (
                    candidate_id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL,
                    trained_chara_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    score REAL NOT NULL,
                    accepted INTEGER NOT NULL DEFAULT 0,
                    selected INTEGER NOT NULL DEFAULT 0,
                    evaluation_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    FOREIGN KEY(campaign_id) REFERENCES campaigns(campaign_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_campaign_candidates_score
                ON campaign_candidates(campaign_id, score DESC, created_at ASC);
                """
            )
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(campaigns)").fetchall()
            }
            if "context_json" not in columns:
                connection.execute(
                    "ALTER TABLE campaigns ADD COLUMN context_json TEXT NOT NULL DEFAULT '{}'"
                )
        finally:
            connection.close()

    @staticmethod
    def _campaign_from_row(row: sqlite3.Row) -> dict[str, Any]:
        spec = _json_loads(row["spec_json"]) or {}
        created_at = float(row["created_at"])
        started_at = float(row["started_at"]) if row["started_at"] is not None else None
        return {
            "campaign_id": row["campaign_id"],
            "account": row["account"],
            "state": row["state"],
            "spec": spec,
            "context": _json_loads(row["context_json"]) or {},
            "created_at": created_at,
            "updated_at": float(row["updated_at"]),
            "started_at": started_at,
            "ended_at": float(row["ended_at"]) if row["ended_at"] is not None else None,
            "paused_from_state": row["paused_from_state"] or "",
            "next_action": row["next_action"] or "",
            "error": row["error_text"] or "",
            "usage": {
                "runs": int(row["run_count"]),
                "carats": int(row["carats_used"]),
                "clocks": int(row["clocks_used"]),
            },
            "selected_candidate_id": row["selected_candidate_id"] or "",
            "version": int(row["version"]),
        }

    @staticmethod
    def _candidate_from_row(row: sqlite3.Row) -> dict[str, Any]:
        evaluation = _json_loads(row["evaluation_json"]) or {}
        return {
            "candidate_id": row["candidate_id"],
            "campaign_id": row["campaign_id"],
            "trained_chara_id": int(row["trained_chara_id"]),
            "name": row["name"],
            "score": float(row["score"]),
            "accepted": bool(row["accepted"]),
            "selected": bool(row["selected"]),
            "evaluation": evaluation,
            "created_at": float(row["created_at"]),
        }

    def _insert_event(
        self,
        connection: sqlite3.Connection,
        campaign_id: str,
        event_type: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        connection.execute(
            "INSERT INTO campaign_events (campaign_id, event_type, created_at, data_json) "
            "VALUES (?, ?, ?, ?)",
            (campaign_id, event_type, float(self.clock()), _json_dumps(data or {})),
        )

    @staticmethod
    def _assert_account_has_no_active_campaign(
        connection: sqlite3.Connection,
        *,
        account: str,
        campaign_id: str,
        target: CampaignState,
    ) -> None:
        if target not in ACTIVE_EXECUTION_STATES:
            return
        placeholders = ",".join("?" for _ in ACTIVE_EXECUTION_STATES)
        row = connection.execute(
            f"SELECT campaign_id FROM campaigns WHERE account=? AND campaign_id<>? "
            f"AND state IN ({placeholders}) LIMIT 1",
            (
                account,
                campaign_id,
                *(state.value for state in ACTIVE_EXECUTION_STATES),
            ),
        ).fetchone()
        if row is not None:
            raise CampaignError(
                f"Account {account} already has active campaign {row['campaign_id']}"
            )

    def create(
        self,
        spec: ParentCampaignSpec | dict[str, Any],
        *,
        campaign_id: str | None = None,
        initial_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        validated = ParentCampaignSpec.model_validate(spec)
        resolved_id = str(campaign_id or uuid.uuid4()).strip()
        if not resolved_id:
            raise ValueError("campaign_id is required")
        now = float(self.clock())
        spec_json = _json_dumps(validated.model_dump(mode="json"))
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO campaigns "
                "(campaign_id, account, state, spec_json, context_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    resolved_id,
                    validated.account,
                    CampaignState.DRAFT.value,
                    spec_json,
                    _json_dumps(initial_context or {}),
                    now,
                    now,
                ),
            )
            self._insert_event(
                connection,
                resolved_id,
                "campaign_created",
                {"account": validated.account},
            )
            connection.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise CampaignError(f"Campaign already exists: {resolved_id}") from exc
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()
        return self.get(resolved_id)

    def get(self, campaign_id: str) -> dict[str, Any]:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM campaigns WHERE campaign_id=?",
                (str(campaign_id),),
            ).fetchone()
            if row is None:
                raise CampaignNotFound(f"Campaign not found: {campaign_id}")
            return self._campaign_from_row(row)
        finally:
            connection.close()

    def set_next_action(
        self,
        campaign_id: str,
        next_action: str,
    ) -> dict[str, Any]:
        now = float(self.clock())
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM campaigns WHERE campaign_id=?",
                (str(campaign_id),),
            ).fetchone()
            if row is None:
                raise CampaignNotFound(f"Campaign not found: {campaign_id}")
            connection.execute(
                "UPDATE campaigns SET next_action=?, updated_at=?, version=version+1 "
                "WHERE campaign_id=?",
                (str(next_action or ""), now, str(campaign_id)),
            )
            self._insert_event(
                connection,
                str(campaign_id),
                "next_action_changed",
                {"next_action": str(next_action or "")},
            )
            updated = connection.execute(
                "SELECT * FROM campaigns WHERE campaign_id=?",
                (str(campaign_id),),
            ).fetchone()
            connection.execute("COMMIT")
            return self._campaign_from_row(updated)
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def update_context(
        self,
        campaign_id: str,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(updates, dict):
            raise ValueError("campaign context updates must be a dict")
        now = float(self.clock())
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM campaigns WHERE campaign_id=?",
                (str(campaign_id),),
            ).fetchone()
            if row is None:
                raise CampaignNotFound(f"Campaign not found: {campaign_id}")
            current = _json_loads(row["context_json"]) or {}
            merged = _deep_merge(current, sanitize_for_storage(updates))
            connection.execute(
                "UPDATE campaigns SET context_json=?, updated_at=?, version=version+1 "
                "WHERE campaign_id=?",
                (_json_dumps(merged), now, str(campaign_id)),
            )
            self._insert_event(
                connection,
                str(campaign_id),
                "context_updated",
                {"keys": sorted(str(key) for key in updates)},
            )
            updated = connection.execute(
                "SELECT * FROM campaigns WHERE campaign_id=?",
                (str(campaign_id),),
            ).fetchone()
            connection.execute("COMMIT")
            return self._campaign_from_row(updated)
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def append_event(
        self,
        campaign_id: str,
        event_type: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not str(event_type or "").strip():
            raise ValueError("event_type is required")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT campaign_id FROM campaigns WHERE campaign_id=?",
                (str(campaign_id),),
            ).fetchone()
            if row is None:
                raise CampaignNotFound(f"Campaign not found: {campaign_id}")
            self._insert_event(connection, str(campaign_id), str(event_type), data)
            event = connection.execute(
                "SELECT * FROM campaign_events WHERE campaign_id=? ORDER BY id DESC LIMIT 1",
                (str(campaign_id),),
            ).fetchone()
            connection.execute("COMMIT")
            return {
                "id": int(event["id"]),
                "campaign_id": event["campaign_id"],
                "event_type": event["event_type"],
                "created_at": float(event["created_at"]),
                "data": _json_loads(event["data_json"]) or {},
            }
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def reserve_prepared_run_start(
        self,
        campaign_id: str,
        operation_id: str,
        *,
        prepared_run: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        operation_id = str(operation_id or "").strip()
        if not operation_id:
            raise ValueError("operation_id is required")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM campaigns WHERE campaign_id=?",
                (str(campaign_id),),
            ).fetchone()
            if row is None:
                raise CampaignNotFound(f"Campaign not found: {campaign_id}")
            context = _json_loads(row["context_json"]) or {}
            current = context.get("run_start") if isinstance(context.get("run_start"), dict) else {}
            now = float(self.clock())
            status = current.get("status")
            reserved_at = current.get("reserved_at", row["updated_at"])
            stale_starting = (
                status == "STARTING"
                and isinstance(reserved_at, (int, float))
                and not isinstance(reserved_at, bool)
                and now - float(reserved_at) >= PREPARED_RUN_START_TIMEOUT_SECONDS
            )
            if status == "STARTED" or (status == "STARTING" and not stale_starting):
                connection.execute("COMMIT")
                return {"acquired": False, "run_start": current}
            run_start = {
                "operation_id": operation_id,
                "status": "STARTING",
                "reserved_at": now,
                "result": None,
                "error": "",
            }
            context["run_start"] = run_start
            if prepared_run is not None:
                context["prepared_run"] = prepared_run
            context["pending_review"] = None
            context["review_required"] = False
            connection.execute(
                "UPDATE campaigns SET context_json=?, updated_at=?, version=version+1 "
                "WHERE campaign_id=?",
                (_json_dumps(context), now, str(campaign_id)),
            )
            self._insert_event(
                connection,
                str(campaign_id),
                "prepared_run_start_reserved",
                {"operation_id": operation_id},
            )
            connection.execute("COMMIT")
            return {"acquired": True, "run_start": run_start}
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def finish_prepared_run_start(
        self,
        campaign_id: str,
        operation_id: str,
        *,
        status: str,
        result: Any = None,
        error: str = "",
    ) -> dict[str, Any]:
        if status not in {"STARTED", "FAILED"}:
            raise ValueError("run start status must be STARTED or FAILED")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM campaigns WHERE campaign_id=?",
                (str(campaign_id),),
            ).fetchone()
            if row is None:
                raise CampaignNotFound(f"Campaign not found: {campaign_id}")
            context = _json_loads(row["context_json"]) or {}
            current = context.get("run_start") if isinstance(context.get("run_start"), dict) else {}
            if current.get("operation_id") != str(operation_id):
                raise CampaignError("prepared run start operation changed")
            run_start = {
                "operation_id": str(operation_id),
                "status": status,
                "result": result if status == "STARTED" else None,
                "error": str(error or "") if status == "FAILED" else "",
            }
            context["run_start"] = run_start
            connection.execute(
                "UPDATE campaigns SET context_json=?, updated_at=?, version=version+1 "
                "WHERE campaign_id=?",
                (_json_dumps(context), float(self.clock()), str(campaign_id)),
            )
            self._insert_event(
                connection,
                str(campaign_id),
                "prepared_run_start_finished",
                {"operation_id": str(operation_id), "status": status, "error": run_start["error"]},
            )
            connection.execute("COMMIT")
            return run_start
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def list(self, *, account: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        connection = self._connect()
        try:
            if account:
                rows = connection.execute(
                    "SELECT * FROM campaigns WHERE account=? "
                    "ORDER BY updated_at DESC, campaign_id DESC LIMIT ?",
                    (str(account), limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM campaigns ORDER BY updated_at DESC, campaign_id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [self._campaign_from_row(row) for row in rows]
        finally:
            connection.close()

    def transition(
        self,
        campaign_id: str,
        new_state: CampaignState | str,
        *,
        next_action: str = "",
        error: str = "",
        context_updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if context_updates is not None and not isinstance(context_updates, dict):
            raise ValueError("campaign context updates must be a dict")
        target = CampaignState(new_state)
        now = float(self.clock())
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM campaigns WHERE campaign_id=?",
                (str(campaign_id),),
            ).fetchone()
            if row is None:
                raise CampaignNotFound(f"Campaign not found: {campaign_id}")
            current = CampaignState(row["state"])
            same_state = current == target
            if not same_state and target not in ALLOWED_TRANSITIONS[current]:
                raise InvalidTransition(
                    f"Campaign {campaign_id} cannot transition from {current.value} to {target.value}"
                )

            self._assert_account_has_no_active_campaign(
                connection,
                account=row["account"],
                campaign_id=str(campaign_id),
                target=target,
            )

            context = _json_loads(row["context_json"]) or {}
            if context_updates is not None:
                context = _deep_merge(context, sanitize_for_storage(context_updates))
            started_at = row["started_at"]
            if started_at is None and target is not CampaignState.DRAFT:
                started_at = now
            ended_at = now if target in TERMINAL_STATES else row["ended_at"]
            connection.execute(
                "UPDATE campaigns SET state=?, updated_at=?, started_at=?, ended_at=?, "
                "next_action=?, error_text=?, context_json=?, paused_from_state='', "
                "version=version+1 "
                "WHERE campaign_id=?",
                (
                    target.value,
                    now,
                    started_at,
                    ended_at,
                    str(next_action or ""),
                    str(error or "")[:4096],
                    _json_dumps(context),
                    str(campaign_id),
                ),
            )
            self._insert_event(
                connection,
                str(campaign_id),
                "state_updated" if same_state else "state_changed",
                {
                    "from": current.value,
                    "to": target.value,
                    "next_action": str(next_action or ""),
                    "error": str(error or "")[:4096],
                    "context_keys": sorted(str(key) for key in (context_updates or {})),
                },
            )
            updated = connection.execute(
                "SELECT * FROM campaigns WHERE campaign_id=?",
                (str(campaign_id),),
            ).fetchone()
            connection.execute("COMMIT")
            return self._campaign_from_row(updated)
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def pause_for_runtime_mismatch(
        self,
        campaign_id: str,
        *,
        error: str,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        return self._pause_for_runtime_reconciliation(
            campaign_id,
            event_type="runtime_reconciliation_mismatch",
            next_action="inspect_current_career",
            error=error,
            status="MISMATCH",
            expected_version=expected_version,
        )

    def recover_missing_active_career(
        self,
        campaign_id: str,
        *,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM campaigns WHERE campaign_id=?",
                (str(campaign_id),),
            ).fetchone()
            if row is None:
                raise CampaignNotFound(f"Campaign not found: {campaign_id}")
            if expected_version is not None and int(row["version"]) != int(expected_version):
                raise CampaignError("campaign version changed during runtime reconciliation")
            if CampaignState(row["state"]) is not CampaignState.RUNNING_CAREER:
                connection.execute("COMMIT")
                return {
                    "recovered": False,
                    "reason": "state_not_running",
                    "campaign": self._campaign_from_row(row),
                }
            context = _json_loads(row["context_json"]) or {}
            run_start = context.get("run_start") if isinstance(context.get("run_start"), dict) else {}
            reserved_at = run_start.get("reserved_at", row["updated_at"])
            non_stale_starting = (
                run_start.get("status") == "STARTING"
                and isinstance(reserved_at, (int, float))
                and not isinstance(reserved_at, bool)
                and float(self.clock()) - float(reserved_at) < PREPARED_RUN_START_TIMEOUT_SECONDS
            )
            if non_stale_starting:
                connection.execute("COMMIT")
                return {
                    "recovered": False,
                    "reason": "run_start_in_progress",
                    "campaign": self._campaign_from_row(row),
                }
            error = "Persisted running career is no longer active"
            context = _deep_merge(
                context,
                {"runtime_reconciliation": {"status": "ACTIVE_CAREER_DISAPPEARED"}},
            )
            now = float(self.clock())
            connection.execute(
                "UPDATE campaigns SET state=?, paused_from_state=?, updated_at=?, next_action=?, "
                "error_text=?, context_json=?, version=version+1 WHERE campaign_id=?",
                (
                    CampaignState.PAUSED.value,
                    CampaignState.RUNNING_CAREER.value,
                    now,
                    "review_missing_active_career",
                    error,
                    _json_dumps(context),
                    str(campaign_id),
                ),
            )
            self._insert_event(
                connection,
                str(campaign_id),
                "runtime_active_career_disappeared",
                {"from": CampaignState.RUNNING_CAREER.value, "error": error},
            )
            updated = connection.execute(
                "SELECT * FROM campaigns WHERE campaign_id=?",
                (str(campaign_id),),
            ).fetchone()
            connection.execute("COMMIT")
            return {"recovered": True, "reason": "", "campaign": self._campaign_from_row(updated)}
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def _pause_for_runtime_reconciliation(
        self,
        campaign_id: str,
        *,
        event_type: str,
        next_action: str,
        error: str,
        status: str,
        expected_version: int | None,
    ) -> dict[str, Any]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM campaigns WHERE campaign_id=?",
                (str(campaign_id),),
            ).fetchone()
            if row is None:
                raise CampaignNotFound(f"Campaign not found: {campaign_id}")
            if expected_version is not None and int(row["version"]) != int(expected_version):
                raise CampaignError("campaign version changed during runtime reconciliation")
            current = CampaignState(row["state"])
            if current is not CampaignState.PAUSED and CampaignState.PAUSED not in ALLOWED_TRANSITIONS[current]:
                raise InvalidTransition(
                    f"Campaign {campaign_id} cannot transition from {current.value} to PAUSED"
                )
            context = _deep_merge(
                _json_loads(row["context_json"]) or {},
                {"runtime_reconciliation": {"status": status}},
            )
            now = float(self.clock())
            connection.execute(
                "UPDATE campaigns SET state=?, paused_from_state=?, updated_at=?, next_action=?, "
                "error_text=?, context_json=?, version=version+1 WHERE campaign_id=?",
                (
                    CampaignState.PAUSED.value,
                    row["paused_from_state"] if current is CampaignState.PAUSED else current.value,
                    now,
                    next_action,
                    str(error or "")[:4096],
                    _json_dumps(context),
                    str(campaign_id),
                ),
            )
            self._insert_event(
                connection,
                str(campaign_id),
                event_type,
                {"from": current.value, "error": str(error or "")[:4096]},
            )
            updated = connection.execute(
                "SELECT * FROM campaigns WHERE campaign_id=?",
                (str(campaign_id),),
            ).fetchone()
            connection.execute("COMMIT")
            return self._campaign_from_row(updated)
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def reopen_completed(
        self,
        campaign_id: str,
        state: CampaignState | str = CampaignState.SELECTING_LINEAGE,
        *,
        next_action: str = "",
        context_updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if context_updates is not None and not isinstance(context_updates, dict):
            raise ValueError("campaign context updates must be a dict")
        target = CampaignState(state)
        if target in TERMINAL_STATES or target is CampaignState.DRAFT:
            raise InvalidTransition(f"Cannot reopen a campaign into {target.value}")
        now = float(self.clock())
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM campaigns WHERE campaign_id=?",
                (str(campaign_id),),
            ).fetchone()
            if row is None:
                raise CampaignNotFound(f"Campaign not found: {campaign_id}")
            current = CampaignState(row["state"])
            if current is not CampaignState.COMPLETED:
                raise InvalidTransition(
                    f"Campaign {campaign_id} cannot reopen from {current.value}; COMPLETED required"
                )
            self._assert_account_has_no_active_campaign(
                connection,
                account=row["account"],
                campaign_id=str(campaign_id),
                target=target,
            )
            context = _json_loads(row["context_json"]) or {}
            if context_updates is not None:
                context = _deep_merge(context, sanitize_for_storage(context_updates))
            connection.execute(
                "UPDATE campaigns SET state=?, updated_at=?, ended_at=NULL, next_action=?, "
                "error_text='', context_json=?, paused_from_state='', version=version+1 "
                "WHERE campaign_id=?",
                (
                    target.value,
                    now,
                    str(next_action or ""),
                    _json_dumps(context),
                    str(campaign_id),
                ),
            )
            self._insert_event(
                connection,
                str(campaign_id),
                "campaign_reopened",
                {
                    "from": current.value,
                    "to": target.value,
                    "next_action": str(next_action or ""),
                    "context_keys": sorted(str(key) for key in (context_updates or {})),
                },
            )
            updated = connection.execute(
                "SELECT * FROM campaigns WHERE campaign_id=?",
                (str(campaign_id),),
            ).fetchone()
            connection.execute("COMMIT")
            return self._campaign_from_row(updated)
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def pause(self, campaign_id: str) -> dict[str, Any]:
        now = float(self.clock())
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM campaigns WHERE campaign_id=?",
                (str(campaign_id),),
            ).fetchone()
            if row is None:
                raise CampaignNotFound(f"Campaign not found: {campaign_id}")
            current = CampaignState(row["state"])
            if current is CampaignState.PAUSED:
                connection.execute("COMMIT")
                return self._campaign_from_row(row)
            if current in TERMINAL_STATES or current is CampaignState.DRAFT:
                raise InvalidTransition(f"Campaign {campaign_id} cannot pause from {current.value}")
            connection.execute(
                "UPDATE campaigns SET state=?, paused_from_state=?, updated_at=?, "
                "next_action='resume_campaign', version=version+1 WHERE campaign_id=?",
                (CampaignState.PAUSED.value, current.value, now, str(campaign_id)),
            )
            self._insert_event(
                connection,
                str(campaign_id),
                "campaign_paused",
                {"from": current.value},
            )
            updated = connection.execute(
                "SELECT * FROM campaigns WHERE campaign_id=?",
                (str(campaign_id),),
            ).fetchone()
            connection.execute("COMMIT")
            return self._campaign_from_row(updated)
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def resume(self, campaign_id: str) -> dict[str, Any]:
        now = float(self.clock())
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM campaigns WHERE campaign_id=?",
                (str(campaign_id),),
            ).fetchone()
            if row is None:
                raise CampaignNotFound(f"Campaign not found: {campaign_id}")
            if CampaignState(row["state"]) is not CampaignState.PAUSED:
                raise InvalidTransition(f"Campaign {campaign_id} is not paused")
            target_value = row["paused_from_state"] or CampaignState.READY.value
            target = CampaignState(target_value)
            if target in TERMINAL_STATES or target is CampaignState.PAUSED:
                target = CampaignState.READY
            self._assert_account_has_no_active_campaign(
                connection,
                account=row["account"],
                campaign_id=str(campaign_id),
                target=target,
            )
            context = _json_loads(row["context_json"]) or {}
            next_action = ""
            prepared_run = context.get("prepared_run")
            if (
                target is CampaignState.SELECTING_LINEAGE
                and isinstance(prepared_run, dict)
                and prepared_run
                and context.get("review_required") is False
                and not context.get("run_start")
            ):
                next_action = "start_career"
            connection.execute(
                "UPDATE campaigns SET state=?, paused_from_state='', updated_at=?, "
                "next_action=?, version=version+1 WHERE campaign_id=?",
                (target.value, now, next_action, str(campaign_id)),
            )
            self._insert_event(
                connection,
                str(campaign_id),
                "campaign_resumed",
                {"to": target.value},
            )
            updated = connection.execute(
                "SELECT * FROM campaigns WHERE campaign_id=?",
                (str(campaign_id),),
            ).fetchone()
            connection.execute("COMMIT")
            return self._campaign_from_row(updated)
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def cancel(self, campaign_id: str, *, reason: str = "") -> dict[str, Any]:
        campaign = self.get(campaign_id)
        current = CampaignState(campaign["state"])
        if current is CampaignState.CANCELLED:
            return campaign
        if current in {CampaignState.COMPLETED, CampaignState.FAILED}:
            raise InvalidTransition(f"Campaign {campaign_id} is already terminal")
        now = float(self.clock())
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE campaigns SET state=?, updated_at=?, ended_at=?, next_action='', "
                "error_text=?, paused_from_state='', version=version+1 WHERE campaign_id=?",
                (
                    CampaignState.CANCELLED.value,
                    now,
                    now,
                    str(reason or "")[:4096],
                    str(campaign_id),
                ),
            )
            self._insert_event(
                connection,
                str(campaign_id),
                "campaign_cancelled",
                {"reason": str(reason or "")[:4096]},
            )
            updated = connection.execute(
                "SELECT * FROM campaigns WHERE campaign_id=?",
                (str(campaign_id),),
            ).fetchone()
            connection.execute("COMMIT")
            return self._campaign_from_row(updated)
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    @staticmethod
    def _budget_limits(campaign: dict[str, Any]) -> dict[str, float]:
        strategy = campaign["spec"]["strategy"]
        return {
            "maximum_runs": int(strategy["maximum_runs"]),
            "maximum_carats": int(strategy.get("maximum_carats") or 0),
            "maximum_clocks": int(strategy.get("maximum_clocks") or 0),
            "maximum_runtime_hours": float(strategy["maximum_runtime_hours"]),
        }

    def assert_within_budget(self, campaign_id: str) -> dict[str, Any]:
        campaign = self.get(campaign_id)
        limits = self._budget_limits(campaign)
        usage = campaign["usage"]
        checks = (
            ("maximum_runs", usage["runs"], limits["maximum_runs"]),
            ("maximum_carats", usage["carats"], limits["maximum_carats"]),
            ("maximum_clocks", usage["clocks"], limits["maximum_clocks"]),
        )
        for name, used, maximum in checks:
            if used > maximum:
                raise BudgetExceeded(f"Campaign {campaign_id} exceeded {name}: {used} > {maximum}")
        origin = campaign["started_at"] or campaign["created_at"]
        elapsed_hours = max(0.0, float(self.clock()) - float(origin)) / 3600.0
        if elapsed_hours > limits["maximum_runtime_hours"]:
            raise BudgetExceeded(
                f"Campaign {campaign_id} exceeded maximum_runtime_hours: "
                f"{elapsed_hours:.2f} > {limits['maximum_runtime_hours']:.2f}"
            )
        campaign["runtime_hours"] = elapsed_hours
        campaign["limits"] = limits
        return campaign

    def add_usage(
        self,
        campaign_id: str,
        *,
        runs: int = 0,
        carats: int = 0,
        clocks: int = 0,
    ) -> dict[str, Any]:
        deltas = {
            "runs": int(runs),
            "carats": int(carats),
            "clocks": int(clocks),
        }
        if any(value < 0 for value in deltas.values()):
            raise ValueError("usage deltas must be non-negative")
        campaign = self.assert_within_budget(campaign_id)
        limits = campaign["limits"]
        proposed = {
            key: campaign["usage"][key] + deltas[key]
            for key in ("runs", "carats", "clocks")
        }
        mapping = {
            "runs": "maximum_runs",
            "carats": "maximum_carats",
            "clocks": "maximum_clocks",
        }
        for key, value in proposed.items():
            maximum_name = mapping[key]
            if value > limits[maximum_name]:
                raise BudgetExceeded(
                    f"Campaign {campaign_id} exceeded {maximum_name}: "
                    f"{value} > {limits[maximum_name]}"
                )

        now = float(self.clock())
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE campaigns SET run_count=?, carats_used=?, clocks_used=?, "
                "updated_at=?, version=version+1 WHERE campaign_id=?",
                (
                    proposed["runs"],
                    proposed["carats"],
                    proposed["clocks"],
                    now,
                    str(campaign_id),
                ),
            )
            self._insert_event(
                connection,
                str(campaign_id),
                "usage_updated",
                {"delta": deltas, "usage": proposed},
            )
            updated = connection.execute(
                "SELECT * FROM campaigns WHERE campaign_id=?",
                (str(campaign_id),),
            ).fetchone()
            connection.execute("COMMIT")
            return self._campaign_from_row(updated)
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def add_candidate(
        self,
        campaign_id: str,
        *,
        trained_chara_id: int,
        name: str,
        score: float,
        evaluation: dict[str, Any],
        candidate_id: str | None = None,
    ) -> dict[str, Any]:
        self.get(campaign_id)
        resolved_id = str(candidate_id or uuid.uuid4()).strip()
        accepted = bool(evaluation.get("accepted"))
        now = float(self.clock())
        connection = self._connect()
        try:
            connection.execute(
                "INSERT INTO campaign_candidates "
                "(candidate_id, campaign_id, trained_chara_id, name, score, accepted, "
                "selected, evaluation_json, created_at) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)",
                (
                    resolved_id,
                    str(campaign_id),
                    int(trained_chara_id),
                    str(name or f"Candidate #{trained_chara_id}"),
                    float(score),
                    1 if accepted else 0,
                    _json_dumps(evaluation),
                    now,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise CampaignError(f"Candidate already exists: {resolved_id}") from exc
        return next(
            row for row in self.list_candidates(campaign_id) if row["candidate_id"] == resolved_id
        )

    def persist_candidate_result(
        self,
        campaign_id: str,
        *,
        candidate_id: str,
        trained_chara_id: int,
        name: str,
        score: float,
        evaluation: dict[str, Any],
        select: bool,
        state: CampaignState | str,
        next_action: str,
        context_updates: dict[str, Any] | None = None,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        target = CampaignState(state)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            campaign_row = connection.execute(
                "SELECT * FROM campaigns WHERE campaign_id=?",
                (str(campaign_id),),
            ).fetchone()
            if campaign_row is None:
                raise CampaignNotFound(f"Campaign not found: {campaign_id}")
            existing = connection.execute(
                "SELECT * FROM campaign_candidates WHERE campaign_id=? AND candidate_id=?",
                (str(campaign_id), str(candidate_id)),
            ).fetchone()
            if existing is not None:
                connection.execute("COMMIT")
                return {
                    "campaign": self._campaign_from_row(campaign_row),
                    "candidate": self._candidate_from_row(existing),
                    "replayed": True,
                }
            if expected_version is not None and int(campaign_row["version"]) != int(expected_version):
                raise CampaignError("campaign version changed while recording candidate")
            current = CampaignState(campaign_row["state"])
            if target != current and target not in ALLOWED_TRANSITIONS[current]:
                raise InvalidTransition(
                    f"Campaign {campaign_id} cannot transition from {current.value} to {target.value}"
                )
            now = float(self.clock())
            connection.execute(
                "INSERT INTO campaign_candidates "
                "(candidate_id, campaign_id, trained_chara_id, name, score, accepted, "
                "selected, evaluation_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(candidate_id),
                    str(campaign_id),
                    int(trained_chara_id),
                    str(name or f"Candidate #{trained_chara_id}"),
                    float(score),
                    1 if evaluation.get("accepted") else 0,
                    1 if select else 0,
                    _json_dumps(evaluation),
                    now,
                ),
            )
            selected_candidate_id = campaign_row["selected_candidate_id"] or ""
            if select:
                connection.execute(
                    "UPDATE campaign_candidates SET selected=0 "
                    "WHERE campaign_id=? AND candidate_id<>?",
                    (str(campaign_id), str(candidate_id)),
                )
                selected_candidate_id = str(candidate_id)
            context = _json_loads(campaign_row["context_json"]) or {}
            context = _deep_merge(context, context_updates or {})
            ended_at = now if target in TERMINAL_STATES else campaign_row["ended_at"]
            connection.execute(
                "UPDATE campaigns SET state=?, context_json=?, selected_candidate_id=?, "
                "next_action=?, updated_at=?, ended_at=?, version=version+1 WHERE campaign_id=?",
                (
                    target.value,
                    _json_dumps(context),
                    selected_candidate_id,
                    str(next_action or ""),
                    now,
                    ended_at,
                    str(campaign_id),
                ),
            )
            self._insert_event(
                connection,
                str(campaign_id),
                "candidate_result_recorded",
                {
                    "candidate_id": str(candidate_id),
                    "selected": bool(select),
                    "state": target.value,
                },
            )
            updated_campaign = connection.execute(
                "SELECT * FROM campaigns WHERE campaign_id=?",
                (str(campaign_id),),
            ).fetchone()
            updated_candidate = connection.execute(
                "SELECT * FROM campaign_candidates WHERE candidate_id=?",
                (str(candidate_id),),
            ).fetchone()
            connection.execute("COMMIT")
            return {
                "campaign": self._campaign_from_row(updated_campaign),
                "candidate": self._candidate_from_row(updated_candidate),
                "replayed": False,
            }
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def list_candidates(self, campaign_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        self.get(campaign_id)
        limit = max(1, min(int(limit), 500))
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM campaign_candidates WHERE campaign_id=? "
                "ORDER BY score DESC, created_at ASC, candidate_id ASC LIMIT ?",
                (str(campaign_id), limit),
            ).fetchall()
            return [self._candidate_from_row(row) for row in rows]
        finally:
            connection.close()

    def get_candidate(self, campaign_id: str, candidate_id: str) -> dict[str, Any]:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM campaign_candidates WHERE campaign_id=? AND candidate_id=?",
                (str(campaign_id), str(candidate_id)),
            ).fetchone()
            if row is None:
                raise CampaignNotFound(
                    f"Candidate {candidate_id} not found in campaign {campaign_id}"
                )
            return self._candidate_from_row(row)
        finally:
            connection.close()

    def apply_candidate_selection(
        self,
        campaign_id: str,
        candidate_id: str,
        *,
        state: CampaignState | str,
        next_action: str,
        context_updates: dict[str, Any] | None = None,
        allowed_candidate_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        target = CampaignState(state)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            campaign_row = connection.execute(
                "SELECT * FROM campaigns WHERE campaign_id=?",
                (str(campaign_id),),
            ).fetchone()
            candidate_row = connection.execute(
                "SELECT * FROM campaign_candidates WHERE campaign_id=? AND candidate_id=?",
                (str(campaign_id), str(candidate_id)),
            ).fetchone()
            if campaign_row is None:
                raise CampaignNotFound(f"Campaign not found: {campaign_id}")
            if candidate_row is None:
                raise CampaignNotFound(
                    f"Candidate {candidate_id} not found in campaign {campaign_id}"
                )
            current = CampaignState(campaign_row["state"])
            current_context = _json_loads(campaign_row["context_json"]) or {}
            review = current_context.get("pending_review")
            review_type = (
                review.get("kind", review.get("type"))
                if isinstance(review, dict)
                else None
            )
            allowed = {str(value) for value in (allowed_candidate_ids or set())}
            if isinstance(review, dict):
                if review.get("candidate_id") is not None:
                    allowed.add(str(review["candidate_id"]))
                allowed.update(str(value) for value in (review.get("candidate_ids") or []))
            if not (
                current is CampaignState.NEEDS_USER_INPUT
                and campaign_row["next_action"] == "select_candidate"
                and review_type == "candidate_tradeoff"
                and str(candidate_id) in allowed
            ):
                raise InvalidTransition(
                    f"Campaign {campaign_id} has no matching candidate selection review"
                )
            if target != current and target not in ALLOWED_TRANSITIONS[current]:
                raise InvalidTransition(
                    f"Campaign {campaign_id} cannot transition from {current.value} to {target.value}"
                )
            now = float(self.clock())
            connection.execute(
                "UPDATE campaign_candidates SET selected=0 WHERE campaign_id=?",
                (str(campaign_id),),
            )
            connection.execute(
                "UPDATE campaign_candidates SET selected=1 WHERE candidate_id=?",
                (str(candidate_id),),
            )
            context = _deep_merge(
                current_context,
                context_updates or {},
            )
            ended_at = now if target in TERMINAL_STATES else campaign_row["ended_at"]
            connection.execute(
                "UPDATE campaigns SET state=?, context_json=?, selected_candidate_id=?, "
                "next_action=?, updated_at=?, ended_at=?, version=version+1 WHERE campaign_id=?",
                (
                    target.value,
                    _json_dumps(context),
                    str(candidate_id),
                    str(next_action or ""),
                    now,
                    ended_at,
                    str(campaign_id),
                ),
            )
            self._insert_event(
                connection,
                str(campaign_id),
                "candidate_selected",
                {"candidate_id": str(candidate_id), "state": target.value},
            )
            updated_campaign = connection.execute(
                "SELECT * FROM campaigns WHERE campaign_id=?",
                (str(campaign_id),),
            ).fetchone()
            updated_candidate = connection.execute(
                "SELECT * FROM campaign_candidates WHERE candidate_id=?",
                (str(candidate_id),),
            ).fetchone()
            connection.execute("COMMIT")
            return {
                "campaign": self._campaign_from_row(updated_campaign),
                "candidate": self._candidate_from_row(updated_candidate),
            }
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def select_candidate(self, campaign_id: str, candidate_id: str) -> dict[str, Any]:
        now = float(self.clock())
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM campaign_candidates WHERE campaign_id=? AND candidate_id=?",
                (str(campaign_id), str(candidate_id)),
            ).fetchone()
            if row is None:
                raise CampaignNotFound(
                    f"Candidate {candidate_id} not found in campaign {campaign_id}"
                )
            connection.execute(
                "UPDATE campaign_candidates SET selected=0 WHERE campaign_id=?",
                (str(campaign_id),),
            )
            connection.execute(
                "UPDATE campaign_candidates SET selected=1 WHERE candidate_id=?",
                (str(candidate_id),),
            )
            connection.execute(
                "UPDATE campaigns SET selected_candidate_id=?, updated_at=?, version=version+1 "
                "WHERE campaign_id=?",
                (str(candidate_id), now, str(campaign_id)),
            )
            self._insert_event(
                connection,
                str(campaign_id),
                "candidate_selected",
                {"candidate_id": str(candidate_id)},
            )
            updated = connection.execute(
                "SELECT * FROM campaign_candidates WHERE candidate_id=?",
                (str(candidate_id),),
            ).fetchone()
            connection.execute("COMMIT")
            return self._candidate_from_row(updated)
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def recent_events(self, campaign_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        self.get(campaign_id)
        limit = max(1, min(int(limit), 200))
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM campaign_events WHERE campaign_id=? "
                "ORDER BY created_at DESC, id DESC LIMIT ?",
                (str(campaign_id), limit),
            ).fetchall()
            return [
                {
                    "id": int(row["id"]),
                    "campaign_id": row["campaign_id"],
                    "event_type": row["event_type"],
                    "created_at": float(row["created_at"]),
                    "data": _json_loads(row["data_json"]) or {},
                }
                for row in rows
            ]
        finally:
            connection.close()
