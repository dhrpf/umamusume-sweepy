from career_bot.affinity import card_to_chara_id
from career_bot.campaigns.legacy.scanner import scan_legacy_loop_pools


def record(
    trained_id,
    card_id,
    *,
    rank_score=20000,
    wins=(10, 20),
    style="late_surger",
    medium=7,
    mile=7,
    long=6,
):
    values = {
        "proper_running_style_nige": 1,
        "proper_running_style_senko": 2,
        "proper_running_style_sashi": 3,
        "proper_running_style_oikomi": 1,
    }
    field = {
        "front_runner": "proper_running_style_nige",
        "pace_chaser": "proper_running_style_senko",
        "late_surger": "proper_running_style_sashi",
        "end_closer": "proper_running_style_oikomi",
    }[style]
    values[field] = 7
    return {
        "trained_chara_id": trained_id,
        "card_id": card_id,
        "rank_score": rank_score,
        "rank": 14,
        "win_saddle_id_array": list(wins),
        "factor_id_array": [10103, 20202],
        "proper_ground_turf": 7,
        "proper_distance_short": 3,
        "proper_distance_mile": mile,
        "proper_distance_middle": medium,
        "proper_distance_long": long,
        **values,
    }


def fake_affinity(_mdb_path, trainee_card_id, parent1, parent2):
    base_ids = {
        card_to_chara_id(trainee_card_id),
        card_to_chara_id(parent1["card_id"]),
        card_to_chara_id(parent2["card_id"]),
    }
    weak = 1005 in base_ids
    return {
        "total": 40 if weak else 160,
        "chara_compat": 25 if weak else 130,
        "race_compat": 15 if weak else 30,
    }


def test_scanner_finds_four_distinct_character_double_circle_pool(tmp_path):
    records = [
        record(101, 100101),
        record(102, 100102, rank_score=19000),  # alt costume, same base character
        record(201, 100201),
        record(301, 100301),
        record(401, 100401),
        record(501, 100501, wins=(), style="front_runner", medium=4, mile=4, long=3),
    ]
    names = {
        101: "Loop A",
        201: "Loop B",
        301: "Loop C",
        401: "Loop D",
        501: "Weak E",
    }

    result = scan_legacy_loop_pools(
        records,
        mdb_path=tmp_path / "unused.mdb",
        veteran_names=names,
        max_characters=5,
        records_per_character=2,
        limit=5,
        affinity_calculator=fake_affinity,
        g1_saddle_ids={10, 20, 30},
    )

    assert result["distinct_characters_available"] == 5
    assert result["characters_considered"] == 5
    best = result["pools"][0]
    assert best["base_chara_ids"] == [1001, 1002, 1003, 1004]
    assert best["affinity"]["worst"] == 160
    assert best["affinity"]["tier"]["name"] == "double_circle"
    assert best["affinity"]["meets_target"] is True
    assert len(best["affinity"]["rotations"]) == 4
    assert best["shared_g1"] == [10, 20]
    assert best["running_style"] == {
        "dominant": "late_surger",
        "matching_members": 4,
        "all_match": True,
    }
    assert best["distance_overlap"]["strict_a_or_better"] == ["mile", "medium"]
    assert best["distance_overlap"]["usable_b_or_better"] == ["mile", "medium", "long"]
    assert [member["name"] for member in best["members"]] == [
        "Loop A",
        "Loop B",
        "Loop C",
        "Loop D",
    ]


def test_scanner_ranks_triangle_pool_below_double_circle(tmp_path):
    records = [
        record(101, 100101),
        record(201, 100201),
        record(301, 100301),
        record(401, 100401),
        record(501, 100501, wins=()),
    ]

    result = scan_legacy_loop_pools(
        records,
        mdb_path=tmp_path / "unused.mdb",
        max_characters=5,
        limit=10,
        affinity_calculator=fake_affinity,
        g1_saddle_ids={10, 20},
    )

    assert result["pools"][0]["affinity"]["tier"]["name"] == "double_circle"
    weak_pools = [pool for pool in result["pools"] if 1005 in pool["base_chara_ids"]]
    assert weak_pools
    assert all(pool["affinity"]["tier"]["name"] == "triangle" for pool in weak_pools)
    assert all(pool["affinity"]["meets_target"] is False for pool in weak_pools)


def test_scanner_requires_four_distinct_base_characters(tmp_path):
    result = scan_legacy_loop_pools(
        [
            record(101, 100101),
            record(102, 100102),
            record(201, 100201),
            record(301, 100301),
        ],
        mdb_path=tmp_path / "unused.mdb",
        affinity_calculator=fake_affinity,
        g1_saddle_ids={10, 20},
    )

    assert result["distinct_characters_available"] == 3
    assert result["pool_count"] == 0
    assert result["pools"] == []
