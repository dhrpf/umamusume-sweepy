import sqlite3

import pytest

from career_bot.independent_training.tp_cost import (
    TpCostResolutionError,
    resolve_independent_training_tp_cost,
)


def _campaign_db(tmp_path, rows=()):
    path = tmp_path / "master.mdb"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE campaign_data (
                campaign_id INTEGER PRIMARY KEY,
                target_type INTEGER NOT NULL,
                effect_type_1 INTEGER NOT NULL,
                effect_value_1 INTEGER NOT NULL,
                start_time INTEGER NOT NULL,
                end_time INTEGER NOT NULL
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO campaign_data (
                campaign_id,
                target_type,
                effect_type_1,
                effect_value_1,
                start_time,
                end_time
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    return path


def test_uses_base_cost_when_no_matching_campaign_is_active(tmp_path):
    path = _campaign_db(
        tmp_path,
        [(1, 1, 4, 15, 200, 300)],
    )

    resolution = resolve_independent_training_tp_cost(
        path,
        base_cost=30,
        server_time=100,
    )

    assert resolution.cost == 30
    assert resolution.source == "base"


def test_uses_active_campaign_effect_value_as_actual_cost(tmp_path):
    path = _campaign_db(
        tmp_path,
        [(1, 1, 4, 15, 100, 200)],
    )

    resolution = resolve_independent_training_tp_cost(
        path,
        base_cost=30,
        server_time=150,
    )

    assert resolution.cost == 15
    assert resolution.source == "campaign"


def test_ignores_other_campaign_targets_and_effects(tmp_path):
    path = _campaign_db(
        tmp_path,
        [
            (1, 2, 4, 5, 100, 200),
            (2, 1, 3, 10, 100, 200),
        ],
    )

    resolution = resolve_independent_training_tp_cost(
        path,
        base_cost=30,
        server_time=150,
    )

    assert resolution.cost == 30


@pytest.mark.parametrize(
    ("base_cost", "server_time"),
    [(0, 100), (-1, 100), (30, 0), (30, -1)],
)
def test_rejects_non_positive_runtime_inputs(tmp_path, base_cost, server_time):
    path = _campaign_db(tmp_path)

    with pytest.raises(TpCostResolutionError):
        resolve_independent_training_tp_cost(
            path,
            base_cost=base_cost,
            server_time=server_time,
        )


def test_rejects_missing_master_database(tmp_path):
    with pytest.raises(TpCostResolutionError, match="master.mdb"):
        resolve_independent_training_tp_cost(
            tmp_path / "missing.mdb",
            base_cost=30,
            server_time=100,
        )


def test_rejects_missing_campaign_table(tmp_path):
    path = tmp_path / "master.mdb"
    sqlite3.connect(path).close()

    with pytest.raises(TpCostResolutionError, match="campaign_data"):
        resolve_independent_training_tp_cost(
            path,
            base_cost=30,
            server_time=100,
        )


def test_rejects_invalid_active_campaign_cost(tmp_path):
    path = _campaign_db(
        tmp_path,
        [(1, 1, 4, 0, 100, 200)],
    )

    with pytest.raises(TpCostResolutionError, match="invalid"):
        resolve_independent_training_tp_cost(
            path,
            base_cost=30,
            server_time=150,
        )


def test_rejects_conflicting_active_campaign_costs(tmp_path):
    path = _campaign_db(
        tmp_path,
        [
            (1, 1, 4, 15, 100, 200),
            (2, 1, 4, 10, 100, 200),
        ],
    )

    with pytest.raises(TpCostResolutionError, match="conflicting"):
        resolve_independent_training_tp_cost(
            path,
            base_cost=30,
            server_time=150,
        )
