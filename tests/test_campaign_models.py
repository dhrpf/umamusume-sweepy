import pytest
from pydantic import ValidationError

from career_bot.campaigns.models import (
    ApprovalMode,
    DeckSelectionMode,
    FactorAggregation,
    FactorScope,
    LineageDepth,
    ParentCampaignSpec,
    ParentGoal,
    ParentStrategy,
    TraineeSelectionMode,
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


def test_goal_supports_aptitude_free_power_nine_direct_lineage_target():
    goal = ParentGoal(
        surface_targets=[],
        distance_targets=[],
        preferred_stats=["power"],
        target_factors=[
            {
                "name": "power",
                "minimum_stars": 9,
                "scope": "lineage",
                "aggregation": "sum",
                "lineage_depth": "direct",
            }
        ],
    )

    target = goal.target_factors[0]
    assert goal.surface_targets == []
    assert goal.distance_targets == []
    assert target.minimum_stars == 9
    assert target.aggregation is FactorAggregation.SUM
    assert target.lineage_depth is LineageDepth.DIRECT


def test_factor_target_rejects_invalid_star_semantics():
    with pytest.raises(ValidationError, match="candidate factor"):
        ParentGoal(
            surface_targets=[],
            distance_targets=[],
            target_factors=[
                {
                    "name": "power",
                    "minimum_stars": 9,
                    "scope": "candidate",
                    "aggregation": "sum",
                }
            ],
        )

    with pytest.raises(ValidationError, match="max aggregation"):
        ParentGoal(
            surface_targets=[],
            distance_targets=[],
            target_factors=[
                {
                    "name": "power",
                    "minimum_stars": 9,
                    "scope": "lineage",
                    "aggregation": "max",
                }
            ],
        )


def test_lineage_factor_target_allows_total_nine_stars():
    goal = ParentGoal(
        surface_targets=["turf"],
        distance_targets=["mile"],
        target_factors=[
            {"name": "power", "minimum_stars": 9, "scope": "lineage"},
        ],
    )

    target = goal.lineage_factors[0]
    assert target.minimum_stars == 9
    assert target.aggregation is FactorAggregation.SUM
    assert target.lineage_depth is LineageDepth.DIRECT


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


def test_campaign_selection_policies_default_to_current_for_backward_compatibility():
    spec = ParentCampaignSpec(
        account="alpha",
        goal={"surface_targets": ["turf"], "preferred_stats": ["stamina"]},
        strategy={
            "preset_name": "MANT Parent",
            "maximum_runs": 10,
            "maximum_runtime_hours": 12,
        },
    )

    assert spec.trainee.mode is TraineeSelectionMode.CURRENT
    assert spec.trainee.name == ""
    assert spec.trainee.card_id == 0
    assert spec.trainee.objective == "best_score"
    assert spec.deck.mode is DeckSelectionMode.CURRENT
    assert spec.deck.name == ""
    assert spec.deck.deck_id == 0


def test_campaign_accepts_named_or_auto_headless_selection_policies():
    named = ParentCampaignSpec(
        account="alpha",
        goal={"surface_targets": ["turf"], "preferred_stats": ["stamina"]},
        strategy={
            "preset_name": "MANT Parent",
            "maximum_runs": 10,
            "maximum_runtime_hours": 12,
        },
        trainee={"mode": "named", "name": " Oguri Cap "},
        deck={"mode": "named", "name": " Parent Stamina "},
    )
    automatic = ParentCampaignSpec(
        account="alpha",
        goal={"surface_targets": ["turf"], "preferred_stats": ["stamina"]},
        strategy=named.strategy,
        trainee={"mode": "auto", "objective": "highest_affinity"},
        deck={"mode": "auto"},
    )

    assert named.trainee.mode is TraineeSelectionMode.NAMED
    assert named.trainee.name == "Oguri Cap"
    assert named.deck.mode is DeckSelectionMode.NAMED
    assert named.deck.name == "Parent Stamina"
    assert automatic.trainee.mode is TraineeSelectionMode.AUTO
    assert automatic.deck.mode is DeckSelectionMode.AUTO


def test_named_selection_policy_requires_name_or_numeric_id():
    with pytest.raises(ValidationError, match="named trainee selection"):
        ParentCampaignSpec(
            account="alpha",
            goal={"surface_targets": ["turf"], "preferred_stats": ["stamina"]},
            strategy={
                "preset_name": "MANT Parent",
                "maximum_runs": 10,
                "maximum_runtime_hours": 12,
            },
            trainee={"mode": "named"},
        )

    with pytest.raises(ValidationError, match="named deck selection"):
        ParentCampaignSpec(
            account="alpha",
            goal={"surface_targets": ["turf"], "preferred_stats": ["stamina"]},
            strategy={
                "preset_name": "MANT Parent",
                "maximum_runs": 10,
                "maximum_runtime_hours": 12,
            },
            deck={"mode": "named"},
        )


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
