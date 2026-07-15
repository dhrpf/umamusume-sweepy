from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class RotationState:
    loop_chara_ids: tuple[int, int, int, int]
    run_index: int
    produced: tuple[tuple[int, str], ...]

    def __post_init__(self) -> None:
        if len(self.loop_chara_ids) != 4 or len(set(self.loop_chara_ids)) != 4:
            raise ValueError("rotation requires four unique characters")
        if len(self.produced) > 8:
            raise ValueError("rotation retains at most eight produced legacies")

    @classmethod
    def bootstrap(cls, chara_ids: list[int]) -> "RotationState":
        normalized = tuple(int(value) for value in chara_ids)
        return cls(normalized, 0, ())

    @property
    def next_trainee_chara_id(self) -> int:
        return self.loop_chara_ids[self.run_index % 4]

    @property
    def available_legacy_ids(self) -> list[str]:
        return [legacy_id for _chara_id, legacy_id in self.produced]

    def to_dict(self) -> dict:
        return asdict(self)


def advance_rotation(state: RotationState, *, produced_legacy_id: str) -> RotationState:
    produced = [
        *state.produced,
        (state.next_trainee_chara_id, str(produced_legacy_id)),
    ]
    return RotationState(
        state.loop_chara_ids,
        state.run_index + 1,
        tuple(produced[-8:]),
    )
