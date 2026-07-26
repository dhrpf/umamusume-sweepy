import json

import pytest

from career_bot import master_data
from career_bot.grand_live_data import (
    GrandLiveData,
    GrandLiveDataError,
    validate_square_reference,
)


def _square(square_id=40000, square_type=4, cost=21):
    return {
        "id": square_id,
        "square_type": square_type,
        "master_bonus_id": square_id,
        "square_title_text_id": square_id,
        "square_content_text_id": square_id,
        "perf_type_1": 2,
        "perf_value_1": cost,
        "perf_type_2": 4,
        "perf_value_2": cost,
        "perf_type_3": 0,
        "perf_value_3": 0,
        "perf_type_4": 0,
        "perf_value_4": 0,
        "perf_type_5": 0,
        "perf_value_5": 0,
    }


def _master(square_rows=None):
    return {
        "tables": {
            "single_mode_live_square": square_rows or [_square()],
            "single_mode_live_master_bonus": [{
                "id": 40000,
                "master_bonus_type": 4,
                "master_bonus_type_value": 1032,
                "master_bonus_gain_type_1": 5,
                "master_bonus_gain_value_1_1": 6,
                "master_bonus_gain_value_1_2": 2,
                "master_bonus_gain_value_1_3": 0,
                "master_bonus_gain_value_1_4": 0,
            }],
            "single_mode_live_song_list": [{
                "id": 2,
                "command_id": 1032,
                "live_id": 1032,
                "master_bonus_content_text_id": 40000,
            }],
        },
        "text": {
            "cat_207_text": [{
                "index": 40000,
                "text": "Training Skill Pt Gain +2",
            }],
            "cat_209_text": [{
                "index": 40000,
                "text": "Run for Our Dream!",
            }],
        },
    }


def test_synthesize_grand_live_data(tmp_path):
    (tmp_path / "data").mkdir()

    result = master_data.synthesize_grand_live_data(tmp_path, _master())
    payload = json.loads(
        (tmp_path / "data" / "grand_live.json").read_text(encoding="utf-8")
    )

    assert result == {"file": "grand_live.json", "squares": 1, "songs": 1}
    assert payload["great_success_song_threshold"] == 3
    assert payload["squares"]["40000"] == {
        "square_type": 4,
        "name": "Run for Our Dream!",
        "reward": "Training Skill Pt Gain +2",
        "grants_sp": True,
        "token_cost": {"Passion": 21, "Visual": 21},
        "adds_song_live_id": 1032,
    }


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ([_square(), _square()], "duplicate Grand Live square id"),
        ([_square(square_type=9)], "invalid Grand Live square type"),
        ([_square(cost=-1)], "negative Grand Live token cost"),
    ],
)
def test_synthesize_grand_live_data_rejects_invalid_rows(tmp_path, rows, message):
    (tmp_path / "data").mkdir()

    with pytest.raises(ValueError, match=message):
        master_data.synthesize_grand_live_data(tmp_path, _master(rows))


def test_synthesis_preserves_existing_artifact_when_tables_are_absent(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    path = data_dir / "grand_live.json"
    original = {"squares": {"11001": {"token_cost": {"Dance": 10}}}}
    path.write_text(json.dumps(original), encoding="utf-8")

    result = master_data.synthesize_grand_live_data(
        tmp_path,
        {"tables": {}, "text": {}},
    )

    assert result == {
        "file": "grand_live.json",
        "squares": 1,
        "songs": 0,
        "preserved_existing": True,
    }
    assert json.loads(path.read_text(encoding="utf-8")) == original


def test_grand_live_data_loader_fails_closed(tmp_path):
    missing = tmp_path / "missing.json"
    with pytest.raises(GrandLiveDataError, match="generate_master_data"):
        GrandLiveData(missing)

    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    with pytest.raises(GrandLiveDataError, match="generate_master_data"):
        GrandLiveData(malformed)


def test_reference_validation_rejects_bad_costs_and_unknown_lookup(tmp_path):
    with pytest.raises(GrandLiveDataError, match="no squares"):
        validate_square_reference({})

    with pytest.raises(GrandLiveDataError, match="negative"):
        validate_square_reference({
            "11001": {
                "square_type": 1,
                "name": "Steps",
                "reward": "Speed +5",
                "grants_sp": False,
                "token_cost": {"Dance": -1},
                "adds_song_live_id": None,
            }
        })

    path = tmp_path / "grand_live.json"
    path.write_text(json.dumps({
        "squares": {
            "11001": {
                "square_type": 1,
                "name": "Steps",
                "reward": "Speed +5",
                "grants_sp": False,
                "token_cost": {"Dance": 10},
                "adds_song_live_id": None,
            }
        }
    }), encoding="utf-8")
    data = GrandLiveData(path)
    assert data.square(11001)["name"] == "Steps"
    assert data.square(99999) is None
