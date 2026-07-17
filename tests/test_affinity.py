from career_bot import affinity


def test_calculate_veteran_affinity_matches_uma_moe_lineage_breakdown(monkeypatch):
    monkeypatch.setattr(
        affinity,
        "_load_relations",
        lambda _mdb: (
            {1: 20, 2: 19, 3: 99},
            {
                1: frozenset({1004, 1014}),
                2: frozenset({1004, 1006}),
                3: frozenset({1014, 1006}),
            },
        ),
    )
    monkeypatch.setattr(
        affinity,
        "_load_g1_saddles",
        lambda _mdb: {10, 11, 12, 14, 15, 18, 26, 27},
    )
    veteran = {
        "card_id": 100401,
        "win_saddle_id_array": [6, 10, 11, 12, 14, 15, 18, 26, 27],
        "succession_chara_array": [
            {
                "position_id": 10,
                "card_id": 101401,
                "win_saddle_id_array": [6, 10, 11, 12, 14, 18, 26],
            },
            {
                "position_id": 20,
                "card_id": 100601,
                "win_saddle_id_array": [6, 10, 14, 15, 27],
            },
        ],
    }

    result = affinity.calculate_veteran_affinity("/tmp/master.mdb", veteran)

    assert result == {
        "total": 69,
        "base": 39,
        "race": 30,
        "parent_1": {
            "position_id": 10,
            "card_id": 101401,
            "base": 20,
            "race": 18,
            "total": 38,
        },
        "parent_2": {
            "position_id": 20,
            "card_id": 100601,
            "base": 19,
            "race": 12,
            "total": 31,
        },
    }


def test_calculate_veteran_affinity_returns_zero_for_missing_direct_parents(monkeypatch):
    monkeypatch.setattr(affinity, "_load_relations", lambda _mdb: ({}, {}))
    monkeypatch.setattr(affinity, "_load_g1_saddles", lambda _mdb: set())

    result = affinity.calculate_veteran_affinity(
        "/tmp/master.mdb",
        {"card_id": 100401, "succession_chara_array": []},
    )

    assert result["total"] == 0
    assert result["base"] == 0
    assert result["race"] == 0
    assert result["parent_1"]["total"] == 0
    assert result["parent_2"]["total"] == 0
