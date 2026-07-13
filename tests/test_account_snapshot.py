import json
import stat

from account_snapshot import (
    SNAPSHOT_FILENAME,
    build_load_index_snapshot,
    build_raw_dashboard,
    compact_account_snapshot,
    load_account_snapshot,
    save_load_index_snapshot,
)


def sample_dashboard():
    return {
        "account": {"tp": 80, "gold": 12345, "viewer_id": 9999999999999},
        "umas": [{"id": "100101", "name": "Alpha"}],
        "supports": [{"id": "30001", "name": "Support", "limit_break_count": 4}],
        "decks": [{"id": 1, "name": "Parent Deck", "cards": [{"id": "30001"}]}],
        "parents": [
            {
                "instance_id": 900001,
                "card_id": "100101",
                "name": "Legacy Alpha",
                "rank": 14,
                "rank_score": 20000,
                "factors": [{"name": "Medium", "stars": 3}],
            }
        ],
    }


def sample_load_index():
    return {
        "card_list": [{"card_id": 100101, "talent_level": 5}],
        "support_card_list": [{"support_card_id": 30001, "limit_break_count": 4}],
        "support_card_deck_array": [{"deck_id": 1, "support_card_id_array": [30001]}],
        "trained_chara": [
            {
                "trained_chara_id": 900001,
                "viewer_id": 9999999999999,
                "card_id": 100101,
                "factor_id_array": [10103],
                "win_saddle_id_array": [10, 20],
                "succession_chara_array": [
                    {
                        "position_id": 10,
                        "card_id": 100201,
                        "viewer_id": 8888888888888,
                        "factor_id_array": [20102],
                    }
                ],
            }
        ],
        "sid": "must-not-be-saved",
        "auth_key": "must-not-be-saved",
    }


def test_raw_dashboard_supports_client_level_load_index_cache():
    dashboard = build_raw_dashboard(sample_load_index())

    assert dashboard["umas"] == [{"id": "100101", "name": "Card #100101"}]
    assert dashboard["supports"][0]["id"] == "30001"
    assert dashboard["decks"][0]["cards"] == [
        {"id": "30001", "limit_break_count": 4}
    ]
    assert dashboard["parents"][0]["instance_id"] == 900001
    assert dashboard["parents"][0]["name"] == "Veteran #900001"


def test_build_snapshot_is_curated_and_removes_sensitive_identifiers():
    snapshot = build_load_index_snapshot(
        dashboard=sample_dashboard(),
        load_index_data=sample_load_index(),
        refreshed_at=123.5,
    )

    assert snapshot["version"] == 1
    assert snapshot["source"] == "load/index"
    assert snapshot["refreshed_at"] == 123.5
    assert snapshot["counts"] == {
        "cards": 1,
        "support_cards": 1,
        "decks": 1,
        "owned_veterans": 1,
    }
    assert "viewer_id" not in snapshot["account"]
    assert "viewer_id" not in snapshot["records"]["trained_chara"][0]
    assert "viewer_id" not in snapshot["records"]["trained_chara"][0]["succession_chara_array"][0]
    encoded = json.dumps(snapshot)
    assert "must-not-be-saved" not in encoded


def test_save_snapshot_is_atomic_private_and_reloadable(tmp_path):
    path = save_load_index_snapshot(
        tmp_path,
        dashboard=sample_dashboard(),
        load_index_data=sample_load_index(),
        refreshed_at=456.0,
    )

    assert path == tmp_path / SNAPSHOT_FILENAME
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    reloaded = load_account_snapshot(tmp_path)
    assert reloaded["refreshed_at"] == 456.0
    assert reloaded["owned_veterans"][0]["instance_id"] == 900001
    assert list(tmp_path.glob("*.tmp")) == []


def test_compact_snapshot_hides_full_records_unless_requested():
    snapshot = build_load_index_snapshot(
        dashboard=sample_dashboard(),
        load_index_data=sample_load_index(),
    )

    compact = compact_account_snapshot(snapshot)
    detailed = compact_account_snapshot(snapshot, include_records=True)

    assert "records" not in compact
    assert detailed["records"]["trained_chara"][0]["trained_chara_id"] == 900001


def test_missing_snapshot_returns_none(tmp_path):
    assert load_account_snapshot(tmp_path) is None
