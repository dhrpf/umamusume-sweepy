from __future__ import annotations

import copy
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any


SNAPSHOT_VERSION = 1
SNAPSHOT_FILENAME = "load-index-cache.json"

_SENSITIVE_KEYS = {
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


def snapshot_path(runtime_dir: str | Path) -> Path:
    return Path(runtime_dir).expanduser().resolve() / SNAPSHOT_FILENAME


def sanitize_for_snapshot(value: Any, key: str = "") -> Any:
    """Return a JSON-safe copy with account/session identifiers removed."""
    if key.lower() in _SENSITIVE_KEYS:
        return None
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for child_key, child_value in value.items():
            child_name = str(child_key)
            if child_name.lower() in _SENSITIVE_KEYS:
                continue
            result[child_name] = sanitize_for_snapshot(child_value, child_name)
        return result
    if isinstance(value, (list, tuple)):
        return [sanitize_for_snapshot(item, key) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def build_raw_dashboard(load_index_data: dict[str, Any]) -> dict[str, Any]:
    """Build a name-light dashboard when load/index is handled outside main.py."""
    data = load_index_data if isinstance(load_index_data, dict) else {}
    cards = []
    for row in data.get("card_list") or []:
        if not isinstance(row, dict):
            continue
        card_id = row.get("card_id") or row.get("id")
        if card_id:
            cards.append({"id": str(card_id), "name": f"Card #{card_id}"})

    supports = []
    support_lb: dict[int, int] = {}
    for row in data.get("support_card_list") or []:
        if not isinstance(row, dict):
            continue
        support_id = int(row.get("support_card_id") or row.get("id") or 0)
        if not support_id:
            continue
        limit_break = int(row.get("limit_break_count") or 0)
        support_lb[support_id] = limit_break
        supports.append(
            {
                "id": str(support_id),
                "name": f"Support #{support_id}",
                "limit_break_count": limit_break,
            }
        )

    decks = []
    for row in data.get("support_card_deck_array") or []:
        if not isinstance(row, dict):
            continue
        deck_id = int(row.get("deck_id") or row.get("id") or 0)
        decks.append(
            {
                "id": deck_id,
                "name": str(row.get("name") or f"Deck {deck_id}"),
                "cards": [
                    {
                        "id": str(card_id),
                        "limit_break_count": support_lb.get(int(card_id), 0),
                    }
                    for card_id in (row.get("support_card_id_array") or [])
                    if int(card_id or 0)
                ],
            }
        )

    parents = []
    for row in data.get("trained_chara") or []:
        if not isinstance(row, dict):
            continue
        trained_id = int(row.get("trained_chara_id") or row.get("id") or 0)
        card_id = int(row.get("card_id") or row.get("chara_id") or 0)
        if not trained_id or not card_id:
            continue
        parents.append(
            {
                "instance_id": trained_id,
                "card_id": str(card_id),
                "name": f"Veteran #{trained_id}",
                "rank": int(row.get("rank") or 0),
                "rank_score": int(row.get("rank_score") or 0),
                "stats": {
                    "speed": int(row.get("speed") or 0),
                    "stamina": int(row.get("stamina") or 0),
                    "power": int(row.get("power") or 0),
                    "guts": int(row.get("guts") or 0),
                    "wit": int(row.get("wiz") or row.get("wit") or 0),
                },
            }
        )

    return {
        "account": {},
        "umas": cards,
        "supports": supports,
        "decks": decks,
        "parents": parents,
    }


def build_load_index_snapshot(
    *,
    dashboard: dict[str, Any],
    load_index_data: dict[str, Any],
    source: str = "load/index",
    refreshed_at: float | None = None,
) -> dict[str, Any]:
    """Build the persistent, MCP-safe projection of a successful load/index."""
    dashboard = dashboard if isinstance(dashboard, dict) else {}
    data = load_index_data if isinstance(load_index_data, dict) else {}
    trained = data.get("trained_chara") if isinstance(data.get("trained_chara"), list) else []
    cards = data.get("card_list") if isinstance(data.get("card_list"), list) else []
    supports = (
        data.get("support_card_list")
        if isinstance(data.get("support_card_list"), list)
        else []
    )
    raw_decks = (
        data.get("support_card_deck_array")
        if isinstance(data.get("support_card_deck_array"), list)
        else []
    )

    snapshot = {
        "version": SNAPSHOT_VERSION,
        "source": source,
        "refreshed_at": float(refreshed_at if refreshed_at is not None else time.time()),
        "account": copy.deepcopy(dashboard.get("account") or {}),
        "cards": copy.deepcopy(dashboard.get("umas") or []),
        "support_cards": copy.deepcopy(dashboard.get("supports") or []),
        "decks": copy.deepcopy(dashboard.get("decks") or []),
        "owned_veterans": copy.deepcopy(dashboard.get("parents") or []),
        "records": {
            "card_list": copy.deepcopy(cards),
            "support_card_list": copy.deepcopy(supports),
            "support_card_deck_array": copy.deepcopy(raw_decks),
            "trained_chara": copy.deepcopy(trained),
        },
        "counts": {
            "cards": len(cards),
            "support_cards": len(supports),
            "decks": len(raw_decks),
            "owned_veterans": len(trained),
        },
    }
    return sanitize_for_snapshot(snapshot)


def save_raw_load_index_snapshot(
    runtime_dir: str | Path,
    load_index_data: dict[str, Any],
    *,
    refreshed_at: float | None = None,
) -> Path:
    return save_load_index_snapshot(
        runtime_dir,
        dashboard=build_raw_dashboard(load_index_data),
        load_index_data=load_index_data,
        refreshed_at=refreshed_at,
    )


def save_load_index_snapshot(
    runtime_dir: str | Path,
    *,
    dashboard: dict[str, Any],
    load_index_data: dict[str, Any],
    source: str = "load/index",
    refreshed_at: float | None = None,
) -> Path:
    """Atomically persist a successful load/index projection with mode 0600."""
    path = snapshot_path(runtime_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    snapshot = build_load_index_snapshot(
        dashboard=dashboard,
        load_index_data=load_index_data,
        source=source,
        refreshed_at=refreshed_at,
    )
    payload = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, path)
        os.chmod(path, 0o600)
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
    return path


def load_account_snapshot(runtime_dir: str | Path) -> dict[str, Any] | None:
    path = snapshot_path(runtime_dir)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Cannot read account snapshot: {path}") from exc
    if not isinstance(value, dict) or int(value.get("version") or 0) != SNAPSHOT_VERSION:
        raise RuntimeError(f"Unsupported account snapshot format: {path}")
    return value


def compact_account_snapshot(
    snapshot: dict[str, Any],
    *,
    include_records: bool = False,
    veteran_limit: int = 200,
) -> dict[str, Any]:
    """Return an agent-friendly snapshot, omitting large raw records by default."""
    result = {
        "version": snapshot.get("version"),
        "source": snapshot.get("source"),
        "refreshed_at": snapshot.get("refreshed_at"),
        "account": copy.deepcopy(snapshot.get("account") or {}),
        "counts": copy.deepcopy(snapshot.get("counts") or {}),
        "cards": copy.deepcopy(snapshot.get("cards") or []),
        "support_cards": copy.deepcopy(snapshot.get("support_cards") or []),
        "decks": copy.deepcopy(snapshot.get("decks") or []),
        "owned_veterans": copy.deepcopy(snapshot.get("owned_veterans") or [])[
            : max(1, min(int(veteran_limit), 1000))
        ],
    }
    if include_records:
        result["records"] = copy.deepcopy(snapshot.get("records") or {})
    return result
