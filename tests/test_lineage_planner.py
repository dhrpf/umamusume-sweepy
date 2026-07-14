import pytest

from career_bot.campaigns.lineage_planner import (
    LineagePlanningError,
    build_inheritance_request,
    choose_lineage_setup,
    resolve_lineage_selection,
)
from career_bot.campaigns.models import ParentCampaignSpec


def campaign_spec():
    return ParentCampaignSpec(
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


def sample_session():
    return {
        "success": True,
        "selection": {
            "trainee": {"id": 100101, "name": "Test Uma"},
            "deck": {"id": 3, "name": "Deck", "cards": [{"id": 301}]},
            "friend": {
                "viewer_id": 90001,
                "support_card_id": 401,
                "support_name": "Friend Support",
            },
            "veterans": [],
        },
        "parents": [
            {
                "instance_id": 7001,
                "trained_chara_id": 7001,
                "name": "Owned A",
                "card_id": 1101,
            },
            {
                "instance_id": 7002,
                "trained_chara_id": 7002,
                "name": "Owned B",
                "card_id": 1102,
            },
        ],
        "friendVeterans": [
            {
                "instance_id": 8001,
                "trained_chara_id": 8001,
                "viewer_id": 99001,
                "name": "Rental A",
                "card_id": 1201,
            },
            {
                "instance_id": 8002,
                "trained_chara_id": 8002,
                "viewer_id": 99002,
                "name": "Rental B",
                "card_id": 1202,
            },
        ],
    }


def test_build_inheritance_request_from_campaign_and_current_trainee():
    payload = build_inheritance_request(campaign_spec(), sample_session(), pool="both")

    assert payload == {
        "target_card_id": 100101,
        "pool": "both",
        "goal": {
            "distance": "medium",
            "surface": "turf",
            "target_factors": [
                {
                    "name": "turf",
                    "minimum_stars": 2,
                    "scope": "lineage",
                    "aggregation": "max",
                    "lineage_depth": "full",
                    "required": True,
                },
                {
                    "name": "medium",
                    "minimum_stars": 2,
                    "scope": "lineage",
                    "aggregation": "max",
                    "lineage_depth": "full",
                    "required": True,
                },
            ],
        },
        "limit": 50,
    }


def test_build_inheritance_request_supports_aptitude_free_power_nine_goal():
    spec = ParentCampaignSpec(
        account="alpha",
        goal={
            "surface_targets": [],
            "distance_targets": [],
            "target_factors": [
                {"name": "power", "minimum_stars": 9, "scope": "lineage"}
            ],
        },
        strategy={
            "preset_name": "MANT Parent",
            "maximum_runs": 20,
            "maximum_runtime_hours": 24,
        },
    )

    payload = build_inheritance_request(spec, sample_session())

    assert payload["goal"]["surface"] == ""
    assert payload["goal"]["distance"] == ""
    assert payload["goal"]["target_factors"] == [
        {
            "name": "power",
            "minimum_stars": 9,
            "scope": "lineage",
            "aggregation": "sum",
            "lineage_depth": "direct",
            "required": True,
        }
    ]


def test_build_request_requires_current_trainee_selection():
    session = sample_session()
    session["selection"]["trainee"] = None

    with pytest.raises(LineagePlanningError, match="trainee"):
        build_inheritance_request(campaign_spec(), session)


def test_choose_setup_skips_same_base_character_as_target():
    response = {
        "success": True,
        "target_base_chara_id": 1001,
        "results": [
            {
                "rank": 1,
                "score": 999,
                "parent1": {"id": 7001, "source": "owned", "card_id": 100102, "base_chara_id": 1001},
                "parent2": {"id": 8001, "source": "veteran", "card_id": 100201, "base_chara_id": 1002},
            },
            {
                "rank": 2,
                "score": 500,
                "parent1": {"id": 7002, "source": "owned", "card_id": 100301, "base_chara_id": 1003},
                "parent2": {"id": 8002, "source": "veteran", "card_id": 100401, "base_chara_id": 1004},
            },
        ],
    }

    selected = choose_lineage_setup(response, target_card_id=100101)

    assert selected["parent1"]["base_chara_id"] == 1003
    assert selected["parent2"]["base_chara_id"] == 1004


def test_choose_setup_resolves_stale_reference_metadata_from_session():
    session = sample_session()
    session["selection"]["trainee"] = {"id": 100601, "name": "Oguri Cap"}
    session["parents"] = [
        {
            "instance_id": 7001,
            "trained_chara_id": 7001,
            "name": "Oguri Cap",
            "card_id": 100602,
            "tree": {"self": {"factors": [{"name": "Power", "stars": 3, "category": "stat"}]}},
        },
        {
            "instance_id": 7002,
            "trained_chara_id": 7002,
            "name": "Maruzensky",
            "card_id": 100401,
            "tree": {"self": {"factors": [{"name": "Power", "stars": 3, "category": "stat"}]}},
        },
        {
            "instance_id": 7003,
            "trained_chara_id": 7003,
            "name": "Gold Ship",
            "card_id": 100701,
            "tree": {"self": {"factors": [{"name": "Power", "stars": 3, "category": "stat"}]}},
        },
    ]
    response = {
        "success": True,
        "results": [
            {
                "rank": 1,
                "score": 999,
                "parent1": {"id": 7001, "source": "owned", "name": "Oguri Cap"},
                "parent2": {"id": 7002, "source": "owned", "name": "Maruzensky"},
            },
            {
                "rank": 2,
                "score": 500,
                "parent1": {"id": 7002, "source": "owned", "name": "Maruzensky"},
                "parent2": {"id": 7003, "source": "owned", "name": "Gold Ship"},
            },
        ],
    }

    selected = choose_lineage_setup(
        response,
        target_card_id=100601,
        session=session,
        target_factors=[
            {
                "name": "power",
                "minimum_stars": 9,
                "scope": "lineage",
                "aggregation": "sum",
                "lineage_depth": "direct",
                "required": True,
            }
        ],
    )

    assert selected["rank"] == 2
    assert selected["target_factor_evidence"] == [
        {
            "name": "power",
            "required_stars": 9,
            "parent1_stars": 3,
            "parent2_stars": 3,
            "maximum_candidate_stars": 3,
            "maximum_total_stars": 9,
            "feasible": True,
        }
    ]


def test_choose_setup_rejects_stale_pair_that_cannot_reach_direct_lineage_target():
    session = sample_session()
    session["parents"] = [
        {
            "instance_id": 7001,
            "trained_chara_id": 7001,
            "name": "Parent A",
            "card_id": 100201,
            "tree": {"self": {"factors": [{"name": "Power", "stars": 3, "category": "stat"}]}},
        },
        {
            "instance_id": 7002,
            "trained_chara_id": 7002,
            "name": "Parent B",
            "card_id": 100301,
            "tree": {"self": {"factors": [{"name": "Power", "stars": 2, "category": "stat"}]}},
        },
    ]
    response = {
        "success": True,
        "results": [
            {
                "rank": 1,
                "score": 999,
                "parent1": {"id": 7001, "source": "owned", "name": "Parent A"},
                "parent2": {"id": 7002, "source": "owned", "name": "Parent B"},
            }
        ],
    }

    with pytest.raises(LineagePlanningError, match="No supported parent pair"):
        choose_lineage_setup(
            response,
            target_card_id=100101,
            session=session,
            target_factors=[
                {
                    "name": "power",
                    "minimum_stars": 9,
                    "scope": "lineage",
                    "aggregation": "sum",
                    "lineage_depth": "direct",
                    "required": True,
                }
            ],
        )


def test_choose_setup_skips_two_rentals_even_when_they_score_highest():
    response = {
        "success": True,
        "results": [
            {
                "rank": 1,
                "score": 999,
                "parent1": {"id": 8001, "source": "veteran", "name": "Rental A"},
                "parent2": {"id": 8002, "source": "veteran", "name": "Rental B"},
            },
            {
                "rank": 2,
                "score": 150,
                "parent1": {"id": 7001, "source": "owned", "name": "Owned A"},
                "parent2": {"id": 8001, "source": "veteran", "name": "Rental A"},
            },
        ],
    }

    selected = choose_lineage_setup(response)

    assert selected["rank"] == 2
    assert selected["score"] == 150


def test_choose_lineage_setup_can_rank_supported_pairs_by_affinity_first():
    response = {
        "success": True,
        "results": [
            {
                "rank": 1,
                "score": 300,
                "compat_total": 150,
                "parent1": {"id": 7001, "source": "owned", "card_id": 100101},
                "parent2": {"id": 7002, "source": "owned", "card_id": 100201},
            },
            {
                "rank": 2,
                "score": 250,
                "compat_total": 180,
                "parent1": {"id": 7003, "source": "owned", "card_id": 100301},
                "parent2": {"id": 7004, "source": "owned", "card_id": 100401},
            },
        ],
    }

    score_first = choose_lineage_setup(response, ranking="score")
    affinity_first = choose_lineage_setup(response, ranking="affinity")

    assert score_first["parent1"]["id"] == 7001
    assert affinity_first["parent1"]["id"] == 7003


def test_choose_setup_fails_when_no_supported_pair_exists():
    response = {
        "success": True,
        "results": [
            {
                "parent1": {"id": 8001, "source": "veteran"},
                "parent2": {"id": 8002, "source": "veteran"},
            }
        ],
    }

    with pytest.raises(LineagePlanningError, match="supported parent pair"):
        choose_lineage_setup(response)


def test_resolve_lineage_selection_preserves_non_parent_ui_selection():
    setup = {
        "rank": 1,
        "score": 200,
        "parent1": {"id": 7001, "source": "owned", "name": "Owned A"},
        "parent2": {"id": 8001, "source": "veteran", "name": "Rental A"},
        "compat_total": 155,
        "compat_tier": "◎",
        "race_score": 20,
        "spark_hits": [{"name": "Medium", "stars": 2}],
    }

    result = resolve_lineage_selection(sample_session(), setup)

    assert result["selection"]["trainee"]["id"] == 100101
    assert result["selection"]["deck"]["id"] == 3
    assert result["selection"]["friend"]["support_card_id"] == 401
    assert result["selection"]["veterans"][0]["instance_id"] == 7001
    assert result["selection"]["veterans"][1]["viewer_id"] == 99001
    assert result["summary"] == {
        "score": 200.0,
        "rank": 1,
        "compat_total": 155,
        "compat_tier": "◎",
        "race_score": 20,
        "parents": [
            {"trained_chara_id": 7001, "name": "Owned A", "source": "owned"},
            {"trained_chara_id": 8001, "name": "Rental A", "source": "veteran"},
        ],
        "spark_hits": [{"name": "Medium", "stars": 2}],
        "target_factor_evidence": [],
    }


def test_resolve_fails_if_recommendation_parent_is_missing_from_session():
    setup = {
        "parent1": {"id": 7001, "source": "owned"},
        "parent2": {"id": 9999, "source": "veteran"},
    }

    with pytest.raises(LineagePlanningError, match="9999"):
        resolve_lineage_selection(sample_session(), setup)
