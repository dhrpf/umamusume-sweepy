import json
from pathlib import Path

from career_bot.objectives import CareerObjectiveResolver, ObjectiveRaceDecision


class RacePlanner:
    def __init__(self, base_dir):
        self.base_dir = Path(base_dir)
        self.meta = {}
        self.program = {}
        self.instance = {}
        self.rejected = set()
        self.objective_results = {}
        self.last_objective_observation = None
        self._load()
        self.objective_resolver = CareerObjectiveResolver(self.base_dir, self.program)

    def _load(self):
        path = self.base_dir / "data" / "race_map.json"
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        self.meta = {int(k): v for k, v in (data.get("meta") or {}).items()}
        self.program = {int(k): v for k, v in (data.get("program") or {}).items()}
        self.instance = {int(k): [int(item) for item in v] for k, v in (data.get("instance") or {}).items()}

    def get_rival_race_map(self, state):
        rivals = (
            state.get("data", {})
            .get("free_data_set", {})
            .get("rival_race_info_array", [])
        )
        return {
            int(r["program_id"]): int(r["chara_id"])
            for r in rivals
            if "program_id" in r and "chara_id" in r
        }

    def wanted_programs(self, preset, turn=None):
        result = []
        seen = set()
        current_turn = int(turn or 0)
        for value in preset.get("extra_race_list") or []:
            try:
                race_id = int(value)
            except (TypeError, ValueError):
                continue
            
            pids = []
            if race_id in self.meta:
                info = self.meta[race_id]
                occurrence_turn = int(info.get("turn") or 0)
                if current_turn and occurrence_turn and occurrence_turn != current_turn:
                    continue
                pid = info.get("program_id")
                if pid:
                    pids.append(pid)
            elif race_id in self.program:
                pids.append(race_id)
            else:
                for program_id in self.instance.get(race_id, []):
                    pids.append(program_id)
            
            for pid in pids:
                if pid not in seen:
                    seen.add(pid)
                    result.append(pid)
        return result

    def available_programs(self, state):
        data = state.get("data") or {}
        rca = data.get("race_condition_array") or []
        available = set()
        for item in rca:
            pid = int(item.get("program_id") or 0)
            if pid:
                available.add(pid)
        return available

    def record_race_result(self, turn, program_id, rank):
        """Cache committed results when a later API response omits history."""
        turn = int(turn or 0)
        program_id = int(program_id or 0)
        if not program_id:
            return
        self.objective_results[(turn, program_id)] = {
            "turn": turn,
            "program_id": program_id,
            "result_rank": int(rank or 0),
        }

    def current_objective_status(self, state):
        # Tests and callers may replace ``program`` after construction.
        self.objective_resolver.race_programs = self.program
        return self.objective_resolver.current_status(
            state,
            cached_results=self.objective_results,
        )

    def objective_training_context(self, state, preset=None):
        """Return the most urgent upcoming specific-race readiness deficit.

        Character routes may contain several fixed races close together.  The
        active objective alone is not enough: while preparing for a mile race,
        the next objective can already be a 2,500m race.  Prefer the upcoming
        race with the largest stamina deficit inside the configured lookahead.
        """
        preset = preset or {}
        self.objective_resolver.race_programs = self.program
        data = (state or {}).get("data") or {}
        chara = data.get("chara_info") or {}
        turn = int(chara.get("turn") or 0)
        lookahead = int(preset.get("objective_training_lookahead", 12))
        contexts = []

        for status in self.objective_resolver.statuses(
            state,
            cached_results=self.objective_results,
        ):
            objective = status.definition
            if status.completed or not status.supported:
                continue
            if objective.condition_type != 1 or int(objective.condition_value_1 or 0) <= 0:
                continue
            deadline = int(status.deadline_turn or 0)
            turns_left = deadline - turn
            if turns_left < 0 or turns_left > lookahead:
                continue
            program_id = int(objective.condition_id or 0)
            info = self.program.get(program_id) or {}
            distance = int(info.get("distance") or 0)
            if not distance:
                continue
            stamina = int(chara.get("stamina") or 0)
            stamina_floor = self._objective_stamina_floor(distance, preset)
            deficit = max(0, stamina_floor - stamina)
            contexts.append({
                "objective_id": status.objective_id,
                "program_id": program_id,
                "name": str(info.get("name") or program_id),
                "deadline_turn": deadline,
                "turns_left": turns_left,
                "distance": distance,
                "required_rank": int(objective.condition_value_1 or 0),
                "stamina": stamina,
                "stamina_floor": stamina_floor,
                "stamina_deficit": deficit,
            })

        if not contexts:
            return None
        contexts.sort(
            key=lambda row: (
                -int(row["stamina_deficit"]),
                int(row["turns_left"]),
                -int(row["distance"]),
            )
        )
        return contexts[0]

    def has_career_win(self, state):
        history = self.objective_resolver.merged_history(
            state,
            cached_results=self.objective_results,
        )
        return any(int(row.get("result_rank") or 0) == 1 for row in history)

    @staticmethod
    def is_maiden_or_debut(info):
        name = str((info or {}).get("name") or "").lower()
        return "maiden race" in name or "make debut" in name

    @staticmethod
    def _objective_stamina_floor(distance, preset=None):
        distance = int(distance or 0)
        preset = preset or {}
        if distance >= 3000:
            return int(preset.get("objective_long_stamina_floor", 450))
        if distance >= 2400:
            return int(preset.get("objective_extended_stamina_floor", 350))
        if distance >= 1800:
            return int(preset.get("objective_middle_stamina_floor", 250))
        return int(preset.get("objective_mile_stamina_floor", 180))

    def _objective_candidate_info(self, chara, program_id, preset=None):
        info = self.program.get(int(program_id or 0)) or {}
        ground_aptitude, distance_aptitude = self.aptitude_values(chara, program_id)
        distance = int(info.get("distance") or 0)
        stamina = int((chara or {}).get("stamina") or 0)
        stamina_floor = self._objective_stamina_floor(distance, preset)
        aptitude_floor = int((preset or {}).get("objective_min_aptitude_floor", 6))
        stamina_deficit = max(0, stamina_floor - stamina)
        score = (
            min(ground_aptitude, distance_aptitude) * 100
            + distance_aptitude * 25
            + ground_aptitude * 15
            - stamina_deficit * 2
        )
        aptitude_ok = (
            ground_aptitude >= aptitude_floor
            and distance_aptitude >= aptitude_floor
        )
        stamina_ready = stamina >= stamina_floor
        safe = aptitude_ok and stamina_ready
        return {
            "program_id": int(program_id or 0),
            "name": str(info.get("name") or program_id),
            "grade": self.objective_resolver.race_grade(program_id),
            "distance": distance,
            "ground_aptitude": ground_aptitude,
            "distance_aptitude": distance_aptitude,
            "stamina": stamina,
            "stamina_floor": stamina_floor,
            "aptitude_ok": aptitude_ok,
            "stamina_ready": stamina_ready,
            "safe": safe,
            "score": float(score),
        }

    def _objective_opportunities(self, state, status, preset=None):
        data = (state or {}).get("data") or {}
        chara = data.get("chara_info") or {}
        current_turn = int(chara.get("turn") or 0)
        deadline = int(status.deadline_turn or 0)
        opportunities = {}

        # Generated meta rows represent concrete race occurrences and turns.
        for row in self.meta.values():
            turn = int((row or {}).get("turn") or 0)
            program_id = int((row or {}).get("program_id") or 0)
            if not program_id or turn < current_turn or turn > deadline:
                continue
            if (turn, program_id) in self.rejected:
                continue
            if not self.can_enter(chara, program_id):
                continue
            if not self.objective_resolver.qualifying_program_ids(status, [program_id]):
                continue
            candidate = self._objective_candidate_info(chara, program_id, preset)
            candidate["turn"] = turn
            opportunities[(turn, program_id)] = candidate

        # Preserve races surfaced by the current API even if the local race map
        # lacks an occurrence row.
        for program_id in self.available_programs(state):
            if not self.objective_resolver.qualifying_program_ids(status, [program_id]):
                continue
            if (current_turn, program_id) in self.rejected:
                continue
            candidate = self._objective_candidate_info(chara, program_id, preset)
            candidate["turn"] = current_turn
            opportunities[(current_turn, program_id)] = candidate

        return sorted(
            opportunities.values(),
            key=lambda row: (row["turn"], -row["score"], row["program_id"]),
        )

    def objective_candidate(self, state, preset=None, best_training_gain=0):
        """Return a progress-aware character-objective race decision.

        This engine is shared by URA Finale and Unity Cup.  Scenario-final
        races remain under the existing scenario lifecycle handlers.
        """
        preset = preset or {}
        if not preset.get("objective_gate_enabled", True):
            return None
        if not self.race_command_enabled(state):
            return None

        status = self.current_objective_status(state)
        if not status or status.completed or not status.supported:
            return None

        data = (state or {}).get("data") or {}
        chara = data.get("chara_info") or {}
        turn = int(chara.get("turn") or 0)
        available = self.available_programs(state)
        objective = status.definition
        mode = str(preset.get("objective_gate_mode", "enforce") or "enforce").lower()
        needed = max(0, int(status.required) - int(status.progress))
        turns_left = max(0, int(status.deadline_turn) - turn)
        detail = {
            "objective": {
                **status.as_dict(),
                "needed": needed,
                "turns_left": turns_left,
            }
        }

        decision = None
        if objective.condition_type == 1:
            program_id = int(objective.condition_id or 0)
            if program_id in available:
                candidate = self._objective_candidate_info(chara, program_id, preset)
                detail["race_candidate"] = candidate
                decision = ObjectiveRaceDecision(
                    program_id=program_id,
                    forced=True,
                    score=candidate["score"],
                    reason=(
                        f"objective {status.objective_id}: target race "
                        f"{candidate['name']} progress={status.progress}/{status.required} "
                        f"deadline={status.deadline_turn}"
                    ),
                    detail=detail,
                )

        elif objective.condition_type == 2:
            current_ids = self.objective_resolver.qualifying_program_ids(status, available)
            current_candidates = [
                self._objective_candidate_info(chara, program_id, preset)
                for program_id in current_ids
                if (turn, int(program_id)) not in self.rejected
                and self.can_enter(chara, program_id)
            ]
            current_candidates.sort(key=lambda row: (-row["safe"], -row["score"], row["program_id"]))
            opportunities = self._objective_opportunities(state, status, preset)
            viable_opportunities = [row for row in opportunities if row["aptitude_ok"]]
            safe_future = [
                row for row in viable_opportunities
                if row["safe"] and row["turn"] > turn
            ]
            buffer_count = int(preset.get("objective_opportunity_buffer", 1))
            lookahead = int(preset.get("objective_gate_lookahead", 8))
            cutoff = float(preset.get("objective_training_gain_cutoff", 45))
            hard_gate = len(viable_opportunities) <= needed + buffer_count
            urgent = turns_left <= lookahead
            detail["objective"].update({
                "remaining_opportunities": len(viable_opportunities),
                "safe_future_opportunities": len(safe_future),
                "hard_gate": hard_gate,
                "urgent": urgent,
                "best_training_gain": float(best_training_gain or 0),
            })

            if current_candidates:
                candidate = current_candidates[0]
                choose = False
                forced = False
                if candidate["safe"]:
                    choose = hard_gate or urgent or float(best_training_gain or 0) <= cutoff
                    forced = hard_gate
                else:
                    # Avoid a risky current race when enough safer future races
                    # remain.  Force it only when skipping would make the goal
                    # mathematically impossible.
                    safe_after_skip = len(safe_future)
                    if hard_gate and safe_after_skip < needed:
                        choose = True
                        forced = True

                if choose:
                    detail["race_candidate"] = candidate
                    decision = ObjectiveRaceDecision(
                        program_id=candidate["program_id"],
                        forced=forced,
                        score=candidate["score"],
                        reason=(
                            f"objective {status.objective_id}: grade {objective.condition_id} "
                            f"progress={status.progress}/{status.required} deadline={status.deadline_turn}; "
                            f"selected {candidate['name']} safe={candidate['safe']} "
                            f"opportunities={len(viable_opportunities)}"
                        ),
                        detail=detail,
                    )

        elif objective.condition_type == 3:
            required = max(1, int(status.required or 0))
            ratio = float(status.progress) / required
            urgent = turns_left <= int(preset.get("objective_fan_lookahead", 4))
            planned = self.planned_fan_completion(state, preset, status)
            detail["objective"].update({
                "fan_ratio": round(ratio, 4),
                "urgent": urgent,
                "planned_fan_race": planned or None,
            })

            if planned and int(planned["turn"]) > turn:
                # A user-planned race before the deadline can both be entered
                # and finish the fan target. Preserve the training turns and
                # wait for that race instead of inserting an unplanned race.
                decision = None
            elif planned and int(planned["program_id"]) in available:
                candidate = self._objective_candidate_info(chara, planned["program_id"], preset)
                detail["race_candidate"] = candidate
                decision = ObjectiveRaceDecision(
                    program_id=candidate["program_id"],
                    forced=True,
                    score=candidate["score"],
                    reason=(
                        f"objective {status.objective_id}: fans "
                        f"{status.progress}/{status.required}; using planned "
                        f"{candidate['name']}"
                    ),
                    detail=detail,
                )
            elif urgent or ratio < float(preset.get("objective_fan_min_ratio", 0.0)):
                candidates = self.fallback_candidates(state)
                if candidates:
                    scored = [self._objective_candidate_info(chara, pid, preset) for pid in candidates]
                    scored.sort(key=lambda row: (-row["safe"], -row["score"], row["program_id"]))
                    candidate = scored[0]
                    detail["race_candidate"] = candidate
                    decision = ObjectiveRaceDecision(
                        program_id=candidate["program_id"],
                        forced=urgent,
                        score=candidate["score"],
                        reason=(
                            f"objective {status.objective_id}: fans "
                            f"{status.progress}/{status.required}; selected {candidate['name']}"
                        ),
                        detail=detail,
                    )

        self.last_objective_observation = detail
        if mode == "observe":
            return None
        if mode == "off":
            return None
        return decision

    def forced_program(self, state, preset=None):
        data = state.get("data") or {}
        home = data.get("home_info") or {}
        commands = home.get("command_info_array") or []
        race_enabled = any(cmd.get("command_type") == 4 and cmd.get("command_id") == 401 and cmd.get("is_enable", 0) for cmd in commands)
        other_enabled = any(cmd.get("command_type") != 4 and cmd.get("is_enable", 0) for cmd in commands)
        if not race_enabled or other_enabled:
            return 0

        available = []
        for item in data.get("race_condition_array") or []:
            pid = int(item.get("program_id") or 0)
            if pid:
                available.append(pid)

        if not available:
            race = data.get("race_start_info") or {}
            return int(race.get("program_id") or 0)

        # Priority 1: planned/wanted program matching this turn
        if preset:
            turn = int((data.get("chara_info") or {}).get("turn") or 0)
            wanted = self.wanted_programs(preset, turn)
            for pid in available:
                if pid in wanted:
                    return pid

        # Priority 2: prefer G1 (race_instance_id leading 1) over lower grades
        g1 = [pid for pid in available if str(self.program.get(pid, {}).get("race_instance_id", "0"))[0] == "1"]
        if g1:
            return g1[0]

        # Fallback: first available
        return available[0]

    def _solver_aptitude_floor(self, preset=None):
        """Minimum aptitude grade (G→S = 1→8) a race must meet. Configurable via preset."""
        return int((preset or {}).get("min_aptitude_floor", 6))

    def aptitude_values(self, chara, program_id):
        info = self.program.get(int(program_id or 0)) or {}
        ground = int(info.get("ground") or 1)
        distance = int(info.get("distance") or 1200)

        if ground == 2:
            ground_aptitude = int(chara.get("proper_ground_dirt") or 1)
        else:
            ground_aptitude = int(chara.get("proper_ground_turf") or 1)

        if distance <= 1400:
            distance_aptitude = int(chara.get("proper_distance_short") or 1)
        elif distance <= 1800:
            distance_aptitude = int(chara.get("proper_distance_mile") or 1)
        elif distance <= 2400:
            distance_aptitude = int(chara.get("proper_distance_middle") or 1)
        else:
            distance_aptitude = int(chara.get("proper_distance_long") or 1)

        return ground_aptitude, distance_aptitude

    def check_aptitude(self, chara, program_id):
        ground_aptitude, distance_aptitude = self.aptitude_values(chara, program_id)
        return ground_aptitude >= 6 and distance_aptitude >= 6

    @staticmethod
    def race_command_enabled(state):
        data = (state or {}).get("data") or {}
        home = data.get("home_info") or {}
        commands = home.get("command_info_array") or []
        return any(
            cmd.get("command_type") == 4
            and cmd.get("command_id") == 401
            and cmd.get("is_enable", 0)
            for cmd in commands
        )

    @staticmethod
    def is_internal_scenario_race(info):
        name = str((info or {}).get("name") or "").lower()
        return "twinkle star climax" in name or "ura finale" in name

    def maiden_candidates(self, state, exclude=None):
        """Return available maiden races ordered by the horse's best aptitude."""
        data = state.get("data") or {}
        chara = data.get("chara_info") or {}
        if not self.race_command_enabled(state):
            return []

        turn = int(chara.get("turn") or 0)
        excluded = {int(pid) for pid in (exclude or set())}
        candidates = []
        for pid in self.available_programs(state):
            if pid in excluded or (turn, pid) in self.rejected:
                continue
            info = self.program.get(pid) or {}
            name = str(info.get("name") or "").lower()
            if "maiden race" not in name:
                continue
            ground_aptitude, distance_aptitude = self.aptitude_values(chara, pid)
            if ground_aptitude < 6 or distance_aptitude < 6:
                continue
            candidates.append((
                -min(ground_aptitude, distance_aptitude),
                -(ground_aptitude + distance_aptitude),
                pid,
            ))
        candidates.sort()
        return [pid for _, _, pid in candidates]

    def minimum_fans(self, program_id):
        """Conservative entry floor derived from the race grade code.

        The server still exposes fan-gated races in race_condition_array, then
        rejects race_entry with 205. G1/G2/G3 need at least 1,000 fans and
        Open/Pre-Open races need at least 350; maiden/debut races have no floor.
        """
        info = self.program.get(int(program_id or 0)) or {}
        instance_id = str(info.get("race_instance_id") or "")
        grade_code = instance_id[:1]
        if grade_code in {"1", "2", "3"}:
            return 1000
        if grade_code == "4":
            return 350
        return 0

    def can_enter(self, chara, program_id):
        fans = int((chara or {}).get("fans") or 0)
        return fans >= self.minimum_fans(program_id)

    def fallback_candidates(self, state, exclude=None):
        if not self.race_command_enabled(state):
            return []
        data = state.get("data") or {}
        chara = data.get("chara_info") or {}
        turn = int(chara.get("turn") or 0)
        excluded = {int(pid) for pid in (exclude or set())}
        has_win = self.has_career_win(state)
        candidates = []
        for pid in self.available_programs(state):
            if pid in excluded or (turn, pid) in self.rejected:
                continue
            if not self.can_enter(chara, pid):
                continue
            if not self.check_aptitude(chara, pid):
                continue
            info = self.program.get(pid) or {}
            if has_win and self.is_maiden_or_debut(info):
                continue
            if self.is_internal_scenario_race(info):
                continue
            grade_code = str(info.get("race_instance_id") or "9")[:1]
            try:
                grade_rank = int(grade_code)
            except ValueError:
                grade_rank = 9
            candidates.append((grade_rank, pid))
        candidates.sort()
        return [pid for _, pid in candidates]

    def _planned_fan_requirement(self, preset, turn, lookahead=1):
        upper_turn = int(turn or 0) + int(lookahead or 0)
        requirements = []
        for value in (preset or {}).get("extra_race_list") or []:
            try:
                race_id = int(value)
            except (TypeError, ValueError):
                continue
            if race_id not in self.meta:
                continue
            info = self.meta[race_id]
            occurrence_turn = int(info.get("turn") or 0)
            if occurrence_turn < int(turn or 0) or occurrence_turn > upper_turn:
                continue
            program_id = int(info.get("program_id") or 0)
            if program_id:
                requirements.append(self.minimum_fans(program_id))
        return max(requirements, default=0)

    def estimated_fan_reward(self, program_id):
        """Conservative fan estimate used only for deferring extra races."""
        grade = int(self.objective_resolver.race_grade(program_id) or 0)
        return {
            100: 5000,
            200: 3000,
            300: 2000,
            400: 1000,
        }.get(grade, 500)

    def planned_fan_completion(self, state, preset, status):
        """Find a planned race that can complete a fan goal by its deadline."""
        data = (state or {}).get("data") or {}
        chara = data.get("chara_info") or {}
        turn = int(chara.get("turn") or 0)
        fans = int(chara.get("fans") or 0)
        required = int(getattr(status, "required", 0) or 0)
        deadline = int(getattr(status, "deadline_turn", 0) or 0)
        rows = []

        for value in (preset or {}).get("extra_race_list") or []:
            try:
                occurrence_id = int(value)
            except (TypeError, ValueError):
                continue
            occurrence = self.meta.get(occurrence_id) or {}
            program_id = int(occurrence.get("program_id") or 0)
            occurrence_turn = int(occurrence.get("turn") or 0)
            if not program_id or occurrence_turn < turn or occurrence_turn > deadline:
                continue
            if (occurrence_turn, program_id) in self.rejected:
                continue
            if not self.can_enter(chara, program_id):
                continue
            projected_fans = fans + self.estimated_fan_reward(program_id)
            if projected_fans < required:
                continue
            info = self.program.get(program_id) or {}
            rows.append({
                "turn": occurrence_turn,
                "program_id": program_id,
                "name": str(info.get("name") or occurrence.get("name") or program_id),
                "estimated_fan_reward": self.estimated_fan_reward(program_id),
                "projected_fans": projected_fans,
            })

        rows.sort(key=lambda row: (row["turn"], -row["estimated_fan_reward"], row["program_id"]))
        return rows[0] if rows else None

    def fan_building_candidate(self, state, preset, lookahead=1):
        data = state.get("data") or {}
        chara = data.get("chara_info") or {}
        turn = int(chara.get("turn") or 0)
        required_soon = self._planned_fan_requirement(
            preset,
            turn,
            lookahead=lookahead,
        )
        fans = int(chara.get("fans") or 0)
        if not required_soon or fans >= required_soon:
            return 0
        candidates = self.fallback_candidates(state)
        return candidates[0] if candidates else 0

    def wanted_available(self, state, preset):
        data = state.get("data") or {}
        chara = data.get("chara_info") or {}
        turn = int(chara.get("turn") or 0)
        available = self.available_programs(state)
        mandatory = set(self.wanted_programs({"extra_race_list": (preset or {}).get("mandatory_race_list") or []}, turn))
        wanted = self.wanted_programs(preset or {}, turn)
        return [
            pid for pid in wanted
            if pid in available
            and (turn, pid) not in self.rejected
            and pid not in mandatory
            and self.can_enter(chara, pid)
        ]

    def mandatory_available(self, state, preset):
        data = state.get("data") or {}
        turn = int((data.get("chara_info") or {}).get("turn") or 0)
        available = self.available_programs(state)
        wanted = self.wanted_programs({"extra_race_list": (preset or {}).get("mandatory_race_list") or []}, turn)
        return [pid for pid in wanted if pid in available and (turn, pid) not in self.rejected]

    def choose(self, state, preset):
        data = state.get("data") or {}
        turn = int((data.get("chara_info") or {}).get("turn") or 0)
        
        home = data.get("home_info") or {}
        commands = home.get("command_info_array") or []
        race_enabled = any(cmd.get("command_type") == 4 and cmd.get("command_id") == 401 and cmd.get("is_enable", 0) for cmd in commands)
        if not race_enabled:
            return 0
    
        available = self.available_programs(state)
        if not available:
            return 0
    
        valid_wanted = self.wanted_available(state, preset)
        
        if not valid_wanted:
            chara = data.get("chara_info") or {}
            fans = int(chara.get("fans") or 0)
            fan_builder = self.fan_building_candidate(state, preset, lookahead=1)
            if fan_builder:
                return fan_builder
            if fans < 350 and turn > 11:
                candidates = self.fallback_candidates(state)
                if candidates:
                    return candidates[0]
            return 0
            
        is_mant = int((data.get("chara_info") or {}).get("scenario_id") or 0) == 4
        if not is_mant:
            return valid_wanted[0]
            
        main_race_id = valid_wanted[0]
        rival_map = self.get_rival_race_map(state)
        
        if main_race_id in rival_map:
            return main_race_id
            
        for overwrite_pid in valid_wanted[1:]:
            if overwrite_pid in rival_map:
                return overwrite_pid
                
        return main_race_id

    def reject(self, turn, program_id):
        self.rejected.add((int(turn or 0), int(program_id or 0)))

    def label(self, program_id):
        info = self.program.get(int(program_id or 0)) or {}
        name = info.get("name") or ""
        race_instance_id = info.get("race_instance_id") or ""
        return f"{program_id} {race_instance_id} {name}".strip()
