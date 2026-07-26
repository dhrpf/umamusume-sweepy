from __future__ import annotations

from typing import Any

from career_bot.campaigns.legacy.veteran_inventory import decode_factors

from .models import FactorTarget


def normalize_factor_candidates(
    raw_candidates: list[dict[str, Any]] | None,
    factor_map: dict[str, Any],
    targets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized_targets = [FactorTarget.model_validate(row) for row in targets]
    rows = []
    for raw in raw_candidates or []:
        factors = decode_factors(
            {"factor_info_array": list(raw.get("factor_info_array") or [])},
            factor_map,
        )
        totals: dict[tuple[str, str], int] = {}
        for factor in factors:
            category = {
                "stat": "blue",
                "aptitude": "pink",
            }.get(factor["category"])
            if category:
                key = (category, factor["name"].strip().casefold())
                totals[key] = max(totals.get(key, 0), int(factor["stars"]))

        target_rows = []
        for target in normalized_targets:
            actual = totals.get((target.category, target.name), 0)
            target_rows.append(
                {
                    "category": target.category,
                    "name": target.name,
                    "minimum_stars": target.minimum_stars,
                    "actual_stars": actual,
                    "matched": actual >= target.minimum_stars,
                }
            )

        rows.append(
            {
                "lottery_id": int(raw.get("lottery_id") or 0),
                "factors": factors,
                "targets": target_rows,
                "matched_targets": sum(
                    1 for row in target_rows if row["matched"]
                ),
                "capped_star_sum": sum(
                    min(row["actual_stars"], row["minimum_stars"])
                    for row in target_rows
                ),
                "all_targets_matched": all(
                    row["matched"] for row in target_rows
                ),
            }
        )
    return rows


def choose_factor_candidate(
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    if not candidates:
        raise ValueError("factor response did not include a candidate")
    best = candidates[0]
    for candidate in candidates[1:]:
        score = (
            candidate["matched_targets"],
            candidate["capped_star_sum"],
        )
        best_score = (
            best["matched_targets"],
            best["capped_star_sum"],
        )
        if score > best_score:
            best = candidate
    return best
