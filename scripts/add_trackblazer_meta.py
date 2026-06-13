"""Add trackblazer epithet metadata to uma.guide presets."""
import json
from pathlib import Path
from career_bot.presets import serialize_preset, slugify

trackblazer_data = {
    "Triple Crown (Mile/Med/Long)": {
        "stat_bonus": 270,
        "skill_hint": "Homestretch Haste",
        "epithets": [
            "Triple Crown (Satsuki Sho, Tokyo Yushun, Kikuka Sho)",
            "Classic Triple Crown",
        ],
    },
    "Triple Tiara (Mile/Med)": {
        "stat_bonus": 210,
        "skill_hint": "Mile Straightaways",
        "epithets": [
            "Triple Tiara (Oka Sho, Japanese Oaks, Shuka Sho)",
            "Spring Queen",
        ],
    },
    "Sprint (Sprint/Mile/Med)": {
        "stat_bonus": 270,
        "skill_hint": "Mile Straightaways",
        "epithets": [
            "Sprint King",
            "Mile Prince/Princess",
        ],
    },
    "Dirt/Turf (Sprint/Mile/Med)": {
        "stat_bonus": 340,
        "skill_hint": "Mile Straightaways",
        "epithets": [
            "Sprint King",
            "Mile Prince/Princess",
            "Dirt King/Queen",
        ],
    },
}

base_dir = Path(__file__).resolve().parent.parent
presets_dir = base_dir / "data" / "presets"

for f in presets_dir.glob("*.json"):
    p = json.loads(f.read_text(encoding="utf-8"))
    name = p.get("name", "")
    tb = trackblazer_data.get(name)
    if tb:
        p["trackblazer"] = tb
        ser = serialize_preset(p)
        f.write_text(json.dumps(ser, ensure_ascii=False, indent=2))
        print(f"  ✓ {name}: +{tb['stat_bonus']} Stats | {tb['skill_hint']}")
    else:
        # strip trackblazer from non-trackblazer presets to avoid stale data
        p.pop("trackblazer", None)
        ser = serialize_preset(p)
        f.write_text(json.dumps(ser, ensure_ascii=False, indent=2))
        print(f"  - {name}: no trackblazer data")

print("\nDone.")
