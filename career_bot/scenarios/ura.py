"""URA Finale scenario strategy — guide-informed training selection."""

from career_bot.scenarios.base import ScenarioStrategy, Decision

TRAINING_COMMANDS = {
    101: ("Speed", 0),
    102: ("Stamina", 1),
    103: ("Power", 2),
    105: ("Guts", 3),
    106: ("Wit", 4),
    # URA summer camp commands — same stat order
    601: ("Speed", 0),
    602: ("Stamina", 1),
    603: ("Power", 2),
    604: ("Guts", 3),
    605: ("Wit", 4),
}

# Energy cost per training: Wit=0, Speed=1, Stamina=1, Power=1, Guts=2
TRAINING_ENERGY = {101: 1, 102: 1, 103: 1, 105: 2, 106: 0}

SUMMER_CAMP_TURNS = {(20, 23), (44, 47)}

# Training levels up after 4 uses
TRAINING_LEVEL_UP = 4

# Orange bond threshold
ORANGE_BOND = 50

# Stat type → training index mapping (from support_list.json type field)
TYPE_TO_IDX = {
    "Speed": 0, "Stamina": 1, "Power": 2, "Guts": 3, "Wisdom": 4,
}
IDX_TO_TYPE = {0: "Speed", 1: "Stamina", 2: "Power", 3: "Guts", 4: "Wit"}

# Load support card type map (card_id → type string)
_SUPPORT_MAP = None


def _load_support_map():
    global _SUPPORT_MAP
    if _SUPPORT_MAP is not None:
        return _SUPPORT_MAP
    import json, os
    path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "support_list.json")
    try:
        with open(path) as f:
            raw = json.load(f)
        # string keys -> int keys
        _SUPPORT_MAP = {int(k): v["type"] for k, v in raw.items()}
    except (FileNotFoundError, json.JSONDecodeError):
        _SUPPORT_MAP = {}
    return _SUPPORT_MAP


class UraStrategy(ScenarioStrategy):
    scenario_id = 1

    def __init__(self, race_planner=None):
        self.race_planner = race_planner
        self._training_counts = {}  # command_id -> use count
        self._rejected_race_ids = set()  # program_ids that got 205 on entry
        _load_support_map()

    def reject_race(self, program_id):
        """Called by runner when race_entry fails with 205/208."""
        self._rejected_race_ids.add(int(program_id))

    # ------------------------------------------------------------------
    # next_decision — main turn loop
    # ------------------------------------------------------------------
    def next_decision(self, state, preset):
        data = state.get("data") or {}
        chara = data.get("chara_info") or {}
        home = data.get("home_info") or {}
        turn = int(chara.get("turn") or 0)
        commands = home.get("command_info_array") or []

        if turn <= 1:
            n_cmds = len(commands)
            cmd_types = set(c.get("command_type") for c in commands if c.get("command_type"))
            has_race_programs = bool(home.get("race_program_info_array"))
            print(f"[URA] turn={turn} cmds={n_cmds} types={cmd_types} race_programs={has_race_programs} "
                  f"events={bool(data.get('unchecked_event_array'))} finish={'single_mode_finish_common' in data} "
                  f"state={chara.get('state')} playing_state={chara.get('playing_state')}", flush=True)

        # Empty chara_info → career already ended server-side
        if not chara or not chara.get("turn"):
            return Decision("finish", {"current_turn": 0}, "no chara_info")

        if "single_mode_finish_common" in data:
            return Decision("finish", {"current_turn": turn}, "finished")
        if chara.get("state") == 3:
            return Decision("finish", {"current_turn": turn}, "ready to finish")

        # --- Events ---
        events = data.get("unchecked_event_array") or []
        if events:
            event = events[0]
            choice = self._choice(event)
            payload = {
                "event_id": event.get("event_id"),
                "chara_id": event.get("chara_id", 0),
                "choice_number": choice,
                "current_turn": turn,
            }
            if choice is None:
                payload = {"event_id": event.get("event_id"), "_event": event, "_current_turn": turn}
            return Decision("event", payload, "event")

        # --- Active race ---
        if data.get("race_start_info") or chara.get("playing_state") in (2, 4):
            if chara.get("playing_state") != 3:
                return Decision(
                    "race_progress",
                    {"current_turn": turn, "chara_info": chara, "race_start_info": data.get("race_start_info"), "_strategy": self},
                    "continue race",
                )

        # --- Forced target race (URA scenario) ---
        forced = self._forced_target_race(state, turn)
        if forced:
            pid = forced["program_id"]
            history_pids = {r.get("program_id") for r in (data.get("race_history") or [])}
            if pid not in history_pids and pid not in self._rejected_race_ids:
                # Don't race if vital too low — rest first, race in next window turn
                v = int(chara.get("vital", 100))
                mv = int(chara.get("max_vital", 100))
                if mv > 0 and v / mv < 0.30:
                    rest_cmd = self._find_rest(commands)
                    if rest_cmd:
                        return Decision(
                            "command",
                            {"command_type": int(rest_cmd["command_type"]),
                             "command_id": int(rest_cmd.get("command_id", 1)),
                             "command_group_id": int(rest_cmd.get("command_group_id", 0)),
                             "select_id": 0, "current_turn": turn, "current_vital": v},
                            f"rest before forced race (vital={v}/{mv})",
                        )
                return Decision(
                    "race",
                    {"program_id": forced["program_id"], "current_turn": turn, "_strategy": self},
                    f"forced race {forced.get('name', '')}",
                )

        # --- Finish check (early: before any race fallback) ---
        if data.get("is_goal", False) or chara.get("playing_state") in (3, 5):
            return Decision("finish", {"current_turn": turn}, "career finished (ps=%s)" % chara.get("playing_state"))

        if self.race_planner:
            fp = self.race_planner.forced_program(state, preset)
            if fp and fp not in {r.get("program_id") for r in (data.get("race_history") or [])}:
                return Decision(
                    "race",
                    {"program_id": fp, "current_turn": turn, "_strategy": self},
                    self.race_planner.label(fp) or f"forced {fp}",
                )

        # --- Skip self-selected races if target race is imminent ---
        # (forced_program above still runs — game forcing a race is fine)
        turns_until_target = self._turns_until_next_forced(data, turn)
        skip_optional = turns_until_target is not None and turns_until_target <= 1

        if not skip_optional:
            # --- Optional race ---
            if self.race_planner:
                pid = self.race_planner.choose(state, preset)
                history_pids = {r.get("program_id") for r in (data.get("race_history") or [])}
                if pid and pid not in history_pids:
                    return Decision(
                        "race",
                        {"program_id": pid, "current_turn": turn, "_strategy": self},
                        self.race_planner.label(pid) or f"race {pid}",
                    )

            # --- Fallback: any available race matching aptitude ---
            alt_pid = self._find_alternative_race(state, chara, turn)
            if alt_pid:
                return Decision(
                    "race",
                    {"program_id": alt_pid, "current_turn": turn, "_strategy": self},
                    f"alt race {alt_pid}",
                )

        # --- Vital/mood check ---
        vital = int(chara.get("vital", 100))
        motivation = int(chara.get("motivation", 5))
        max_vital = int(chara.get("max_vital", 100))
        vital_pct = vital / max_vital if max_vital > 0 else 1.0

        # Forced rest: <20% vital, or low mood + low vital
        force_rest = vital_pct < 0.20 or vital < 20
        if not force_rest and motivation <= 2 and vital_pct < 0.50:
            force_rest = True

        if force_rest:
            rest_cmd = self._find_rest(commands)
            if rest_cmd:
                return Decision(
                    "command",
                    {
                        "command_type": int(rest_cmd["command_type"]),
                        "command_id": int(rest_cmd.get("command_id", 1)),
                        "command_group_id": int(rest_cmd.get("command_group_id", 0)),
                        "select_id": 0,
                        "current_turn": turn,
                        "current_vital": vital,
                    },
                    f"rest (vital={vital}/{max_vital} mood={motivation})",
                )

        # --- Mood recovery (recreation/date) ---
        # Guide: date worth it if you'll have 6+ training turns after,
        # and especially valuable if mood is neutral (2-step potential).
        # Skip if close to forced races (uses those turns instead of training).
        turns_until_next_forced = self._turns_until_next_forced(data, turn)
        date_worthwhile = turns_until_next_forced is None or turns_until_next_forced >= 6

        # Guide: summer camp auto-raises mood from rest, skip date near camp
        in_camp = any(s <= turn <= e for s, e in SUMMER_CAMP_TURNS)
        pre_camp = any(turn >= s - 5 and turn < s for s, e in SUMMER_CAMP_TURNS)

        should_date = (
            motivation <= 3
            and vital_pct >= 0.60
            and date_worthwhile
            and not in_camp
            and turn <= 60
        )
        if should_date:
            rec_cmd = self._find_recreation(commands)
            if rec_cmd:
                import os
                if os.environ.get("SWEEPY_DEBUG"):
                    print(f"[recreation] found type={rec_cmd.get('command_type')} id={rec_cmd.get('command_id')} is_enable={rec_cmd.get('is_enable')}", flush=True)
                return Decision(
                    "command",
                    {
                        "command_type": int(rec_cmd["command_type"]),
                        "command_id": 0,
                        "command_group_id": int(rec_cmd.get("command_id") or rec_cmd.get("command_group_id", 301)),
                        "select_id": 0,
                        "current_turn": turn,
                        "current_vital": vital,
                    },
                    f"recreation (mood={motivation})",
                )

        # --- Training selection ---
        # Check failure rate: rest if best training is too risky
        training_cmds = [c for c in commands if c.get("command_type") == 1 and c.get("is_enable", 0) == 1]
        if training_cmds:
            min_failure = min(c.get("failure_rate", 100) for c in training_cmds)
            if min_failure >= 30:
                rest_cmd = self._find_rest(commands)
                if rest_cmd:
                    return Decision(
                        "command",
                        {
                            "command_type": int(rest_cmd["command_type"]),
                            "command_id": int(rest_cmd.get("command_id", 1)),
                            "command_group_id": int(rest_cmd.get("command_group_id", 0)),
                            "select_id": 0,
                            "current_turn": turn,
                            "current_vital": vital,
                        },
                        f"rest (failure={min_failure}%)",
                    )

        is_camp = any(s <= turn <= e for s, e in SUMMER_CAMP_TURNS)
        pre_camp = any(turn >= s - 5 and turn < s for s, e in SUMMER_CAMP_TURNS)

        best, chosen_idx = self._best_training(commands, preset, chara, turn, is_camp, pre_camp)
        if best:
            if chosen_idx is not None:
                self._training_counts[chosen_idx] = self._training_counts.get(chosen_idx, 0) + 1
            return Decision(
                "command",
                {
                    "command_type": int(best.get("command_type") or 1),
                    "command_id": int(best.get("command_id") or 601),
                    "command_group_id": int(best.get("command_group_id") or 0),
                    "select_id": 0,
                    "current_turn": turn,
                    "current_vital": vital,
                },
                best.get("_label", "train"),
            )

        # --- Fallback: any race or rest ---
        if self.race_planner:
            any_pid = self.race_planner.choose(state, preset)
            if any_pid:
                return Decision(
                    "race",
                    {"program_id": any_pid, "current_turn": turn, "_strategy": self},
                    f"fill {self.race_planner.label(any_pid) or any_pid}",
                )

        rest_cmd = self._find_rest(commands)
        if rest_cmd:
            return Decision(
                "command",
                {
                    "command_type": int(rest_cmd["command_type"]),
                    "command_id": int(rest_cmd.get("command_id", 1)),
                    "command_group_id": int(rest_cmd.get("command_group_id", 0)),
                    "current_turn": turn,
                    "current_vital": vital,
                },
                "rest (fallback)",
            )

        if not commands:
            return Decision("done", {"current_turn": turn}, "no commands available")

        return Decision("idle", {}, "no commands available")

    # ------------------------------------------------------------------
    # Event helpers
    # ------------------------------------------------------------------
    def _choice(self, event):
        """Pick event choice. Returns None if ambiguous (let user decide)."""
        choices = ((event.get("event_contents_info") or {}).get("choice_array") or [])
        if not choices:
            return 0
        if len(choices) > 1:
            # Multiple choices — pick the one with stat gains
            return self._choose_from_event(event, 0)
        return 0

    def _choose_from_event(self, event, current_turn):
        """Pick event choice that gives stat/skill gains."""
        choices = ((event.get("event_contents_info") or {}).get("choice_array") or [])
        if not choices:
            return 0
        for choice in choices:
            effects = choice.get("event_effect_array") or []
            # effect_type 1-5 = speed/stamina/power/guts/wiz, 11 = skill
            if any(e.get("effect_type") in (1, 2, 3, 4, 5, 11) for e in effects):
                return choice.get("choice_number", choice.get("select_index", 1))
        return choices[0].get("choice_number", choices[0].get("select_index", 1))

    # ------------------------------------------------------------------
    # Race planning helpers
    # ------------------------------------------------------------------
    def _forced_target_race(self, state, turn):
        """Check if a target race is imminent and available."""
        chara = (state.get("data") or {}).get("chara_info") or {}
        home = (state.get("data") or {}).get("home_info") or {}
        programs = self._program_lookup(state)

        targets = None
        for key in (
            "target_chara_race_info_array",
            "target_chara_race_info",
            "target_race_info_array",
            "target_race_info",
            "race_target_info_array",
        ):
            val = chara.get(key) or home.get(key)
            if val and isinstance(val, list):
                targets = val
                break

        if not targets:
            return None

        for t in targets:
            pid = int(t.get("program_id") or t.get("id") or 0)
            if pid == 0:
                continue
            if t.get("is_cleared", False):
                continue
            deadline = int(t.get("target_turn") or t.get("deadline_turn") or 0)
            in_window = deadline > 0 and (deadline - 1 <= turn <= deadline + 1)
            prog_avail = self._program_available(state, pid)
            if in_window or prog_avail:
                prog = programs.get(pid)
                if prog:
                    return {"program_id": pid, "name": prog.get("name", f"target {pid}")}
                if self._program_available(state, pid):
                    return {"program_id": pid, "name": f"target {pid}"}

        return None

    @staticmethod
    def _program_lookup(state):
        home = (state.get("data") or {}).get("home_info") or {}
        array = home.get("race_program_info_array") or []
        return {int(p.get("program_id", 0)): p for p in array}

    @staticmethod
    def _program_available(state, pid):
        if pid in UraStrategy._program_lookup(state):
            return True
        # Also check race_condition_array (actual entry-available races this turn)
        for item in state.get("data", {}).get("race_condition_array", []):
            if int(item.get("program_id") or 0) == pid:
                return True
        return False

    def _turns_until_next_forced(self, data, turn):
        """How many turns before the next forced target race?"""
        chara = data.get("chara_info") or {}
        home = data.get("home_info") or {}
        targets = None
        for key in (
            "target_chara_race_info_array",
            "target_chara_race_info",
            "target_race_info_array",
            "target_race_info",
            "race_target_info_array",
        ):
            val = chara.get(key) or home.get(key)
            if val and isinstance(val, list):
                targets = val
                break
        if not targets:
            return None
        nearest = None
        for t in targets:
            if t.get("is_cleared", False):
                continue
            deadline = int(t.get("target_turn") or t.get("deadline_turn") or 0)
            if deadline > 0:
                remaining = deadline - turn
                if remaining >= 0 and (nearest is None or remaining < nearest):
                    nearest = remaining
        return nearest

    def _find_alternative_race(self, state, chara, turn):
        """Scan available race programs for one the horse can enter (aptitude check).
        Used as fallback when the forced debut race gets 205."""
        programs = self._program_lookup(state)
        history_pids = {r.get("program_id") for r in ((state.get("data") or {}).get("race_history") or [])}
        candidates = []
        for pid in programs:
            if pid in history_pids or pid in self._rejected_race_ids:
                continue
            if self.race_planner and hasattr(self.race_planner, 'check_aptitude'):
                try:
                    if self.race_planner.check_aptitude(chara, pid):
                        candidates.append(pid)
                except Exception:
                    continue
            else:
                candidates.append(pid)
        if not candidates:
            return None
        # Prefer G1 (race_instance_id leading 1)
        prog_map = getattr(self.race_planner, 'program', {}) if self.race_planner else {}
        g1 = [pid for pid in candidates if str(prog_map.get(str(pid), {}).get("race_instance_id", "0"))[0] == "1"]
        if g1:
            return g1[0]
        return candidates[0]

    # ------------------------------------------------------------------
    # Bond map
    # ------------------------------------------------------------------
    def _bond_map(self, chara):
        result = {}
        for row in (chara.get("evaluation_info_array") or []):
            result[row.get("target_id", 0)] = row.get("evaluation", 0)
        return result

    # ------------------------------------------------------------------
    # Rest / recreation
    # ------------------------------------------------------------------
    @staticmethod
    def _find_rest(commands):
        for cmd in commands:
            ct = int(cmd.get("command_type") or 0)
            # URA: type 7 = rest, type 8 = medic (illness cure, not generic rest)
            if ct in (2, 7) and int(cmd.get("is_enable", 1)) == 1:
                return cmd
        return None

    @staticmethod
    def _find_recreation(commands):
        for cmd in commands:
            ct = int(cmd.get("command_type") or 0)
            if ct == 3 and int(cmd.get("is_enable", 1)) == 1:
                return cmd
        return None

    # ------------------------------------------------------------------
    # Training selection — guide-informed
    # ------------------------------------------------------------------
    def _best_training(self, commands, preset, chara, turn, is_camp, pre_camp):
        """Score trainings using URA strategy guide rules.

        Scoring (additive, not deficit-multiplied):
          1. Stat gain (primary)
          2. Training level bonus (+15%/level)
          3. Partner count (supports at training)
          4. Non-orange bond bonus (guide: +1 per non-orange)
          5. Wit bonus (no energy cost)
          6. Guts penalty (2x energy)
          7. Deck composition bonus
          8. Near level-up bonus
          9. Stat deficit (muted, only as tiebreaker)
         10. Fail chance gating (skip if gain < 2× fail%)
        """
        priority = preset.get("expect_attribute") or [600, 600, 600, 400, 400]
        bonds = self._bond_map(chara)

        # Precompute deck stat distribution
        deck_type_counts = self._deck_type_counts(chara)

        best = None
        best_score = -1.0
        best_idx = None
        scores_log = []

        for cmd in commands:
            if int(cmd.get("command_type") or 0) != 1:
                continue
            if int(cmd.get("is_enable", 1)) != 1:
                continue
            cid = int(cmd.get("command_id") or 0)
            if cid not in TRAINING_COMMANDS:
                continue

            idx = TRAINING_COMMANDS[cid][1]
            name = TRAINING_COMMANDS[cid][0]
            gain = self._training_gain(cmd)
            if is_camp:
                gain *= 5.0

            # Training level
            uses = self._training_counts.get(cid, 0)
            level = (uses // TRAINING_LEVEL_UP) + 1

            # --- Fail chance gate (guide rule) ---
            fail_pct = int(cmd.get("fail_percent") or 0)
            if fail_pct > 0 and gain < fail_pct * 2 and not is_camp:
                continue  # rest would be strictly better

            # --- Base: stat gain × level bonus ---
            score = float(gain) * (1.0 + (level - 1) * 0.15)

            # --- Partner count ---
            partners = cmd.get("training_partner_array") or []
            partner_count = len(partners)
            score += partner_count * 10

            # --- Non-orange bond bonus (guide: +1 per non-orange bonded card) ---
            partner_ids = [
                p.get("support_card_id", p) if isinstance(p, dict) else p
                for p in partners
            ]
            non_orange = sum(1 for pid in partner_ids if bonds.get(pid, 0) < ORANGE_BOND)
            score += non_orange * 8

            # --- Deck composition: prefer trainings matching your deck ---
            total_deck = sum(deck_type_counts.values()) or 1
            type_pct = deck_type_counts.get(idx, 0) / total_deck
            score += type_pct * 25  # up to +25 for primary stat

            # --- Wit bonus (0 energy) / Guts penalty (2× energy) ---
            energy_cost = TRAINING_ENERGY.get(cid, 1)
            if energy_cost == 0:
                score += 20  # Wit: free training
            elif energy_cost >= 2:
                score -= 10  # Guts: double cost

            # --- Near level-up ---
            uses_mod = uses % TRAINING_LEVEL_UP
            if uses_mod >= TRAINING_LEVEL_UP - 2:
                score += 12

            # --- Pre-camp bond building ---
            if pre_camp:
                if partners:
                    avg_bond = sum(bonds.get(pid, 0) for pid in partner_ids) / len(partner_ids)
                    score += max(0, ORANGE_BOND - avg_bond) * 0.3  # prep for camp

            # --- Stat deficit (muted) ---
            current = self._current_stat(chara, idx)
            target = priority[idx]
            flip = preset.get("deficit_flip", False)
            if flip:
                # Reward over-target stats (build strengths)
                deficit = max(0, current - target)
            else:
                # Reward under-target stats (catch up weaknesses)
                deficit = max(0, target - current)
            if deficit > 200:
                score += 20
            elif deficit > 100:
                score += 10
            # small per-point signal so very low stats still get attention
            score += deficit * 0.03

            # --- Fail penalty (score reduction for non-zero fail) ---
            if fail_pct > 0 and not is_camp:
                score -= fail_pct * 0.5

            scores_log.append((name, gain, score, level, partner_count, cid))

            if score > best_score:
                best_score = score
                cmd["_label"] = f"{name} +{gain:.0f} Lv{level}"
                best = cmd
                best_idx = cid

        # Debug log top 3
        if scores_log:
            scores_log.sort(key=lambda x: -x[2])
            top3 = " | ".join(
                f"{n}:+{g:.0f} sc={s:.1f} Lv{l} p={cnt}"
                for n, g, s, l, cnt, _ in scores_log[:3]
            )
            import os
            if os.environ.get("SWEEPY_DEBUG"):
                print(f"[URA_train] turn={turn} {top3}", flush=True)

        return best, best_idx

    def _deck_type_counts(self, chara):
        """Count support card types in the deck → training index counts."""
        card_ids = {row.get("target_id", 0) for row in (chara.get("evaluation_info_array") or [])}
        counts = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}
        smap = _SUPPORT_MAP or {}
        for cid in card_ids:
            stype = smap.get(cid, "")
            idx = TYPE_TO_IDX.get(stype)
            if idx is not None:
                counts[idx] = counts.get(idx, 0) + 1
        return counts

    # ------------------------------------------------------------------
    # Training gain / stat helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _training_gain(cmd):
        # URA commands use params_inc_dec_info_array instead of effect_array
        values = cmd.get("params_inc_dec_info_array") or cmd.get("effect_array") or []
        total = 0.0
        for e in values:
            val = int(e.get("effect_value", e.get("value", 0)))
            target = int(e.get("target_type", 0))
            # Only count stat/skill gains, not HP changes (target_type 10 = vitality)
            if target not in (10,):
                if val > 0:
                    total += val
        return total

    @staticmethod
    def _current_stat(chara, idx):
        keys = ["speed", "stamina", "power", "guts", "wiz"]
        if 0 <= idx < len(keys):
            return int(chara.get(keys[idx], 0))
        return 0
