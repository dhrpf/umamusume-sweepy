import json
from pathlib import Path


class RacePlanner:
    def __init__(self, base_dir):
        self.base_dir = Path(base_dir)
        self.meta = {}
        self.program = {}
        self.instance = {}
        self.rejected = set()
        self._load()

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

    def maiden_candidates(self, state, exclude=None):
        """Return available maiden races ordered by the horse's best aptitude."""
        data = state.get("data") or {}
        chara = data.get("chara_info") or {}
        home = data.get("home_info") or {}
        commands = home.get("command_info_array") or []
        race_enabled = any(
            cmd.get("command_type") == 4
            and cmd.get("command_id") == 401
            and cmd.get("is_enable", 0)
            for cmd in commands
        )
        if not race_enabled:
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
        data = state.get("data") or {}
        chara = data.get("chara_info") or {}
        turn = int(chara.get("turn") or 0)
        excluded = {int(pid) for pid in (exclude or set())}
        candidates = []
        for pid in self.available_programs(state):
            if pid in excluded or (turn, pid) in self.rejected:
                continue
            if not self.can_enter(chara, pid):
                continue
            if not self.check_aptitude(chara, pid):
                continue
            info = self.program.get(pid) or {}
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
