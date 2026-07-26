from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunState(str, Enum):
    QUEUED = "QUEUED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    COLLECTING = "COLLECTING"
    FINALIZING = "FINALIZING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"
    CANCELLED = "CANCELLED"


class TpMode(str, Enum):
    WAIT = "wait"
    CARAT = "carat"
    STOP = "stop"


class FactorTarget(StrictModel):
    category: Literal["blue", "pink"]
    name: str
    minimum_stars: int = Field(ge=1, le=3)

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category(cls, value):
        return {
            "stat": "blue",
            "blue": "blue",
            "aptitude": "pink",
            "pink": "pink",
        }.get(str(value or "").strip().casefold(), value)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value):
        normalized = str(value or "").strip().casefold()
        if not normalized:
            raise ValueError("factor target name is required")
        return normalized


class FactorReroll(StrictModel):
    enabled: bool = False
    targets: list[FactorTarget] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_targets(self):
        if self.enabled and not self.targets:
            raise ValueError("enabled factor reroll requires at least one target")
        return self


class PrioritySkill(StrictModel):
    priority: int = Field(ge=1)
    skill_id: int = Field(gt=0)


class RaceEntry(StrictModel):
    year: int = Field(ge=1, le=3)
    program_id: int = Field(gt=0)


class IndependentSetup(StrictModel):
    card_id: int = Field(gt=0)
    support_card_ids: list[int] = Field(min_length=5, max_length=5)
    friend_viewer_id: int = Field(gt=0)
    friend_card_id: int = Field(gt=0)
    parent_id_1: int = Field(gt=0)
    parent_id_2: int = Field(gt=0)
    rental_viewer_id: int = Field(default=0, ge=0)
    rental_trained_chara_id: int = Field(default=0, ge=0)
    scenario_id: int = Field(gt=0)
    deck_id: int = Field(default=1, gt=0)
    running_style: int = Field(ge=1, le=4)
    difficulty_id: int = Field(default=0, ge=0)
    difficulty: int = Field(default=0, ge=0)
    is_boost: int = Field(default=0, ge=0)
    boost_story_event_id: int = Field(default=0, ge=0)
    training_policy_ground_type: int = Field(gt=0)
    training_policy_param_rate_set_id: int = Field(gt=0)
    priority_skill_array: list[PrioritySkill] = Field(default_factory=list)
    race_array: list[RaceEntry] = Field(default_factory=list)
    use_tp: int = Field(default=30, ge=0)
    factor_reroll: FactorReroll = Field(default_factory=FactorReroll)

    @field_validator("support_card_ids")
    @classmethod
    def distinct_supports(cls, value):
        if len(set(value)) != 5 or any(int(item) <= 0 for item in value):
            raise ValueError(
                "support_card_ids must contain five distinct positive IDs"
            )
        return value

    @model_validator(mode="after")
    def distinct_parents(self):
        if self.parent_id_1 == self.parent_id_2:
            raise ValueError("parent selections must be distinct")
        return self


class EnqueueRuns(StrictModel):
    setup: IndependentSetup
    count: int = Field(default=1, ge=1, le=100)
    tp_mode: TpMode = TpMode.WAIT
