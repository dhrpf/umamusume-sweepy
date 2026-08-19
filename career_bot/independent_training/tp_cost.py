from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


class TpCostResolutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class TpCostResolution:
    cost: int
    source: str
    campaign_ids: tuple[int, ...] = ()


def resolve_independent_training_tp_cost(
    master_mdb_path,
    *,
    base_cost: int,
    server_time: int,
) -> TpCostResolution:
    base_cost = int(base_cost or 0)
    server_time = int(server_time or 0)
    if base_cost <= 0:
        raise TpCostResolutionError(
            "Independent Training base TP cost is unavailable"
        )
    if server_time <= 0:
        raise TpCostResolutionError(
            "Authoritative server time is unavailable"
        )

    path = Path(master_mdb_path)
    if not path.is_file():
        raise TpCostResolutionError(f"master.mdb not found at {path}")

    try:
        with sqlite3.connect(
            f"file:{path.resolve()}?mode=ro",
            uri=True,
        ) as connection:
            rows = connection.execute(
                """
                SELECT campaign_id, effect_value_1
                FROM campaign_data
                WHERE target_type = 1
                  AND effect_type_1 = 4
                  AND start_time <= ?
                  AND end_time >= ?
                ORDER BY campaign_id
                """,
                (server_time, server_time),
            ).fetchall()
    except sqlite3.Error as exc:
        raise TpCostResolutionError(
            f"Unable to read campaign_data from master.mdb: {exc}"
        ) from exc

    if not rows:
        return TpCostResolution(cost=base_cost, source="base")

    costs = {int(row[1] or 0) for row in rows}
    if any(cost <= 0 for cost in costs):
        raise TpCostResolutionError(
            "Active TP campaign has an invalid effect value"
        )
    if len(costs) != 1:
        raise TpCostResolutionError(
            "Active TP campaigns have conflicting effect values"
        )

    return TpCostResolution(
        cost=costs.pop(),
        source="campaign",
        campaign_ids=tuple(int(row[0]) for row in rows),
    )
