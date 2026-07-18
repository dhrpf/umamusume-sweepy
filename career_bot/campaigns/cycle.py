from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class CampaignCycleState:
    bootstrap_chara_ids: tuple[int, ...]
    run_index: int
    final_stage_active: bool
    final_repeat_count: int
    produced: tuple[tuple[int, str], ...]

    def __post_init__(self) -> None:
        bootstrap = tuple(int(value) for value in self.bootstrap_chara_ids)
        produced = tuple(
            (int(chara_id), str(legacy_id))
            for chara_id, legacy_id in self.produced
        )
        object.__setattr__(self, "bootstrap_chara_ids", bootstrap)
        object.__setattr__(self, "produced", produced)

        if not bootstrap or len(set(bootstrap)) != len(bootstrap):
            raise ValueError("cycle state requires unique bootstrap characters")
        if any(value <= 0 for value in bootstrap):
            raise ValueError("bootstrap chara ids must be positive")
        if isinstance(self.run_index, bool) or not isinstance(self.run_index, int):
            raise ValueError("run_index must be an integer")
        if self.run_index < 0:
            raise ValueError("run_index must be non-negative")
        if isinstance(self.final_stage_active, bool) is False:
            raise ValueError("final_stage_active must be a boolean")
        if isinstance(self.final_repeat_count, bool) or not isinstance(
            self.final_repeat_count,
            int,
        ):
            raise ValueError("final_repeat_count must be an integer")
        if self.final_repeat_count < 0:
            raise ValueError("final_repeat_count must be non-negative")

    @classmethod
    def bootstrap(cls, chara_ids: Sequence[int]) -> "CampaignCycleState":
        return cls(
            bootstrap_chara_ids=tuple(int(value) for value in chara_ids),
            run_index=0,
            final_stage_active=False,
            final_repeat_count=0,
            produced=(),
        )

    @property
    def next_bootstrap_chara_id(self) -> int:
        if self.final_stage_active:
            return 0
        return self.bootstrap_chara_ids[
            self.run_index % len(self.bootstrap_chara_ids)
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "bootstrap_chara_ids": list(self.bootstrap_chara_ids),
            "run_index": self.run_index,
            "final_stage_active": self.final_stage_active,
            "final_repeat_count": self.final_repeat_count,
            "produced": [list(row) for row in self.produced],
        }


def advance_bootstrap_rotation(
    state: CampaignCycleState,
    *,
    produced_legacy_id: str,
) -> CampaignCycleState:
    if state.final_stage_active:
        raise ValueError("cannot advance bootstrap rotation after final stage begins")
    legacy_id = str(produced_legacy_id or "").strip()
    if not legacy_id:
        raise ValueError("produced_legacy_id must be a non-empty string")
    produced = (
        *state.produced,
        (state.next_bootstrap_chara_id, legacy_id),
    )
    return CampaignCycleState(
        bootstrap_chara_ids=state.bootstrap_chara_ids,
        run_index=state.run_index + 1,
        final_stage_active=False,
        final_repeat_count=state.final_repeat_count,
        produced=produced,
    )


def enter_final_stage(state: CampaignCycleState) -> CampaignCycleState:
    return CampaignCycleState(
        bootstrap_chara_ids=state.bootstrap_chara_ids,
        run_index=state.run_index,
        final_stage_active=True,
        final_repeat_count=state.final_repeat_count,
        produced=state.produced,
    )


def record_final_repeat(state: CampaignCycleState) -> CampaignCycleState:
    if not state.final_stage_active:
        raise ValueError("cannot record final repeat before final stage begins")
    return CampaignCycleState(
        bootstrap_chara_ids=state.bootstrap_chara_ids,
        run_index=state.run_index,
        final_stage_active=True,
        final_repeat_count=state.final_repeat_count + 1,
        produced=state.produced,
    )


def migrate_stage_state_to_cycle(
    bootstrap_chara_ids: Sequence[int],
    stage_state: Mapping[str, Any] | None,
) -> CampaignCycleState:
    bootstrap = tuple(int(value) for value in bootstrap_chara_ids)
    saved = dict(stage_state or {})
    produced: list[tuple[int, str]] = []
    for row in saved.get("produced") or []:
        if not isinstance(row, (list, tuple)) or len(row) != 2:
            continue
        try:
            chara_id = int(row[0])
        except (TypeError, ValueError):
            continue
        legacy_id = str(row[1] or "").strip()
        if chara_id > 0 and legacy_id:
            produced.append((chara_id, legacy_id))

    return CampaignCycleState(
        bootstrap_chara_ids=bootstrap,
        run_index=len(produced),
        final_stage_active=False,
        final_repeat_count=max(0, int(saved.get("final_repeat_count") or 0)),
        produced=tuple(produced),
    )


__all__ = [
    "CampaignCycleState",
    "advance_bootstrap_rotation",
    "enter_final_stage",
    "migrate_stage_state_to_cycle",
    "record_final_repeat",
]
