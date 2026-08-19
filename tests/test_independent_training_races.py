import sqlite3

import pytest

from career_bot.independent_training.races import (
    canonicalize_race_array,
    canonicalize_start_race_array,
)


def test_canonicalize_races_filters_filly_only_and_adds_missing_objective():
    races = [
        {"year": 2, "program_id": 183},
        {"year": 1, "program_id": 623},
        {"year": 1, "program_id": 1107},
        {"year": 2, "program_id": 77},
        {"year": 2, "program_id": 167},
    ]
    objectives = [
        {"turn": 12, "program_id": 846},
        {"turn": 27, "program_id": 183},
    ]
    programs = {
        623: {"month": 12, "half": 1, "filly_only_flag": 1},
        1107: {"month": 12, "half": 2, "filly_only_flag": 0},
        77: {"month": 11, "half": 1, "filly_only_flag": 1},
        167: {"month": 10, "half": 2, "filly_only_flag": 1},
        183: {"month": 2, "half": 1, "filly_only_flag": 0},
        846: {"month": 6, "half": 2, "filly_only_flag": 0},
    }

    assert canonicalize_race_array(
        races,
        objectives=objectives,
        programs=programs,
        chara_sex=1,
    ) == [
        {"year": 2, "program_id": 183},
        {"year": 1, "program_id": 1107},
        {"year": 1, "program_id": 846},
    ]


def test_start_race_loader_uses_master_card_sex_and_objectives(tmp_path):
    db_path = tmp_path / "master.mdb"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE card_data (id INTEGER, chara_id INTEGER);
            CREATE TABLE chara_data (id INTEGER, sex INTEGER);
            CREATE TABLE single_mode_program (
                id INTEGER,
                month INTEGER,
                half INTEGER,
                filly_only_flag INTEGER
            );
            CREATE TABLE single_mode_route (
                id INTEGER,
                scenario_id INTEGER,
                chara_id INTEGER,
                race_set_id INTEGER,
                priority INTEGER
            );
            CREATE TABLE single_mode_route_race (
                id INTEGER,
                race_set_id INTEGER,
                scenario_group_id INTEGER,
                target_type INTEGER,
                sort_id INTEGER,
                turn INTEGER,
                race_type INTEGER,
                condition_type INTEGER,
                condition_id INTEGER,
                determine_race INTEGER,
                determine_race_flag INTEGER
            );
            INSERT INTO card_data VALUES (101401, 1014);
            INSERT INTO chara_data VALUES (1014, 1);
            INSERT INTO single_mode_program VALUES (623, 12, 1, 1);
            INSERT INTO single_mode_program VALUES (846, 6, 2, 0);
            INSERT INTO single_mode_route VALUES (1, 0, 1014, 1014, 1);
            INSERT INTO single_mode_route_race VALUES (
                1, 1014, 0, 1, 1, 12, 0, 1, 846, 0, 0
            );
            """
        )

    assert canonicalize_start_race_array(
        tmp_path,
        {
            "card_id": 101401,
            "race_array": [{"year": 1, "program_id": 623}],
        },
        master_mdb_path=db_path,
    ) == [{"year": 1, "program_id": 846}]


def test_start_race_loader_resolves_card_specific_objective(tmp_path):
    db_path = tmp_path / "master.mdb"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE card_data (id INTEGER, chara_id INTEGER);
            CREATE TABLE chara_data (id INTEGER, sex INTEGER);
            CREATE TABLE single_mode_program (
                id INTEGER,
                month INTEGER,
                half INTEGER,
                filly_only_flag INTEGER
            );
            CREATE TABLE single_mode_route (
                id INTEGER,
                scenario_id INTEGER,
                chara_id INTEGER,
                race_set_id INTEGER,
                priority INTEGER
            );
            CREATE TABLE single_mode_route_race (
                id INTEGER,
                race_set_id INTEGER,
                scenario_group_id INTEGER,
                target_type INTEGER,
                sort_id INTEGER,
                turn INTEGER,
                race_type INTEGER,
                condition_type INTEGER,
                condition_id INTEGER,
                determine_race INTEGER,
                determine_race_flag INTEGER
            );
            INSERT INTO card_data VALUES (100901, 1009);
            INSERT INTO chara_data VALUES (1009, 2);
            INSERT INTO single_mode_program VALUES (165, 5, 2, 1);
            INSERT INTO single_mode_program VALUES (166, 5, 2, 0);
            INSERT INTO single_mode_route VALUES (1, 0, 1009, 1009, 1);
            INSERT INTO single_mode_route_race VALUES (
                1, 1009, 0, 1, 4, 34, 0, 1, 165, 1, 0
            );
            INSERT INTO single_mode_route_race VALUES (
                2, 1009, 0, 1, 4, 34, 0, 1, 166, 2, 100901
            );
            """
        )

    assert canonicalize_start_race_array(
        tmp_path,
        {"card_id": 100901, "race_array": []},
        master_mdb_path=db_path,
    ) == [{"year": 2, "program_id": 166}]


def test_start_race_loader_falls_back_when_costume_cards_unreleased(tmp_path):
    db_path = tmp_path / "master.mdb"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE card_data (id INTEGER, chara_id INTEGER);
            CREATE TABLE chara_data (id INTEGER, sex INTEGER);
            CREATE TABLE single_mode_program (
                id INTEGER,
                month INTEGER,
                half INTEGER,
                filly_only_flag INTEGER
            );
            CREATE TABLE single_mode_route (
                id INTEGER,
                scenario_id INTEGER,
                chara_id INTEGER,
                race_set_id INTEGER,
                priority INTEGER
            );
            CREATE TABLE single_mode_route_race (
                id INTEGER,
                race_set_id INTEGER,
                scenario_group_id INTEGER,
                target_type INTEGER,
                sort_id INTEGER,
                turn INTEGER,
                race_type INTEGER,
                condition_type INTEGER,
                condition_id INTEGER,
                determine_race INTEGER,
                determine_race_flag INTEGER
            );
            INSERT INTO card_data VALUES (100501, 1005);
            INSERT INTO chara_data VALUES (1005, 1);
            INSERT INTO single_mode_program VALUES (168, 8, 2, 0);
            INSERT INTO single_mode_program VALUES (78, 8, 2, 0);
            INSERT INTO single_mode_route VALUES (1, 0, 1005, 1005, 1);
            INSERT INTO single_mode_route_race VALUES (
                421, 1005, 100, 1, 6, 44, 0, 1, 168, 3, 100503
            );
            INSERT INTO single_mode_route_race VALUES (
                422, 1005, 100, 1, 6, 46, 0, 1, 78, 3, 100504
            );
            """
        )

    assert canonicalize_start_race_array(
        tmp_path,
        {"card_id": 100501, "race_array": []},
        master_mdb_path=db_path,
    ) == [{"year": 2, "program_id": 168}]


def test_start_race_loader_ignores_non_program_objective(tmp_path):
    db_path = tmp_path / "master.mdb"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE card_data (id INTEGER, chara_id INTEGER);
            CREATE TABLE chara_data (id INTEGER, sex INTEGER);
            CREATE TABLE single_mode_program (
                id INTEGER,
                month INTEGER,
                half INTEGER,
                filly_only_flag INTEGER
            );
            CREATE TABLE single_mode_route (
                id INTEGER,
                scenario_id INTEGER,
                chara_id INTEGER,
                race_set_id INTEGER,
                priority INTEGER
            );
            CREATE TABLE single_mode_route_race (
                id INTEGER,
                race_set_id INTEGER,
                scenario_group_id INTEGER,
                target_type INTEGER,
                sort_id INTEGER,
                turn INTEGER,
                race_type INTEGER,
                condition_type INTEGER,
                condition_id INTEGER,
                determine_race INTEGER,
                determine_race_flag INTEGER
            );
            INSERT INTO card_data VALUES (105201, 1052);
            INSERT INTO chara_data VALUES (1052, 1);
            INSERT INTO single_mode_route VALUES (1, 0, 1052, 1052, 1);
            INSERT INTO single_mode_route_race VALUES (
                1, 1052, 0, 1, 8, 69, 4, 1, 20002, 0, 0
            );
            """
        )

    assert canonicalize_start_race_array(
        tmp_path,
        {"card_id": 105201, "race_array": []},
        master_mdb_path=db_path,
    ) == []


def test_start_race_loader_rejects_unknown_queued_program(tmp_path):
    db_path = tmp_path / "master.mdb"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE card_data (id INTEGER, chara_id INTEGER);
            CREATE TABLE chara_data (id INTEGER, sex INTEGER);
            CREATE TABLE single_mode_program (
                id INTEGER,
                month INTEGER,
                half INTEGER,
                filly_only_flag INTEGER
            );
            CREATE TABLE single_mode_route (
                id INTEGER,
                scenario_id INTEGER,
                chara_id INTEGER,
                race_set_id INTEGER,
                priority INTEGER
            );
            CREATE TABLE single_mode_route_race (
                id INTEGER,
                race_set_id INTEGER,
                scenario_group_id INTEGER,
                target_type INTEGER,
                sort_id INTEGER,
                turn INTEGER,
                race_type INTEGER,
                condition_type INTEGER,
                condition_id INTEGER,
                determine_race INTEGER,
                determine_race_flag INTEGER
            );
            INSERT INTO card_data VALUES (101401, 1014);
            INSERT INTO chara_data VALUES (1014, 1);
            INSERT INTO single_mode_route VALUES (1, 0, 1014, 1014, 1);
            """
        )

    with pytest.raises(ValueError, match="missing race programs"):
        canonicalize_start_race_array(
            tmp_path,
            {
                "card_id": 101401,
                "race_array": [{"year": 1, "program_id": 999}],
            },
            master_mdb_path=db_path,
        )


def test_canonicalize_races_preserves_filly_only_for_eligible_trainee():
    races = [{"year": 1, "program_id": 623}]

    assert canonicalize_race_array(
        races,
        objectives=[],
        programs={
            623: {"month": 12, "half": 1, "filly_only_flag": 1},
        },
        chara_sex=2,
    ) == races


def test_canonicalize_races_replaces_race_in_mandatory_objective_slot():
    races = [
        {"year": 1, "program_id": 999},
        {"year": 2, "program_id": 183},
    ]

    assert canonicalize_race_array(
        races,
        objectives=[{"turn": 12, "program_id": 846}],
        programs={
            999: {"month": 6, "half": 2, "filly_only_flag": 0},
            183: {"month": 2, "half": 1, "filly_only_flag": 0},
            846: {"month": 6, "half": 2, "filly_only_flag": 0},
        },
        chara_sex=1,
    ) == [
        {"year": 2, "program_id": 183},
        {"year": 1, "program_id": 846},
    ]
