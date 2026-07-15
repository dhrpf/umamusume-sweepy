from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from numbers import Real
from typing import Literal


@dataclass(frozen=True)
class LegacySlot:
    role: str
    mode: Literal["LOCKED", "FLEXIBLE"]
    trained_chara_id: int = 0

    def __post_init__(self) -> None:
        if self.mode not in {"LOCKED", "FLEXIBLE"}:
            raise ValueError("mode must be LOCKED or FLEXIBLE")
        if self.mode == "LOCKED" and (
            type(self.trained_chara_id) is not int or self.trained_chara_id <= 0
        ):
            raise ValueError("LOCKED trained_chara_id must be a positive integer")
        if self.mode == "FLEXIBLE" and (
            type(self.trained_chara_id) is not int or self.trained_chara_id < 0
        ):
            raise ValueError("trained_chara_id must be a non-negative integer")


class LegacyResolver:
    def __init__(self, *, allow_rental: bool) -> None:
        if type(allow_rental) is not bool:
            raise TypeError("allow_rental must be a boolean")
        self.allow_rental = allow_rental

    def resolve_slot(self, slot: LegacySlot, *, candidates: list[dict]) -> dict:
        validated = [self._validate_candidate(row) for row in candidates]
        allowed = [row for row in validated if self.allow_rental or not row["rental"]]
        if slot.mode == "LOCKED":
            for row in allowed:
                if row["trained_chara_id"] == slot.trained_chara_id:
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

        sort_keys = [(row["score"], row["trained_chara_id"]) for row in allowed]
        if len(sort_keys) != len(set(sort_keys)):
            raise ValueError("duplicate candidate sort key")
        ranked = sorted(allowed, key=lambda row: (-row["score"], row["trained_chara_id"]))
        if not ranked:
            return {
                "status": "UNRESOLVED",
                "role": slot.role,
                "reason": "no allowed veteran candidate",
            }

        best = ranked[0]
        old_id = slot.trained_chara_id
        new_id = best["trained_chara_id"]
        return {
            **best,
            "status": "RESOLVED",
            "replacement": bool(old_id and old_id != new_id),
            "previous_trained_chara_id": old_id,
            "reason": best.get("reason") or "highest deterministic resolver score",
        }

    @staticmethod
    def _validate_candidate(candidate: dict) -> dict:
        if not isinstance(candidate, dict):
            raise ValueError("candidate must be a dictionary")
        trained_chara_id = candidate.get("trained_chara_id")
        if type(trained_chara_id) is not int or trained_chara_id <= 0:
            raise ValueError("candidate trained_chara_id must be a positive integer")
        score = candidate.get("score")
        if isinstance(score, bool) or not isinstance(score, Real) or not isfinite(score):
            raise ValueError("candidate score must be finite numeric")
        if type(candidate.get("rental")) is not bool:
            raise ValueError("candidate rental must be an explicit boolean")
        return candidate
