import main


def test_start_career_sends_calculated_affinity(monkeypatch):
    captured = {}

    class FakeClient:
        item_map = {59: 1000, 75: 42}

        def call(self, endpoint, _payload):
            assert endpoint == "load/index"
            return {
                "data": {
                    "tp_info": {
                        "current_tp": 100,
                        "max_tp": 100,
                        "max_recovery_time": 0,
                    },
                    "item_list": [
                        {"item_id": 59, "number": 1000},
                        {"item_id": 75, "number": 42},
                    ],
                }
            }

        def refresh_cached_account_state(self, _data):
            return None

        def pre_single_mode(self):
            return None

        def start_career(self, **kwargs):
            captured.update(kwargs)
            return {"data": {}}

        def change_support_card_deck_party(self, _party):
            return None

    monkeypatch.setattr(main, "active_client", FakeClient())
    monkeypatch.setattr(main, "active_account", None)
    monkeypatch.setattr(main, "active_dashboard_data", None)
    monkeypatch.setattr(main, "active_start_state", {})
    monkeypatch.setattr(main, "active_support_card_deck_array", [])
    monkeypatch.setattr(main, "active_parent_cards", {})
    monkeypatch.setattr(main, "active_parent_rank_points", {})
    monkeypatch.setattr(main, "active_parent_full", {1: {"card_id": 100101}, 2: {"card_id": 100201}})
    monkeypatch.setattr(
        main.affinity_calc,
        "calculate_affinity",
        lambda *_args: {"total": 177, "chara_compat": 156, "race_compat": 21},
    )
    monkeypatch.setattr(main, "dna_sleep", lambda *_args: None)

    request = main.RunCareerRequest(
        card_id=101301,
        support_card_ids=[30016, 30107, 30028, 30010, 30054],
        friend_viewer_id=1,
        friend_card_id=30108,
        parent_id_1=1,
        parent_id_2=2,
        scenario_id=2,
        deck_id=3,
    )

    result = main.start_career_from_request(request)

    assert result["success"] is True
    assert captured["succession_rank_point"] == 177
