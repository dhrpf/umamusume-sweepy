import main


def test_dashboard_builder_persists_successful_load_index_projection(monkeypatch, tmp_path):
    captured = {}

    def fake_save(runtime_dir, *, dashboard, load_index_data, source="load/index", refreshed_at=None):
        captured["runtime_dir"] = runtime_dir
        captured["dashboard"] = dashboard
        captured["load_index_data"] = load_index_data
        captured["source"] = source
        return tmp_path / "load-index-cache.json"

    monkeypatch.setattr(main, "save_load_index_snapshot", fake_save)
    monkeypatch.setattr(main, "runtime_output_root", lambda: tmp_path)

    response = {
        "data": {
            "card_list": [{"card_id": 100101}],
            "support_card_list": [],
            "support_card_deck_array": [],
            "trained_chara": [],
            "item_list": [],
        }
    }

    dashboard = main._build_dashboard_from_login_response(response)

    assert dashboard["success"] is True
    assert dashboard["umas"][0]["id"] == "100101"
    assert captured["runtime_dir"] == tmp_path
    assert captured["load_index_data"] is response["data"]
    assert captured["dashboard"] is dashboard
    assert captured["source"] == "load/index"
