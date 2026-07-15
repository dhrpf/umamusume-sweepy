from pathlib import Path

import main


ROOT = Path(__file__).resolve().parent.parent


def test_normalize_friend_veterans_emits_parent_compatible_lineage_tree(monkeypatch):
    monkeypatch.setattr(main, "chara_map", {
        "100101": "Self Uma",
        "100201": "Parent One",
        "100301": "Parent Two",
        "100401": "Grandparent One",
        "100501": "Grandparent Two",
        "100601": "Grandparent Three",
        "100701": "Grandparent Four",
    })
    monkeypatch.setattr(main, "get_factors", lambda ids, card_id: [
        {"name": f"Factor {factor_id}", "stars": 3, "category": "blue"}
        for factor_id in ids
    ])
    monkeypatch.setattr(main, "get_win_summary", lambda ids: {
        "total": len(ids), "g1": len(ids), "g2": 0, "g3": 0
    })
    main.active_parent_rank_points = {}

    data = {
        "summary_user_info_array": [{"viewer_id": 77, "name": "Trainer"}],
        "succession_trained_chara_array": [{
            "viewer_id": 77,
            "trained_chara_id": 9001,
            "card_id": 100101,
            "rank": 20,
            "rank_score": 12345,
            "factor_info_array": [{"factor_id": 101}],
            "win_saddle_id_array": [1, 2],
            "succession_chara_array": [
                {"position_id": 10, "card_id": 100201, "factor_id_array": [201], "win_saddle_id_array": [3]},
                {"position_id": 20, "card_id": 100301, "factor_id_array": [301], "win_saddle_id_array": [4]},
                {"position_id": 11, "card_id": 100401, "factor_id_array": [401], "win_saddle_id_array": [5]},
                {"position_id": 12, "card_id": 100501, "factor_id_array": [501], "win_saddle_id_array": [6]},
                {"position_id": 21, "card_id": 100601, "factor_id_array": [601], "win_saddle_id_array": [7]},
                {"position_id": 22, "card_id": 100701, "factor_id_array": [701], "win_saddle_id_array": [8]},
            ],
        }],
    }

    veterans, source = main.normalize_friend_veterans(data)

    assert source == "ok"
    assert len(veterans) == 1
    tree = veterans[0]["tree"]
    assert list(tree) == ["self", "p1", "p2", "gp1", "gp2", "gp3", "gp4"]
    assert tree["self"] == {
        "card_id": 100101,
        "name": "Self Uma",
        "factors": [{"name": "Factor 101", "stars": 3, "category": "blue"}],
        "wins": {"total": 2, "g1": 2, "g2": 0, "g3": 0},
    }
    assert tree["p1"]["name"] == "Parent One"
    assert tree["p2"]["name"] == "Parent Two"
    assert tree["gp1"]["name"] == "Grandparent One"
    assert tree["gp2"]["name"] == "Grandparent Two"
    assert tree["gp3"]["name"] == "Grandparent Three"
    assert tree["gp4"]["name"] == "Grandparent Four"
    assert veterans[0]["parent_card_ids"] == [100201, 100301]


def test_veteran_views_use_chrono_style_grouped_direct_lineage_sparks():
    app_js = (ROOT / "public" / "app.js").read_text(encoding="utf-8")

    renderer_start = app_js.index("function renderVeteranSparkGroups(parent)")
    renderer_end = app_js.index("function renderParentStats", renderer_start)
    renderer_source = app_js[renderer_start:renderer_end]
    friend_card_start = app_js.index("function friendCardHtml(v, idx)")
    friend_card_end = app_js.index("async function loadFriendVeterans", friend_card_start)
    friend_card_source = app_js[friend_card_start:friend_card_end]
    detail_start = app_js.index("function renderVeteranDetail(parent)")
    detail_end = app_js.index("function openVeteranDetail", detail_start)
    detail_source = app_js[detail_start:detail_end]

    assert "['self', 'p1', 'p2']" in renderer_source
    assert "gp1" not in renderer_source
    assert "bluePink" in renderer_source
    assert "unique" in renderer_source
    assert "white" in renderer_source
    assert "spark-summary-chip" in renderer_source
    assert "factor.source === 'self'" in renderer_source
    assert "stars-own" in renderer_source
    assert "stars-blue" in renderer_source
    assert "stars-pink" in renderer_source
    assert "renderVeteranSparkGroups(v)" in friend_card_source
    assert "renderVeteranSparkGroups(parent)" in detail_source
    assert "renderVetParents(v)" not in friend_card_source

    styles = (ROOT / "public" / "styles.css").read_text(encoding="utf-8")
    assert ".stars.stars-own" in styles
    assert ".stars.stars-blue" in styles
    assert ".stars.stars-pink" in styles
