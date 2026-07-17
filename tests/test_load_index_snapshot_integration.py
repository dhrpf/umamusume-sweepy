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


def test_dashboard_builder_attaches_per_veteran_affinity(monkeypatch, tmp_path):
    master_mdb = tmp_path / "master.mdb"
    master_mdb.write_bytes(b"")
    expected = {
        "total": 69,
        "base": 39,
        "race": 30,
        "parent_1": {"position_id": 10, "card_id": 101401, "base": 20, "race": 18, "total": 38},
        "parent_2": {"position_id": 20, "card_id": 100601, "base": 19, "race": 12, "total": 31},
    }
    captured = {}

    monkeypatch.setattr(main.master_data, "configured_master_mdb_path", lambda _base: master_mdb)
    monkeypatch.setattr(
        main.affinity_calc,
        "calculate_veteran_affinity",
        lambda mdb_path, veteran: captured.update({"path": mdb_path, "veteran": veteran}) or expected,
    )
    monkeypatch.setattr(main, "save_load_index_snapshot", lambda *_args, **_kwargs: None)

    veteran = {
        "trained_chara_id": 1772,
        "card_id": 100401,
        "rank": 14,
        "rank_score": 11690,
        "succession_chara_array": [
            {"position_id": 10, "card_id": 101401},
            {"position_id": 20, "card_id": 100601},
        ],
    }
    dashboard = main._build_dashboard_from_login_response({
        "data": {
            "card_list": [],
            "support_card_list": [],
            "support_card_deck_array": [],
            "trained_chara": [veteran],
            "item_list": [],
        }
    })

    assert captured == {"path": str(master_mdb), "veteran": veteran}
    assert dashboard["parents"][0]["affinity"] == expected
