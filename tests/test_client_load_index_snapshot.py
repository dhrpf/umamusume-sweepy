from pathlib import Path

import uma_api.client as client_module


def test_client_level_load_index_cache_uses_runtime_directory(monkeypatch, tmp_path):
    captured = {}

    def fake_save(runtime_dir, data):
        captured["runtime_dir"] = Path(runtime_dir)
        captured["data"] = data

    monkeypatch.setattr(client_module, "runtime_output_root", lambda: tmp_path)
    monkeypatch.setattr(
        "account_snapshot.save_raw_load_index_snapshot",
        fake_save,
    )
    data = {"trained_chara": [{"trained_chara_id": 1, "card_id": 100101}]}

    client_module._cache_successful_load_index(data)

    assert captured == {"runtime_dir": tmp_path, "data": data}
