import pytest
from pydantic import ValidationError

from career_bot.campaigns.models import (
    ApprovalMode,
    FactorScope,
    ParentCampaignSpec,
    ParentGoal,
    ParentStrategy,
)


def test_medium_turf_goal_normalizes_and_builds_default_lineage_targets():
    goal = ParentGoal(
        surface_targets=[" Turf "],
        distance_targets=["MEDIUM"],
        minimum_rank="s",
        preferred_stats=["Speed", "stamina"],
    )

    assert goal.surface_targets == ["turf"]
    assert goal.distance_targets == ["medium"]
    assert goal.minimum_rank == "S"
    assert goal.preferred_stats == ["speed", "stamina"]
    assert [(row.name, row.minimum_stars, row.scope) for row in goal.target_factors] == [
        ("turf", 2, FactorScope.LINEAGE),
        ("medium", 2, FactorScope.LINEAGE),
    ]


def test_goal_separates_candidate_and_lineage_requirements():
    goal = ParentGoal(
        surface_targets=["turf"],
        distance_targets=["medium"],
        target_factors=[
            {"name": "speed", "minimum_stars": 3, "scope": "candidate", "required": True},
            {"name": "medium", "minimum_stars": 2, "scope": "lineage", "required": True},
        ],
    )

    assert goal.candidate_factors[0].name == "speed"
    assert goal.lineage_factors[0].name == "medium"


def test_strategy_requires_hard_positive_limits_and_safe_tp_policy():
    strategy = ParentStrategy(
        preset_name="MANT Parent",
        maximum_runs=20,
        maximum_carats=0,
        maximum_clocks=0,
        maximum_runtime_hours=12,
        tp_mode="wait",
        use_clocks=False,
        approval_mode="ambiguity_only",
    )

    assert strategy.maximum_runs == 20
    assert strategy.approval_mode is ApprovalMode.AMBIGUITY_ONLY

    with pytest.raises(ValidationError):
        ParentStrategy(
            preset_name="MANT Parent",
            maximum_runs=0,
            maximum_runtime_hours=12,
        )

    with pytest.raises(ValidationError, match="maximum_carats"):
        ParentStrategy(
            preset_name="MANT Parent",
            maximum_runs=20,
            maximum_carats=0,
            maximum_runtime_hours=12,
            tp_mode="carat",
        )


def test_campaign_spec_is_account_scoped_and_serializable():
    spec = ParentCampaignSpec(
        account="alpha",
        goal={
            "surface_targets": ["turf"],
            "distance_targets": ["medium"],
        },
        strategy={
            "preset_name": "MANT Parent",
            "maximum_runs": 20,
            "maximum_runtime_hours": 24,
        },
    )

    dumped = spec.model_dump(mode="json")

    assert dumped["account"] == "alpha"
    assert dumped["goal"]["target_factors"][0]["scope"] == "lineage"
    assert dumped["strategy"]["maximum_runs"] == 20


def test_invalid_surface_distance_stat_and_factor_scope_are_rejected():
    with pytest.raises(ValidationError):
        ParentGoal(surface_targets=["water"], distance_targets=["medium"])
    with pytest.raises(ValidationError):
        ParentGoal(surface_targets=["turf"], distance_targets=["ultra"])
    with pytest.raises(ValidationError):
        ParentGoal(
            surface_targets=["turf"],
            distance_targets=["medium"],
            preferred_stats=["luck"],
        )
    with pytest.raises(ValidationError):
        ParentGoal(
            surface_targets=["turf"],
            distance_targets=["medium"],
            target_factors=[
                {"name": "medium", "minimum_stars": 2, "scope": "unknown"}
            ],
        )
