import json
import re
from pathlib import Path
MARK_WHITE_CIRCLE = "○"
MARK_DOUBLE_CIRCLE = "◎"
MARK_X = "×"
MARK_LARGE_CIRCLE = "◯"
MOJI_WHITE_CIRCLE = "â—‹"
MOJI_LARGE_CIRCLE = "â—¯"
MOJI_DOUBLE_CIRCLE = "â—Ž"
MOJI_X = "Ã—"

SKILL_LEARN_PRIORITY_LIST = [
    [
        'Corner Acceleration ○', 'Corner Adept ○', 'Slipstream', 'Tail Held High',
        'Straightaway Spurt', 'Ramp Up', 'Inside Scoop', 'Passing Pro', 'Homestretch Haste',
        'Fast-Paced', 'Outer Swell', 'Sprinting Gear', 'Slick Surge', 'Corner Recovery ○',
        'Hydrate', 'After-School Stroll', 'Clean Heart', 'Dominator', 'All-Seeing Eyes', 'Mystifying Murmur'
    ],
    [
        'Acceleration', 'Focus', 'Go with the Flow', 'I Can See Right Through You',
        'Nimble Navigator', 'Straightaway Recovery', 'Deep Breaths', 'Preferred Position',
        'Groundwork', 'Up-Tempo', 'Unyielding Spirit', 'Pressure', 'Strategist', 'Triple 7s',
        'Shake It Out', 'Intimidate', 'Stamina Eater', 'Intense Gaze', 'Speed Star',
        'Staggering Lead', 'Blinding Flash', 'Restless', 'Trackblazer', 'Meticulous Measures',
        'Keeping the Lead', 'Leader\'s Pride', 'Wait-and-See', 'A Small Breather'
    ],
    [
        'Levelheaded', 'Stop Right There!', 'Super Lucky Seven', 'Maverick ○', 'Sympathy',
        'Long Shot ○', 'Inner Post Proficiency ○', 'Outer Post Proficiency ○', 'Right-Handed ○',
        'Left-Handed ○', 'Firm Conditions ○', 'Wet Conditions ○', 'Standard Distance ○',
        'Non-Standard Distance ○', 'Competitive Spirit ○', 'Target in Sight ○', 'Lone Wolf'
    ]
]


def norm(text):
    return re.sub(r'[^a-z0-9]+', '', str(text or '').lower())


def strip_mark(text):
    if not text:
        return ""
    for m in [MARK_WHITE_CIRCLE, MARK_DOUBLE_CIRCLE, MARK_X, MARK_LARGE_CIRCLE,
              MOJI_WHITE_CIRCLE, MOJI_DOUBLE_CIRCLE, MOJI_X, MOJI_LARGE_CIRCLE]:
        text = text.replace(m, "")
    return text.strip()


class SkillBuyer:
    def __init__(self, base_dir):
        self.base_dir = Path(base_dir)
        self.skill_names = {}
        self.skill_rarities = {}
        self.skill_costs = {}
        self.skill_grade_values = {}
        self.skill_tags = {}
        self.skill_disabled_singlemode = set()
        self.skill_id_exists = set()
        self.group_to_skill_ids = {}
        self.skill_to_group_id = {}
        self.failed_this_turn = {}
        self.current_turn = None
        self.last_candidates = []
        self.last_selected = []
        self.last_attempt = []
        self.last_result = {}
        self.recover_after_error = False
        self.attempt_events = []
        self._load()

    def _load(self):
        path = self.base_dir / "data" / "skill_data.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self.skill_names = {}
            self.skill_rarities = {}
            self.skill_costs = {}
            self.skill_grade_values = {}
            self.skill_tags = {}
            self.skill_disabled_singlemode = set()
            self.skill_to_group_id = {}
            for raw_id, raw_info in data.items():
                skill_id = int(raw_id)
                if isinstance(raw_info, dict):
                    self.skill_names[skill_id] = raw_info.get("name") or str(skill_id)
                    self.skill_rarities[skill_id] = int(raw_info.get("rarity") or 0)
                    self.skill_costs[skill_id] = int(raw_info.get("need_skill_point") or 0)
                    self.skill_grade_values[skill_id] = int(raw_info.get("grade_value") or 0)
                    self.skill_tags[skill_id] = {
                        int(tag) for tag in (raw_info.get("tags") or [])
                        if int(tag or 0)
                    }
                    if int(raw_info.get("disable_singlemode") or 0):
                        self.skill_disabled_singlemode.add(skill_id)
                    group_id = int(raw_info.get("group_id") or 0)
                    if group_id:
                        self.skill_to_group_id[skill_id] = group_id
                else:
                    self.skill_names[skill_id] = raw_info
        except Exception:
            return
        self.skill_id_exists = set(self.skill_names)
        self.group_to_skill_ids = {}
        for skill_id in self.skill_names:
            group_id = self.skill_to_group_id.get(skill_id) or (skill_id if skill_id < 100000 else skill_id // 10)
            self.skill_to_group_id[skill_id] = group_id
            self.group_to_skill_ids.setdefault(group_id, []).append(skill_id)
        
        for group_id, ids in self.group_to_skill_ids.items():
            children = [sid for sid in ids if sid >= 100000]
            if children:
                self.group_to_skill_ids[group_id] = sorted(children, key=self._tier_sort_key)
            else:
                self.group_to_skill_ids[group_id] = sorted(ids, key=self._tier_sort_key)

    def _tier_sort_key(self, skill_id):
        grade_value = int(self.skill_grade_values.get(skill_id) or 0)
        return (
            int(self.skill_rarities.get(skill_id) or 99),
            1 if grade_value <= 0 else 0,
            grade_value if grade_value > 0 else 999999,
            int(skill_id),
        )

    def _tier_ids(self, group_id, rarity):
        ids = [
            sid for sid in self.group_to_skill_ids.get(group_id, [])
            if self.skill_rarities.get(sid, 0) == rarity and self.skill_grade_values.get(sid, 0) > 0
        ]
        return sorted(ids, key=self._tier_sort_key)

    def _best_owned_tier_index(self, tiers, owned_skill_ids):
        best = -1
        for index, sid in enumerate(tiers):
            if sid in owned_skill_ids:
                best = index
        return best

    def _is_red_skill(self, skill_id):
        name = self.skill_names.get(skill_id, "")
        if name.endswith(MARK_X) or name.endswith(MOJI_X):
            return True
        return int(self.skill_grade_values.get(skill_id) or 0) < 0

    def _owned_red_in_group(self, group_id, owned_skill_ids):
        return [
            sid for sid in owned_skill_ids
            if self.skill_to_group_id.get(sid) == group_id and self._is_red_skill(sid)
        ]

    def _owned_red_skills(self, owned_skill_ids):
        return [sid for sid in owned_skill_ids if self._is_red_skill(sid)]

    def _resolve_buyable_tier(self, group_id, rarity, owned_skill_ids):
        tiers = self._tier_ids(group_id, rarity)
        if not tiers:
            candidates = [
                sid for sid in self.group_to_skill_ids.get(group_id, [])
                if self.skill_rarities.get(sid, 0) == rarity and sid not in owned_skill_ids
            ]
            return sorted(candidates, key=self._tier_sort_key)[0] if candidates else 0
        # Own red × in group → no ○/◎ until red cleared via re-buy ×.
        if self._owned_red_in_group(group_id, owned_skill_ids):
            return 0
        # Only offer next tier above best owned positive skill. Own ◎ → no ○.
        next_idx = self._best_owned_tier_index(tiers, owned_skill_ids) + 1
        if next_idx < len(tiers):
            return tiers[next_idx]
        return 0

    def _unowned_white_tiers(self, group_id, owned_skill_ids):
        tiers = self._tier_ids(group_id, 1)
        if self._best_owned_tier_index(tiers, owned_skill_ids) >= 0:
            return []
        return [sid for sid in tiers if sid not in owned_skill_ids]

    def reset_scoped_failures(self):
        self.failed_this_turn = {}
        self.current_turn = None
        self.last_candidates = []
        self.last_selected = []
        self.last_attempt = []
        self.last_result = {}

    def _set_turn(self, turn):
        turn = int(turn or 0)
        if self.current_turn != turn:
            self.current_turn = turn
            self.failed_this_turn = {turn: set()}
        self.failed_this_turn.setdefault(turn, set())

    def _failed_for_turn(self, turn=None):
        turn = int(turn if turn is not None else self.current_turn or 0)
        return self.failed_this_turn.setdefault(turn, set())

    def buy(self, client, state, preset, force=False):
        data = state.get("data") or {}
        chara = data.get("chara_info") or data.get("single_mode_chara_light") or {}
        self.recover_after_error = False
        self.attempt_events = []
        if not chara:
            return state, 0

        points = int(chara.get("skill_point") or 0)
        turn = int(chara.get("turn") or 0)
        self._set_turn(turn)
        is_hoarding = points > 1500
        threshold = int(preset.get("learn_skill_threshold") or 444)
        if not force and not is_hoarding and points <= threshold:
            self.last_candidates = []
            self.last_selected = []
            self.last_attempt = []
            self.last_result = {"skip": "threshold", "points": points, "threshold": threshold}
            return state, 0

        if preset.get("manual_purchase_at_end") and not force:
            self.last_candidates = []
            self.last_selected = []
            self.last_attempt = []
            self.last_result = {"skip": "manual_purchase_at_end"}
            return state, 0

        candidates = self._candidates(chara, preset)
        if force and not candidates:
            candidates = self._candidates(chara, {**preset, "learn_skill_only_user_provided": False})

        self.last_candidates = [dict(item) for item in candidates]
        if not candidates:
            self.last_selected = []
            self.last_attempt = []
            self.last_result = {"skip": "no_candidates", "points": points}
            return state, 0

        # Clear owned × first alone — re-buy red skill_id removes debuff.
        clear_red = [c for c in candidates if c.get("clears_red")]
        pool = clear_red or candidates

        selected = []
        spent = 0
        for candidate in pool:
            cost = int(candidate.get("cost") or self._estimate_cost(candidate))
            if spent + cost > points:
                continue
            selected.append(candidate)
            spent += cost
            if candidate.get("clears_red"):
                break

        if not selected:
            self.last_selected = []
            self.last_attempt = []
            self.last_result = {"skip": "not_enough_points", "points": points}
            return state, 0

        self.last_selected = [dict(item) for item in selected]

        current_state, total_bought = self._buy_batch(client, state, selected, turn)
        return current_state, total_bought

    def preview(self, state, preset, force=False):
        data = state.get("data") or {}
        chara = data.get("chara_info") or data.get("single_mode_chara_light") or {}
        if not chara:
            self.last_candidates = []
            self.last_selected = []
            return
        turn = int(chara.get("turn") or 0)
        self._set_turn(turn)
        points = int(chara.get("skill_point") or 0)
        threshold = int(preset.get("learn_skill_threshold") or 444)
        if not force and points <= threshold:
            self.last_candidates = []
            self.last_selected = []
            return
        if preset.get("manual_purchase_at_end") and not force:
            self.last_candidates = []
            self.last_selected = []
            return
        candidates = self._candidates(chara, preset)
        selected = []
        spent = 0
        for candidate in candidates:
            cost = int(candidate.get("cost") or self._estimate_cost(candidate))
            if spent + cost > points:
                continue
            selected.append(candidate)
            spent += cost
        self.last_candidates = [dict(item) for item in candidates]
        self.last_selected = [dict(item) for item in selected]

    def _priority(self, rows):
        result = {}
        for index, row in enumerate(rows):
            for name in row:
                key = norm(name)
                result[key] = min(index, result.get(key, index))
        return result

    def _priority_value(self, skill_id, name, base_name, priority):
        values = [priority.get(str(skill_id)), priority.get(norm(name)), priority.get(norm(base_name))]
        values = [v for v in values if v is not None]
        return min(values) if values else 999

    def _priority_context(self, preset):
        raw_priority = preset.get("learn_skill_list") or []
        if not raw_priority and not preset.get("learn_skill_only_user_provided"):
            raw_priority = SKILL_LEARN_PRIORITY_LIST
        return self._priority(raw_priority)

    def _blacklist(self, preset):
        return {norm(item) for item in preset.get("learn_skill_blacklist") or []}

    @staticmethod
    def _running_style(preset):
        preset = preset or {}
        raw = preset.get("running_style")
        if raw in (None, ""):
            raw = (preset.get("unity_config") or {}).get("default_running_style")
        try:
            value = int(raw or 0)
        except (TypeError, ValueError):
            value = 0
        return value if value in (1, 2, 3, 4) else 0

    def _style_compatible(self, skill_id, preset):
        """Reject skills tied to a different running style.

        Master-data tags 101..104 map directly to running styles 1..4.
        Skills without one of those tags are style-neutral.
        """
        desired_style = self._running_style(preset)
        if not desired_style:
            return True
        style_tags = set(self.skill_tags.get(int(skill_id or 0), set())) & {101, 102, 103, 104}
        if not style_tags:
            return True
        return (100 + desired_style) in style_tags

    def _candidates(self, chara, preset):
        owned = {int(item.get("skill_id") or 0) for item in chara.get("skill_array") or []}
        owned_groups = {self.skill_to_group_id.get(skill_id, skill_id // 10) for skill_id in owned}
        priority = self._priority_context(preset)
        blacklist = self._blacklist(preset)
        tip_groups = {
            int(tip.get("group_id") or 0)
            for tip in (chara.get("skill_tips_array") or [])
            if int(tip.get("group_id") or 0)
        }
        result = []

        # Re-buy owned × to clear debuff. Must precede normal tip buys.
        for red_id in self._owned_red_skills(owned):
            group_id = self.skill_to_group_id.get(red_id) or (red_id // 10)
            if group_id not in tip_groups:
                continue
            name = self.skill_names.get(red_id, "")
            base_name = strip_mark(name)
            if norm(name) in blacklist or norm(base_name) in blacklist:
                continue
            if not self._style_compatible(red_id, preset):
                continue
            if red_id in self._failed_for_turn():
                continue
            cost = self._estimate_cost({"skill_id": red_id, "hint_level": 0, "name": name})
            result.append({
                "skill_id": red_id,
                "group_id": group_id,
                "tip_rarity": self.skill_rarities.get(red_id, 1),
                "hint_level": 0,
                "name": name,
                "priority": -1000,
                "cost": cost,
                "bundled_skill_ids": [],
                "resolution_reason": "clear_red",
                "failed_scope": None,
                "candidate_skill_ids": [red_id],
                "clears_red": True,
            })

        for tip in chara.get("skill_tips_array") or []:
            resolved = self.resolve_skill_tip(tip, owned, owned_groups, priority, blacklist, preset)
            if not resolved or resolved.get("skip_reason"):
                continue
            result.append({
                "skill_id": resolved["resolved_skill_id"],
                "group_id": resolved["group_id"],
                "tip_rarity": resolved["tip_rarity"],
                "hint_level": resolved["hint_level"],
                "name": resolved["resolved_name"],
                "priority": resolved["priority"],
                "cost": resolved["cost"],
                "bundled_skill_ids": resolved.get("bundled_skill_ids") or [],
                "resolution_reason": resolved["resolution_reason"],
                "failed_scope": resolved["failed_scope"],
                "candidate_skill_ids": resolved["candidate_skill_ids"],
                "clears_red": False,
            })
        result.sort(key=lambda item: (item["priority"], -item["hint_level"], item["cost"], item["skill_id"]))

        deduped = []
        seen = set()
        for item in result:
            if item["skill_id"] not in seen:
                seen.add(item["skill_id"])
                deduped.append(item)
        result = deduped

        if preset.get("learn_skill_only_user_provided"):
            if not any(row for row in (preset.get("learn_skill_list") or [])):
                return []
            return [item for item in result if item["priority"] < 999 or item.get("clears_red")]
        return result

    def resolve_skill_tip(self, tip, owned_skill_ids, owned_groups, priority, blacklist, preset):
        group_id = int(tip.get("group_id") or 0)
        tip_rarity = int(tip.get("rarity") or 0)
        hint_level = int(tip.get("level") or 0)
        failed = self._failed_for_turn()
        if tip_rarity:
            buyable_tier = self._resolve_buyable_tier(group_id, tip_rarity, owned_skill_ids)
            candidate_skill_ids = [buyable_tier] if buyable_tier else []
        else:
            candidate_skill_ids = [
                sid for sid in self.group_to_skill_ids.get(group_id, [])
                if sid not in owned_skill_ids
            ]
        
        row = {
            "group_id": group_id,
            "tip_rarity": tip_rarity,
            "hint_level": hint_level,
            "candidate_skill_ids": list(candidate_skill_ids),
            "resolved_skill_id": 0,
            "resolved_name": "",
            "cost": 0,
            "priority": 999,
            "resolution_reason": "",
            "master_exists": False,
            "skip_reason": None,
            "failed_scope": None,
        }
        if not candidate_skill_ids:
            tiers = self._tier_ids(group_id, tip_rarity) if tip_rarity else []
            if any(sid in owned_skill_ids for sid in tiers):
                row["skip_reason"] = "already_owned_tier"
            else:
                row["skip_reason"] = "unknown_master"
            return row

        usable = [sid for sid in candidate_skill_ids if sid not in failed]
        if not usable:
            row["skip_reason"] = "failed_this_turn"
            row["failed_scope"] = "this_turn"
            return row

        normal = [sid for sid in usable if not (self.skill_names.get(sid, "").endswith(MARK_X) or self.skill_names.get(sid, "").endswith(MOJI_X))]
        if not normal:
            row["skip_reason"] = "no_normal_skills"
            return row

        style_compatible = [sid for sid in normal if self._style_compatible(sid, preset)]
        if not style_compatible:
            row["skip_reason"] = "running_style_mismatch"
            return row
        normal = style_compatible

        normal.sort(key=self._tier_sort_key)
        resolved = normal[0]
        name = self.skill_names.get(resolved, "")
        
        best_priority = 999
        reason = "first_valid_variant"
        
        for sid in normal:
            s_name = self.skill_names.get(sid, "")
            base_name = strip_mark(s_name)
            if norm(s_name) in blacklist or norm(base_name) in blacklist:
                row["skip_reason"] = "blacklist"
                return row
            p_val = self._priority_value(sid, s_name, base_name, priority)
            if p_val < best_priority:
                best_priority = p_val
                reason = "priority_match"
                
        if best_priority == 999:
            for sid in normal:
                s_name = self.skill_names.get(sid, "")
                if any(s_name.endswith(m) for m in [MARK_WHITE_CIRCLE, MARK_LARGE_CIRCLE, MOJI_WHITE_CIRCLE, MOJI_LARGE_CIRCLE]):
                    best_priority = 500
                    reason = "circle_variant"
                    break

        if not name:
            row["skip_reason"] = "unknown_master"
            return row
            
        is_double = name.endswith(MARK_DOUBLE_CIRCLE) or name.endswith(MOJI_DOUBLE_CIRCLE)
        if preset.get("skip_double_circle_unless_high_hint", False) and is_double and hint_level < 4:
            row["skip_reason"] = "rule_rejected"
            return row

        row["resolved_skill_id"] = resolved
        row["resolved_name"] = name
        bundled_skill_ids = []
        cost = self._estimate_cost({"skill_id": resolved, "hint_level": hint_level, "name": name})
        if self.skill_rarities.get(resolved, 0) == 2:
            bundled_skill_ids = self._unowned_white_tiers(group_id, owned_skill_ids)
            for bundled_id in bundled_skill_ids:
                cost += self._estimate_cost({
                    "skill_id": bundled_id,
                    "hint_level": 0,
                    "name": self.skill_names.get(bundled_id, ""),
                })

        row["priority"] = best_priority
        row["cost"] = cost
        row["bundled_skill_ids"] = bundled_skill_ids
        row["resolution_reason"] = reason
        row["master_exists"] = resolved in self.skill_id_exists
        if resolved in failed:
            row["failed_scope"] = "this_turn"

        return row

    def _buy_batch(self, client, state, candidates, turn):
        if not candidates:
            return state, 0

        data = state.get("data") or {}
        chara = data.get("chara_info") or data.get("single_mode_chara_light") or {}
        current_turn = int(chara.get("turn") or 0)
        
        if current_turn != turn:
            self.last_result = {"skip": "stale_turn_detected", "request_current_turn": turn, "source_state_turn": current_turn}
            return state, 0

        valid_tips = set()
        for tip in chara.get("skill_tips_array") or []:
            group_id = int(tip.get("group_id") or 0)
            valid_tips.update(self.group_to_skill_ids.get(group_id, []))

        points = int(chara.get("skill_point") or 0)
        selected_total_cost = 0
        valid_candidates = []

        for item in candidates:
            skill_id = item["skill_id"]
            if skill_id <= 0 or item.get("skip_reason"):
                item["preflight_error"] = "invalid_skill"
                continue
            if skill_id not in valid_tips:
                item["preflight_error"] = "not_in_tips"
                continue
            bundled = [int(s or 0) for s in (item.get("bundled_skill_ids") or [])]
            cost = int(item.get("cost") or 0) + sum(self.skill_costs.get(sid, 0) for sid in bundled)
            if not cost:
                cost = int(item.get("cost") or 0)
            if selected_total_cost + cost > points:
                item["preflight_error"] = "unaffordable"
                continue
            item["preflight_passed"] = True
            item["total_cost"] = cost
            selected_total_cost += cost
            valid_candidates.append(item)

        if not valid_candidates:
            self.last_result = {"skip": "preflight_failed", "turn": turn, "points": points}
            return state, 0

        # ponytail: expose in SkillBuyerConfig when per-scenario tuning needed
        MAX_BATCH = 4  # >4 skills in one gain_skills call → API 217 (resource busy)
        # One gain_skills entry per candidate (main skill_id). Bundled whites prepended.
        # Chunk by candidates so total_cost stays aligned with remaining SP after each res.
        self.last_attempt = [dict(item) for item in valid_candidates]
        event = {
            "turn": turn,
            "selected": [dict(item) for item in candidates],
            "attempt": [dict(item) for item in valid_candidates],
            "payload": [],
            "result": {},
        }
        self.attempt_events.append(event)

        remaining = points
        remaining_candidates = list(valid_candidates)
        sent_payload = []
        bought_ids = set()
        failed_ids = set()
        merged = state

        while remaining_candidates:
            chunk_items = []
            chunk_cost = 0
            for item in remaining_candidates:
                cost = int(item.get("total_cost") or item.get("cost") or 0)
                if cost <= 0:
                    continue
                if chunk_cost + cost > remaining:
                    continue
                if len(chunk_items) >= MAX_BATCH:
                    break
                chunk_items.append(item)
                chunk_cost += cost
            if not chunk_items:
                break

            chunk_payload = []
            chunk_ids = set()
            for item in chunk_items:
                for skill_id in [*(item.get("bundled_skill_ids") or []), item["skill_id"]]:
                    skill_id = int(skill_id or 0)
                    if skill_id > 0 and skill_id not in chunk_ids:
                        chunk_payload.append({"skill_id": skill_id, "level": 1})
                        chunk_ids.add(skill_id)
            sent_payload.extend(chunk_payload)

            try:
                res = client.gain_skills(chunk_payload, turn)
            except Exception as exc:
                print(f"Skill Purchase Error at turn {turn}: {exc}")
                if "session fully invalidated" in str(exc) or "no uma_password_hash" in str(exc):
                    raise
                if any(code in str(exc) for code in ("201", "205", "208")):
                    self.recover_after_error = True
                failed_ids.update(int(item["skill_id"]) for item in chunk_items)
                # Permanent fail for this chunk — don't re-send same skills.
                chunk_mains = {int(item["skill_id"]) for item in chunk_items}
                remaining_candidates = [
                    item for item in remaining_candidates if int(item["skill_id"]) not in chunk_mains
                ]
                continue

            if res and isinstance(res, dict) and "data" in res:
                merged = self._merge_state(merged, res)
                chara = (merged.get("data") or {}).get("chara_info") or {}
                remaining = int(chara.get("skill_point") or max(0, remaining - chunk_cost))
            else:
                remaining = max(0, remaining - chunk_cost)

            bought_ids.update(int(item["skill_id"]) for item in chunk_items)
            chunk_mains = {int(item["skill_id"]) for item in chunk_items}
            remaining_candidates = [
                item for item in remaining_candidates if int(item["skill_id"]) not in chunk_mains
            ]

        event["payload"] = sent_payload
        bought_count = len(bought_ids)
        if bought_count > 0:
            self.last_result = {
                "result": "ok",
                "turn": turn,
                "count": bought_count,
                "payload": sent_payload,
                "remaining_sp": remaining,
            }
            event["result"] = self.last_result
            self._failed_for_turn(turn).clear()
            return merged, bought_count

        if failed_ids:
            self._failed_for_turn(turn).update(failed_ids)
            self.last_result = {
                "result": "failed",
                "turn": turn,
                "error": "all chunks failed",
                "payload": sent_payload,
            }
        else:
            self.last_result = {
                "skip": "unaffordable_after_chunk",
                "turn": turn,
                "points": remaining,
                "payload": sent_payload,
            }
        event["result"] = self.last_result
        return merged if sent_payload else state, 0

    def _merge_state(self, state, res):
        if res and isinstance(res, dict) and "data" in res:
            if not state: state = {}
            if "data" not in state: state["data"] = {}
            for k, v in res["data"].items():
                if isinstance(v, dict) and isinstance(state["data"].get(k), dict):
                    state["data"][k].update(v)
                else:
                    state["data"][k] = v
        return state


    def _select_skill_id(self, group_id, priority, owned, rarity=0):
        owned_groups = {self.skill_to_group_id.get(sid, sid // 10) for sid in owned}
        resolved = self.resolve_skill_tip({"group_id": group_id, "rarity": rarity, "level": 0}, set(owned), owned_groups, priority, set(), {})
        return int((resolved or {}).get("resolved_skill_id") or 0)

    def _estimate_cost(self, candidate):
        name = candidate.get("name") or ""
        skill_id = candidate.get("skill_id") or 0
        level = candidate.get("hint_level") or 0
        
        is_circle = any(m in name for m in [MARK_WHITE_CIRCLE, MARK_LARGE_CIRCLE, MOJI_WHITE_CIRCLE, MOJI_LARGE_CIRCLE])
        
        base = self.skill_costs.get(skill_id)
        if not base:
            if is_circle:
                base = 130
            elif skill_id >= 900000:
                base = 200
            else:
                base = 200 if self.skill_rarities.get(skill_id, 0) >= 2 else 160
        return max(1, int(base * (100 - min(level, 5) * 10) / 100))
