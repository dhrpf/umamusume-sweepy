from pathlib import Path

import pytest

from career_bot.presets import hydrate_preset, serialize_preset


def test_grand_live_weight_round_trips_and_preserves_zero():
    serialized = serialize_preset({
        "name": "Grand Live",
        "scenario_id": 3,
        "performance_training_weight": 0,
    })

    assert serialized["scenario_id"] == 3
    assert serialized["performance_training_weight"] == 0
    assert hydrate_preset(serialized)["performance_training_weight"] == 0


@pytest.mark.parametrize(
    "value",
    [float("nan"), float("inf"), float("-inf"), -0.1, "bad", None],
)
def test_invalid_grand_live_weight_uses_default(value):
    serialized = serialize_preset({
        "name": "Grand Live",
        "scenario_id": 3,
        "performance_training_weight": value,
    })

    assert serialized["performance_training_weight"] == 0.6


def test_grand_live_controls_are_exposed_and_conditionally_visible():
    root = Path(__file__).resolve().parents[1]
    index_html = (root / "public" / "index.html").read_text(encoding="utf-8")
    app_js = (root / "public" / "app.js").read_text(encoding="utf-8")

    assert '<option value="3">Grand Live</option>' in index_html
    assert 'id="grand-live-config"' in index_html
    assert 'id="performance-training-weight"' in index_html
    assert "performance_training_weight" in app_js
    assert "els.grandLiveConfig.hidden = scenarioId !== 3" in app_js
    assert 'const scenarioTypes = { 1: "Ura", 2: "Unity", 3: "Grand Live", 4: "Mant" };' in app_js
    assert '<script src="app.js?v=22"></script>' in index_html
