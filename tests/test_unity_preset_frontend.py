from pathlib import Path

from career_bot.presets import hydrate_preset, serialize_preset


ROOT = Path(__file__).resolve().parent.parent


def test_unity_config_round_trips_through_preset_serialization():
    raw = {
        "name": "Unity Test",
        "scenario_id": 2,
        "running_style": 3,
        "unity_config": {
            "unity_training_weight": 0.75,
            "spirit_burst_weight": 6.5,
            "default_distance_type": 2,
            "default_running_style": 4,
        },
    }

    serialized = serialize_preset(raw)
    hydrated = hydrate_preset(serialized)

    assert serialized["scenario_id"] == 2
    assert serialized["unity_config"] == {
        "unity_training_weight": 0.75,
        "spirit_burst_weight": 6.5,
        "default_distance_type": 2,
        "default_running_style": 4,
    }
    assert hydrated["unity_config"] == serialized["unity_config"]


def test_unity_config_defaults_are_available_after_hydration():
    hydrated = hydrate_preset({"name": "Unity Defaults", "scenario_id": 2})

    assert hydrated["unity_config"] == {
        "unity_training_weight": 0.6,
        "spirit_burst_weight": 5.0,
        "default_distance_type": 1,
        "default_running_style": 1,
    }


def test_frontend_exposes_unity_scenario_and_tuning_fields():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    app_js = (ROOT / "public" / "app.js").read_text(encoding="utf-8")

    assert '<option value="2">Unity Cup</option>' in index_html
    assert 'id="unity-training-weight"' in index_html
    assert 'id="unity-burst-weight"' in index_html
    assert "unity_training_weight" in app_js
    assert "spirit_burst_weight" in app_js
    assert 'const scenarioTypes = { 1: "Ura", 2: "Unity", 4: "Mant" };' in app_js
    assert "Number.isFinite(unityTrainingWeight)" in app_js
    assert "Number.isFinite(unityBurstWeight)" in app_js
    assert '<script src="app.js?v=18"></script>' in index_html
