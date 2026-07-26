from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
from career_bot.campaigns.store import CampaignStore
from career_bot.presets import PresetStore


ROOT = Path(__file__).resolve().parents[1]


def source_preset(name="Original"):
    return {
        "name": name,
        "scenario_id": 3,
        "running_style": 2,
        "extra_race_list": [101, 202],
        "mandatory_race_list": [303],
        "learn_skill_list": [["Skill A"]],
        "learn_skill_blacklist": ["Skill B"],
        "performance_training_weight": 0.75,
    }


def campaign_spec(preset_name, account):
    return {
        "account": account,
        "goal": {
            "surface_targets": ["turf"],
            "distance_targets": ["medium"],
        },
        "strategy": {
            "preset_name": preset_name,
            "maximum_runs": 3,
            "maximum_carats": 0,
            "maximum_clocks": 1,
            "maximum_runtime_hours": 12,
        },
    }


def test_preset_store_rename_preserves_fields_and_removes_source(tmp_path):
    store = PresetStore(tmp_path)
    store.write(source_preset())

    renamed = store.rename("original", " Renamed ")

    assert renamed["name"] == "Renamed"
    assert renamed["scenario_id"] == 3
    assert renamed["running_style"] == 2
    assert renamed["extra_race_list"] == [101, 202]
    assert renamed["mandatory_race_list"] == [303]
    assert renamed["learn_skill_list"] == [["Skill A"]]
    assert renamed["learn_skill_blacklist"] == ["Skill B"]
    assert renamed["performance_training_weight"] == 0.75
    assert store.read_one("Original") is None
    assert store.read_one("renamed") == renamed


def test_preset_store_duplicate_keeps_source_independent(tmp_path):
    store = PresetStore(tmp_path)
    store.write(source_preset())

    duplicated = store.duplicate("ORIGINAL", "Original_copy")
    duplicated["extra_race_list"].append(404)
    store.write(duplicated)

    assert duplicated["name"] == "Original_copy"
    assert store.read_one("Original")["extra_race_list"] == [101, 202]
    assert store.read_one("Original_copy")["extra_race_list"] == [101, 202, 404]


@pytest.mark.parametrize("operation", ["rename", "duplicate"])
def test_preset_store_rejects_empty_target_name(tmp_path, operation):
    store = PresetStore(tmp_path)
    store.write(source_preset())

    with pytest.raises(ValueError, match="name is required"):
        getattr(store, operation)("Original", "   ")


@pytest.mark.parametrize("operation", ["rename", "duplicate"])
def test_preset_store_rejects_missing_source(tmp_path, operation):
    store = PresetStore(tmp_path)

    with pytest.raises(ValueError, match="Preset not found"):
        getattr(store, operation)("Missing", "Target")


@pytest.mark.parametrize("operation", ["rename", "duplicate"])
def test_preset_store_rejects_case_insensitive_conflict(tmp_path, operation):
    store = PresetStore(tmp_path)
    store.write(source_preset())
    store.write(source_preset("Existing"))

    with pytest.raises(ValueError, match="already exists"):
        getattr(store, operation)("Original", "existing")


def test_preset_store_same_name_rename_is_noop(tmp_path):
    store = PresetStore(tmp_path)
    original = store.write(source_preset())

    renamed = store.rename("original", "ORIGINAL")

    assert renamed == original
    assert store.read_all() == [original]
    assert len(list(store.preset_dir.glob("*.json"))) == 1


def test_preset_store_duplicate_requires_distinct_name(tmp_path):
    store = PresetStore(tmp_path)
    store.write(source_preset())

    with pytest.raises(ValueError, match="must differ"):
        store.duplicate("Original", "ORIGINAL")


def test_campaign_store_renames_matching_preset_references_durably(tmp_path):
    database = tmp_path / "campaigns.sqlite3"
    store = CampaignStore(database)
    store.create(campaign_spec("Original", "acct01"), campaign_id="campaign-1")
    store.create(campaign_spec("ORIGINAL", "acct02"), campaign_id="campaign-2")
    store.create(campaign_spec("Unrelated", "acct03"), campaign_id="campaign-3")

    updated = store.rename_preset_references("original", "Renamed")

    reopened = CampaignStore(database)
    assert updated == 2
    assert reopened.get("campaign-1")["spec"]["strategy"]["preset_name"] == "Renamed"
    assert reopened.get("campaign-2")["spec"]["strategy"]["preset_name"] == "Renamed"
    assert reopened.get("campaign-3")["spec"]["strategy"]["preset_name"] == "Unrelated"


def test_api_rename_preset_cascades_campaign_references(tmp_path, monkeypatch):
    preset_store = PresetStore(tmp_path)
    preset_store.write(source_preset())
    campaign_store = CampaignStore(tmp_path / "campaigns.sqlite3")
    campaign_store.create(campaign_spec("ORIGINAL", "acct01"), campaign_id="campaign-1")
    monkeypatch.setattr(main, "preset_store", preset_store)
    monkeypatch.setattr(main, "campaign_store", campaign_store)

    response = TestClient(main.app).post(
        "/api/presets/rename",
        json={"old_name": "original", "new_name": "Renamed"},
    )

    payload = response.json()
    assert payload["success"] is True
    assert payload["preset"]["name"] == "Renamed"
    assert payload["campaigns_updated"] == 1
    assert campaign_store.get("campaign-1")["spec"]["strategy"]["preset_name"] == "Renamed"


def test_api_duplicate_preset_keeps_campaign_references_unchanged(tmp_path, monkeypatch):
    preset_store = PresetStore(tmp_path)
    preset_store.write(source_preset())
    campaign_store = CampaignStore(tmp_path / "campaigns.sqlite3")
    campaign_store.create(campaign_spec("Original", "acct01"), campaign_id="campaign-1")
    monkeypatch.setattr(main, "preset_store", preset_store)
    monkeypatch.setattr(main, "campaign_store", campaign_store)

    response = TestClient(main.app).post(
        "/api/presets/duplicate",
        json={"source_name": "Original", "new_name": "Original_copy"},
    )

    payload = response.json()
    assert payload["success"] is True
    assert payload["preset"]["name"] == "Original_copy"
    assert preset_store.read_one("Original") is not None
    assert campaign_store.get("campaign-1")["spec"]["strategy"]["preset_name"] == "Original"


def test_api_rename_preset_restores_source_when_campaign_cascade_fails(tmp_path, monkeypatch):
    preset_store = PresetStore(tmp_path)
    preset_store.write(source_preset())
    campaign_store = CampaignStore(tmp_path / "campaigns.sqlite3")

    def fail_cascade(*args, **kwargs):
        raise RuntimeError("campaign database unavailable")

    monkeypatch.setattr(campaign_store, "rename_preset_references", fail_cascade)
    monkeypatch.setattr(main, "preset_store", preset_store)
    monkeypatch.setattr(main, "campaign_store", campaign_store)

    response = TestClient(main.app).post(
        "/api/presets/rename",
        json={"old_name": "Original", "new_name": "Renamed"},
    )

    payload = response.json()
    assert payload["success"] is False
    assert "campaign database unavailable" in payload["detail"]
    assert preset_store.read_one("Original") is not None
    assert preset_store.read_one("Renamed") is None


def test_api_preset_management_returns_validation_errors(tmp_path, monkeypatch):
    preset_store = PresetStore(tmp_path)
    preset_store.write(source_preset())
    preset_store.write(source_preset("Existing"))
    monkeypatch.setattr(main, "preset_store", preset_store)
    monkeypatch.setattr(main, "campaign_store", CampaignStore(tmp_path / "campaigns.sqlite3"))
    client = TestClient(main.app)

    rename = client.post(
        "/api/presets/rename",
        json={"old_name": "Original", "new_name": "existing"},
    ).json()
    duplicate = client.post(
        "/api/presets/duplicate",
        json={"source_name": "Missing", "new_name": "Missing_copy"},
    ).json()

    assert rename["success"] is False
    assert "already exists" in rename["detail"]
    assert duplicate["success"] is False
    assert "Preset not found" in duplicate["detail"]


def test_campaign_store_preset_reference_rename_rolls_back_on_failure(tmp_path, monkeypatch):
    database = tmp_path / "campaigns.sqlite3"
    store = CampaignStore(database)
    store.create(campaign_spec("Original", "acct01"), campaign_id="campaign-1")
    store.create(campaign_spec("Original", "acct02"), campaign_id="campaign-2")

    def fail_event(*args, **kwargs):
        raise RuntimeError("event write failed")

    monkeypatch.setattr(store, "_insert_event", fail_event)

    with pytest.raises(RuntimeError, match="event write failed"):
        store.rename_preset_references("Original", "Renamed")

    reopened = CampaignStore(database)
    assert reopened.get("campaign-1")["spec"]["strategy"]["preset_name"] == "Original"
    assert reopened.get("campaign-2")["spec"]["strategy"]["preset_name"] == "Original"


def test_dashboard_exposes_preset_rename_and_duplicate_controls():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
    app_js = (ROOT / "public" / "app.js").read_text(encoding="utf-8")

    assert 'id="preset-rename-btn"' in index_html
    assert 'id="preset-duplicate-btn"' in index_html
    assert 'prompt("Rename preset:", current.name)' in app_js
    assert 'prompt("Duplicate preset:", `${current.name}_copy`)' in app_js
    assert "apiJson('/api/presets/rename'" in app_js
    assert "apiJson('/api/presets/duplicate'" in app_js
    assert "JSON.stringify({ old_name: current.name, new_name: normalizedName })" in app_js
    assert "JSON.stringify({ source_name: current.name, new_name: normalizedName })" in app_js


def test_dashboard_preset_management_bumps_app_asset_version():
    index_html = (ROOT / "public" / "index.html").read_text(encoding="utf-8")

    assert '<script src="app.js?v=22"></script>' in index_html
