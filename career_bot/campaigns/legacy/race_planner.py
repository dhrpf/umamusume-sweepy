from __future__ import annotations

from collections import defaultdict
from typing import Any


DEFAULT_SUMMER_CAMP_TURNS = frozenset({37, 38, 39, 40, 61, 62, 63, 64})


def _race_chain_length(turns: set[int], candidate: int) -> int:
    values = set(turns)
    values.add(candidate)
    left = candidate
    while left - 1 in values:
        left -= 1
    right = candidate
    while right + 1 in values:
        right += 1
    return right - left + 1


def _year_priority(row: dict[str, Any], prefer_senior: bool) -> int:
    date = str(row.get("date") or "").lower()
    if "senior" in date:
        return 0 if prefer_senior else 2
    if "classic" in date:
        return 1
    if "junior" in date:
        return 2 if prefer_senior else 0
    return 3


def build_shared_g1_agenda(
    race_rows: list[dict[str, Any]],
    *,
    terrain: str = "Turf",
    distances: list[str] | tuple[str, ...] = ("Mile", "Medium", "Long"),
    protect_summer_camp: bool = True,
    maximum_consecutive_races: int = 3,
    prefer_senior_repeats: bool = True,
    summer_camp_turns: set[int] | frozenset[int] = DEFAULT_SUMMER_CAMP_TURNS,
) -> dict[str, Any]:
    wanted_terrain = str(terrain or "Turf").strip().casefold()
    wanted_distances = {str(value).strip().casefold() for value in distances if str(value).strip()}
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in race_rows or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("type") or "").strip().upper() != "G1":
            continue
        if str(row.get("terrain") or "").strip().casefold() != wanted_terrain:
            continue
        if str(row.get("distance") or "").strip().casefold() not in wanted_distances:
            continue
        program_id = int(row.get("program_id") or row.get("id") or 0)
        turn = int(row.get("turn") or 0)
        if program_id <= 0 or turn <= 0:
            continue
        grouped[program_id].append(dict(row))

    chosen: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    selected_turns: set[int] = set()
    groups = sorted(grouped.items(), key=lambda item: min(int(row.get("turn") or 999) for row in item[1]))
    max_chain = max(1, min(int(maximum_consecutive_races), 5))

    for program_id, occurrences in groups:
        ordered = sorted(
            occurrences,
            key=lambda row: (
                bool(protect_summer_camp and int(row.get("turn") or 0) in summer_camp_turns),
                _year_priority(row, prefer_senior_repeats),
                int(row.get("turn") or 0),
            ),
        )
        selected = None
        rejection_reasons = []
        for row in ordered:
            turn = int(row.get("turn") or 0)
            if protect_summer_camp and turn in summer_camp_turns:
                rejection_reasons.append(f"turn {turn} overlaps summer camp")
                continue
            if _race_chain_length(selected_turns, turn) > max_chain:
                rejection_reasons.append(
                    f"turn {turn} would exceed {max_chain} consecutive races"
                )
                continue
            selected = dict(row)
            break
        if selected is None:
            first = ordered[0]
            skipped.append(
                {
                    "program_id": program_id,
                    "name": str(first.get("name") or f"Race #{program_id}"),
                    "reason": "; ".join(rejection_reasons) or "no valid occurrence",
                    "occurrences": [
                        {
                            "turn": int(row.get("turn") or 0),
                            "date": row.get("date"),
                        }
                        for row in ordered
                    ],
                }
            )
            continue
        selected_turns.add(int(selected["turn"]))
        chosen.append(selected)

    chosen.sort(key=lambda row: (int(row.get("turn") or 0), str(row.get("name") or "")))
    return {
        "terrain": terrain,
        "distances": [str(value).title() for value in distances],
        "protect_summer_camp": bool(protect_summer_camp),
        "maximum_consecutive_races": max_chain,
        "selected_count": len(chosen),
        "skipped_count": len(skipped),
        "agenda": chosen,
        "skipped": skipped,
        "notes": [
            "One occurrence is selected per G1 program because the shared win saddle is the affinity objective.",
            "A race only contributes shared-win progress when it is won.",
            "Senior repeats are preferred when they avoid summer camp or an excessive race chain.",
        ],
    }
