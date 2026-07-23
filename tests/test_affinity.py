import sqlite3

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


def test_direct_relation_score_exposes_pair_base_compatibility(monkeypatch):
    monkeypatch.setattr(
        affinity,
        "_load_relations",
        lambda _mdb: (
            {1: 5, 2: 10, 3: 20},
            {
                1: frozenset({1004, 1007}),
                2: frozenset({1004, 1030}),
                3: frozenset({1007, 1030}),
            },
        ),
    )

    assert affinity.direct_relation_score("/tmp/master.mdb", 1004, 1007) == 5
    assert affinity.direct_relation_score("/tmp/master.mdb", 1004, 1030) == 10


def test_race_compat_counts_three_points_per_shared_g1():
    result = affinity.race_compat(
        [1, 2, 9],
        [[1, 2, 9], [2, 3]],
        [2, 3, 4, 9],
        [[3, 4], [1, 4]],
        {1, 2, 3, 4},
    )

    assert result == 21


def test_load_g1_saddle_program_map_resolves_race_instances_to_programs(tmp_path):
    path = tmp_path / "master.mdb"
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE single_mode_wins_saddle (
            id INTEGER PRIMARY KEY,
            win_saddle_type INTEGER NOT NULL,
            race_instance_id_1 INTEGER NOT NULL,
            race_instance_id_2 INTEGER NOT NULL,
            race_instance_id_3 INTEGER NOT NULL
        );
        CREATE TABLE single_mode_program (
            id INTEGER PRIMARY KEY,
            race_instance_id INTEGER NOT NULL
        );
        INSERT INTO single_mode_program (id, race_instance_id) VALUES
            (101, 1001), (102, 1002), (103, 1003), (104, 1002);
        INSERT INTO single_mode_wins_saddle
            (id, win_saddle_type, race_instance_id_1, race_instance_id_2, race_instance_id_3)
        VALUES
            (10, 3, 1001, 1002, 0),
            (20, 3, 1003, 0, 0),
            (30, 2, 1001, 0, 0);
        """
    )
    db.close()
    affinity.load_g1_saddle_program_map.cache_clear()

    result = affinity.load_g1_saddle_program_map(str(path))

    assert result == {
        101: {10},
        102: {10},
        103: {20},
        104: {10},
    }


def test_project_displayed_affinity_counts_planned_g1_per_direct_parent(monkeypatch):
    monkeypatch.setattr(
        affinity,
        "_pair_relation_score",
        lambda _path, _trainee, parent: {1002: 20, 1003: 30}.get(parent, 0),
    )

    result = affinity.project_displayed_veteran_affinity(
        "/tmp/master.mdb",
        trainee_card_id=100101,
        parent1={"card_id": 100201, "win_saddle_id_array": [10, 20]},
        parent2={"card_id": 100301, "win_saddle_id_array": [20, 30]},
        planned_g1_saddle_ids={10, 20},
    )

    assert result["base"] == 50
    assert result["planned_race"] == 9
    assert result["total"] == 59
    assert result["saddle_gains"] == {10: 3, 20: 6}


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
