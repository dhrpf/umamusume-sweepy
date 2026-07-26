"""Validated runtime access to generated Grand Live lesson metadata."""

import json
from pathlib import Path


PERFORMANCE_NAMES = frozenset({"Dance", "Passion", "Vocal", "Visual", "Mental"})
SQUARE_TYPES = frozenset({1, 2, 3, 4})


class GrandLiveDataError(RuntimeError):
    """Raised when generated Grand Live metadata cannot be trusted."""


def validate_square_reference(squares):
    if not isinstance(squares, dict):
        raise GrandLiveDataError("Grand Live square reference must be an object")
    if not squares:
        raise GrandLiveDataError("Grand Live square reference contains no squares")

    validated = {}
    for raw_id, raw_row in squares.items():
        try:
            square_id = int(raw_id)
        except (TypeError, ValueError) as exc:
            raise GrandLiveDataError(
                f"invalid Grand Live square id: {raw_id!r}"
            ) from exc
        if square_id <= 0 or str(square_id) in validated:
            raise GrandLiveDataError(
                f"invalid or duplicate Grand Live square id: {raw_id!r}"
            )
        if not isinstance(raw_row, dict):
            raise GrandLiveDataError(
                f"Grand Live square {square_id} must be an object"
            )

        square_type = raw_row.get("square_type")
        if isinstance(square_type, bool) or square_type not in SQUARE_TYPES:
            raise GrandLiveDataError(
                f"invalid Grand Live square type for {square_id}"
            )

        raw_cost = raw_row.get("token_cost")
        if not isinstance(raw_cost, dict):
            raise GrandLiveDataError(
                f"Grand Live square {square_id} token_cost must be an object"
            )
        token_cost = {}
        for raw_name, raw_value in raw_cost.items():
            if raw_name not in PERFORMANCE_NAMES:
                raise GrandLiveDataError(
                    f"unknown Grand Live performance type {raw_name!r}"
                )
            if isinstance(raw_value, bool) or not isinstance(raw_value, int):
                raise GrandLiveDataError(
                    f"Grand Live square {square_id} has non-integer token cost"
                )
            if raw_value < 0:
                raise GrandLiveDataError(
                    f"Grand Live square {square_id} has negative token cost"
                )
            if raw_value:
                token_cost[raw_name] = raw_value

        song_id = raw_row.get("adds_song_live_id")
        if song_id is not None:
            if isinstance(song_id, bool):
                raise GrandLiveDataError(
                    f"Grand Live square {square_id} has invalid song id"
                )
            try:
                song_id = int(song_id)
            except (TypeError, ValueError) as exc:
                raise GrandLiveDataError(
                    f"Grand Live square {square_id} has invalid song id"
                ) from exc
            if song_id <= 0:
                raise GrandLiveDataError(
                    f"Grand Live square {square_id} has invalid song id"
                )

        validated[str(square_id)] = {
            "square_type": square_type,
            "name": str(raw_row.get("name") or square_id),
            "reward": str(raw_row.get("reward") or ""),
            "grants_sp": bool(raw_row.get("grants_sp")),
            "token_cost": token_cost,
            "adds_song_live_id": song_id,
        }

    return validated


class GrandLiveData:
    def __init__(self, path):
        self.path = Path(path)
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            self.squares = validate_square_reference(payload.get("squares"))
        except GrandLiveDataError as exc:
            raise GrandLiveDataError(
                f"{exc}; run python scripts/generate_master_data.py "
                "--only grand-live"
            ) from exc
        except (OSError, json.JSONDecodeError, AttributeError) as exc:
            raise GrandLiveDataError(
                "Grand Live metadata is missing or malformed; run "
                "python scripts/generate_master_data.py"
            ) from exc

    def square(self, square_id):
        try:
            key = str(int(square_id))
        except (TypeError, ValueError):
            return None
        return self.squares.get(key)


def default_grand_live_data_path():
    return Path(__file__).resolve().parent.parent / "data" / "grand_live.json"


def load_default_square_reference():
    return GrandLiveData(default_grand_live_data_path()).squares
