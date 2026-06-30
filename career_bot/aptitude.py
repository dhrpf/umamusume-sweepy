"""
Aptitude prediction: combines trainee base aptitude (card_id → master data)
with parent factor stars to estimate final grade per category.

Grade values: 1=G, 2=F, 3=E, 4=D, 5=C, 6=B, 7=A, 8=S
"""
import json
from pathlib import Path
from collections import defaultdict

GRADE_MAP = {1: 'G', 2: 'F', 3: 'E', 4: 'D', 5: 'C', 6: 'B', 7: 'A', 8: 'S'}
GRADE_TO_NUM = {v: k for k, v in GRADE_MAP.items()}

# UI label per short key
APTITUDE_LABELS = {
    'turf': 'Turf', 'dirt': 'Dirt',
    'short': 'Sprint', 'mile': 'Mile', 'medium': 'Medium', 'long': 'Long',
    'front': 'Front Runner', 'pace': 'Pace Chaser', 'late': 'Late Surger', 'end': 'End Closer',
}

# Category groups for the 3-row table layout
APTITUDE_CATEGORY_ORDER = [
    ("Track", ["turf", "dirt"]),
    ("Distance", ["short", "mile", "medium", "long"]),
    ("Style", ["front", "pace", "late", "end"]),
]


def _load_chara_aptitude(data_dir=None):
    """Load base aptitude per card_id from chara_aptitude.json.
    Returns {card_id_str: {key: int_value_1_to_8}}."""
    if data_dir is None:
        data_dir = Path(__file__).resolve().parent.parent / "data"
    else:
        data_dir = Path(data_dir)
    path = data_dir / "chara_aptitude.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def predict_aptitude(parents, factor_map=None, trainee_card_id=None, data_dir=None):
    """Compute predicted aptitude per category.

    If trainee_card_id is provided and chara_aptitude.json exists:
      base + parent_stars → final value (capped at 8), plus grade letter.
    Otherwise falls back to parent-only star counts.

    Returns dict with:
        prediction - {categories: [{key, label, base, stars, final_val, grade}]}
        trainee_card_id - validated or none
        has_base - bool whether base data was available
    """
    from career_bot.master_data import _APTITUDE_GRADE_MAP
    factor_map = factor_map or {}
    chara_base = _load_chara_aptitude(data_dir) if trainee_card_id else {}
    base_vals = chara_base.get(str(trainee_card_id), {}) if trainee_card_id else {}
    has_base = bool(base_vals)

    # Sum stars per category from parents (self factors only — the horse's own factors)
    category_stars = defaultdict(int)
    for parent in parents:
        tree = parent.get("tree", {})
        # Only the parent's own factors (self) pass to the child in breeding.
        # Grandparent factors (p1/p2/gp*) are already baked into the parent.
        self_node = tree.get("self", {})
        for f in self_node.get("factors", []):
            fid = f.get("id") if isinstance(f, dict) else f
            if not fid:
                continue
            info = factor_map.get(str(fid), {})
            if info.get("category") != "aptitude":
                continue
            name = info.get("name", "")
            stars = info.get("stars", 0)
            key = _factor_name_to_key(name)
            if key:
                category_stars[key] += stars

    categories = []
    for category_group, keys in APTITUDE_CATEGORY_ORDER:
        for key in keys:
            stars = category_stars.get(key, 0)
            base = base_vals.get(key)
            label = APTITUDE_LABELS.get(key, key)
            entry = {
                "key": key,
                "label": label,
                "category_group": category_group,
                "stars": stars,
            }
            if base is not None:
                final_val = min(8, base + stars)
                entry["base"] = base
                entry["base_grade"] = _APTITUDE_GRADE_MAP.get(base, "?")
                entry["final_val"] = final_val
                entry["grade"] = _APTITUDE_GRADE_MAP.get(final_val, "?")
            else:
                entry["base"] = None
                entry["base_grade"] = None
                entry["final_val"] = None
                entry["grade"] = _grade_for_stars(stars)
            categories.append(entry)

    return {
        "prediction": {
            "categories": categories,
            "category_order": APTITUDE_CATEGORY_ORDER,
        },
        "trainee_card_id": trainee_card_id,
        "has_base": has_base,
    }


def _factor_name_to_key(name):
    """Map factor name → short aptitude key. Returns None if unrecognized."""
    if not name:
        return None
    name_lower = name.lower().replace("  ", " ").strip()
    mapping = {
        "turf": "turf", "dirt": "dirt",
        "sprint": "short", "short": "short",
        "mile": "mile",
        "medium": "medium", "middle": "medium", "long": "long",
        "front runner": "front", "pace chaser": "pace",
        "late surger": "late", "end closer": "end",
        "nige": "front", "senko": "pace", "sashi": "late", "oikomi": "end",
    }
    for k, v in mapping.items():
        if k in name_lower:
            return v
    return None


def _grade_for_stars(stars: int) -> str:
    """Heuristic grade from star count alone (fallback when no base data)."""
    if stars >= 14:
        return "S"
    if stars >= 10:
        return "A"
    if stars >= 7:
        return "B"
    if stars >= 4:
        return "C"
    if stars >= 2:
        return "D"
    if stars >= 1:
        return "E"
    return "F"
