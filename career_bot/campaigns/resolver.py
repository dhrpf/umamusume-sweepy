from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class LegacySlot:
    role: str
    mode: Literal["LOCKED", "FLEXIBLE"]
    trained_chara_id: int = 0

    def __post_init__(self) -> None:
        if self.mode not in {"LOCKED", "FLEXIBLE"}:
            raise ValueError("mode must be LOCKED or FLEXIBLE")


class LegacyResolver:
    def __init__(self, *, allow_rental: bool) -> None:
        self.allow_rental = allow_rental

    def resolve_slot(self, slot: LegacySlot, *, candidates: list[dict]) -> dict:
        allowed = [
            row
            for row in candidates
            if self.allow_rental or not bool(row.get("rental"))
        ]
        if slot.mode == "LOCKED":
            for row in allowed:
                if int(row.get("trained_chara_id") or 0) == slot.trained_chara_id:
                    return {
                        **row,
                        "status": "RESOLVED",
                        "replacement": False,
                        "reason": "locked campaign lineage",
                    }
            return {
                "status": "UNRESOLVED",
                "role": slot.role,
                "reason": "locked veteran unavailable",
            }

        ranked = sorted(
            allowed,
            key=lambda row: (
                -float(row.get("score") or 0.0),
                int(row.get("trained_chara_id") or 0),
            ),
        )
        if not ranked:
            return {
                "status": "UNRESOLVED",
                "role": slot.role,
                "reason": "no allowed veteran candidate",
            }

        best = ranked[0]
        old_id = int(slot.trained_chara_id or 0)
        new_id = int(best.get("trained_chara_id") or 0)
        return {
            **best,
            "status": "RESOLVED",
            "replacement": bool(old_id and old_id != new_id),
            "previous_trained_chara_id": old_id,
            "reason": best.get("reason") or "highest deterministic resolver score",
        }
