from __future__ import annotations

import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from career_bot.master_data import configured_master_mdb_path


def _race_turn(year: int, program: dict[str, Any]) -> int:
    month = int(program.get("month") or 0)
    half = int(program.get("half") or 0)
    if year not in {1, 2, 3} or not 1 <= month <= 12 or half not in {1, 2}:
        return 0
    return (year - 1) * 24 + (month - 1) * 2 + half


def canonicalize_race_array(
    race_array: Iterable[dict[str, Any]],
    *,
    objectives: Iterable[dict[str, Any]],
    programs: dict[int, dict[str, Any]],
    chara_sex: int,
) -> list[dict[str, int]]:
    objective_rows = []
    objective_by_turn = {}
    for row in objectives:
        turn = int(row.get("turn") or 0)
        program_id = int(row.get("program_id") or 0)
        year = (turn - 1) // 24 + 1 if turn > 0 else 0
        if year not in {1, 2, 3} or program_id <= 0:
            continue
        if program_id not in programs:
            raise ValueError(
                f"objective references missing race program {program_id}"
            )
        normalized = {"year": year, "program_id": program_id}
        objective_rows.append(normalized)
        key = (year, program_id)
        existing = objective_by_turn.get(turn)
        if existing is not None and existing != key:
            raise ValueError(
                f"multiple mandatory objectives share turn {turn}"
            )
        objective_by_turn[turn] = key

    result = []
    seen = set()
    for row in race_array or []:
        year = int(row.get("year") or 0)
        program_id = int(row.get("program_id") or 0)
        key = (year, program_id)
        if year not in {1, 2, 3} or program_id <= 0 or key in seen:
            continue

        program = programs.get(program_id)
        if program is None:
            raise ValueError(f"missing race program {program_id}")
        if (
            int(chara_sex or 0) == 1
            and int(program.get("filly_only_flag") or 0) == 1
        ):
            continue

        turn = _race_turn(year, program)
        required = objective_by_turn.get(turn)
        if required is not None and required != key:
            continue

        seen.add(key)
        result.append({"year": year, "program_id": program_id})

    for row in objective_rows:
        key = (row["year"], row["program_id"])
        if key not in seen:
            seen.add(key)
            result.append(dict(row))
    return result


def _load_start_objectives(conn, *, chara_id: int, card_id: int):
    route = conn.execute(
        """
        SELECT race_set_id
        FROM single_mode_route
        WHERE scenario_id = 0 AND chara_id = ?
        ORDER BY priority DESC, id ASC
        LIMIT 1
        """,
        (int(chara_id),),
    ).fetchone()
    if route is None:
        raise ValueError(
            f"career objective route is missing for character {chara_id}"
        )

    rows = conn.execute(
        """
        SELECT sort_id, turn, condition_id,
               determine_race, determine_race_flag
        FROM single_mode_route_race
        WHERE race_set_id = ?
          AND target_type = 1
          AND condition_type = 1
          AND race_type = 0
        ORDER BY sort_id, id
        """,
        (int(route[0]),),
    ).fetchall()
    grouped = defaultdict(list)
    for sort_id, turn, program_id, determine, flag in rows:
        grouped[int(sort_id)].append({
            "turn": int(turn),
            "program_id": int(program_id),
            "determine_race": int(determine),
            "determine_race_flag": int(flag),
        })

    objectives = []
    for sort_id in sorted(grouped):
        group = grouped[sort_id]
        exact = [
            row
            for row in group
            if row["determine_race"] in {2, 3, 4}
            and row["determine_race_flag"] == int(card_id)
        ]
        if any(row["determine_race"] == 4 for row in exact):
            raise ValueError(
                f"unsupported conditional objective at sort {sort_id}"
            )
        candidates = (
            exact
            or [row for row in group if row["determine_race"] == 0]
            or [row for row in group if row["determine_race"] == 1]
        )
        if not candidates and all(
            row["determine_race"] == 3 for row in group
        ):
            # Costume-specific rows referencing outfits absent from this
            # server's card_data (unreleased/future costumes). None of them
            # can match the active card, so fall back to the lowest-id row.
            candidates = [group[0]]  # rows pre-sorted by id (see query above)
        if len(candidates) != 1:
            raise ValueError(
                "unable to resolve objective "
                f"sort {sort_id} for trainee card {card_id}"
            )
        objectives.append({
            "turn": candidates[0]["turn"],
            "program_id": candidates[0]["program_id"],
        })
    return objectives


def canonicalize_start_race_array(
    base_dir,
    setup: dict[str, Any],
    *,
    master_mdb_path=None,
) -> list[dict[str, int]]:
    base_dir = Path(base_dir)
    db_path = Path(
        master_mdb_path
        if master_mdb_path is not None
        else configured_master_mdb_path(base_dir)
    )
    if not db_path.exists():
        raise ValueError("master.mdb is unavailable for race validation")

    card_id = int(setup.get("card_id") or 0)
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            chara_row = conn.execute(
                """
                SELECT card_data.chara_id, chara_data.sex
                FROM card_data
                JOIN chara_data ON chara_data.id = card_data.chara_id
                WHERE card_data.id = ?
                """,
                (card_id,),
            ).fetchone()
            if chara_row is None:
                raise ValueError(
                    f"trainee card {card_id} is missing from master.mdb"
                )

            chara_id, chara_sex = map(int, chara_row)
            objectives = _load_start_objectives(
                conn,
                chara_id=chara_id,
                card_id=card_id,
            )
            requested_program_ids = {
                int(row.get("program_id") or 0)
                for row in (setup.get("race_array") or [])
                if int(row.get("program_id") or 0) > 0
            }
            objective_program_ids = {
                int(row["program_id"])
                for row in objectives
            }
            program_ids = sorted({
                *requested_program_ids,
                *objective_program_ids,
            })
            programs = {}
            if program_ids:
                placeholders = ",".join("?" for _ in program_ids)
                rows = conn.execute(
                    f"""
                    SELECT id, month, half, filly_only_flag
                    FROM single_mode_program
                    WHERE id IN ({placeholders})
                    """,
                    program_ids,
                ).fetchall()
                programs = {
                    int(program_id): {
                        "month": int(month),
                        "half": int(half),
                        "filly_only_flag": int(filly_only_flag),
                    }
                    for program_id, month, half, filly_only_flag in rows
                }
            missing_requested = sorted(requested_program_ids - programs.keys())
            if missing_requested:
                raise ValueError(
                    f"missing race programs: {missing_requested}"
                )
            missing_objectives = sorted(
                objective_program_ids - programs.keys()
            )
            if missing_objectives:
                raise ValueError(
                    f"missing objective race programs: {missing_objectives}"
                )
    except sqlite3.Error as exc:
        raise ValueError(f"master.mdb race validation failed: {exc}") from exc

    return canonicalize_race_array(
        setup.get("race_array") or [],
        objectives=objectives,
        programs=programs,
        chara_sex=chara_sex,
    )
