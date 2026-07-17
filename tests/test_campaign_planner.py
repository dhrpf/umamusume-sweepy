from career_bot.campaigns.planner import CampaignPlanner


FACTOR_MAP = {
    "301": {"name": "Power", "stars": 1, "category": "stat"},
    "303": {"name": "Power", "stars": 3, "category": "stat"},
}


def veteran(trained_id, card_id, *, factor_id=301, rank_score=20000, wins=(10, 20)):
    return {
        "trained_chara_id": trained_id,
        "card_id": card_id,
        "rank_score": rank_score,
        "factor_id_array": [factor_id],
        "win_saddle_id_array": list(wins),
        "proper_running_style_sashi": 7,
        "proper_distance_mile": 7,
        "proper_distance_middle": 7,
        "proper_distance_long": 6,
    }


def affinity(trainee_card_id, parent1, parent2):
    chara_ids = {
        trainee_card_id // 100,
        parent1["card_id"] // 100,
        parent2["card_id"] // 100,
    }
    total = 170 if 1001 in chara_ids else 155
    return {"total": total, "chara_compat": total - 20, "race_compat": 20}


def planner(final_uma_card_id=100601):
    records = [
        veteran(101, 100101, factor_id=303, rank_score=22000),
        veteran(102, 100102, factor_id=301, rank_score=18000),
        veteran(201, 100201),
        veteran(301, 100301),
        veteran(401, 100401),
        veteran(501, 100501),
    ]
    return CampaignPlanner(
        owned_chara_ids={1001, 1002, 1003, 1004},
        veteran_records=records,
        display_by_id={row["trained_chara_id"]: {"name": f"V{row['trained_chara_id']}"} for row in records},
        factor_map=FACTOR_MAP,
        spark_targets=[
            {"category": "blue", "name": "power", "minimum_stars": 3, "priority": "required"}
        ],
        final_uma_card_id=final_uma_card_id,
        g1_saddle_ids={10, 20},
        race_rows=[
            {"program_id": 10, "name": "G1 A", "type": "G1", "terrain": "Turf", "distance": "Medium", "turn": 30},
            {"program_id": 20, "name": "G1 B", "type": "G1", "terrain": "Turf", "distance": "Long", "turn": 50},
        ],
        affinity_for_pair=affinity,
    )


def test_final_parent_recommendations_are_deterministic_unique_characters():
    campaign_planner = planner()

    result = campaign_planner.recommend_final_parents(limit=3)

    assert len(result) == 3
    assert result == campaign_planner.recommend_final_parents(limit=3)
    assert result == sorted(result, key=lambda row: (-row["score"], row["chara_id"]))
    assert len({row["chara_id"] for row in result}) == 3
    assert result[0]["chara_id"] == 1001
    assert result[0]["veteran"]["trained_chara_id"] == 101
    assert result[0]["pairing"]["affinity"] == 170
    assert result[0]["score_breakdown"] == {
        "required_progress": 1.0,
        "preferred_progress": 1.0,
        "final_affinity": 170,
        "existing_veteran": True,
        "remaining_effort": 0.0,
    }



def test_final_parent_recommendations_exclude_final_uma_character():
    campaign_planner = planner(final_uma_card_id=100101)

    result = campaign_planner.recommend_final_parents(limit=10)

    assert result
    assert all(row["chara_id"] != 1001 for row in result)
    assert all(row["pairing"].get("second_parent_chara_id") != 1001 for row in result)


def test_loop_recommendations_require_selected_final_parent_character(tmp_path):
    campaign_planner = planner()

    result = campaign_planner.recommend_loops(
        pinned_chara_ids={1001},
        final_parent_chara_id=1004,
        limit=3,
        mdb_path=tmp_path / "unused.mdb",
    )

    assert result["loops"]
    assert all({1001, 1004}.issubset(set(row["chara_ids"])) for row in result["loops"])

def test_loop_recommendations_are_owned_pinned_enriched_and_separate_upgrades(tmp_path):
    campaign_planner = planner()

    result = campaign_planner.recommend_loops(
        pinned_chara_ids={1001},
        limit=3,
        mdb_path=tmp_path / "unused.mdb",
    )

    assert result["loops"]
    assert all(row["owned"] is True for row in result["loops"])
    assert all(1001 in row["chara_ids"] for row in result["loops"])
    assert all(row["shared_g1_agenda"]["selected_count"] == 2 for row in result["loops"])
    assert all("final_target_fit" in row["score_breakdown"] for row in result["loops"])
    assert result["ideal_upgrades"]
    assert all(1005 in row["chara_ids"] for row in result["ideal_upgrades"])
    assert all(row["owned"] is False for row in result["ideal_upgrades"])


def test_loop_recommendations_preserve_low_ranked_pin_past_scanner_cap(tmp_path):
    records = [
        veteran(base_id, base_id * 100 + 1, rank_score=30000 - base_id)
        for base_id in range(1001, 1014)
    ]
    records[-1]["rank_score"] = 1
    campaign_planner = CampaignPlanner(
        owned_chara_ids=set(range(1001, 1014)),
        veteran_records=records,
        display_by_id={},
        g1_saddle_ids={10, 20},
        race_rows=[],
        affinity_for_pair=affinity,
    )

    result = campaign_planner.recommend_loops(
        pinned_chara_ids={1013},
        limit=3,
        mdb_path=tmp_path / "unused.mdb",
    )

    assert result["loops"]
    assert all(1013 in row["chara_ids"] for row in result["loops"])


def test_loop_recommendations_are_deterministic_for_input_permutations(tmp_path):
    records = [veteran(base_id, base_id * 100 + 1) for base_id in range(1001, 1006)]

    def recommend(rows):
        campaign_planner = CampaignPlanner(
            owned_chara_ids=set(range(1001, 1006)),
            veteran_records=rows,
            display_by_id={},
            g1_saddle_ids={10, 20},
            race_rows=[],
            affinity_for_pair=affinity,
        )
        return campaign_planner.recommend_loops(
            limit=5,
            mdb_path=tmp_path / "unused.mdb",
        )

    assert recommend(records) == recommend(list(reversed(records)))
