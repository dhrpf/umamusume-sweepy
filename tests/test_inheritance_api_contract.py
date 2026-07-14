import asyncio
from types import SimpleNamespace

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


def test_inheritance_recommend_excludes_same_base_character_and_alt_costumes(monkeypatch):
    monkeypatch.setattr(
        main,
        "active_dashboard_data",
        {
            "parents": [
                {"instance_id": 1, "card_id": "100102", "name": "Target Alt", "tree": {"self": {}}, "rank_score": 50000},
                {"instance_id": 2, "card_id": "100201", "name": "Parent B", "tree": {"self": {}}, "rank_score": 40000},
                {"instance_id": 3, "card_id": "100202", "name": "Parent B Alt", "tree": {"self": {}}, "rank_score": 39000},
                {"instance_id": 4, "card_id": "100301", "name": "Parent C", "tree": {"self": {}}, "rank_score": 38000},
            ],
            "friendVeterans": [],
        },
    )
    monkeypatch.setattr(
        main,
        "active_parent_full",
        {
            1: {"trained_chara_id": 1, "card_id": 100102, "succession_chara_array": []},
            2: {"trained_chara_id": 2, "card_id": 100201, "succession_chara_array": []},
            3: {"trained_chara_id": 3, "card_id": 100202, "succession_chara_array": []},
            4: {"trained_chara_id": 4, "card_id": 100301, "succession_chara_array": []},
        },
    )
    monkeypatch.setattr(main.master_data, "status", lambda _base_dir: {"master_mdb_path": "/tmp/master.mdb"})
    monkeypatch.setattr(
        main.affinity_calc,
        "calculate_affinity",
        lambda *_args, **_kwargs: {"total": 160, "race_compat": 30},
    )

    result = asyncio.run(
        main.inheritance_recommend(
            main.InheritanceRecommendRequest(
                target_card_id=100101,
                pool="owned",
                goal={},
                limit=20,
            )
        )
    )

    assert result["success"] is True
    assert result["target_base_chara_id"] == 1001
    assert result["excluded_same_as_trainee"] == 1
    assert result["excluded_same_parent_character_pairs"] == 1
    assert result["results"]
    for row in result["results"]:
        bases = {row["parent1"]["base_chara_id"], row["parent2"]["base_chara_id"]}
        assert 1001 not in bases
        assert len(bases) == 2


def test_inheritance_recommend_filters_pairs_that_cannot_reach_direct_lineage_power_nine(monkeypatch):
    def parent(instance_id, card_id, name, power_stars):
        factors = []
        if power_stars:
            factors.append({"name": "Power", "stars": power_stars, "category": "stat"})
        return {
            "instance_id": instance_id,
            "card_id": str(card_id),
            "name": name,
            "rank_score": 20000,
            "tree": {"self": {"factors": factors, "wins": []}},
        }

    monkeypatch.setattr(
        main,
        "active_dashboard_data",
        {
            "parents": [
                parent(1, 100201, "Power A", 3),
                parent(2, 100301, "Power B", 3),
                parent(3, 100401, "Power C", 2),
                parent(4, 100501, "No Power", 0),
            ],
            "friendVeterans": [],
        },
    )
    monkeypatch.setattr(main, "active_parent_full", {})
    monkeypatch.setattr(main.master_data, "status", lambda _base_dir: {})

    result = asyncio.run(
        main.inheritance_recommend(
            main.InheritanceRecommendRequest(
                target_card_id=100101,
                pool="owned",
                goal={
                    "distance": "",
                    "surface": "",
                    "target_factors": [
                        {
                            "name": "power",
                            "minimum_stars": 9,
                            "scope": "lineage",
                            "aggregation": "sum",
                            "lineage_depth": "direct",
                            "required": True,
                        }
                    ],
                },
                limit=20,
            )
        )
    )

    assert result["success"] is True
    assert result["excluded_factor_infeasible_pairs"] == 5
    assert len(result["results"]) == 1
    selected = result["results"][0]
    assert {selected["parent1"]["id"], selected["parent2"]["id"]} == {1, 2}
    assert selected["target_factor_feasible"] is True
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


def test_start_selection_rejects_alt_costume_of_trainee_as_direct_parent(monkeypatch):
    monkeypatch.setattr(main, "support_map", {"9001": {"name": "Friend Support"}})
    monkeypatch.setattr(main, "chara_map", {"100101": "Target"})
    monkeypatch.setattr(main, "active_parent_cards", {11: [100102], 22: [100201]})
    request = SimpleNamespace(
        support_card_ids=[],
        friend_card_id=9001,
        card_id=100101,
        parent_id_1=11,
        parent_id_2=22,
    )

    assert main.validate_start_selection(request) == "Selected direct parent is same character as trainee"


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
