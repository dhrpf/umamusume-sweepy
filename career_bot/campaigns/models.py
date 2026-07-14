from __future__ import annotations

import re
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ApprovalMode(str, Enum):
    FULLY_AUTOMATIC = "fully_automatic"
    PER_GENERATION = "per_generation"
    AMBIGUITY_ONLY = "ambiguity_only"


class FactorScope(str, Enum):
    CANDIDATE = "candidate"
    LINEAGE = "lineage"


class FactorAggregation(str, Enum):
    MAX = "max"
    SUM = "sum"


class LineageDepth(str, Enum):
    DIRECT = "direct"
    FULL = "full"


class CampaignState(str, Enum):
    DRAFT = "DRAFT"
    READY = "READY"
    STARTING_BOT = "STARTING_BOT"
    WAITING_FOR_LOGIN = "WAITING_FOR_LOGIN"
    SELECTING_LINEAGE = "SELECTING_LINEAGE"
    RUNNING_CAREER = "RUNNING_CAREER"
    EVALUATING_RESULT = "EVALUATING_RESULT"
    WAITING_FOR_TP = "WAITING_FOR_TP"
    NEEDS_USER_INPUT = "NEEDS_USER_INPUT"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class FactorTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    minimum_stars: int = Field(default=2, ge=1, le=21)
    scope: FactorScope = FactorScope.LINEAGE
    aggregation: FactorAggregation = FactorAggregation.MAX
    lineage_depth: LineageDepth = LineageDepth.FULL
    required: bool = True

    @model_validator(mode="before")
    @classmethod
    def infer_total_lineage_semantics(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        try:
            minimum = int(payload.get("minimum_stars") or 0)
        except (TypeError, ValueError):
            minimum = 0
        scope = str(payload.get("scope") or FactorScope.LINEAGE.value).strip().lower()
        if (
            scope == FactorScope.LINEAGE.value
            and minimum > 3
            and "aggregation" not in payload
        ):
            payload["aggregation"] = FactorAggregation.SUM.value
            payload.setdefault("lineage_depth", LineageDepth.DIRECT.value)
        return payload

    @model_validator(mode="after")
    def validate_star_semantics(self) -> "FactorTarget":
        if self.scope is FactorScope.CANDIDATE:
            if self.aggregation is not FactorAggregation.MAX or self.minimum_stars > 3:
                raise ValueError(
                    "candidate factor targets require max aggregation and cannot exceed 3 stars"
                )
            return self

        if self.aggregation is FactorAggregation.MAX and self.minimum_stars > 3:
            raise ValueError("max aggregation cannot require more than 3 stars")
        if self.aggregation is FactorAggregation.SUM:
            maximum = 9 if self.lineage_depth is LineageDepth.DIRECT else 21
            if self.minimum_stars > maximum:
                raise ValueError(
                    f"{self.lineage_depth.value} lineage total cannot exceed {maximum} stars"
                )
        return self

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if not normalized:
            raise ValueError("factor name is required")
        return normalized


class ParentGoal(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    purpose: Literal["parent"] = "parent"
    surface_targets: list[str] = Field(default_factory=list)
    distance_targets: list[str] = Field(default_factory=list)
    minimum_rank: str = "S"
    preferred_stats: list[str] = Field(default_factory=lambda: ["speed", "stamina"])
    target_factors: list[FactorTarget] = Field(default_factory=list)

    @field_validator("surface_targets")
    @classmethod
    def normalize_surfaces(cls, values: list[str]) -> list[str]:
        allowed = {"turf", "dirt"}
        normalized = []
        for value in values:
            item = str(value or "").strip().lower()
            if item not in allowed:
                raise ValueError(f"unsupported surface target: {item or value}")
            if item not in normalized:
                normalized.append(item)
        return normalized

    @field_validator("distance_targets")
    @classmethod
    def normalize_distances(cls, values: list[str]) -> list[str]:
        allowed = {"sprint", "mile", "medium", "long"}
        normalized = []
        for value in values:
            item = str(value or "").strip().lower()
            if item not in allowed:
                raise ValueError(f"unsupported distance target: {item or value}")
            if item not in normalized:
                normalized.append(item)
        return normalized

    @field_validator("preferred_stats")
    @classmethod
    def normalize_stats(cls, values: list[str]) -> list[str]:
        allowed = {"speed", "stamina", "power", "guts", "wisdom"}
        normalized = []
        for value in values:
            item = str(value or "").strip().lower()
            if item not in allowed:
                raise ValueError(f"unsupported preferred stat: {item or value}")
            if item not in normalized:
                normalized.append(item)
        return normalized

    @field_validator("minimum_rank")
    @classmethod
    def normalize_rank(cls, value: str) -> str:
        normalized = str(value or "").strip().upper()
        allowed = {
            "G",
            "G+",
            "F",
            "F+",
            "E",
            "E+",
            "D",
            "D+",
            "C",
            "C+",
            "B",
            "B+",
            "A",
            "A+",
            "S",
            "S+",
            "SS",
            "SS+",
            "UG",
            "UF",
            "UE",
            "UD",
        }
        if normalized not in allowed:
            raise ValueError(f"unsupported minimum rank: {normalized}")
        return normalized

    @model_validator(mode="after")
    def build_default_factor_targets(self) -> "ParentGoal":
        if not self.target_factors:
            self.target_factors = [
                FactorTarget(name=name, minimum_stars=2, scope=FactorScope.LINEAGE)
                for name in [*self.surface_targets, *self.distance_targets]
            ]
        return self

    @property
    def candidate_factors(self) -> list[FactorTarget]:
        return [row for row in self.target_factors if row.scope is FactorScope.CANDIDATE]

    @property
    def lineage_factors(self) -> list[FactorTarget]:
        return [row for row in self.target_factors if row.scope is FactorScope.LINEAGE]


class ParentStrategy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preset_name: str
    maximum_runs: int = Field(ge=1, le=1000)
    maximum_carats: int = Field(default=0, ge=0)
    maximum_clocks: int = Field(default=0, ge=0)
    maximum_runtime_hours: float = Field(gt=0, le=720)
    tp_mode: Literal["wait", "carat"] = "wait"
    use_clocks: bool = False
    approval_mode: ApprovalMode = ApprovalMode.AMBIGUITY_ONLY
    stop_when_target_reached: bool = True

    @field_validator("preset_name")
    @classmethod
    def normalize_preset_name(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("preset_name is required")
        return normalized

    @model_validator(mode="after")
    def validate_resource_policies(self) -> "ParentStrategy":
        if self.tp_mode == "carat" and self.maximum_carats <= 0:
            raise ValueError("maximum_carats must be positive when tp_mode is carat")
        if self.use_clocks and self.maximum_clocks <= 0:
            raise ValueError("maximum_clocks must be positive when use_clocks is true")
        return self


class TraineeSelectionMode(str, Enum):
    CURRENT = "current"
    NAMED = "named"
    AUTO = "auto"


class DeckSelectionMode(str, Enum):
    CURRENT = "current"
    NAMED = "named"
    AUTO = "auto"


class TraineeSelectionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: TraineeSelectionMode = TraineeSelectionMode.CURRENT
    name: str = ""
    card_id: int = Field(default=0, ge=0)
    objective: Literal["best_score", "highest_affinity"] = "best_score"

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return str(value or "").strip()

    @model_validator(mode="after")
    def validate_named_selector(self) -> "TraineeSelectionPolicy":
        if self.mode is TraineeSelectionMode.NAMED and not self.name and self.card_id <= 0:
            raise ValueError("named trainee selection requires name or card_id")
        return self


class DeckSelectionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: DeckSelectionMode = DeckSelectionMode.CURRENT
    name: str = ""
    deck_id: int = Field(default=0, ge=0)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return str(value or "").strip()

    @model_validator(mode="after")
    def validate_named_selector(self) -> "DeckSelectionPolicy":
        if self.mode is DeckSelectionMode.NAMED and not self.name and self.deck_id <= 0:
            raise ValueError("named deck selection requires name or deck_id")
        return self


class ParentCampaignSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account: str
    goal: ParentGoal
    strategy: ParentStrategy
    trainee: TraineeSelectionPolicy = Field(default_factory=TraineeSelectionPolicy)
    deck: DeckSelectionPolicy = Field(default_factory=DeckSelectionPolicy)

    @field_validator("account")
    @classmethod
    def normalize_account(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("account is required")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", normalized):
            raise ValueError("account contains unsupported characters")
        return normalized
