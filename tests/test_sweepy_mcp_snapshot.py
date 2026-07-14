from pathlib import Path

from account_snapshot import save_load_index_snapshot

import sweepy_mcp


class FakeRegistry:
    def __init__(self):
        self.accounts_path = Path("/tmp/accounts.json")

    def resolve(self, account=""):
        if account not in {"", "alpha"}:
            raise ValueError("unknown account")
        return "alpha", object()


class FakeSupervisor:
    def __init__(self, root):
        self.root = Path(root)

    def runtime_dir(self, account):
        return self.root / account


def seed_snapshot(root):
    save_load_index_snapshot(
        root / "alpha",
        dashboard={
            "account": {"tp": 80},
            "umas": [{"id": "100101", "name": "Alpha"}],
            "supports": [],
            "decks": [{"id": 1, "name": "Deck", "cards": []}],
            "parents": [
                {
                    "instance_id": 900001,
                    "card_id": "100101",
                    "name": "Legacy Alpha",
                    "rank": 14,
                    "rank_score": 20000,
                }
            ],
        },
        load_index_data={
            "card_list": [{"card_id": 100101}],
            "support_card_list": [],
            "support_card_deck_array": [{"deck_id": 1}],
            "trained_chara": [
                {
                    "trained_chara_id": 900001,
                    "card_id": 100101,
                    "factor_id_array": [10103],
                }
            ],
        },
        refreshed_at=123.0,
    )


def test_snapshot_tools_read_cache_without_gateway_requests(monkeypatch, tmp_path):
    seed_snapshot(tmp_path)
    monkeypatch.setattr(sweepy_mcp, "account_registry", FakeRegistry())
    monkeypatch.setattr(sweepy_mcp, "supervisor", FakeSupervisor(tmp_path))

    compact = sweepy_mcp.get_cached_account_snapshot(account="alpha")
    detailed = sweepy_mcp.get_cached_account_snapshot(
        account="alpha",
        include_records=True,
    )
    veterans = sweepy_mcp.list_cached_veterans(account="alpha")

    assert compact["success"] is True
    assert compact["cached"] is True
    assert compact["snapshot"]["refreshed_at"] == 123.0
    assert "records" not in compact["snapshot"]
    assert detailed["snapshot"]["records"]["trained_chara"][0]["trained_chara_id"] == 900001
    assert veterans["success"] is True
    assert veterans["account"] == "alpha"
    assert veterans["cached"] is True
    assert veterans["refreshed_at"] == 123.0
    assert veterans["count"] == 1
    assert veterans["returned"] == 1
    veteran = veterans["veterans"][0]
    assert veteran["trained_chara_id"] == 900001
    assert veteran["card_id"] == 100101
    assert veteran["name"] == "Legacy Alpha"
    assert veteran["rank"] == 14
    assert veteran["rank_score"] == 20000
    assert "direct_lineage_blue_totals" in veteran
    assert veterans["definitions"]["final_stats_are_not_factors"] is True


def test_legacy_rules_and_scan_use_cached_records_only(monkeypatch, tmp_path):
    seed_snapshot(tmp_path)
    monkeypatch.setattr(sweepy_mcp, "account_registry", FakeRegistry())
    monkeypatch.setattr(sweepy_mcp, "supervisor", FakeSupervisor(tmp_path))
    monkeypatch.setattr(
        sweepy_mcp.master_data,
        "configured_master_mdb_path",
        lambda _base_dir: tmp_path / "master.mdb",
    )
    captured = {}

    def fake_scan(records, **kwargs):
        captured["records"] = records
        captured["kwargs"] = kwargs
        return {
            "minimum_affinity": kwargs["minimum_affinity"],
            "pool_count": 1,
            "pools": [{"base_chara_ids": [1001, 1002, 1003, 1004]}],
        }

    monkeypatch.setattr(sweepy_mcp, "scan_legacy_loop_pools", fake_scan)

    rules = sweepy_mcp.get_legacy_spark_rules()
    result = sweepy_mcp.scan_cached_legacy_loops(
        account="alpha",
        minimum_affinity=151,
        max_characters=8,
        records_per_character=3,
        limit=5,
    )

    assert rules["success"] is True
    assert rules["compatibility"] == {
        "double_circle": ">150",
        "single_circle": "50-150",
        "triangle": "<50",
    }
    assert result["success"] is True
    assert result["cached"] is True
    assert result["pool_count"] == 1
    assert captured["records"][0]["trained_chara_id"] == 900001
    assert captured["kwargs"]["veteran_names"] == {900001: "Legacy Alpha"}
    assert captured["kwargs"]["minimum_affinity"] == 151
    assert captured["kwargs"]["max_characters"] == 8
    assert captured["kwargs"]["records_per_character"] == 3
    assert captured["kwargs"]["limit"] == 5


def test_snapshot_tool_reports_missing_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(sweepy_mcp, "account_registry", FakeRegistry())
    monkeypatch.setattr(sweepy_mcp, "supervisor", FakeSupervisor(tmp_path))

    result = sweepy_mcp.get_cached_account_snapshot(account="alpha")

    assert result["success"] is False
    assert result["cached"] is False
    assert "No load/index snapshot" in result["detail"]
