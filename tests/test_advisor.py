from career_bot import advisor


def test_support_type_counts_maps_wit_to_wisdom_slot():
    lookup = {
        "1": {"type": "Speed"},
        "2": {"type": "Wit"},
        "3": {"type": "Unknown"},
    }

    assert advisor.support_type_counts([1, "2", 3], lookup) == [1, 0, 0, 0, 1]


def test_deck_archetype_prefers_guts_meta():
    assert advisor.deck_archetype([1, 0, 0, 3, 2]) == "Guts meta"


def test_score_parent_candidate_penalizes_same_direct_parent():
    result = advisor.score_parent_candidate({"card_id": 42}, trainee_card_id=42, running_style=0)

    assert result["score"] < 0
    assert "direct parent is same character as trainee" in result["warnings"]


def test_prepare_runtime_preset_relaxes_low_speed_deck_without_mutating_input():
    preset = {
        "running_style": 0,
        "min_stats": [900, 500, 900, 300, 400],
        "_deck_type_counts": [1, 0, 0, 0, 2],
    }

    out = advisor.prepare_runtime_preset(preset)

    assert out is not preset
    assert out["train_min_total_stat_gain"] == 34
    assert out["_runtime_advisor"]["notes"] == ["low speed support count: relaxed training threshold"]
    assert "train_min_total_stat_gain" not in preset
