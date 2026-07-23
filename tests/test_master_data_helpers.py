import json

from career_bot.master_data import (
    build_race_context,
    distance_label,
    factor_category,
    is_ui_selectable_race,
    legacy_race_ids_by_occurrence,
    race_date_label,
    race_occurrence_id,
    race_turn,
    synthesize_public_race_data,
    year_offsets_for_permission,
)


def test_race_date_turn_and_occurrence_helpers():
    assert race_date_label(4, 1, 24) == "Classic Year Early Apr"
    assert race_turn(4, 2, 24) == 32
    assert race_occurrence_id(123, 24) == 200123


def test_distance_and_permission_labels():
    assert distance_label(1400) == "Sprint"
    assert distance_label(1800) == "Mile"
    assert distance_label(2400) == "Medium"
    assert distance_label(2500) == "Long"
    assert year_offsets_for_permission(3) == [24, 48]
    assert year_offsets_for_permission(0) == []


def test_factor_category_by_id_shape():
    assert factor_category(101) == "stat"
    assert factor_category(1001) == "aptitude"
    assert factor_category(1000001) == "race"
    assert factor_category(2000001) == "skill"
    assert factor_category(3000001) == "scenario"
    assert factor_category(10000001) == "unique"
    assert factor_category(1) == "other"


def test_is_ui_selectable_race_rejects_generated_and_debut_rows():
    valid = {
        "program": {"base_program_id": 0, "race_permission": 3},
        "race": {"grade": 100},
        "name": "Arima Kinen",
    }
    assert is_ui_selectable_race(valid) is True

    generated = {**valid, "program": {"base_program_id": 99, "race_permission": 3}}
    assert is_ui_selectable_race(generated) is False

    debut = {**valid, "name": "Make Debut"}
    assert is_ui_selectable_race(debut) is False


def test_build_race_context_fills_missing_global_dirt_g1_programs():
    master_data = {
        "tables": {
            "race": [],
            "race_course_set": [],
            "race_instance": [],
            "single_mode_program": [],
        },
        "text": {
            "cat_28_text": [
                {"index": 110701, "text": "Kawasaki Kinen"},
                {"index": 110801, "text": "Zen-Nippon Junior Yushun"},
                {"index": 110901, "text": "Kashiwa Kinen"},
                {"index": 111001, "text": "M.C. Nambu Hai"},
            ]
        },
    }

    context = build_race_context(master_data)

    assert context[1106]["name"] == "Kawasaki Kinen"
    assert context[1106]["program"]["race_permission"] == 4
    assert context[1106]["program"]["month"] == 2
    assert context[1106]["program"]["half"] == 1
    assert context[1106]["course"] == {"ground": 2, "distance": 2100, "race_track_id": 10103}

    assert context[1107]["name"] == "Zen-Nippon Junior Yushun"
    assert context[1107]["program"]["race_permission"] == 1
    assert context[1107]["program"]["month"] == 12
    assert context[1107]["program"]["half"] == 2
    assert context[1107]["course"] == {"ground": 2, "distance": 1600, "race_track_id": 10103}

    assert context[1108]["name"] == "Kashiwa Kinen"
    assert context[1108]["program"]["race_permission"] == 4
    assert context[1108]["course"] == {"ground": 2, "distance": 1600, "race_track_id": 10104}

    assert context[1109]["name"] == "M.C. Nambu Hai"
    assert context[1109]["program"]["race_permission"] == 3
    assert context[1109]["program"]["month"] == 10
    assert context[1109]["program"]["half"] == 1
    assert context[1109]["course"] == {"ground": 2, "distance": 1600, "race_track_id": 10105}


def test_missing_global_dirt_g1_fallbacks_generate_planner_occurrences(tmp_path):
    master_data = {
        "tables": {
            "race": [],
            "race_course_set": [],
            "race_instance": [],
            "single_mode_program": [],
        },
        "text": {"cat_28_text": []},
    }
    context = build_race_context(master_data)
    (tmp_path / "public" / "assets" / "data").mkdir(parents=True)

    result = synthesize_public_race_data(tmp_path, context)
    rows = json.loads((tmp_path / "public" / "assets" / "data" / "uma_race_data.json").read_text(encoding="utf-8"))["races"]
    fallback_rows = [row for row in rows if row["program_id"] in {1106, 1107, 1108, 1109}]

    assert result["rows"] == 5
    assert [(row["program_id"], row["date"]) for row in fallback_rows] == [
        (1107, "Junior Year Late Dec"),
        (1109, "Classic Year Early Oct"),
        (1106, "Senior Year Early Feb"),
        (1108, "Senior Year Early May"),
        (1109, "Senior Year Early Oct"),
    ]
    by_program = {row["program_id"]: row for row in fallback_rows}
    assert by_program[1106]["venue"] == "Kawasaki"
    assert by_program[1107]["venue"] == "Kawasaki"
    assert by_program[1108]["venue"] == "Funabashi"
    assert by_program[1109]["venue"] == "Morioka"
    assert all(row["type"] == "G1" and row["terrain"] == "Dirt" for row in fallback_rows)


def test_native_global_dirt_g1_program_wins_over_fallback():
    master_data = {
        "tables": {
            "race": [{"id": 999, "grade": 100, "course_set": 888}],
            "race_course_set": [{"id": 888, "ground": 2, "distance": 1234, "race_track_id": 10101}],
            "race_instance": [{"id": 777, "race_id": 999}],
            "single_mode_program": [
                {"id": 1106, "base_program_id": 0, "race_instance_id": 777, "race_permission": 4, "month": 3, "half": 2}
            ],
        },
        "text": {"cat_28_text": [{"index": 777, "text": "Native Kawasaki"}]},
    }

    context = build_race_context(master_data)

    assert context[1106]["race_instance_id"] == 777
    assert context[1106]["name"] == "Native Kawasaki"
    assert context[1106]["course"]["distance"] == 1234
    assert context[1106]["program"]["month"] == 3


def test_legacy_race_ids_by_occurrence_filters_new_ids():
    existing_meta = {
        "77": {"program_id": 1001, "turn": 12},
        "77_duplicate": {"program_id": 1001, "turn": 12},
        "1001": {"program_id": 1001, "turn": 12},
        "2001001": {"program_id": 1001, "turn": 36},
        "bad": {"program_id": "x", "turn": 1},
    }

    assert legacy_race_ids_by_occurrence(existing_meta) == {(1001, 12): [77]}
