import main


def test_inheritance_request_model_matches_frontend_contract():
    request = main.InheritanceRecommendRequest(
        target_card_id=100101,
        pool="both",
        goal={"distance": "medium", "surface": "turf"},
        limit=10,
    )

    assert request.target_card_id == 100101
    assert request.pool == "both"
    assert request.goal == {"distance": "medium", "surface": "turf"}
    assert request.limit == 10


def test_compatibility_tiers_follow_legacy_circle_thresholds():
    assert main._compat_tier(49) == "△"
    assert main._compat_tier(50) == "◯"
    assert main._compat_tier(150) == "◯"
    assert main._compat_tier(151) == "◎"


def test_trained_aptitudes_map_game_fields_for_campaign_evaluation():
    assert main.get_trained_aptitudes(
        {
            "proper_ground_turf": 7,
            "proper_ground_dirt": 4,
            "proper_distance_short": 3,
            "proper_distance_mile": 6,
            "proper_distance_middle": 8,
            "proper_distance_long": 5,
        }
    ) == {
        "turf": 7,
        "dirt": 4,
        "sprint": 3,
        "mile": 6,
        "medium": 8,
        "long": 5,
    }


def test_inheritance_request_normalizes_limits_and_rejects_bad_pool():
    request = main.InheritanceRecommendRequest(
        target_card_id=100101,
        pool="owned",
        goal={},
        limit=500,
    )
    assert request.limit == 50

    try:
        main.InheritanceRecommendRequest(
            target_card_id=100101,
            pool="unknown",
            goal={},
        )
    except Exception as exc:
        assert "pool" in str(exc)
    else:
        raise AssertionError("bad inheritance pool must be rejected")
