from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class CampaignStageState:
    bootstrap_chara_ids: tuple[int, ...]
    stage_index: int
    completed_bootstrap_stages: tuple[int, ...]
    final_repeat_count: int
    produced: tuple[tuple[int, str], ...]

    def __post_init__(self) -> None:
        bootstrap = tuple(int(value) for value in self.bootstrap_chara_ids)
        completed = tuple(sorted({int(value) for value in self.completed_bootstrap_stages}))
        produced = tuple((int(chara_id), str(legacy_id)) for chara_id, legacy_id in self.produced)
        object.__setattr__(self, "bootstrap_chara_ids", bootstrap)
        object.__setattr__(self, "completed_bootstrap_stages", completed)
        object.__setattr__(self, "produced", produced)

        if not bootstrap or len(set(bootstrap)) != len(bootstrap):
            raise ValueError("stage state requires unique bootstrap characters")
        if any(value <= 0 for value in bootstrap):
            raise ValueError("bootstrap chara ids must be positive")
        if isinstance(self.stage_index, bool) or not isinstance(self.stage_index, int):
            raise ValueError("stage_index must be an integer")
        if self.stage_index < 0 or self.stage_index > len(bootstrap):
            raise ValueError("stage_index is outside the campaign stage range")
        if isinstance(self.final_repeat_count, bool) or self.final_repeat_count < 0:
            raise ValueError("final_repeat_count must be non-negative")
        if any(index < 0 or index >= len(bootstrap) for index in completed):
            raise ValueError("completed bootstrap stage index is invalid")

    @classmethod
    def bootstrap(cls, chara_ids: Sequence[int]) -> "CampaignStageState":
        return cls(tuple(int(value) for value in chara_ids), 0, (), 0, ())

    @property
    def is_final_stage(self) -> bool:
        return self.stage_index >= len(self.bootstrap_chara_ids)

    @property
    def current_bootstrap_chara_id(self) -> int:
        if self.is_final_stage:
            return 0
        return self.bootstrap_chara_ids[self.stage_index]

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["bootstrap_chara_ids"] = list(self.bootstrap_chara_ids)
        value["completed_bootstrap_stages"] = list(self.completed_bootstrap_stages)
        value["produced"] = [list(row) for row in self.produced]
        return value


def build_stage_goal_assignments(
    targets: Sequence[Mapping[str, Any]],
    *,
    bootstrap_count: int,
) -> dict[str, list[dict[str, Any]]]:
    count = int(bootstrap_count)
    if count <= 0:
        raise ValueError("bootstrap_count must be positive")
    result = {str(index): [] for index in range(count)}
    for index, target in enumerate(targets or []):
        result[str(index % count)].append(dict(target))
    return result


def record_stage_result(
    state: CampaignStageState,
    *,
    produced_legacy_id: str,
    goal_complete: bool,
) -> CampaignStageState:
    legacy_id = str(produced_legacy_id or "").strip()
    if not legacy_id:
        raise ValueError("produced_legacy_id must be a non-empty string")

    if state.is_final_stage:
        return CampaignStageState(
            bootstrap_chara_ids=state.bootstrap_chara_ids,
            stage_index=state.stage_index,
            completed_bootstrap_stages=state.completed_bootstrap_stages,
            final_repeat_count=state.final_repeat_count + 1,
            produced=state.produced,
        )

    produced = (*state.produced, (state.current_bootstrap_chara_id, legacy_id))
    if not goal_complete:
        return CampaignStageState(
            bootstrap_chara_ids=state.bootstrap_chara_ids,
            stage_index=state.stage_index,
            completed_bootstrap_stages=state.completed_bootstrap_stages,
            final_repeat_count=state.final_repeat_count,
            produced=produced,
        )

    completed = tuple(sorted({*state.completed_bootstrap_stages, state.stage_index}))
    return CampaignStageState(
        bootstrap_chara_ids=state.bootstrap_chara_ids,
        stage_index=min(state.stage_index + 1, len(state.bootstrap_chara_ids)),
        completed_bootstrap_stages=completed,
        final_repeat_count=state.final_repeat_count,
        produced=produced,
    )


def migrate_legacy_rotation(
    loop_chara_ids: Sequence[int],
    rotation: Mapping[str, Any] | None,
) -> CampaignStageState:
    members = tuple(int(value) for value in loop_chara_ids)
    if not members or len(set(members)) != len(members):
        raise ValueError("legacy campaign requires unique loop members")
    saved = dict(rotation or {})
    try:
        run_index = max(0, int(saved.get("run_index") or 0))
    except (TypeError, ValueError):
        run_index = 0
    offset = run_index % len(members)
    ordered = (*members[offset:], *members[:offset])
    produced = []
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
    return CampaignStageState(
        bootstrap_chara_ids=tuple(ordered),
        stage_index=0,
        completed_bootstrap_stages=(),
        final_repeat_count=0,
        produced=tuple(produced[-8:]),
    )


__all__ = [
    "CampaignStageState",
    "build_stage_goal_assignments",
    "migrate_legacy_rotation",
    "record_stage_result",
]
