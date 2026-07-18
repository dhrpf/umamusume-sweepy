from __future__ import annotations

import itertools
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from career_bot.affinity import card_to_chara_id

from .final_setup import rank_final_parent_candidates
from .legacy.race_planner import build_shared_g1_agenda
from .legacy.scanner import scan_legacy_loop_pools
from .legacy.veteran_inventory import summarize_veteran
from .targets import evaluate_spark_targets


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


class CampaignPlanner:
    def __init__(
        self,
        *,
        owned_chara_ids: set[int],
        veteran_records: list[dict[str, Any]],
        display_by_id: dict[int, dict[str, Any]],
        g1_saddle_ids: set[int],
        race_rows: list[dict[str, Any]],
        affinity_for_pair: Callable[[int, dict[str, Any], dict[str, Any]], Mapping[str, Any]],
        factor_map: dict[str, Any] | None = None,
        spark_targets: Sequence[Mapping[str, Any]] = (),
        final_uma_card_id: int = 0,
    ) -> None:
        self.owned_chara_ids = {int(value) for value in owned_chara_ids}
        self.veteran_records = [dict(row) for row in veteran_records if isinstance(row, dict)]
        self.display_by_id = display_by_id
        self.factor_map = factor_map or {}
        self.spark_targets = list(spark_targets)
        self.final_uma_card_id = int(final_uma_card_id)
        self.g1_saddle_ids = set(g1_saddle_ids)
        self.race_rows = race_rows
        self.affinity_for_pair = affinity_for_pair

    @staticmethod
    def _chara_id(record: Mapping[str, Any]) -> int:
        card_id = _int(record.get("card_id") or record.get("chara_id"))
        return card_to_chara_id(card_id) if card_id else 0

    def _summary(self, record: dict[str, Any]) -> dict[str, Any]:
        trained_id = _int(record.get("trained_chara_id") or record.get("instance_id"))
        return summarize_veteran(
            record,
            factor_map=self.factor_map,
            display=self.display_by_id.get(trained_id),
        )

    @staticmethod
    def _spark_totals(summary: Mapping[str, Any]) -> dict[tuple[str, str], int]:
        totals: dict[tuple[str, str], int] = {}
        for node in (summary.get("factor_tree") or {}).values():
            if not isinstance(node, Mapping):
                continue
            for category in ("blue", "pink"):
                for factor in node.get(category) or []:
                    key = (category, str(factor.get("name") or "").strip().lower())
                    totals[key] = totals.get(key, 0) + _int(factor.get("stars"))
        return totals

    def recommend_final_parents(self, *, limit: int = 3) -> list[dict[str, Any]]:
        rows = []
        final_uma_chara_id = (
            card_to_chara_id(self.final_uma_card_id)
            if self.final_uma_card_id >= 100000
            else self.final_uma_card_id
        )
        for candidate in self.veteran_records:
            chara_id = self._chara_id(candidate)
            if chara_id <= 0 or chara_id == final_uma_chara_id:
                continue
            summary = self._summary(candidate)
            target_progress = evaluate_spark_targets(
                self.spark_targets,
                self._spark_totals(summary),
            )
            pairings = []
            for second_parent in self.veteran_records:
                second_chara_id = self._chara_id(second_parent)
                if second_parent is candidate or second_chara_id in {
                    0,
                    chara_id,
                    final_uma_chara_id,
                }:
                    continue
                affinity = self.affinity_for_pair(
                    self.final_uma_card_id,
                    candidate,
                    second_parent,
                )
                pairings.append(
                    {
                        "affinity": _int(affinity.get("total")),
                        "chara_compat": _int(affinity.get("chara_compat")),
                        "race_compat": _int(affinity.get("race_compat")),
                        "second_parent_trained_chara_id": _int(second_parent.get("trained_chara_id")),
                        "second_parent_chara_id": second_chara_id,
                    }
                )
            pairing = max(
                pairings,
                key=lambda row: (
                    row["affinity"],
                    row["race_compat"],
                    row["chara_compat"],
                    -row["second_parent_trained_chara_id"],
                ),
                default={"affinity": 0, "chara_compat": 0, "race_compat": 0},
            )
            rows.append(
                {
                    "key": f"{chara_id}:{summary['trained_chara_id']}",
                    "chara_id": chara_id,
                    "veteran": summary,
                    "pairing": pairing,
                    "best_affinity": pairing["affinity"],
                    "required_progress": target_progress["required_progress"],
                    "preferred_progress": target_progress["preferred_progress"],
                    "existing": True,
                    "effort": 0.0,
                    "score_breakdown": {
                        "required_progress": target_progress["required_progress"],
                        "preferred_progress": target_progress["preferred_progress"],
                        "final_affinity": pairing["affinity"],
                        "existing_veteran": True,
                        "remaining_effort": 0.0,
                    },
                }
            )

        unique: dict[int, dict[str, Any]] = {}
        for row in rank_final_parent_candidates(rows):
            unique.setdefault(row["chara_id"], row)
        ranked = sorted(unique.values(), key=lambda row: (-row["score"], row["chara_id"]))
        return ranked[: max(0, int(limit))]

    def _loop_row(self, pool: Mapping[str, Any], *, owned: bool) -> dict[str, Any]:
        member_ids = {_int(row.get("trained_chara_id")) for row in pool.get("members") or []}
        records = [
            row
            for row in self.veteran_records
            if _int(row.get("trained_chara_id")) in member_ids
        ]
        final_fit = max(
            (
                _int(self.affinity_for_pair(self.final_uma_card_id, first, second).get("total"))
                for first, second in itertools.combinations(records, 2)
            ),
            default=0,
        )
        breakdown = {
            "mutual_compatibility": _int(pool["affinity"]["worst"]),
            "stable_affinity": float(pool["affinity"]["average"]),
            "shared_g1": _int(pool.get("shared_g1_count")),
            "style_alignment": _int(pool["running_style"]["matching_members"]),
            "distance_overlap": len(pool["distance_overlap"]["usable_b_or_better"]),
            "final_target_fit": final_fit,
        }
        score = (
            breakdown["mutual_compatibility"] * 10
            + breakdown["stable_affinity"]
            + breakdown["shared_g1"] * 20
            + breakdown["style_alignment"] * 5
            + breakdown["distance_overlap"] * 5
            + breakdown["final_target_fit"] * 2
        )
        return {
            **dict(pool),
            "chara_ids": list(pool["base_chara_ids"]),
            "owned": owned,
            "shared_g1_agenda": build_shared_g1_agenda(self.race_rows),
            "score": score,
            "score_breakdown": breakdown,
        }

    def recommend_bootstraps(
        self,
        *,
        pinned_chara_ids: set[int] | None = None,
        limit: int = 3,
        mdb_path: str | Path = "",
    ) -> dict[str, list[dict[str, Any]]]:
        pinned = {int(value) for value in (pinned_chara_ids or set())}
        names = {
            trained_id: str(display.get("name") or "")
            for trained_id, display in self.display_by_id.items()
        }

        def scan(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
            result = scan_legacy_loop_pools(
                records,
                mdb_path=mdb_path,
                veteran_names=names,
                limit=50,
                affinity_calculator=lambda _path, trainee, first, second: self.affinity_for_pair(
                    trainee, first, second
                ),
                g1_saddle_ids=self.g1_saddle_ids,
                required_base_chara_ids=pinned,
                pool_size=3,
            )
            return [
                pool
                for pool in result["pools"]
                if pinned.issubset(set(pool["base_chara_ids"]))
            ]

        owned_records = [
            row for row in self.veteran_records if self._chara_id(row) in self.owned_chara_ids
        ]
        runnable = [self._loop_row(pool, owned=True) for pool in scan(owned_records)]
        upgrades = [
            self._loop_row(pool, owned=False)
            for pool in scan(self.veteran_records)
            if not set(pool["base_chara_ids"]).issubset(self.owned_chara_ids)
        ]
        order = lambda row: (-row["score"], tuple(row["chara_ids"]))
        return {
            "bootstraps": sorted(runnable, key=order)[: max(0, int(limit))],
            "ideal_upgrades": sorted(upgrades, key=order)[: max(0, int(limit))],
        }

    def recommend_loops(
        self,
        *,
        pinned_chara_ids: set[int] | None = None,
        final_parent_chara_id: int = 0,
        limit: int = 3,
        mdb_path: str | Path = "",
    ) -> dict[str, list[dict[str, Any]]]:
        pinned = {int(value) for value in (pinned_chara_ids or set())}
        required_chara_ids = set(pinned)
        if int(final_parent_chara_id or 0) > 0:
            required_chara_ids.add(int(final_parent_chara_id))
        names = {
            trained_id: str(display.get("name") or "")
            for trained_id, display in self.display_by_id.items()
        }

        def scan(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
            result = scan_legacy_loop_pools(
                records,
                mdb_path=mdb_path,
                veteran_names=names,
                limit=50,
                affinity_calculator=lambda _path, trainee, first, second: self.affinity_for_pair(
                    trainee, first, second
                ),
                g1_saddle_ids=self.g1_saddle_ids,
                required_base_chara_ids=required_chara_ids,
            )
            return [
                pool
                for pool in result["pools"]
                if required_chara_ids.issubset(set(pool["base_chara_ids"]))
            ]

        owned_records = [
            row for row in self.veteran_records if self._chara_id(row) in self.owned_chara_ids
        ]
        runnable = [self._loop_row(pool, owned=True) for pool in scan(owned_records)]
        upgrades = [
            self._loop_row(pool, owned=False)
            for pool in scan(self.veteran_records)
            if not set(pool["base_chara_ids"]).issubset(self.owned_chara_ids)
        ]
        order = lambda row: (-row["score"], tuple(row["chara_ids"]))
        return {
            "loops": sorted(runnable, key=order)[: max(0, int(limit))],
            "ideal_upgrades": sorted(upgrades, key=order)[: max(0, int(limit))],
        }


__all__ = ["CampaignPlanner"]
