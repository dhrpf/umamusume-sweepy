from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Callable

import httpx
from mcp.server.fastmcp import FastMCP

from account_snapshot import compact_account_snapshot, load_account_snapshot
from career_bot import master_data
from career_bot.campaigns.legacy.race_planner import build_shared_g1_agenda
from career_bot.campaigns.legacy.rules import DEFAULT_SPARK_RULESET
from career_bot.campaigns.legacy.scanner import scan_legacy_loop_pools
from career_bot.campaigns.lineage_planner import (
    LineagePlanningError,
    build_inheritance_request,
    choose_lineage_setup,
    resolve_lineage_selection,
)
from career_bot.campaigns.models import CampaignState, ParentCampaignSpec
from career_bot.campaigns.runner import CampaignRunner
from career_bot.campaigns.store import CampaignStore
from sweepy_jobs import LeaseConflict, OperationConflict, SweepyJobStore
from sweepy_supervisor import SweepySupervisor


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

TOOL_NAMES = (
    "list_accounts",
    "get_bot_state",
    "list_career_presets",
    "get_legend_races",
    "run_dailies",
    "stop_dailies",
    "run_career",
    "stop_career",
    "refresh_account",
    "refill_tp",
    "set_turn_delay",
    "get_account_runtime",
    "get_bot_logs",
    "launch_bot",
    "stop_bot",
    "restart_bot",
    "wait_until_ready",
    "get_recent_operations",
    "get_cached_account_snapshot",
    "list_cached_veterans",
    "get_legacy_spark_rules",
    "scan_cached_legacy_loops",
    "preview_shared_g1_agenda",
    "preview_parent_campaign",
    "create_parent_campaign",
    "list_parent_campaigns",
    "get_parent_campaign",
    "get_parent_campaign_summary",
    "start_parent_campaign",
    "advance_parent_campaign",
    "pause_parent_campaign",
    "resume_parent_campaign",
    "cancel_parent_campaign",
    "list_parent_candidates",
    "select_parent_candidate",
    "prepare_parent_campaign_run",
    "run_parent_campaign_career",
    "collect_parent_campaign_result",
)

INSTRUCTIONS = """
Operate the local Sweepy Uma Musume bot through its loopback HTTP API.
Call list_accounts first and pass the intended account name to every account-specific
tool. Read runtime and bot state before starting work. Side-effecting tools require
confirm=true. Workflow stop tools are safe, but process launch/stop/restart still
require confirmation. Never ask for or expose credentials, SID, auth keys, Steam
tickets, device identifiers, IP addresses, or raw payloads. Do not start Career
and Dailies concurrently on the same account.
""".strip()

logging.basicConfig(
    level=os.environ.get("SWEEPY_MCP_LOG_LEVEL", "WARNING").upper(),
    stream=sys.stderr,
)
logger = logging.getLogger("sweepy.mcp")


def redact_sensitive(value: Any, key: str = "") -> Any:
    if key.lower() in SENSITIVE_KEYS:
        return "<redacted>"
    if isinstance(value, dict):
        return {
            str(child_key): redact_sensitive(child_value, str(child_key))
            for child_key, child_value in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive(item, key) for item in value]
    if isinstance(value, tuple):
        return [redact_sensitive(item, key) for item in value]
    return value


class SweepyGateway:
    def __init__(
        self,
        base_url: str | None = None,
        timeout: float | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        default_port = os.environ.get("PORT", "1616")
        self.base_url = (
            base_url
            or os.environ.get("SWEEPY_BASE_URL")
            or f"http://127.0.0.1:{default_port}"
        ).rstrip("/")
        self.timeout = float(timeout or os.environ.get("SWEEPY_MCP_TIMEOUT", "20"))
        self._client = client

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not path.startswith("/api/"):
            raise ValueError("MCP gateway only allows Sweepy /api/ routes")
        if method not in {"GET", "POST"}:
            raise ValueError(f"Unsupported HTTP method: {method}")

        own_client = self._client is None
        client = self._client or httpx.Client(base_url=self.base_url, timeout=self.timeout)
        try:
            response = client.request(method, path, json=payload if method == "POST" else None)
            try:
                data = response.json()
            except ValueError as exc:
                raise RuntimeError(
                    f"Sweepy returned non-JSON response for {method} {path} "
                    f"(HTTP {response.status_code})"
                ) from exc
            if response.is_error:
                detail = data.get("detail") if isinstance(data, dict) else None
                raise RuntimeError(
                    detail or f"Sweepy API failed: {method} {path} HTTP {response.status_code}"
                )
            if not isinstance(data, dict):
                raise RuntimeError(f"Unexpected Sweepy response type for {method} {path}")
            return redact_sensitive(data)
        except httpx.RequestError as exc:
            raise RuntimeError(
                f"Cannot reach Sweepy at {self.base_url}. Start the bot web server first."
            ) from exc
        finally:
            if own_client:
                client.close()



class SweepyAccountRegistry:
    def __init__(
        self,
        accounts_path: str | Path | None = None,
        default_gateway: SweepyGateway | None = None,
    ) -> None:
        configured_path = accounts_path or os.environ.get("SWEEPY_ACCOUNTS_FILE")
        self.accounts_path = Path(configured_path or Path(__file__).with_name("accounts.json"))
        self.default_gateway = default_gateway or SweepyGateway()
        self._gateways: dict[str, tuple[int, SweepyGateway]] = {}

    def list_accounts(self) -> list[dict[str, Any]]:
        if not self.accounts_path.exists():
            return []
        try:
            raw = json.loads(self.accounts_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"Cannot read Sweepy accounts file: {self.accounts_path}") from exc
        if not isinstance(raw, list):
            raise RuntimeError("accounts.json must contain a JSON array")

        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in raw:
            if not isinstance(item, dict) or not item.get("enabled", True):
                continue
            name = str(item.get("name") or "").strip()
            try:
                port = int(item.get("port") or 0)
            except (TypeError, ValueError):
                port = 0
            if not name or port <= 0 or port > 65535:
                raise RuntimeError("Each enabled Sweepy account needs a valid name and port")
            if name in seen:
                raise RuntimeError(f"Duplicate Sweepy account name: {name}")
            seen.add(name)
            rows.append({"name": name, "port": port, "enabled": True})
        return rows

    def resolve(self, account: str = "") -> tuple[str, SweepyGateway]:
        rows = self.list_accounts()
        requested = str(account or "").strip()
        if not requested:
            requested = str(os.environ.get("SWEEPY_ACCOUNT") or "").strip()

        if requested:
            row = next((item for item in rows if item["name"] == requested), None)
            if row is None:
                available = ", ".join(item["name"] for item in rows) or "none"
                raise ValueError(
                    f"Unknown Sweepy account: {requested}. Available accounts: {available}"
                )
            port = int(row["port"])
            cached = self._gateways.get(requested)
            if cached is None or cached[0] != port:
                cached = (port, SweepyGateway(base_url=f"http://127.0.0.1:{port}"))
                self._gateways[requested] = cached
            return requested, cached[1]

        if len(rows) == 1:
            return self.resolve(rows[0]["name"])
        if len(rows) > 1:
            available = ", ".join(item["name"] for item in rows)
            raise ValueError(f"account is required. Available accounts: {available}")

        default_name = str(os.environ.get("SWEEPY_ACCOUNT") or "default").strip() or "default"
        return default_name, self.default_gateway


gateway = SweepyGateway()
account_registry = SweepyAccountRegistry(default_gateway=gateway)
supervisor = SweepySupervisor(
    repo_root=Path(__file__).resolve().parent,
    accounts_file=account_registry.accounts_path,
)
job_store = SweepyJobStore(
    os.environ.get("SWEEPY_JOBS_DB")
    or Path(__file__).resolve().parent / "uma_runtime" / "control-plane.sqlite3"
)
campaign_store = CampaignStore(
    os.environ.get("SWEEPY_CAMPAIGNS_DB")
    or Path(__file__).resolve().parent / "uma_runtime" / "campaigns.sqlite3"
)
campaign_runner = CampaignRunner(campaign_store)


def _snapshot_runtime_dir(account: str) -> Path:
    runtime_dir = getattr(supervisor, "runtime_dir", None)
    if callable(runtime_dir):
        return Path(runtime_dir(account))
    accounts_path = getattr(account_registry, "accounts_path", None)
    root = Path(accounts_path).resolve().parent if accounts_path else Path(__file__).resolve().parent
    return root / "uma_runtime" / account


def _compact_career(career: Any) -> dict[str, Any] | None:
    if not isinstance(career, dict):
        return None
    return {
        key: career.get(key)
        for key in (
            "active",
            "card_id",
            "name",
            "turn",
            "scenario_id",
            "fans",
            "vital",
            "max_vital",
            "deck_id",
        )
        if key in career
    }


def _compact_veteran(row: Any) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    trained_chara_id = int(
        row.get("instance_id") or row.get("trained_chara_id") or row.get("id") or 0
    )
    if trained_chara_id <= 0:
        return None
    return {
        "trained_chara_id": trained_chara_id,
        "name": row.get("name") or row.get("chara_name") or f"Veteran #{trained_chara_id}",
        "rank_score": int(row.get("rank_score") or row.get("evaluation_point") or 0),
        "card_id": int(row.get("card_id") or 0),
    }


def _selection_summary(selection: Any) -> dict[str, Any]:
    if not isinstance(selection, dict):
        return {"deck": None, "trainee": None, "friend": None, "veterans": []}

    deck = selection.get("deck") if isinstance(selection.get("deck"), dict) else None
    trainee = selection.get("trainee") if isinstance(selection.get("trainee"), dict) else None
    friend = selection.get("friend") if isinstance(selection.get("friend"), dict) else None
    veteran_rows = selection.get("veterans") if isinstance(selection.get("veterans"), list) else []

    veterans = []
    for row in veteran_rows:
        compact = _compact_veteran(row)
        if compact:
            compact["rental"] = bool(isinstance(row, dict) and row.get("viewer_id"))
            veterans.append(compact)

    return {
        "deck": (
            {"id": int(deck.get("id") or 0), "name": deck.get("name") or ""}
            if deck
            else None
        ),
        "trainee": (
            {"id": int(trainee.get("id") or 0), "name": trainee.get("name") or ""}
            if trainee
            else None
        ),
        "friend": (
            {
                "support_card_id": int(friend.get("support_card_id") or 0),
                "support_name": friend.get("support_name") or friend.get("name") or "",
            }
            if friend
            else None
        ),
        "veterans": veterans,
    }


def compact_session(session: dict[str, Any]) -> dict[str, Any]:
    logged_in = bool(session.get("success"))
    account_raw = session.get("account") if isinstance(session.get("account"), dict) else {}
    account = {
        "tp": account_raw.get("tp") or {"current": 0, "max": 0},
        "carrots": account_raw.get("carrots") or {"free": 0, "paid": 0, "total": 0},
        "gold": int(account_raw.get("gold") or 0),
        "clocks": int(account_raw.get("clocks") or 0),
        "career": _compact_career(account_raw.get("career")),
    }

    parents = session.get("parents") if isinstance(session.get("parents"), list) else []
    recommended_veterans = []
    for row in parents:
        compact = _compact_veteran(row)
        if compact:
            recommended_veterans.append(compact)
    recommended_veterans.sort(
        key=lambda row: (-int(row.get("rank_score") or 0), int(row["trained_chara_id"]))
    )

    result = {
        "logged_in": logged_in,
        "account": account,
        "counts": {
            "umas": len(session.get("umas") or []),
            "supports": len(session.get("supports") or []),
            "decks": len(session.get("decks") or []),
            "friends": len(session.get("friends") or []),
            "veterans": len(parents),
        },
        "selection": _selection_summary(session.get("selection")),
        "recommended_veterans": recommended_veterans[:20],
    }
    return redact_sensitive(result)


def _compact_runner(response: dict[str, Any]) -> dict[str, Any]:
    runner = response.get("runner") if isinstance(response.get("runner"), dict) else response
    if not isinstance(runner, dict):
        return {}
    result = {
        key: runner.get(key)
        for key in (
            "running",
            "finished",
            "turn",
            "steps",
            "last_action",
            "last_error",
            "preset_name",
            "clocks_used",
            "burn_clocks",
        )
        if key in runner
    }
    log = runner.get("log")
    if isinstance(log, list):
        result["recent_log"] = redact_sensitive(log[-20:])
    return redact_sensitive(result)


def _compact_dailies(response: dict[str, Any]) -> dict[str, Any]:
    status = response.get("status") if isinstance(response.get("status"), dict) else response
    if not isinstance(status, dict):
        return {}
    result = {
        key: status.get(key)
        for key in ("running", "finished", "task", "tasks", "results", "error")
        if key in status
    }
    log = status.get("log")
    if isinstance(log, list):
        result["recent_log"] = redact_sensitive(log[-30:])
    return redact_sensitive(result)


WORKFLOW_LEASE_TTL_SECONDS = float(
    os.environ.get("SWEEPY_WORKFLOW_LEASE_TTL", str(24 * 60 * 60))
)
MUTATION_LOCK_TTL_SECONDS = float(os.environ.get("SWEEPY_MUTATION_LOCK_TTL", "120"))


def _normalize_operation_id(operation_id: str = "") -> str:
    value = str(operation_id or "").strip()
    return value or str(uuid.uuid4())


def _requires_confirmation(
    action: str,
    details: dict[str, Any],
    operation_id: str = "",
) -> dict[str, Any]:
    resolved_operation_id = _normalize_operation_id(operation_id)
    return {
        "success": False,
        "requires_confirmation": True,
        "operation_id": resolved_operation_id,
        "action": action,
        "details": redact_sensitive(details),
        "instruction": "Call the same tool again with confirm=true after user approval.",
    }


def _operation_replay(operation: dict[str, Any]) -> dict[str, Any]:
    operation_id = str(operation.get("operation_id") or "")
    status = str(operation.get("status") or "")
    if status in {"completed", "failed"}:
        result = operation.get("result")
        if not isinstance(result, dict):
            result = {
                "success": status == "completed",
                "detail": operation.get("error") or f"Operation {status}",
            }
        result = redact_sensitive(dict(result))
        result["operation_id"] = operation_id
        result["operation_status"] = status
        result["replayed"] = True
        return result
    return {
        "success": False,
        "operation_id": operation_id,
        "operation_status": status or "in_progress",
        "operation_in_progress": True,
        "detail": "This operation is already in progress; it was not executed again.",
    }


def _runner_is_running(response: dict[str, Any], container_key: str) -> bool:
    payload = response.get(container_key) if isinstance(response.get(container_key), dict) else response
    return bool(payload.get("running")) if isinstance(payload, dict) else False


def _sync_workflow_lease(
    account: str,
    career_response: dict[str, Any],
    dailies_response: dict[str, Any],
) -> dict[str, Any] | None:
    career_running = _runner_is_running(career_response, "runner")
    dailies_running = _runner_is_running(dailies_response, "status")
    active_type = "career" if career_running else "dailies" if dailies_running else ""
    lease = job_store.get_workflow_lease(account)

    if not active_type:
        if lease and lease.get("workflow_type") in {"career", "dailies"}:
            job_store.release_workflow_lease(account)
        return None

    if lease and lease.get("workflow_type") == active_type:
        try:
            return job_store.heartbeat_workflow_lease(
                account,
                owner=str(lease.get("owner") or ""),
                ttl_seconds=WORKFLOW_LEASE_TTL_SECONDS,
            )
        except LeaseConflict:
            return job_store.get_workflow_lease(account)
    if lease:
        return lease

    try:
        return job_store.acquire_workflow_lease(
            account,
            owner=f"external:{active_type}:{account}",
            workflow_type=active_type,
            ttl_seconds=WORKFLOW_LEASE_TTL_SECONDS,
            metadata={"source": "observed_api_state"},
        )
    except LeaseConflict:
        return job_store.get_workflow_lease(account)


def _observe_workflow_lease(
    account: str,
    selected_gateway: SweepyGateway,
) -> dict[str, Any] | None:
    career = selected_gateway.request("GET", "/api/career/runner")
    dailies = selected_gateway.request("GET", "/api/dailies/status")
    return _sync_workflow_lease(account, career, dailies)


def _execute_mutation(
    *,
    account: str,
    action: str,
    operation_id: str,
    arguments: dict[str, Any],
    callback: Callable[[], dict[str, Any]],
    selected_gateway: SweepyGateway | None = None,
    workflow_type: str = "",
    retain_workflow: bool = False,
    release_workflow: bool = False,
    mutation_ttl_seconds: float | None = None,
) -> dict[str, Any]:
    resolved_operation_id = _normalize_operation_id(operation_id)
    owner = f"operation:{resolved_operation_id}"
    created = False
    mutation_locked = False
    workflow_acquired = False

    try:
        started = job_store.begin_operation(
            operation_id=resolved_operation_id,
            account=account,
            action=action,
            arguments=arguments,
        )
        if not started.get("created"):
            return _operation_replay(started.get("operation") or {})
        created = True

        job_store.acquire_mutation_lock(
            account,
            owner=owner,
            ttl_seconds=max(
                MUTATION_LOCK_TTL_SECONDS,
                float(mutation_ttl_seconds or 0),
            ),
        )
        mutation_locked = True

        if retain_workflow:
            if selected_gateway is not None and job_store.get_workflow_lease(account) is None:
                _observe_workflow_lease(account, selected_gateway)
            job_store.acquire_workflow_lease(
                account,
                owner=owner,
                workflow_type=workflow_type,
                ttl_seconds=WORKFLOW_LEASE_TTL_SECONDS,
                metadata={"operation_id": resolved_operation_id, "action": action},
            )
            workflow_acquired = True

        raw_result = callback()
        result = raw_result if isinstance(raw_result, dict) else {"success": True, "result": raw_result}
        result = redact_sensitive(dict(result))
        result.setdefault("account", account)
        result["operation_id"] = resolved_operation_id
        result["replayed"] = False

        if result.get("success") is False:
            if workflow_acquired:
                job_store.release_workflow_lease(account, owner=owner)
            job_store.fail_operation(resolved_operation_id, result)
        else:
            if release_workflow:
                job_store.release_workflow_lease(
                    account,
                    workflow_type=workflow_type or None,
                )
            job_store.complete_operation(resolved_operation_id, result)
            job_store.record_event(
                account,
                action,
                {"success": True},
                operation_id=resolved_operation_id,
            )
        return result
    except (LeaseConflict, OperationConflict, ValueError, RuntimeError) as exc:
        result = {
            "success": False,
            "detail": str(exc),
            "account": account,
            "operation_id": resolved_operation_id,
            "replayed": False,
        }
        if workflow_acquired:
            job_store.release_workflow_lease(account, owner=owner)
        if created:
            job_store.fail_operation(resolved_operation_id, result)
        return result
    except Exception as exc:
        result = {
            "success": False,
            "detail": str(exc),
            "account": account,
            "operation_id": resolved_operation_id,
            "replayed": False,
        }
        if workflow_acquired:
            job_store.release_workflow_lease(account, owner=owner)
        if created:
            job_store.fail_operation(resolved_operation_id, result)
        return result
    finally:
        if mutation_locked:
            job_store.release_mutation_lock(account, owner=owner)


def _find_recommended_veteran(session: dict[str, Any]) -> int:
    selection = session.get("selection") if isinstance(session.get("selection"), dict) else {}
    selected = selection.get("veterans") if isinstance(selection.get("veterans"), list) else []
    for row in selected:
        if not isinstance(row, dict) or row.get("viewer_id"):
            continue
        candidate = int(row.get("instance_id") or row.get("trained_chara_id") or 0)
        if candidate:
            return candidate

    parents = session.get("parents") if isinstance(session.get("parents"), list) else []
    candidates = []
    for row in parents:
        if not isinstance(row, dict):
            continue
        candidate = int(row.get("instance_id") or row.get("trained_chara_id") or 0)
        if candidate:
            candidates.append((int(row.get("rank_score") or 0), candidate))
    if not candidates:
        return 0
    candidates.sort(reverse=True)
    return candidates[0][1]


def build_career_payload(
    session: dict[str, Any],
    preset: dict[str, Any],
    *,
    max_steps: int,
    burn_clocks: bool,
    dev_mode: bool,
) -> dict[str, Any]:
    preset_name = str(preset.get("name") or "").strip()
    if not preset_name:
        raise ValueError("Preset has no name")

    common = {
        "preset_name": preset_name,
        "max_steps": max(1, min(int(max_steps), 3000)),
        "burn_clocks": bool(burn_clocks),
        "dev_mode": bool(dev_mode),
        "run_delay_min_min": int(preset.get("run_delay_min_min") or 0),
        "run_delay_max_min": int(preset.get("run_delay_max_min") or 0),
        "tp_mode": "wait" if preset.get("tp_mode") == "wait" else "carat",
    }

    account = session.get("account") if isinstance(session.get("account"), dict) else {}
    career = account.get("career") if isinstance(account.get("career"), dict) else None
    if career and career.get("active"):
        return common

    selection = session.get("selection") if isinstance(session.get("selection"), dict) else {}
    deck = selection.get("deck") if isinstance(selection.get("deck"), dict) else None
    trainee = selection.get("trainee") if isinstance(selection.get("trainee"), dict) else None
    friend = selection.get("friend") if isinstance(selection.get("friend"), dict) else None
    veterans = selection.get("veterans") if isinstance(selection.get("veterans"), list) else []

    if not deck or not deck.get("cards"):
        raise ValueError("Current UI selection has no support deck")
    if not trainee or not trainee.get("id"):
        raise ValueError("Current UI selection has no trainee")
    if not friend or not friend.get("support_card_id") or not friend.get("viewer_id"):
        raise ValueError("Current UI selection has no friend support")

    own = [row for row in veterans if isinstance(row, dict) and not row.get("viewer_id")]
    rental = [row for row in veterans if isinstance(row, dict) and row.get("viewer_id")]
    if len(own) + len(rental) < 2:
        raise ValueError("Current UI selection needs two veterans/parents")

    payload = {
        "card_id": int(trainee["id"]),
        "support_card_ids": [
            int(card.get("id") or 0)
            for card in deck.get("cards", [])
            if isinstance(card, dict) and int(card.get("id") or 0)
        ],
        "friend_viewer_id": int(friend["viewer_id"]),
        "friend_card_id": int(friend["support_card_id"]),
        "parent_id_1": int(own[0].get("instance_id") or 0) if own else 0,
        "parent_id_2": int(own[1].get("instance_id") or 0) if len(own) > 1 else 0,
        "rental_viewer_id": int(rental[0].get("viewer_id") or 0) if rental else 0,
        "rental_trained_chara_id": (
            int(rental[0].get("trained_chara_id") or rental[0].get("instance_id") or 0)
            if rental
            else 0
        ),
        "deck_id": int(deck.get("id") or 0),
        "scenario_id": int(preset.get("scenario_id") or preset.get("scenario") or 4),
        "use_tp": 30,
        "difficulty_id": 0,
        "difficulty": 0,
        "is_boost": 0,
        "boost_story_event_id": 0,
    }
    payload.update(common)
    return payload


def _get_session(selected_gateway: SweepyGateway) -> dict[str, Any]:
    session = selected_gateway.request("GET", "/api/session")
    if not session.get("success"):
        raise RuntimeError("Sweepy is not logged in")
    return session


def _get_presets(selected_gateway: SweepyGateway) -> list[dict[str, Any]]:
    response = selected_gateway.request("GET", "/api/presets")
    presets = response.get("presets") if isinstance(response.get("presets"), list) else []
    return [preset for preset in presets if isinstance(preset, dict)]


def _find_preset(name: str, selected_gateway: SweepyGateway) -> dict[str, Any]:
    wanted = name.strip().casefold()
    for preset in _get_presets(selected_gateway):
        if str(preset.get("name") or "").strip().casefold() == wanted:
            return preset
    raise ValueError(f"Career preset not found: {name}")


mcp = FastMCP(
    "Sweepy Bot",
    instructions=INSTRUCTIONS,
    host=os.environ.get("SWEEPY_MCP_HOST", "127.0.0.1"),
    port=int(os.environ.get("SWEEPY_MCP_PORT", "8765")),
    streamable_http_path="/mcp",
    json_response=True,
    log_level=os.environ.get("SWEEPY_MCP_LOG_LEVEL", "WARNING").upper(),
)


@mcp.tool()
def list_accounts() -> dict[str, Any]:
    """List enabled Sweepy account names and their local web ports."""
    try:
        return {"success": True, "accounts": account_registry.list_accounts()}
    except Exception as exc:
        return {"success": False, "detail": str(exc), "accounts": []}


@mcp.tool()
def get_cached_account_snapshot(
    account: str = "",
    include_records: bool = False,
    veteran_limit: int = 200,
) -> dict[str, Any]:
    """Read the last successful load/index snapshot without calling the game API."""
    try:
        account_name, _selected_gateway = account_registry.resolve(account)
        snapshot = load_account_snapshot(_snapshot_runtime_dir(account_name))
        if snapshot is None:
            return {
                "success": False,
                "account": account_name,
                "cached": False,
                "detail": "No load/index snapshot exists for this account yet",
            }
        return {
            "success": True,
            "account": account_name,
            "cached": True,
            "snapshot": redact_sensitive(
                compact_account_snapshot(
                    snapshot,
                    include_records=bool(include_records),
                    veteran_limit=veteran_limit,
                )
            ),
        }
    except Exception as exc:
        return {"success": False, "detail": str(exc), "account": str(account or "")}


@mcp.tool()
def list_cached_veterans(
    account: str = "",
    limit: int = 200,
) -> dict[str, Any]:
    """List owned veterans from the last load/index cache while the bot may be offline."""
    result = get_cached_account_snapshot(
        account=account,
        include_records=False,
        veteran_limit=limit,
    )
    if not result.get("success"):
        return {
            "success": False,
            "account": result.get("account", str(account or "")),
            "cached": bool(result.get("cached")),
            "detail": result.get("detail", "Cached account data unavailable"),
            "veterans": [],
        }
    snapshot = result.get("snapshot") if isinstance(result.get("snapshot"), dict) else {}
    return {
        "success": True,
        "account": result["account"],
        "cached": True,
        "refreshed_at": snapshot.get("refreshed_at"),
        "count": int((snapshot.get("counts") or {}).get("owned_veterans") or 0),
        "veterans": snapshot.get("owned_veterans") or [],
    }


@mcp.tool()
def get_legacy_spark_rules() -> dict[str, Any]:
    """Return the configured legacy spark rules and the affinity-loop principle."""
    return {
        "success": True,
        "compatibility": {
            "double_circle": ">150",
            "single_circle": "50-150",
            "triangle": "<50",
        },
        "rules": redact_sensitive(DEFAULT_SPARK_RULESET),
        "principles": [
            "Legacy loops improve affinity and spark proc chance; they do not increase 3-star roll odds.",
            "Affinity comes from character compatibility and shared race wins; shared G1 wins are the planning priority.",
            "Stats, skills, and aptitudes affect spark quality or utility, not affinity itself.",
        ],
    }


@mcp.tool()
def scan_cached_legacy_loops(
    account: str = "",
    minimum_affinity: int = 151,
    max_characters: int = 12,
    records_per_character: int = 2,
    limit: int = 10,
) -> dict[str, Any]:
    """Rank four-character legacy-loop pools from the cached load/index only."""
    try:
        account_name, _selected_gateway = account_registry.resolve(account)
        snapshot = load_account_snapshot(_snapshot_runtime_dir(account_name))
        if snapshot is None:
            return {
                "success": False,
                "account": account_name,
                "cached": False,
                "detail": "No load/index snapshot exists for this account yet",
                "pools": [],
            }
        records = (snapshot.get("records") or {}).get("trained_chara") or []
        names = {
            int(row.get("instance_id") or row.get("trained_chara_id") or 0): str(
                row.get("name") or ""
            )
            for row in (snapshot.get("owned_veterans") or [])
            if isinstance(row, dict)
            and int(row.get("instance_id") or row.get("trained_chara_id") or 0) > 0
        }
        mdb_path = master_data.configured_master_mdb_path(Path(__file__).resolve().parent)
        scan = scan_legacy_loop_pools(
            records,
            mdb_path=mdb_path,
            veteran_names=names,
            minimum_affinity=max(0, int(minimum_affinity)),
            max_characters=max_characters,
            records_per_character=records_per_character,
            limit=limit,
        )
        return {
            "success": True,
            "account": account_name,
            "cached": True,
            "refreshed_at": snapshot.get("refreshed_at"),
            **redact_sensitive(scan),
        }
    except Exception as exc:
        return {
            "success": False,
            "account": str(account or ""),
            "detail": str(exc),
            "pools": [],
        }


@mcp.tool()
def preview_shared_g1_agenda(
    terrain: str = "Turf",
    distances: list[str] | None = None,
    protect_summer_camp: bool = True,
    maximum_consecutive_races: int = 3,
    prefer_senior_repeats: bool = True,
) -> dict[str, Any]:
    """Build an offline shared-G1 race agenda from generated master race data."""
    try:
        path = Path(__file__).resolve().parent / "public" / "assets" / "data" / "uma_race_data.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        rows = raw.get("races") if isinstance(raw, dict) else raw
        if not isinstance(rows, list):
            raise RuntimeError("uma_race_data.json has no races array")
        agenda = build_shared_g1_agenda(
            rows,
            terrain=terrain,
            distances=distances or ["Mile", "Medium", "Long"],
            protect_summer_camp=bool(protect_summer_camp),
            maximum_consecutive_races=maximum_consecutive_races,
            prefer_senior_repeats=bool(prefer_senior_repeats),
        )
        return {"success": True, **agenda}
    except Exception as exc:
        return {"success": False, "detail": str(exc), "agenda": [], "skipped": []}


@mcp.tool()
def get_account_runtime(account: str = "") -> dict[str, Any]:
    """Read one account's managed process, API readiness, and workflow activity."""
    try:
        account_name, _selected_gateway = account_registry.resolve(account)
        return {
            "success": True,
            "account": account_name,
            "runtime": redact_sensitive(supervisor.status(account_name)),
            "workflow_lease": redact_sensitive(
                job_store.get_workflow_lease(account_name)
            ),
        }
    except Exception as exc:
        return {"success": False, "detail": str(exc), "account": str(account or "")}


@mcp.tool()
def get_bot_logs(account: str = "", lines: int = 100) -> dict[str, Any]:
    """Read a capped, redacted tail of one account's supervisor log."""
    try:
        account_name, _selected_gateway = account_registry.resolve(account)
        return redact_sensitive(
            supervisor.tail_logs(account_name, lines=max(1, min(int(lines), 500)))
        )
    except Exception as exc:
        return {
            "success": False,
            "detail": str(exc),
            "account": str(account or ""),
            "lines": [],
        }


@mcp.tool()
def launch_bot(
    account: str = "",
    confirm: bool = False,
    operation_id: str = "",
) -> dict[str, Any]:
    """Launch one account's detached Sweepy launcher. Requires confirm=true."""
    try:
        account_name, _selected_gateway = account_registry.resolve(account)
    except Exception as exc:
        return {"success": False, "detail": str(exc), "account": str(account or "")}
    details = {"account": account_name}
    if not confirm:
        return _requires_confirmation("launch_bot", details, operation_id)
    return _execute_mutation(
        account=account_name,
        action="launch_bot",
        operation_id=operation_id,
        arguments=details,
        callback=lambda: supervisor.launch(account_name),
    )


@mcp.tool()
def stop_bot(
    account: str = "",
    timeout_seconds: float = 10,
    force: bool = False,
    confirm: bool = False,
    operation_id: str = "",
) -> dict[str, Any]:
    """Stop one managed launcher process. Requires confirm=true; force escalates to SIGKILL."""
    try:
        account_name, _selected_gateway = account_registry.resolve(account)
    except Exception as exc:
        return {"success": False, "detail": str(exc), "account": str(account or "")}
    timeout_seconds = max(0.0, min(float(timeout_seconds), 60.0))
    details = {
        "account": account_name,
        "force": bool(force),
        "timeout_seconds": timeout_seconds,
    }
    if not confirm:
        return _requires_confirmation("stop_bot", details, operation_id)
    return _execute_mutation(
        account=account_name,
        action="stop_bot",
        operation_id=operation_id,
        arguments=details,
        callback=lambda: supervisor.stop(
            account_name,
            timeout_seconds=timeout_seconds,
            force=bool(force),
        ),
        release_workflow=True,
        mutation_ttl_seconds=timeout_seconds + 30,
    )


@mcp.tool()
def restart_bot(
    account: str = "",
    timeout_seconds: float = 10,
    force: bool = False,
    confirm: bool = False,
    operation_id: str = "",
) -> dict[str, Any]:
    """Restart one managed launcher process. Requires confirm=true."""
    try:
        account_name, _selected_gateway = account_registry.resolve(account)
    except Exception as exc:
        return {"success": False, "detail": str(exc), "account": str(account or "")}
    timeout_seconds = max(0.0, min(float(timeout_seconds), 60.0))
    details = {
        "account": account_name,
        "force": bool(force),
        "timeout_seconds": timeout_seconds,
    }
    if not confirm:
        return _requires_confirmation("restart_bot", details, operation_id)
    return _execute_mutation(
        account=account_name,
        action="restart_bot",
        operation_id=operation_id,
        arguments=details,
        callback=lambda: supervisor.restart(
            account_name,
            timeout_seconds=timeout_seconds,
            force=bool(force),
        ),
        release_workflow=True,
        mutation_ttl_seconds=timeout_seconds + 30,
    )


@mcp.tool()
def wait_until_ready(
    account: str = "",
    timeout_seconds: float = 30,
    require_login: bool = False,
) -> dict[str, Any]:
    """Wait for one account's local API, optionally requiring a logged-in session."""
    try:
        account_name, _selected_gateway = account_registry.resolve(account)
        result = redact_sensitive(
            supervisor.wait_until_ready(
                account_name,
                timeout_seconds=max(0.0, min(float(timeout_seconds), 300.0)),
                require_login=bool(require_login),
            )
        )
        result.setdefault("account", account_name)
        return result
    except Exception as exc:
        return {"success": False, "detail": str(exc), "account": str(account or "")}


@mcp.tool()
def get_recent_operations(account: str = "", limit: int = 20) -> dict[str, Any]:
    """List compact durable MCP mutations for one account."""
    try:
        account_name, _selected_gateway = account_registry.resolve(account)
        return {
            "success": True,
            "account": account_name,
            "operations": redact_sensitive(
                job_store.recent_operations(
                    account_name,
                    limit=max(1, min(int(limit), 100)),
                )
            ),
        }
    except Exception as exc:
        return {
            "success": False,
            "detail": str(exc),
            "account": str(account or ""),
            "operations": [],
        }


def _campaign_context(
    campaign_id: str,
) -> tuple[dict[str, Any], str, SweepyGateway]:
    campaign = campaign_store.get(str(campaign_id))
    account_name, selected_gateway = account_registry.resolve(campaign["account"])
    return campaign, account_name, selected_gateway


def _require_campaign_lease(account: str) -> dict[str, Any]:
    lease = job_store.get_workflow_lease(account)
    if not lease or lease.get("workflow_type") != "campaign":
        raise LeaseConflict(
            f"Account {account} has no active campaign lease; start or resume the campaign first"
        )
    return lease


def _parent_row_id(row: Any) -> int:
    if not isinstance(row, dict):
        return 0
    return int(
        row.get("instance_id")
        or row.get("trained_chara_id")
        or row.get("id")
        or 0
    )


def _rank_label(value: Any) -> str:
    labels = [
        "G", "G+", "F", "F+", "E", "E+", "D", "D+", "C", "C+",
        "B", "B+", "A", "A+", "S", "S+", "SS", "SS+", "UG", "UF",
        "UE", "UD",
    ]
    if isinstance(value, str) and not value.strip().isdigit():
        return value.strip().upper() or "G"
    try:
        index = int(value or 1) - 1
    except (TypeError, ValueError):
        index = 0
    return labels[max(0, min(index, len(labels) - 1))]


def _factor_rows(value: Any) -> list[dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    result = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or row.get("factor_name") or "").strip()
        if not name:
            continue
        result.append(
            {
                "name": name,
                "stars": int(row.get("stars") or row.get("star") or row.get("level") or 0),
            }
        )
    return result


def _campaign_candidate_from_parent(
    parent: dict[str, Any],
    lineage_summary: dict[str, Any],
) -> dict[str, Any]:
    tree = parent.get("tree") if isinstance(parent.get("tree"), dict) else {}
    self_node = tree.get("self") if isinstance(tree.get("self"), dict) else {}
    candidate_factors = _factor_rows(parent.get("factors") or self_node.get("factors"))
    lineage_factors = []
    for node in tree.values():
        if isinstance(node, dict):
            lineage_factors.extend(_factor_rows(node.get("factors")))
    if not lineage_factors:
        lineage_factors = list(candidate_factors)

    raw_stats = parent.get("stats") if isinstance(parent.get("stats"), dict) else parent
    stats = {
        "speed": int(raw_stats.get("speed") or 0),
        "stamina": int(raw_stats.get("stamina") or 0),
        "power": int(raw_stats.get("power") or 0),
        "guts": int(raw_stats.get("guts") or 0),
        "wisdom": int(raw_stats.get("wisdom") or raw_stats.get("wiz") or 0),
    }
    aptitudes = parent.get("aptitudes") if isinstance(parent.get("aptitudes"), dict) else {}
    wins = parent.get("wins")
    wins_count = len(wins) if isinstance(wins, list) else int(wins or 0)
    compatibility = int(lineage_summary.get("compat_total") or 0)
    race_score = int(lineage_summary.get("race_score") or 0)
    return {
        "trained_chara_id": _parent_row_id(parent),
        "name": str(parent.get("name") or parent.get("chara_name") or ""),
        "rank": _rank_label(parent.get("rank")),
        "stats": stats,
        "aptitudes": aptitudes,
        "candidate_factors": candidate_factors,
        "lineage_factors": lineage_factors,
        "compatibility_score": min(100, compatibility),
        "race_history_score": min(100, max(wins_count * 5, race_score * 2)),
    }


@mcp.tool()
def preview_parent_campaign(spec: ParentCampaignSpec) -> dict[str, Any]:
    """Validate and preview a durable parent-building campaign without creating it."""
    try:
        validated = ParentCampaignSpec.model_validate(spec)
        account_name, _selected_gateway = account_registry.resolve(validated.account)
        dumped = validated.model_dump(mode="json")
        strategy = dumped["strategy"]
        warnings = []
        if int(strategy.get("maximum_carats") or 0) > 0:
            warnings.append("Campaign may spend carats up to its configured hard limit.")
        if int(strategy.get("maximum_clocks") or 0) > 0:
            warnings.append("Campaign may spend clocks up to its configured hard limit.")
        return {
            "success": True,
            "account": account_name,
            "spec": dumped,
            "budget": {
                "maximum_runs": strategy["maximum_runs"],
                "maximum_carats": strategy["maximum_carats"],
                "maximum_clocks": strategy["maximum_clocks"],
                "maximum_runtime_hours": strategy["maximum_runtime_hours"],
            },
            "warnings": warnings,
        }
    except Exception as exc:
        return {"success": False, "detail": str(exc)}


@mcp.tool()
def create_parent_campaign(
    spec: ParentCampaignSpec,
    confirm: bool = False,
    operation_id: str = "",
) -> dict[str, Any]:
    """Create a durable parent campaign in DRAFT state. Requires confirm=true."""
    try:
        validated = ParentCampaignSpec.model_validate(spec)
        account_name, _selected_gateway = account_registry.resolve(validated.account)
    except Exception as exc:
        return {"success": False, "detail": str(exc)}
    dumped = validated.model_dump(mode="json")
    details = {"account": account_name, "spec": dumped}
    if not confirm:
        return _requires_confirmation("create_parent_campaign", details, operation_id)
    return _execute_mutation(
        account=account_name,
        action="create_parent_campaign",
        operation_id=operation_id,
        arguments=details,
        callback=lambda: {
            "success": True,
            "campaign": campaign_store.create(validated),
        },
    )


@mcp.tool()
def list_parent_campaigns(account: str = "", limit: int = 20) -> dict[str, Any]:
    """List durable parent campaigns for one account."""
    try:
        account_name, _selected_gateway = account_registry.resolve(account)
        return {
            "success": True,
            "account": account_name,
            "campaigns": campaign_store.list(
                account=account_name,
                limit=max(1, min(int(limit), 100)),
            ),
        }
    except Exception as exc:
        return {
            "success": False,
            "detail": str(exc),
            "account": str(account or ""),
            "campaigns": [],
        }


@mcp.tool()
def get_parent_campaign(campaign_id: str) -> dict[str, Any]:
    """Read one campaign with recent events and ranked candidates."""
    try:
        campaign, account_name, _selected_gateway = _campaign_context(campaign_id)
        return {
            "success": True,
            "account": account_name,
            "campaign": campaign,
            "events": campaign_store.recent_events(campaign_id, limit=30),
            "candidates": campaign_store.list_candidates(campaign_id, limit=30),
        }
    except Exception as exc:
        return {"success": False, "detail": str(exc), "campaign_id": campaign_id}


@mcp.tool()
def get_parent_campaign_summary(campaign_id: str) -> dict[str, Any]:
    """Return a compact Discord-friendly campaign progress summary."""
    try:
        campaign, account_name, _selected_gateway = _campaign_context(campaign_id)
        candidates = campaign_store.list_candidates(campaign_id, limit=1)
        best = candidates[0] if candidates else None
        strategy = campaign["spec"]["strategy"]
        best_summary = None
        if best:
            evaluation = best.get("evaluation") if isinstance(best.get("evaluation"), dict) else {}
            best_summary = {
                "candidate_id": best["candidate_id"],
                "trained_chara_id": best["trained_chara_id"],
                "name": best["name"],
                "score": best["score"],
                "accepted": best["accepted"],
                "selected": best["selected"],
                "decision": evaluation.get("decision") or "",
                "matched_targets": evaluation.get("matched_targets") or [],
                "missing_targets": evaluation.get("missing_targets") or [],
            }
        return {
            "success": True,
            "account": account_name,
            "campaign_id": campaign_id,
            "state": campaign["state"],
            "next_action": campaign["next_action"],
            "needs_user_input": campaign["state"] == CampaignState.NEEDS_USER_INPUT.value,
            "usage": campaign["usage"],
            "budget": {
                "maximum_runs": int(strategy["maximum_runs"]),
                "maximum_carats": int(strategy.get("maximum_carats") or 0),
                "maximum_clocks": int(strategy.get("maximum_clocks") or 0),
                "maximum_runtime_hours": float(strategy["maximum_runtime_hours"]),
            },
            "best_candidate": best_summary,
            "error": campaign.get("error") or "",
        }
    except Exception as exc:
        return {"success": False, "detail": str(exc), "campaign_id": campaign_id}


@mcp.tool()
def start_parent_campaign(
    campaign_id: str,
    confirm: bool = False,
    operation_id: str = "",
) -> dict[str, Any]:
    """Start campaign orchestration and acquire the account campaign lease."""
    try:
        _campaign, account_name, selected_gateway = _campaign_context(campaign_id)
    except Exception as exc:
        return {"success": False, "detail": str(exc), "campaign_id": campaign_id}
    details = {"account": account_name, "campaign_id": campaign_id}
    if not confirm:
        return _requires_confirmation("start_parent_campaign", details, operation_id)

    def start_campaign() -> dict[str, Any]:
        runtime = supervisor.status(account_name)
        bot_state = get_bot_state(account=account_name)
        if not bot_state.get("success"):
            bot_state = {}
        return {
            "success": True,
            "campaign": campaign_runner.start(
                campaign_id,
                runtime=runtime,
                bot_state=bot_state,
            ),
        }

    return _execute_mutation(
        account=account_name,
        action="start_parent_campaign",
        operation_id=operation_id,
        arguments=details,
        callback=start_campaign,
        selected_gateway=selected_gateway,
        workflow_type="campaign",
        retain_workflow=True,
    )


@mcp.tool()
def advance_parent_campaign(
    campaign_id: str,
    operation_id: str = "",
) -> dict[str, Any]:
    """Safely reconcile campaign state after bot launch, login, or Career completion."""
    try:
        _campaign, account_name, _selected_gateway = _campaign_context(campaign_id)
    except Exception as exc:
        return {"success": False, "detail": str(exc), "campaign_id": campaign_id}
    details = {"account": account_name, "campaign_id": campaign_id}

    def reconcile_campaign() -> dict[str, Any]:
        runtime = supervisor.status(account_name)
        bot_state = get_bot_state(account=account_name)
        if not bot_state.get("success"):
            bot_state = {}
        campaign = campaign_runner.reconcile(
            campaign_id,
            runtime=runtime,
            bot_state=bot_state,
        )
        if campaign["state"] in {
            CampaignState.COMPLETED.value,
            CampaignState.FAILED.value,
            CampaignState.CANCELLED.value,
        }:
            job_store.release_workflow_lease(
                account_name,
                workflow_type="campaign",
            )
        return {"success": True, "campaign": campaign}

    return _execute_mutation(
        account=account_name,
        action="advance_parent_campaign",
        operation_id=operation_id,
        arguments=details,
        callback=reconcile_campaign,
    )


@mcp.tool()
def pause_parent_campaign(
    campaign_id: str,
    confirm: bool = False,
    operation_id: str = "",
) -> dict[str, Any]:
    """Pause a parent campaign and release its account workflow lease."""
    try:
        _campaign, account_name, _selected_gateway = _campaign_context(campaign_id)
    except Exception as exc:
        return {"success": False, "detail": str(exc), "campaign_id": campaign_id}
    details = {"account": account_name, "campaign_id": campaign_id}
    if not confirm:
        return _requires_confirmation("pause_parent_campaign", details, operation_id)
    return _execute_mutation(
        account=account_name,
        action="pause_parent_campaign",
        operation_id=operation_id,
        arguments=details,
        callback=lambda: {
            "success": True,
            "campaign": campaign_runner.pause(campaign_id),
        },
        workflow_type="campaign",
        release_workflow=True,
    )


@mcp.tool()
def resume_parent_campaign(
    campaign_id: str,
    confirm: bool = False,
    operation_id: str = "",
) -> dict[str, Any]:
    """Resume a paused parent campaign and reacquire its account workflow lease."""
    try:
        _campaign, account_name, selected_gateway = _campaign_context(campaign_id)
    except Exception as exc:
        return {"success": False, "detail": str(exc), "campaign_id": campaign_id}
    details = {"account": account_name, "campaign_id": campaign_id}
    if not confirm:
        return _requires_confirmation("resume_parent_campaign", details, operation_id)

    def resume_campaign() -> dict[str, Any]:
        campaign_runner.resume(campaign_id)
        runtime = supervisor.status(account_name)
        bot_state = get_bot_state(account=account_name)
        if not bot_state.get("success"):
            bot_state = {}
        return {
            "success": True,
            "campaign": campaign_runner.reconcile(
                campaign_id,
                runtime=runtime,
                bot_state=bot_state,
            ),
        }

    return _execute_mutation(
        account=account_name,
        action="resume_parent_campaign",
        operation_id=operation_id,
        arguments=details,
        callback=resume_campaign,
        selected_gateway=selected_gateway,
        workflow_type="campaign",
        retain_workflow=True,
    )


@mcp.tool()
def cancel_parent_campaign(
    campaign_id: str,
    reason: str = "",
    confirm: bool = False,
    operation_id: str = "",
) -> dict[str, Any]:
    """Cancel a parent campaign and release its account workflow lease."""
    try:
        _campaign, account_name, _selected_gateway = _campaign_context(campaign_id)
    except Exception as exc:
        return {"success": False, "detail": str(exc), "campaign_id": campaign_id}
    details = {
        "account": account_name,
        "campaign_id": campaign_id,
        "reason": str(reason or "")[:500],
    }
    if not confirm:
        return _requires_confirmation("cancel_parent_campaign", details, operation_id)
    return _execute_mutation(
        account=account_name,
        action="cancel_parent_campaign",
        operation_id=operation_id,
        arguments=details,
        callback=lambda: {
            "success": True,
            "campaign": campaign_runner.cancel(campaign_id, reason=reason),
        },
        workflow_type="campaign",
        release_workflow=True,
    )


@mcp.tool()
def list_parent_candidates(campaign_id: str, limit: int = 30) -> dict[str, Any]:
    """List ranked candidates produced by one parent campaign."""
    try:
        _campaign, account_name, _selected_gateway = _campaign_context(campaign_id)
        return {
            "success": True,
            "account": account_name,
            "campaign_id": campaign_id,
            "candidates": campaign_store.list_candidates(
                campaign_id,
                limit=max(1, min(int(limit), 100)),
            ),
        }
    except Exception as exc:
        return {
            "success": False,
            "detail": str(exc),
            "campaign_id": campaign_id,
            "candidates": [],
        }


@mcp.tool()
def select_parent_candidate(
    campaign_id: str,
    candidate_id: str,
    confirm: bool = False,
    operation_id: str = "",
) -> dict[str, Any]:
    """Select a candidate when a campaign requires user input."""
    try:
        _campaign, account_name, _selected_gateway = _campaign_context(campaign_id)
    except Exception as exc:
        return {"success": False, "detail": str(exc), "campaign_id": campaign_id}
    details = {
        "account": account_name,
        "campaign_id": campaign_id,
        "candidate_id": candidate_id,
    }
    if not confirm:
        return _requires_confirmation("select_parent_candidate", details, operation_id)

    def select_candidate() -> dict[str, Any]:
        result = campaign_runner.select_candidate(campaign_id, candidate_id)
        if result["campaign"]["state"] == CampaignState.COMPLETED.value:
            job_store.release_workflow_lease(
                account_name,
                workflow_type="campaign",
            )
        return {"success": True, **result}

    return _execute_mutation(
        account=account_name,
        action="select_parent_candidate",
        operation_id=operation_id,
        arguments=details,
        callback=select_candidate,
    )


@mcp.tool()
def prepare_parent_campaign_run(
    campaign_id: str,
    pool: str = "both",
    confirm: bool = False,
    operation_id: str = "",
) -> dict[str, Any]:
    """Choose the best supported lineage and save it into current account selection."""
    try:
        campaign, account_name, selected_gateway = _campaign_context(campaign_id)
    except Exception as exc:
        return {"success": False, "detail": str(exc), "campaign_id": campaign_id}
    details = {
        "account": account_name,
        "campaign_id": campaign_id,
        "pool": str(pool or "both").lower(),
    }
    if not confirm:
        return _requires_confirmation("prepare_parent_campaign_run", details, operation_id)

    def prepare_lineage() -> dict[str, Any]:
        _require_campaign_lease(account_name)
        current = campaign_store.get(campaign_id)
        if current["state"] != CampaignState.SELECTING_LINEAGE.value:
            raise ValueError(
                f"Campaign {campaign_id} must be in SELECTING_LINEAGE, not {current['state']}"
            )
        session = _get_session(selected_gateway)
        inheritance_payload = build_inheritance_request(
            ParentCampaignSpec.model_validate(current["spec"]),
            session,
            pool=pool,
        )
        recommendation = selected_gateway.request(
            "POST",
            "/api/inheritance/recommend",
            inheritance_payload,
        )
        setup = choose_lineage_setup(recommendation)
        resolved = resolve_lineage_selection(session, setup)
        selection_result = selected_gateway.request(
            "POST",
            "/api/selection",
            {"selection": resolved["selection"]},
        )
        if selection_result.get("success") is False:
            return selection_result

        baseline_parent_ids = sorted(
            {
                _parent_row_id(row)
                for row in (session.get("parents") or [])
                if _parent_row_id(row) > 0
            }
        )
        campaign_store.update_context(
            campaign_id,
            {
                "baseline_parent_ids": baseline_parent_ids,
                "lineage": {
                    "setup": setup,
                    "summary": resolved["summary"],
                    "inheritance_request": inheritance_payload,
                },
            },
        )
        updated = campaign_store.set_next_action(campaign_id, "start_career")
        return {
            "success": True,
            "campaign": updated,
            "lineage": resolved["summary"],
        }

    return _execute_mutation(
        account=account_name,
        action="prepare_parent_campaign_run",
        operation_id=operation_id,
        arguments=details,
        callback=prepare_lineage,
    )


@mcp.tool()
def run_parent_campaign_career(
    campaign_id: str,
    confirm: bool = False,
    operation_id: str = "",
) -> dict[str, Any]:
    """Start one Career run for a prepared campaign. Requires confirm=true."""
    try:
        campaign, account_name, selected_gateway = _campaign_context(campaign_id)
    except Exception as exc:
        return {"success": False, "detail": str(exc), "campaign_id": campaign_id}
    details = {"account": account_name, "campaign_id": campaign_id}
    if not confirm:
        return _requires_confirmation("run_parent_campaign_career", details, operation_id)
    resolved_operation_id = _normalize_operation_id(operation_id)

    def start_campaign_career() -> dict[str, Any]:
        _require_campaign_lease(account_name)
        current = campaign_store.get(campaign_id)
        if current["state"] != CampaignState.SELECTING_LINEAGE.value:
            raise ValueError(
                f"Campaign {campaign_id} must be in SELECTING_LINEAGE, not {current['state']}"
            )
        lineage = current.get("context", {}).get("lineage") or {}
        setup = lineage.get("setup") if isinstance(lineage, dict) else None
        if not isinstance(setup, dict):
            raise LineagePlanningError(
                "Campaign has no prepared lineage; call prepare_parent_campaign_run first"
            )

        campaign_store.assert_within_budget(campaign_id)
        strategy = current["spec"]["strategy"]
        if current["usage"]["runs"] >= int(strategy["maximum_runs"]):
            raise ValueError("Campaign maximum_runs budget is exhausted")

        session = _get_session(selected_gateway)
        resolved = resolve_lineage_selection(session, setup)
        selection_result = selected_gateway.request(
            "POST",
            "/api/selection",
            {"selection": resolved["selection"]},
        )
        if selection_result.get("success") is False:
            return selection_result

        preset = _find_preset(strategy["preset_name"], selected_gateway)
        payload = build_career_payload(
            {**session, "selection": resolved["selection"]},
            preset,
            max_steps=2500,
            burn_clocks=bool(strategy.get("use_clocks")),
            dev_mode=True,
        )
        payload["tp_mode"] = strategy.get("tp_mode", "wait")
        payload["stop_on_empty_tp"] = False
        response = selected_gateway.request("POST", "/api/career/run", payload)
        if response.get("success") is False:
            return response

        updated = campaign_runner.begin_run(campaign_id)
        campaign_store.update_context(
            campaign_id,
            {
                "active_run": {
                    "operation_id": resolved_operation_id,
                    "preset_name": strategy["preset_name"],
                    "lineage_summary": resolved["summary"],
                }
            },
        )
        return {
            "success": True,
            "campaign": campaign_store.get(campaign_id),
            "runner": response.get("runner") or {},
            "account_state": response.get("account") or {},
        }

    return _execute_mutation(
        account=account_name,
        action="run_parent_campaign_career",
        operation_id=resolved_operation_id,
        arguments=details,
        callback=start_campaign_career,
    )


@mcp.tool()
def collect_parent_campaign_result(
    campaign_id: str,
    operation_id: str = "",
) -> dict[str, Any]:
    """Collect and evaluate the new veteran after a campaign Career finishes."""
    try:
        campaign, account_name, selected_gateway = _campaign_context(campaign_id)
    except Exception as exc:
        return {"success": False, "detail": str(exc), "campaign_id": campaign_id}

    runner_response = selected_gateway.request("GET", "/api/career/runner")
    runner_payload = (
        runner_response.get("runner")
        if isinstance(runner_response.get("runner"), dict)
        else {}
    )
    if runner_payload.get("running"):
        return {
            "success": False,
            "detail": "Career is still running",
            "account": account_name,
            "campaign_id": campaign_id,
        }

    current = campaign_store.get(campaign_id)
    if current["state"] == CampaignState.RUNNING_CAREER.value:
        campaign_runner.reconcile(
            campaign_id,
            runtime=supervisor.status(account_name),
            bot_state={"career_runner": runner_payload},
        )
    details = {"account": account_name, "campaign_id": campaign_id}

    def collect_result() -> dict[str, Any]:
        _require_campaign_lease(account_name)
        current_campaign = campaign_store.get(campaign_id)
        if current_campaign["state"] != CampaignState.EVALUATING_RESULT.value:
            raise ValueError(
                f"Campaign {campaign_id} must be in EVALUATING_RESULT, "
                f"not {current_campaign['state']}"
            )
        refreshed = selected_gateway.request("POST", "/api/account/refresh")
        if refreshed.get("success") is False:
            return refreshed
        parents = refreshed.get("parents") if isinstance(refreshed.get("parents"), list) else []
        baseline_ids = {
            int(value)
            for value in current_campaign.get("context", {}).get("baseline_parent_ids", [])
            if int(value or 0) > 0
        }
        new_rows = [row for row in parents if _parent_row_id(row) not in baseline_ids]
        if not new_rows:
            raise ValueError("No new trained veteran was found after the completed Career")
        new_rows.sort(
            key=lambda row: (
                float(row.get("acquired_at") or 0),
                int(row.get("rank_score") or 0),
                _parent_row_id(row),
            ),
            reverse=True,
        )
        parent = new_rows[0]
        lineage_summary = (
            current_campaign.get("context", {}).get("lineage", {}).get("summary", {})
        )
        candidate = _campaign_candidate_from_parent(parent, lineage_summary)
        existing_candidates = campaign_store.list_candidates(campaign_id)
        baseline_score = (
            max(float(row["score"]) for row in existing_candidates)
            if existing_candidates
            else None
        )
        result = campaign_runner.record_candidate(
            campaign_id,
            candidate,
            baseline_score=baseline_score,
        )
        campaign_store.update_context(
            campaign_id,
            {
                "baseline_parent_ids": sorted(
                    {_parent_row_id(row) for row in parents if _parent_row_id(row) > 0}
                ),
                "last_result": {
                    "trained_chara_id": candidate["trained_chara_id"],
                    "score": result["evaluation"]["score"],
                    "decision": result["evaluation"]["decision"],
                },
                "active_run": {},
            },
        )
        final_campaign = campaign_store.get(campaign_id)
        if final_campaign["state"] in {
            CampaignState.COMPLETED.value,
            CampaignState.FAILED.value,
            CampaignState.CANCELLED.value,
        }:
            job_store.release_workflow_lease(
                account_name,
                workflow_type="campaign",
            )
        return {
            "success": True,
            "campaign": final_campaign,
            "candidate": result["candidate"],
            "evaluation": result["evaluation"],
        }

    return _execute_mutation(
        account=account_name,
        action="collect_parent_campaign_result",
        operation_id=operation_id,
        arguments=details,
        callback=collect_result,
    )


@mcp.tool()
def get_bot_state(account: str = "") -> dict[str, Any]:
    """Read one account's current session, Career runner, Dailies runner, and delay state."""
    try:
        account_name, selected_gateway = account_registry.resolve(account)
        session = selected_gateway.request("GET", "/api/session")
        career = selected_gateway.request("GET", "/api/career/runner")
        dailies = selected_gateway.request("GET", "/api/dailies/status")
        delay = selected_gateway.request("GET", "/api/settings/turn-delay")
        workflow_lease = _sync_workflow_lease(account_name, career, dailies)
        return {
            "success": True,
            "account": account_name,
            "session": compact_session(session),
            "career_runner": _compact_runner(career),
            "dailies": _compact_dailies(dailies),
            "workflow_lease": redact_sensitive(workflow_lease),
            "turn_delay": redact_sensitive(delay),
        }
    except Exception as exc:
        return {"success": False, "detail": str(exc), "account": str(account or "")}


@mcp.tool()
def list_career_presets(account: str = "") -> dict[str, Any]:
    """List career presets without exposing their large internal configuration."""
    try:
        account_name, selected_gateway = account_registry.resolve(account)
        rows = []
        for preset in _get_presets(selected_gateway):
            rows.append(
                {
                    "name": preset.get("name"),
                    "scenario_id": int(preset.get("scenario_id") or preset.get("scenario") or 4),
                    "tp_mode": "wait" if preset.get("tp_mode") == "wait" else "carat",
                    "run_delay_min_min": int(preset.get("run_delay_min_min") or 0),
                    "run_delay_max_min": int(preset.get("run_delay_max_min") or 0),
                }
            )
        return {"success": True, "account": account_name, "presets": rows}
    except Exception as exc:
        return {"success": False, "detail": str(exc), "account": str(account or ""), "presets": []}


@mcp.tool()
def get_legend_races(account: str = "") -> dict[str, Any]:
    """List Daily Legend Race bosses currently offered by the game."""
    try:
        account_name, selected_gateway = account_registry.resolve(account)
        result = redact_sensitive(
            selected_gateway.request("POST", "/api/dailies/legend_options")
        )
        result["account"] = account_name
        return result
    except Exception as exc:
        return {
            "success": False,
            "detail": str(exc),
            "account": str(account or ""),
            "legend_races": [],
        }


@mcp.tool()
def run_dailies(
    account: str = "",
    team_trials: bool = True,
    daily_races: bool = False,
    legend_races: bool = False,
    daily_shop: bool = False,
    trained_chara_id: int = 0,
    opponent_strength: int = 1,
    legend_race_id: int = 0,
    confirm: bool = False,
    operation_id: str = "",
) -> dict[str, Any]:
    """Run selected Dailies. Requires confirm=true because it spends RP/attempts/gold."""
    try:
        account_name, selected_gateway = account_registry.resolve(account)
    except Exception as exc:
        return {"success": False, "detail": str(exc), "account": str(account or "")}

    details = {
        "account": account_name,
        "team_trials": bool(team_trials),
        "daily_races": bool(daily_races),
        "legend_races": bool(legend_races),
        "daily_shop": bool(daily_shop),
        "trained_chara_id": int(trained_chara_id),
        "opponent_strength": int(opponent_strength),
        "legend_race_id": int(legend_race_id),
    }
    if not confirm:
        return _requires_confirmation("run_dailies", details, operation_id)
    if not any((team_trials, daily_races, legend_races, daily_shop)):
        return {"success": False, "detail": "Select at least one daily task"}
    if opponent_strength not in (1, 2, 3):
        return {"success": False, "detail": "opponent_strength must be 1, 2, or 3"}

    def start_dailies() -> dict[str, Any]:
        selected_veteran = int(trained_chara_id)
        if (daily_races or legend_races) and selected_veteran <= 0:
            selected_veteran = _find_recommended_veteran(_get_session(selected_gateway))
        if (daily_races or legend_races) and selected_veteran <= 0:
            return {"success": False, "detail": "No owned veteran is available"}
        if legend_races and legend_race_id <= 0:
            return {"success": False, "detail": "legend_race_id is required"}
        return selected_gateway.request(
            "POST",
            "/api/dailies/run",
            {
                "team_trials": bool(team_trials),
                "daily_races": bool(daily_races),
                "legend_races": bool(legend_races),
                "daily_shop": bool(daily_shop),
                "trained_chara_id": selected_veteran,
                "opponent_strength": int(opponent_strength),
                "legend_race_id": int(legend_race_id),
            },
        )

    return _execute_mutation(
        account=account_name,
        action="run_dailies",
        operation_id=operation_id,
        arguments=details,
        callback=start_dailies,
        selected_gateway=selected_gateway,
        workflow_type="dailies",
        retain_workflow=True,
    )


@mcp.tool()
def stop_dailies(
    account: str = "",
    operation_id: str = "",
) -> dict[str, Any]:
    """Safely request one account's Dailies runner to stop."""
    try:
        account_name, selected_gateway = account_registry.resolve(account)
    except Exception as exc:
        return {"success": False, "detail": str(exc), "account": str(account or "")}
    return _execute_mutation(
        account=account_name,
        action="stop_dailies",
        operation_id=operation_id,
        arguments={"account": account_name},
        callback=lambda: selected_gateway.request("POST", "/api/dailies/stop"),
        workflow_type="dailies",
        release_workflow=True,
    )


@mcp.tool()
def run_career(
    preset_name: str,
    account: str = "",
    max_steps: int = 2500,
    burn_clocks: bool = False,
    dev_mode: bool = True,
    confirm: bool = False,
    operation_id: str = "",
) -> dict[str, Any]:
    """Start/resume Career using the current Sweepy UI selection. Requires confirm=true."""
    try:
        account_name, selected_gateway = account_registry.resolve(account)
    except Exception as exc:
        return {"success": False, "detail": str(exc), "account": str(account or "")}

    details = {
        "account": account_name,
        "preset_name": preset_name,
        "max_steps": int(max_steps),
        "burn_clocks": bool(burn_clocks),
        "dev_mode": bool(dev_mode),
    }
    if not confirm:
        return _requires_confirmation("run_career", details, operation_id)

    def start_career() -> dict[str, Any]:
        session = _get_session(selected_gateway)
        preset = _find_preset(preset_name, selected_gateway)
        payload = build_career_payload(
            session,
            preset,
            max_steps=max_steps,
            burn_clocks=burn_clocks,
            dev_mode=dev_mode,
        )
        return selected_gateway.request("POST", "/api/career/run", payload)

    return _execute_mutation(
        account=account_name,
        action="run_career",
        operation_id=operation_id,
        arguments=details,
        callback=start_career,
        selected_gateway=selected_gateway,
        workflow_type="career",
        retain_workflow=True,
    )


@mcp.tool()
def stop_career(
    account: str = "",
    operation_id: str = "",
) -> dict[str, Any]:
    """Safely stop one account's Career runner and multi-career loop."""
    try:
        account_name, selected_gateway = account_registry.resolve(account)
    except Exception as exc:
        return {"success": False, "detail": str(exc), "account": str(account or "")}
    return _execute_mutation(
        account=account_name,
        action="stop_career",
        operation_id=operation_id,
        arguments={"account": account_name},
        callback=lambda: selected_gateway.request("POST", "/api/career/runner/stop"),
        workflow_type="career",
        release_workflow=True,
    )


@mcp.tool()
def refresh_account(account: str = "") -> dict[str, Any]:
    """Refresh one account's state from the game, then return a compact safe summary."""
    try:
        account_name, selected_gateway = account_registry.resolve(account)
        response = selected_gateway.request("POST", "/api/account/refresh")
        if not response.get("success"):
            response["account"] = account_name
            return response
        return {
            "success": True,
            "account": account_name,
            "session": compact_session(_get_session(selected_gateway)),
        }
    except Exception as exc:
        return {"success": False, "detail": str(exc), "account": str(account or "")}


@mcp.tool()
def refill_tp(
    count: int = 1,
    account: str = "",
    confirm: bool = False,
    operation_id: str = "",
) -> dict[str, Any]:
    """Refill TP using the bot's configured recovery method. Requires confirm=true."""
    count = int(count)
    if count < 1 or count > 10:
        return {"success": False, "detail": "count must be between 1 and 10"}
    try:
        account_name, selected_gateway = account_registry.resolve(account)
    except Exception as exc:
        return {"success": False, "detail": str(exc), "account": str(account or "")}
    details = {"account": account_name, "count": count}
    if not confirm:
        return _requires_confirmation("refill_tp", details, operation_id)
    return _execute_mutation(
        account=account_name,
        action="refill_tp",
        operation_id=operation_id,
        arguments=details,
        callback=lambda: selected_gateway.request(
            "POST", "/api/tp/refill", {"count": count}
        ),
    )


@mcp.tool()
def set_turn_delay(
    min_seconds: float,
    max_seconds: float,
    account: str = "",
    disabled: bool = False,
    confirm: bool = False,
    operation_id: str = "",
) -> dict[str, Any]:
    """Change API pacing delay. Requires confirm=true because it changes bot behavior."""
    min_seconds = float(min_seconds)
    max_seconds = float(max_seconds)
    if min_seconds < 0 or max_seconds < 0 or max_seconds < min_seconds:
        return {
            "success": False,
            "detail": "Delay values must be non-negative and max_seconds >= min_seconds",
        }
    try:
        account_name, selected_gateway = account_registry.resolve(account)
    except Exception as exc:
        return {"success": False, "detail": str(exc), "account": str(account or "")}

    details = {
        "account": account_name,
        "min_seconds": min_seconds,
        "max_seconds": max_seconds,
        "disabled": bool(disabled),
    }
    if not confirm:
        return _requires_confirmation("set_turn_delay", details, operation_id)
    return _execute_mutation(
        account=account_name,
        action="set_turn_delay",
        operation_id=operation_id,
        arguments=details,
        callback=lambda: selected_gateway.request(
            "POST",
            "/api/settings/turn-delay",
            {"min": min_seconds, "max": max_seconds, "disabled": bool(disabled)},
        ),
    )


@mcp.resource("sweepy://accounts")
def sweepy_accounts_resource() -> str:
    """Enabled Sweepy account names and local ports as JSON."""
    return json.dumps(list_accounts(), ensure_ascii=False, indent=2)


@mcp.resource("sweepy://snapshot/{account}")
def sweepy_snapshot_resource(account: str) -> str:
    """Last successful load/index snapshot for one account as JSON."""
    return json.dumps(
        get_cached_account_snapshot(account=account, include_records=False),
        ensure_ascii=False,
        indent=2,
    )


@mcp.resource("sweepy://runtime/{account}")
def sweepy_runtime_resource(account: str) -> str:
    """Managed process and API readiness state for one Sweepy account as JSON."""
    return json.dumps(get_account_runtime(account=account), ensure_ascii=False, indent=2)


@mcp.resource("sweepy://state/{account}")
def sweepy_state_resource(account: str) -> str:
    """Current compact state for one Sweepy account as JSON."""
    return json.dumps(get_bot_state(account=account), ensure_ascii=False, indent=2)


@mcp.resource("sweepy://operations/{account}")
def sweepy_operations_resource(account: str) -> str:
    """Recent durable MCP mutations for one Sweepy account as JSON."""
    return json.dumps(
        get_recent_operations(account=account, limit=20),
        ensure_ascii=False,
        indent=2,
    )


@mcp.prompt()
def operate_sweepy(goal: str, account: str = "") -> str:
    """Safe operating procedure for asking an agent to manage Sweepy."""
    return (
        f"Goal: {goal}\nAccount: {account or 'not selected'}\n\n"
        "First call list_accounts, then get_account_runtime and get_bot_state with the chosen account. "
        "Pass that same account to every later tool. If the bot is stopped, preview launch_bot, "
        "ask for approval, launch it, and call wait_until_ready. Do not start Career while "
        "Dailies are running, or Dailies while Career is active. Inspect presets or Legend "
        "options before starting those workflows. For any tool requiring confirmation, "
        "summarize the exact process/resource/state change and ask the user before calling "
        "it again with confirm=true and the same operation_id from the preview. Use a stable "
        "Discord message ID as operation_id when available. Workflow stop tools may be called immediately, but "
        "process stop/restart tools still require confirmation."
    )


def registered_tool_names() -> tuple[str, ...]:
    return TOOL_NAMES


def main() -> None:
    parser = argparse.ArgumentParser(description="Sweepy MCP server")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http", "sse"),
        default=os.environ.get("SWEEPY_MCP_TRANSPORT", "stdio"),
    )
    args = parser.parse_args()
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
