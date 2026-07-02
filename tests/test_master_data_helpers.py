from career_bot.master_data import (
    distance_label,
    factor_category,
    is_ui_selectable_race,
    legacy_race_ids_by_occurrence,
    race_date_label,
    race_occurrence_id,
    race_turn,
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


def test_legacy_race_ids_by_occurrence_filters_new_ids():
    existing_meta = {
        "77": {"program_id": 1001, "turn": 12},
        "77_duplicate": {"program_id": 1001, "turn": 12},
        "1001": {"program_id": 1001, "turn": 12},
        "2001001": {"program_id": 1001, "turn": 36},
        "bad": {"program_id": "x", "turn": 1},
    }

    assert legacy_race_ids_by_occurrence(existing_meta) == {(1001, 12): [77]}
