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
        "goal": {"distance": "medium", "surface": "turf"},
        "limit": 50,
    }


def test_build_request_requires_current_trainee_selection():
    session = sample_session()
    session["selection"]["trainee"] = None

    with pytest.raises(LineagePlanningError, match="trainee"):
        build_inheritance_request(campaign_spec(), session)


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
    }


def test_resolve_fails_if_recommendation_parent_is_missing_from_session():
    setup = {
        "parent1": {"id": 7001, "source": "owned"},
        "parent2": {"id": 9999, "source": "veteran"},
    }

    with pytest.raises(LineagePlanningError, match="9999"):
        resolve_lineage_selection(sample_session(), setup)
