"""Serialize/hydrate roundtrip + exclusion tests for presets.py."""

from __future__ import annotations

from career_bot.presets import (
    EXCLUDED_KEYS,
    RENAMES,
    PresetStore,
    hydrate_preset,
    normalize_skill_list,
    serialize_preset,
    slugify,
    split_csv,
)


def test_slugify_safe():
    assert slugify("URA Finale") == "URA Finale"


def test_slugify_specials_collapsed():
    assert slugify("run **now**!") == "run now"


def test_slugify_empty_fallback():
    assert slugify("") == "preset"


def test_split_csv_list_passthrough():
    assert split_csv([1, 2, 3]) == [1, 2, 3]


def test_split_csv_string_split():
    assert split_csv("a,b,,c") == ["a", "b", "c"]


def test_normalize_skill_list_nested():
    assert normalize_skill_list([["a,b", "c"], "d"]) == [["a", "b", "c"], ["d"]]


def test_serialize_excluded_keys_dropped():
    raw = {"facility_period_configs": {"x": 1}, "facility_ratios": {"y": 2}, "name": "keep"}
    out = serialize_preset(raw)
    for k in EXCLUDED_KEYS:
        assert k not in out


def test_serialize_renames_applied():
    raw = {"race_list": "a", "skill_priority_list": "b"}
    out = serialize_preset(raw)
    assert "extra_race_list" in out
    assert "learn_skill_list" in out
    assert "race_list" not in out


def test_serialize_use_mcts_roundtrip():
    raw = {"name": "u", "use_mcts": True, "expect_attribute": [900, 450, 650, 250, 650]}
    out = serialize_preset(raw)
    assert out["use_mcts"] is True
    assert hydrate_preset(out)["use_mcts"] is True


def test_serialize_use_mcts_default_false():
    out = serialize_preset({"name": "u"})
    assert out["use_mcts"] is False


def test_serialize_mcts_config_allowed_fields():
    raw = {
        "name": "u",
        "mcts_config": {
            "time_budget_sec": 2.0,
            "max_simulations": 500,
            "not_a_field": 99,
        },
    }
    out = serialize_preset(raw)
    assert out["mcts_config"]["time_budget_sec"] == 2.0
    assert out["mcts_config"]["max_simulations"] == 500
    assert "not_a_field" not in out["mcts_config"]


def test_hydrate_preserves_mcts_fields():
    raw = {
        "name": "u",
        "use_mcts": True,
        "mcts_config": {"time_budget_sec": 0.5},
    }
    out = hydrate_preset(raw)
    assert out["use_mcts"] is True
    assert out["mcts_config"]["time_budget_sec"] == 0.5


def test_excluded_keys_not_in_renames_values():
    overlap = set(EXCLUDED_KEYS) & set(RENAMES.values())
    assert not overlap
