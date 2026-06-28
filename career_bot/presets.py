import json
import re
from pathlib import Path


EXCLUDED_KEYS = {
    "facility_period_configs",
    "facility_ratios",
}

RENAMES = {
    "race_list": "extra_race_list",
    "skill_priority_list": "learn_skill_list",
    "skill_blacklist": "learn_skill_blacklist",
    "blacklistedSkills": "learn_skill_blacklist",
    "extraWeight": "extra_weight",
    "scoreValue": "score_value",
    "baseScore": "base_score",
    "statValueMultiplier": "stat_value_multiplier",
    "witSpecialMultiplier": "wit_special_multiplier",
    "cureAsapConditions": "cure_asap_conditions",
}

MANT_SCENARIO_ID = 4


def slugify(value):
    text = re.sub(r"[^a-zA-Z0-9._ -]+", "", str(value or "").strip())
    text = re.sub(r"\s+", " ", text).strip()
    return text or "preset"


def split_csv(value):
    if isinstance(value, list):
        return value
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def normalize_skill_list(value):
    rows = value if isinstance(value, list) else []
    result = []
    for row in rows:
        if isinstance(row, list):
            parts = []
            for item in row:
                parts.extend(split_csv(item))
        else:
            parts = split_csv(row)
        if parts:
            result.append(parts)
    return result


def as_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


STAT_VECTOR_LEN = 5
DEFAULT_MIN_STATS = [0, 0, 0, 0, 0]
DEFAULT_MAX_STATS = [1200, 1200, 1200, 1200, 1200]

DEFAULT_RACE_COUNT_TARGET = 36

# Per-running-style "parent breeding" stat profiles.
# Style ids: 1 = Front Runner, 2 = Pace Chaser, 3 = Late Surger, 4 = End Closer.
STYLE_STAT_PROFILES = {
    1: {"min": [1200, 1100,  600,    0,  500],
        "max": [1200, 1200, 1200, 1200, 1200]},
    2: {"min": [1200,  900, 1100,    0,  500],
        "max": [1200, 1200, 1200, 1200, 1200]},
    3: {"min": [1200,  700, 1100,    0,  600],
        "max": [1200, 1200, 1200, 1200, 1200]},
    4: {"min": [1200, 1100, 1100,    0,  500],
        "max": [1200, 1200, 1200, 1200, 1200]},
}


def stat_profile_for_style(style_id, key="min"):
    profile = STYLE_STAT_PROFILES.get(int(style_id or 0))
    if not profile:
        return list(DEFAULT_MIN_STATS if key == "min" else DEFAULT_MAX_STATS)
    return list(profile.get(key) or (DEFAULT_MIN_STATS if key == "min" else DEFAULT_MAX_STATS))


def normalize_stat_vector(value, fallback):
    base = list(fallback) if fallback else [0] * STAT_VECTOR_LEN
    if isinstance(value, dict):
        keys = ("speed", "stamina", "power", "guts", "wit")
        for idx, key in enumerate(keys):
            base[idx] = as_int(value.get(key, base[idx]), base[idx])
        return base[:STAT_VECTOR_LEN]
    if isinstance(value, list):
        for idx in range(STAT_VECTOR_LEN):
            if idx < len(value):
                base[idx] = as_int(value[idx], base[idx])
        return base[:STAT_VECTOR_LEN]
    return base[:STAT_VECTOR_LEN]


def normalize_race_list(value):
    result = []
    for item in value if isinstance(value, list) else []:
        race_id = as_int(item, None)
        if race_id is not None:
            result.append(race_id)
    return result


def normalize_team_selection(value):
    """Keep only the id fields needed to re-select a saved team on reload."""
    if not isinstance(value, dict):
        return None
    result = {}

    deck = value.get("deck")
    if isinstance(deck, dict) and deck.get("id") not in (None, ""):
        result["deck"] = {"id": deck["id"]}

    trainee = value.get("trainee")
    if isinstance(trainee, dict) and trainee.get("id") not in (None, ""):
        result["trainee"] = {"id": trainee["id"]}

    veterans = []
    for vet in value.get("veterans") or []:
        if isinstance(vet, dict) and vet.get("instance_id") not in (None, ""):
            veterans.append({"instance_id": vet["instance_id"]})
    if veterans:
        result["veterans"] = veterans

    friend = value.get("friend")
    if isinstance(friend, dict) and friend.get("viewer_id") not in (None, ""):
        result["friend"] = {
            "viewer_id": friend.get("viewer_id"),
            "support_card_id": friend.get("support_card_id"),
        }

    return result or None


def serialize_preset(raw):
    data = dict(raw or {})
    serialized = {}

    serialized["name"] = slugify(data.get("name") or "preset")
    serialized["running_style"] = as_int(data.get("running_style"), 1)
    serialized["learn_skill_list"] = normalize_skill_list(data.get("learn_skill_list"))

    blacklist = []
    blacklist.extend(split_csv(data.get("blacklistedSkills")))
    blacklist.extend(split_csv(data.get("skill_blacklist")))
    blacklist.extend(split_csv(data.get("learn_skill_blacklist")))
    serialized["learn_skill_blacklist"] = list(dict.fromkeys(blacklist))

    serialized["extra_race_list"] = normalize_race_list(data.get("extra_race_list", data.get("race_list", [])))
    serialized["learn_skill_threshold"] = as_int(data.get("learn_skill_threshold"), 888)

    if data.get("trackblazer"):
        serialized["trackblazer"] = data["trackblazer"]

    team_selection = normalize_team_selection(data.get("team_selection"))
    if team_selection:
        serialized["team_selection"] = team_selection

    # Run pacing / TP
    serialized["run_delay_min_min"] = as_int(data.get("run_delay_min_min"), 10)
    serialized["run_delay_max_min"] = as_int(data.get("run_delay_max_min"), 50)
    serialized["tp_mode"] = "wait" if str(data.get("tp_mode") or "").strip().lower() == "wait" else "carat"
    serialized["turn_delay_min_sec"] = float(data.get("turn_delay_min_sec") or 2.5)
    serialized["turn_delay_max_sec"] = float(data.get("turn_delay_max_sec") or 5.0)
    serialized["turn_delay_disabled"] = bool(data.get("turn_delay_disabled", False))

    return serialized

def hydrate_preset(raw):
    data = serialize_preset(raw)

    data["scenario_id"] = MANT_SCENARIO_ID
    data["scenario"] = MANT_SCENARIO_ID
    data["cure_asap_conditions"] = ["Migraine", "Night Owl", "Skin Outbreak", "Slacker", "Slow Metabolism", "(Practice poor isn't worth a turn to cure)"]
    data["expect_attribute"] = [9999, 9999, 9999, 9999, 9999]
    data["score_value"] = [[0.11, 0.1, 0.006, 0.09], [0.11, 0.1, 0.006, 0.09], [0.11, 0.1, 0.006, 0.09], [0.03, 0.05, 0.006, 0.09], [0, 0, 0.006, 0]]
    data["base_score"] = [0, 0, 0, 0, 0]
    data["stat_value_multiplier"] = [0.01, 0.01, 0.01, 0.01, 0.01, 0.005]
    data["extra_weight"] = [[0, 0, 0, 0, 0]] * 4
    data["npc_score_value"] = [[0.05, 0.05, 0.05], [0.05, 0.05, 0.05], [0.05, 0.05, 0.05], [0.03, 0.05, 0.05], [0, 0, 0.05]]
    data["special_training"] = [0.095, 0.095, 0.095, 0.095, 0]
    data["spirit_explosion"] = [[0.16, 0.16, 0.16, 0.06, 0.11]] * 5
    data["wit_special_multiplier"] = [1.57, 1.37]
    data["compensate_failure"] = True
    data["summer_score_threshold"] = 0.34
    data["motivation_threshold_year1"] = 3
    data["motivation_threshold_year2"] = 4
    data["motivation_threshold_year3"] = 4
    data["prioritize_recreation"] = False
    data["pal_thresholds"] = []
    data["pal_friendship_score"] = [0.08, 0.057, 0.018]
    data["pal_card_multiplier"] = 0.1
    data["rest_threshold"] = 48
    data["manual_purchase_at_end"] = False
    data["mant_config"] = {}

    return data

class PresetStore:
    def __init__(self, base_dir):
        self.base_dir = Path(base_dir)
        self.preset_dir = self.base_dir / "data" / "presets"

    def ensure(self):
        self.preset_dir.mkdir(parents=True, exist_ok=True)

    def read_all(self):
        self.ensure()
        loaded = {}
        for path in self._source_files():
            try:
                data = hydrate_preset(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                continue
            loaded[data["name"]] = data
        return sorted(loaded.values(), key=lambda item: item["name"].lower())

    def read_one(self, name):
        wanted = str(name or "").strip().lower()
        for preset in self.read_all():
            if preset["name"].lower() == wanted:
                return preset
        return None

    def write(self, preset):
        self.ensure()
        serialized_data = serialize_preset(preset)
        path = self.preset_dir / f"{slugify(serialized_data['name'])}.json"
        path.write_text(json.dumps(serialized_data, ensure_ascii=False, indent=2), encoding="utf-8")
        return hydrate_preset(serialized_data)

    def delete(self, name):
        path = self.preset_dir / f"{slugify(name)}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    def _source_files(self):
        if self.preset_dir.exists():
            return list(self.preset_dir.glob("*.json"))
        return []
