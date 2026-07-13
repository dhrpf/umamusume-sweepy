"""Shared character-objective resolution for career scenarios.

The API exposes ``route_id`` and ``route_race_id_array`` but not a friendly
objective description or progress counter.  This module joins those route IDs
with master data and evaluates the supported objective conditions against the
current career state.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from career_bot.master_data import configured_master_mdb_path


SUPPORTED_CONDITION_TYPES = {1, 2, 3}


@dataclass(frozen=True)
class ObjectiveDefinition:
    objective_id: int
    scenario_group_id: int
    target_type: int
    sort_id: int
    deadline_turn: int
    race_type: int
    condition_type: int
    condition_id: int
    condition_value_1: int
    condition_value_2: int

    @classmethod
    def from_dict(cls, row):
        row = row or {}
        return cls(
            objective_id=int(row.get("id") or row.get("objective_id") or 0),
            scenario_group_id=int(row.get("scenario_group_id") or 0),
            target_type=int(row.get("target_type") or 0),
            sort_id=int(row.get("sort_id") or 0),
            deadline_turn=int(row.get("turn") or row.get("deadline_turn") or 0),
            race_type=int(row.get("race_type") or 0),
            condition_type=int(row.get("condition_type") or 0),
            condition_id=int(row.get("condition_id") or 0),
            condition_value_1=int(row.get("condition_value_1") or 0),
            condition_value_2=int(row.get("condition_value_2") or 0),
        )


@dataclass
class ObjectiveRaceDecision:
    program_id: int
    forced: bool
    reason: str
    score: float
    detail: dict = field(default_factory=dict)


@dataclass
class ObjectiveStatus:
    definition: ObjectiveDefinition
    window_start_turn: int
    progress: int
    required: int
    completed: bool
    supported: bool = True
    qualifying_results: list[dict] = field(default_factory=list)

    @property
    def objective_id(self):
        return self.definition.objective_id

    @property
    def deadline_turn(self):
        return self.definition.deadline_turn

    @property
    def condition_type(self):
        return self.definition.condition_type

    def as_dict(self):
        return {
            "id": self.objective_id,
            "condition_type": self.condition_type,
            "condition_id": self.definition.condition_id,
            "condition_value_1": self.definition.condition_value_1,
            "condition_value_2": self.definition.condition_value_2,
            "window_start_turn": self.window_start_turn,
            "deadline_turn": self.deadline_turn,
            "progress": self.progress,
            "required": self.required,
            "completed": self.completed,
            "supported": self.supported,
        }


class CareerObjectiveResolver:
    """Resolve and evaluate shared character objectives.

    Character routes use ``scenario_id = 0`` in master data and are shared by
    URA Finale and Unity Cup.  Scenario-final targets use another target type;
    the MVP deliberately evaluates only ``target_type == 1``.
    """

    def __init__(self, base_dir, race_programs=None):
        self.base_dir = Path(base_dir)
        self.race_programs = race_programs if race_programs is not None else {}
        self.routes = {}
        self._load()

    def _load(self):
        path = self.base_dir / "data" / "career_objectives.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self.routes = {
                    int(route_id): value
                    for route_id, value in (data.get("routes") or {}).items()
                }
            except (OSError, ValueError, TypeError):
                self.routes = {}

        # Generated JSON is preferred.  The one-time SQLite fallback makes a
        # newly installed objective engine immediately usable before the user
        # regenerates legacy data files.
        if not self.routes and self.base_dir.exists():
            self.routes = self._load_from_master_mdb()

    def _load_from_master_mdb(self):
        db_path = configured_master_mdb_path(self.base_dir)
        try:
            if not db_path.exists():
                return {}
            with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
                route_rows = conn.execute(
                    "SELECT id, scenario_id, chara_id, race_set_id, condition_set_id, priority "
                    "FROM single_mode_route"
                ).fetchall()
                objective_rows = conn.execute(
                    "SELECT id, race_set_id, scenario_group_id, target_type, sort_id, turn, "
                    "race_type, condition_type, condition_id, condition_value_1, "
                    "condition_value_2, determine_race, determine_race_flag "
                    "FROM single_mode_route_race ORDER BY race_set_id, sort_id"
                ).fetchall()
        except (OSError, sqlite3.Error):
            return {}

        objectives_by_set = {}
        objective_columns = (
            "id", "race_set_id", "scenario_group_id", "target_type", "sort_id",
            "turn", "race_type", "condition_type", "condition_id",
            "condition_value_1", "condition_value_2", "determine_race",
            "determine_race_flag",
        )
        for values in objective_rows:
            row = dict(zip(objective_columns, values))
            objectives_by_set.setdefault(int(row["race_set_id"]), []).append(row)

        routes = {}
        route_columns = (
            "id", "scenario_id", "chara_id", "race_set_id",
            "condition_set_id", "priority",
        )
        for values in route_rows:
            row = dict(zip(route_columns, values))
            route_id = int(row["id"])
            race_set_id = int(row["race_set_id"])
            routes[route_id] = {
                **row,
                "objectives": objectives_by_set.get(race_set_id, []),
            }
        return routes

    def route_objectives(self, state):
        data = (state or {}).get("data") or {}
        chara = data.get("chara_info") or {}
        route_id = int(chara.get("route_id") or 0)
        if not route_id:
            return []
        route = self.routes.get(route_id) or {}
        allowed = {
            int(value)
            for value in (chara.get("route_race_id_array") or [])
            if int(value or 0)
        }
        definitions = []
        for row in route.get("objectives") or []:
            objective = ObjectiveDefinition.from_dict(row)
            if not objective.objective_id:
                continue
            if allowed and objective.objective_id not in allowed:
                continue
            # target_type 1 = shared character objective. Scenario finals stay
            # under their existing URA/Unity lifecycle handlers.
            if objective.target_type != 1:
                continue
            definitions.append(objective)
        return sorted(definitions, key=lambda item: (item.sort_id, item.objective_id))

    def merged_history(self, state, cached_results=None):
        data = (state or {}).get("data") or {}
        merged = {}
        rows = list(data.get("race_history") or [])
        if isinstance(cached_results, dict):
            rows.extend(cached_results.values())
        elif cached_results:
            rows.extend(cached_results)

        for row in rows:
            if not isinstance(row, dict):
                continue
            turn = int(row.get("turn") or 0)
            program_id = int(row.get("program_id") or 0)
            if not program_id:
                continue
            key = (turn, program_id)
            previous = merged.get(key) or {}
            # Prefer a row carrying an actual result rank.
            if not previous or int(row.get("result_rank") or 0):
                merged[key] = {
                    "turn": turn,
                    "program_id": program_id,
                    "result_rank": int(row.get("result_rank") or 0),
                }
        return sorted(merged.values(), key=lambda row: (row["turn"], row["program_id"]))

    def race_grade(self, program_id):
        info = self.race_programs.get(int(program_id or 0)) or {}
        grade = int(info.get("grade") or 0)
        if grade:
            return grade

        # Backward-compatible fallback for existing race_map.json files.  The
        # first digit of normal race instance IDs encodes G1/G2/G3/Open.
        text = str(info.get("race_instance_id") or "")
        if text and text[0] in {"1", "2", "3", "4"}:
            return int(text[0]) * 100
        return 0

    def _window_start(self, definitions, index):
        if index <= 0:
            return 1
        return int(definitions[index - 1].deadline_turn or 0) + 1

    def evaluate(self, objective, state, window_start_turn, cached_results=None):
        data = (state or {}).get("data") or {}
        chara = data.get("chara_info") or {}
        history = self.merged_history(state, cached_results)
        deadline = int(objective.deadline_turn or 0)
        history = [
            row for row in history
            if int(window_start_turn) <= int(row.get("turn") or 0) <= deadline
        ]

        if objective.condition_type == 1:
            required_rank = int(objective.condition_value_1 or 0)
            matching = [
                row for row in history
                if int(row.get("program_id") or 0) == objective.condition_id
                and (
                    required_rank <= 0
                    or 0 < int(row.get("result_rank") or 0) <= required_rank
                )
            ]
            progress = 1 if matching else 0
            return ObjectiveStatus(
                objective, window_start_turn, progress, 1, bool(progress),
                qualifying_results=matching,
            )

        if objective.condition_type == 2:
            required_rank = int(objective.condition_value_1 or 0)
            required_count = max(1, int(objective.condition_value_2 or 0))
            matching = [
                row for row in history
                if self.race_grade(row.get("program_id")) == objective.condition_id
                and 0 < int(row.get("result_rank") or 0) <= required_rank
            ]
            progress = len(matching)
            return ObjectiveStatus(
                objective,
                window_start_turn,
                progress,
                required_count,
                progress >= required_count,
                qualifying_results=matching,
            )

        if objective.condition_type == 3:
            required_fans = max(0, int(objective.condition_value_1 or 0))
            fans = int(chara.get("fans") or 0)
            return ObjectiveStatus(
                objective,
                window_start_turn,
                fans,
                required_fans,
                fans >= required_fans,
            )

        return ObjectiveStatus(
            objective,
            window_start_turn,
            0,
            1,
            False,
            supported=False,
        )

    def statuses(self, state, cached_results=None):
        definitions = self.route_objectives(state)
        return [
            self.evaluate(
                objective,
                state,
                self._window_start(definitions, index),
                cached_results,
            )
            for index, objective in enumerate(definitions)
        ]

    def current_status(self, state, cached_results=None):
        data = (state or {}).get("data") or {}
        chara = data.get("chara_info") or {}
        current_turn = int(chara.get("turn") or 0)
        for status in self.statuses(state, cached_results):
            if status.completed:
                continue
            # Normal turn responses often omit historical race results.  If the
            # career has already advanced past an objective deadline, the server
            # necessarily accepted that objective; do not let missing history
            # pin the resolver to an old goal forever.
            if status.deadline_turn and current_turn > status.deadline_turn:
                continue
            return status
        return None

    def qualifying_program_ids(self, status, program_ids: Iterable[int]):
        objective = status.definition
        candidates = []
        for raw_program_id in program_ids:
            program_id = int(raw_program_id or 0)
            if not program_id:
                continue
            if objective.condition_type == 1:
                if program_id == objective.condition_id:
                    candidates.append(program_id)
            elif objective.condition_type == 2:
                if self.race_grade(program_id) == objective.condition_id:
                    candidates.append(program_id)
            elif objective.condition_type == 3:
                candidates.append(program_id)
        return candidates
