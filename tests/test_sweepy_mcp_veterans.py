import sweepy_mcp


class Registry:
    def resolve(self, account=""):
        return account or "alpha", object()


FACTOR_MAP = {
    "301": {"name": "Power", "stars": 1, "category": "stat"},
    "302": {"name": "Power", "stars": 2, "category": "stat"},
    "303": {"name": "Power", "stars": 3, "category": "stat"},
    "1002301": {"name": "Arima Kinen", "stars": 1, "category": "race"},
    "1002302": {"name": "Arima Kinen", "stars": 2, "category": "race"},
}


def record(trained_id, *, power, self_factors, parent1_factors, parent2_factors):
    return {
        "trained_chara_id": trained_id,
        "card_id": 100000 + trained_id,
        "rank": 13,
        "rank_score": 10000 + trained_id,
        "power": power,
        "factor_info_array": [{"factor_id": factor_id} for factor_id in self_factors],
        "succession_chara_array": [
            {
                "position_id": 10,
                "card_id": 100201,
                "factor_info_array": [
                    {"factor_id": factor_id} for factor_id in parent1_factors
                ],
            },
            {
                "position_id": 20,
                "card_id": 100301,
                "factor_info_array": [
                    {"factor_id": factor_id} for factor_id in parent2_factors
                ],
            },
        ],
    }


def snapshot():
    rows = [
        record(
            1001,
            power=1200,
            self_factors=[1002301, 1002302],
            parent1_factors=[1002301],
            parent2_factors=[1002302],
        ),
        record(
            1002,
            power=700,
            self_factors=[303],
            parent1_factors=[303],
            parent2_factors=[303],
        ),
    ]
    return {
        "version": 1,
        "refreshed_at": 123.5,
        "counts": {"owned_veterans": 2},
        "owned_veterans": [
            {
                "instance_id": 1001,
                "name": "Synthetic Veteran A",
                "rank": 17,
                "rank_score": 17000,
            },
            {
                "instance_id": 1002,
                "name": "Synthetic Veteran B",
                "rank": 13,
                "rank_score": 11000,
            },
        ],
        "records": {"trained_chara": rows},
    }


def setup(monkeypatch):
    monkeypatch.setattr(sweepy_mcp, "account_registry", Registry())
    monkeypatch.setattr(sweepy_mcp, "_snapshot_runtime_dir", lambda _account: "/tmp")
    monkeypatch.setattr(sweepy_mcp, "load_account_snapshot", lambda _path: snapshot())
    monkeypatch.setattr(sweepy_mcp, "_load_factor_map", lambda: FACTOR_MAP)


def test_list_cached_veterans_returns_decoded_blue_factor_summary(monkeypatch):
    setup(monkeypatch)

    result = sweepy_mcp.list_cached_veterans(account="alpha")

    assert result["success"] is True
    by_id = {row["trained_chara_id"]: row for row in result["veterans"]}
    assert by_id[1001]["final_stats"]["power"] == 1200
    assert by_id[1001]["direct_lineage_blue_totals"].get("Power", 0) == 0
    assert by_id[1001]["legacy_tags"] == []
    assert by_id[1002]["direct_lineage_blue_totals"] == {"Power": 9}
    assert by_id[1002]["legacy_tags"] == ["Power 9★"]
    assert "factor_tree" not in by_id[1002]


def test_find_cached_veterans_answers_power_nine_star_query(monkeypatch):
    setup(monkeypatch)

    result = sweepy_mcp.find_cached_veterans(
        account="alpha",
        blue_factor="Power",
        minimum_lineage_stars=9,
    )

    assert result["success"] is True
    assert result["match_count"] == 1
    assert result["matches"][0]["trained_chara_id"] == 1002
    assert result["matches"][0]["matched_blue_stars"] == 9
    assert result["query"]["definition"] == (
        "self + direct parent 1 + direct parent 2"
    )


def test_get_cached_veteran_details_never_confuses_race_spark_with_power(monkeypatch):
    setup(monkeypatch)

    result = sweepy_mcp.get_cached_veteran_details(
        account="alpha",
        trained_chara_id=1001,
    )

    assert result["success"] is True
    veteran = result["veteran"]
    assert veteran["final_stats"]["power"] == 1200
    assert veteran["direct_lineage_blue_totals"].get("Power", 0) == 0
    assert veteran["factor_tree"]["self"]["white_race"][0]["name"] == "Arima Kinen"
