#!/usr/bin/env python3
"""Import uma.guide agenda planner presets into local preset format.

Usage:
  # Import from share URL
  python scripts/import_uma_guide.py --url "https://uma.guide/agenda-planner/?data=..."

  # Import from race data file (JSON list exported from uma.guide)
  python scripts/import_uma_guide.py --file races.json

  # Import a known preset by name
  python scripts/import_uma_guide.py --preset triple-crown
  python scripts/import_uma_guide.py --preset triple-tiara

  # List all known presets
  python scripts/import_uma_guide.py --list

  # Save as preset
  python scripts/import_uma_guide.py --preset triple-crown --save
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from career_bot.presets import serialize_preset, hydrate_preset, slugify

# --- uma.guide format constants ---
PREFIX = "a2|"
YEAR_MAP = {"First Year": 0, "Second Year": 1, "Third Year": 2}


def uma_turn_to_game_turn(year, month, half):
    """Convert uma.guide year/month/half (1-indexed) to game turn (1-indexed).
    
    Game has 24 turns per year (12 months x 2 halves).
    First Year = turns 1-24, Second Year = 25-48, Third Year = 49-72.
    """
    yi = YEAR_MAP[year]
    return yi * 24 + (month - 1) * 2 + half


def parse_turn_code(turn_code):
    """Parse uma.guide turn code 'MM_HH' to (month, half)."""
    m = re.match(r"(\d+)_(\d+)", turn_code)
    if not m:
        raise ValueError(f"Invalid turn code: {turn_code}")
    return int(m.group(1)), int(m.group(2))


def decode_share_url(url):
    """Decode uma.guide share URL to list of race objects.
    
    Format: a2|<base36-index>.<base36-index>...
    Each index refers to a position in the internal race catalog.
    
    We can't decode locally without the catalog, so we rely on the 
    JSON export format or manually defined presets.
    
    Returns the raw data query param.
    """
    from urllib.parse import urlparse, parse_qs
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    raw = params.get("data", [None])[0]
    if not raw:
        raise ValueError("No 'data' parameter found in URL")
    return raw


def load_race_meta():
    """Load race_map.json and build lookup by (name_lower, turn)."""
    base = Path(__file__).resolve().parent.parent
    data = json.loads((base / "data" / "race_map.json").read_text())
    meta = data.get("meta", {})
    lookup = {}
    for rid_str, info in meta.items():
        key = (info["name"].lower(), info["turn"])
        if key not in lookup:
            lookup[key] = int(rid_str)
    return lookup


def race_name_to_ids(races_data):
    """Convert list of (year, turn_code, race_name) tuples to meta race IDs.
    
    Returns list of (race_id, race_name, game_turn) for matched races,
    and a list of unmatched race names.
    """
    lookup = load_race_meta()
    ids = []
    unmatched = []
    
    for year, turn_code, race_name in races_data:
        month, half = parse_turn_code(turn_code)
        game_turn = uma_turn_to_game_turn(year, month, half)
        key = (race_name.lower(), game_turn)
        
        if key in lookup:
            ids.append(lookup[key])
        else:
            # Try matching just by name (some races may have different turn mappings)
            # Search all turns for this race name
            matched = False
            for (rname, rturn), rid in lookup.items():
                if rname == race_name.lower():
                    ids.append(rid)
                    game_turn = rturn
                    matched = True
                    break
            if not matched:
                unmatched.append(f"{year}|{turn_code}|{race_name} (turn={game_turn})")
    
    return ids, unmatched


TRACKBLAZER_DATA = {
    "Triple Crown MileMedLong": {
        "stat_bonus": 270,
        "skill_hint": "Homestretch Haste",
        "epithets": [
            "Triple Crown (Satsuki Sho, Tokyo Yushun, Kikuka Sho)",
            "Classic Triple Crown",
        ],
    },
    "Triple Tiara MileMed": {
        "stat_bonus": 210,
        "skill_hint": "Mile Straightaways",
        "epithets": ["Triple Tiara (Oka Sho, Japanese Oaks, Shuka Sho)", "Spring Queen"],
    },
    "Sprint SprintMileMed": {
        "stat_bonus": 270,
        "skill_hint": "Mile Straightaways",
        "epithets": ["Sprint King", "Mile Prince/Princess"],
    },
    "DirtTurf SprintMileMed": {
        "stat_bonus": 340,
        "skill_hint": "Mile Straightaways",
        "epithets": ["Sprint King", "Mile Prince/Princess", "Dirt King/Queen"],
    },
}


def make_preset(name, race_ids, running_style=1, skill_threshold=888):
    """Create a preset dict from race IDs."""
    preset = {
        "name": name,
        "running_style": running_style,
        "learn_skill_list": [],
        "learn_skill_blacklist": [],
        "extra_race_list": race_ids,
        "learn_skill_threshold": skill_threshold,
    }
    slug = slugify(preset["name"])
    tb = TRACKBLAZER_DATA.get(slug)
    if tb:
        preset["trackblazer"] = tb
    return preset


def save_preset(preset):
    """Save preset to disk."""
    base = Path(__file__).resolve().parent.parent
    store_path = base / "data" / "presets"
    store_path.mkdir(parents=True, exist_ok=True)
    
    serialized = serialize_preset(preset)
    path = store_path / f"{slugify(serialized['name'])}.json"
    path.write_text(json.dumps(serialized, ensure_ascii=False, indent=2))
    return path


# --- Built-in known presets ---
# These were extracted from uma.guide agenda planner

KNOWN_PRESETS = {
    "triple-crown": {
        "name": "Triple Crown (Mile/Med/Long)",
        "races": [
            ("First Year", "08_02", "Niigata Junior Stakes"),
            ("First Year", "09_01", "Sapporo Junior Stakes"),
            ("First Year", "10_01", "Saudi Arabia Royal Cup"),
            ("First Year", "10_02", "Artemis Stakes"),
            ("First Year", "11_02", "Tokyo Sports Hai Junior Stakes"),
            ("First Year", "12_01", "Hanshin Juvenile Fillies"),
            ("First Year", "12_02", "Hopeful Stakes"),
            ("Second Year", "02_01", "Kyodo News Hai"),
            ("Second Year", "03_02", "Spring Stakes"),
            ("Second Year", "04_01", "Satsuki Sho"),
            ("Second Year", "05_01", "NHK Mile Cup"),
            ("Second Year", "05_02", "Tokyo Yushun (Japanese Derby)"),
            ("Second Year", "06_02", "Takarazuka Kinen"),
            ("Second Year", "09_01", "Niigata Kinen"),
            ("Second Year", "09_02", "All Comers"),
            ("Second Year", "10_02", "Kikuka Sho"),
            ("Second Year", "11_01", "Queen Elizabeth II Cup"),
            ("Second Year", "11_02", "Mile Championship"),
            ("Second Year", "12_02", "Arima Kinen"),
            ("Third Year", "01_02", "American JCC"),
            ("Third Year", "02_01", "Kyoto Kinen"),
            ("Third Year", "03_01", "Kinko Sho"),
            ("Third Year", "03_02", "Osaka Hai"),
            ("Third Year", "04_02", "Tenno Sho (Spring)"),
            ("Third Year", "05_01", "Victoria Mile"),
            ("Third Year", "06_01", "Yasuda Kinen"),
            ("Third Year", "06_02", "Takarazuka Kinen"),
            ("Third Year", "09_01", "Niigata Kinen"),
            ("Third Year", "09_02", "All Comers"),
            ("Third Year", "10_02", "Tenno Sho (Autumn)"),
            ("Third Year", "11_01", "Queen Elizabeth II Cup"),
            ("Third Year", "11_02", "Japan Cup"),
            ("Third Year", "12_02", "Arima Kinen"),
        ],
    },
    "dirt-turf": {
        "name": "Dirt/Turf (Sprint/Mile/Med)",
        "races": [
            ("First Year", "08_02", "Niigata Junior Stakes"),
            ("First Year", "09_01", "Sapporo Junior Stakes"),
            ("First Year", "10_01", "Saudi Arabia Royal Cup"),
            ("First Year", "10_02", "Artemis Stakes"),
            ("First Year", "11_02", "Tokyo Sports Hai Junior Stakes"),
            ("First Year", "12_01", "Hanshin Juvenile Fillies"),
            ("First Year", "12_02", "Hopeful Stakes"),
            ("Second Year", "02_01", "Kyodo News Hai"),
            ("Second Year", "03_02", "Spring Stakes"),
            ("Second Year", "04_01", "Oka Sho"),
            ("Second Year", "05_01", "NHK Mile Cup"),
            ("Second Year", "05_02", "Japanese Oaks"),
            ("Second Year", "06_02", "Takarazuka Kinen"),
            ("Second Year", "07_01", "Japan Dirt Derby"),
            ("Second Year", "09_01", "Niigata Kinen"),
            ("Second Year", "09_02", "Sprinters Stakes"),
            ("Second Year", "10_02", "Shuka Sho"),
            ("Second Year", "11_01", "Queen Elizabeth II Cup"),
            ("Second Year", "11_02", "Mile Championship"),
            ("Second Year", "12_02", "Tokyo Daishoten"),
            ("Third Year", "01_02", "American JCC"),
            ("Third Year", "02_02", "February Stakes"),
            ("Third Year", "03_01", "Nakayama Umamusume Stakes"),
            ("Third Year", "03_02", "Takamatsunomiya Kinen"),
            ("Third Year", "04_02", "Fukushima Umamusume Stakes"),
            ("Third Year", "05_01", "Victoria Mile"),
            ("Third Year", "06_01", "Yasuda Kinen"),
            ("Third Year", "06_02", "Teio Sho"),
            ("Third Year", "09_01", "Niigata Kinen"),
            ("Third Year", "10_01", "Fuchu Umamusume Stakes"),
            ("Third Year", "10_02", "Tenno Sho (Autumn)"),
            ("Third Year", "11_01", "Queen Elizabeth II Cup"),
            ("Third Year", "11_02", "Japan Cup"),
            ("Third Year", "12_02", "Tokyo Daishoten"),
        ],
    },
    "sprint": {
        "name": "Sprint (Sprint/Mile/Med)",
        "races": [
            ("First Year", "08_02", "Niigata Junior Stakes"),
            ("First Year", "09_01", "Sapporo Junior Stakes"),
            ("First Year", "10_01", "Saudi Arabia Royal Cup"),
            ("First Year", "10_02", "Artemis Stakes"),
            ("First Year", "11_02", "Tokyo Sports Hai Junior Stakes"),
            ("First Year", "12_01", "Hanshin Juvenile Fillies"),
            ("First Year", "12_02", "Hopeful Stakes"),
            ("Second Year", "02_01", "Kyodo News Hai"),
            ("Second Year", "03_02", "Spring Stakes"),
            ("Second Year", "04_01", "Oka Sho"),
            ("Second Year", "05_01", "NHK Mile Cup"),
            ("Second Year", "05_02", "Japanese Oaks"),
            ("Second Year", "06_02", "Takarazuka Kinen"),
            ("Second Year", "09_01", "Niigata Kinen"),
            ("Second Year", "09_02", "Sprinters Stakes"),
            ("Second Year", "10_02", "Shuka Sho"),
            ("Second Year", "11_01", "Queen Elizabeth II Cup"),
            ("Second Year", "11_02", "Mile Championship"),
            ("Second Year", "12_02", "Hanshin Cup"),
            ("Third Year", "01_02", "American JCC"),
            ("Third Year", "02_01", "Kyoto Kinen"),
            ("Third Year", "03_01", "Nakayama Umamusume Stakes"),
            ("Third Year", "03_02", "Takamatsunomiya Kinen"),
            ("Third Year", "04_02", "Fukushima Umamusume Stakes"),
            ("Third Year", "05_01", "Victoria Mile"),
            ("Third Year", "06_01", "Yasuda Kinen"),
            ("Third Year", "06_02", "Takarazuka Kinen"),
            ("Third Year", "09_01", "Niigata Kinen"),
            ("Third Year", "10_01", "Fuchu Umamusume Stakes"),
            ("Third Year", "10_02", "Tenno Sho (Autumn)"),
            ("Third Year", "11_01", "Queen Elizabeth II Cup"),
            ("Third Year", "11_02", "Japan Cup"),
            ("Third Year", "12_02", "Hanshin Cup"),
        ],
    },
    "triple-tiara": {
        "name": "Triple Tiara (Mile/Med)",
        "races": [
            ("First Year", "08_02", "Niigata Junior Stakes"),
            ("First Year", "09_01", "Sapporo Junior Stakes"),
            ("First Year", "10_01", "Saudi Arabia Royal Cup"),
            ("First Year", "10_02", "Artemis Stakes"),
            ("First Year", "11_02", "Tokyo Sports Hai Junior Stakes"),
            ("First Year", "12_01", "Hanshin Juvenile Fillies"),
            ("First Year", "12_02", "Hopeful Stakes"),
            ("Second Year", "02_01", "Kyodo News Hai"),
            ("Second Year", "03_02", "Spring Stakes"),
            ("Second Year", "04_01", "Oka Sho"),
            ("Second Year", "05_01", "NHK Mile Cup"),
            ("Second Year", "05_02", "Japanese Oaks"),
            ("Second Year", "06_02", "Takarazuka Kinen"),
            ("Second Year", "09_01", "Niigata Kinen"),
            ("Second Year", "09_02", "All Comers"),
            ("Second Year", "10_02", "Shuka Sho"),
            ("Second Year", "11_01", "Queen Elizabeth II Cup"),
            ("Second Year", "11_02", "Mile Championship"),
            ("Third Year", "01_01", "Nikkei Shinshun Hai"),
            ("Third Year", "01_02", "American JCC"),
            ("Third Year", "02_01", "Kyoto Kinen"),
            ("Third Year", "03_01", "Nakayama Umamusume Stakes"),
            ("Third Year", "03_02", "Osaka Hai"),
            ("Third Year", "04_02", "Fukushima Umamusume Stakes"),
            ("Third Year", "05_01", "Victoria Mile"),
            ("Third Year", "06_01", "Yasuda Kinen"),
            ("Third Year", "06_02", "Takarazuka Kinen"),
            ("Third Year", "09_01", "Niigata Kinen"),
            ("Third Year", "10_01", "Fuchu Umamusume Stakes"),
            ("Third Year", "10_02", "Tenno Sho (Autumn)"),
            ("Third Year", "11_01", "Queen Elizabeth II Cup"),
            ("Third Year", "11_02", "Japan Cup"),
        ],
    },
}


def import_from_races_data(races_data, name="uma-guide-import"):
    """Import races from parsed uma.guide data."""
    ids, unmatched = race_name_to_ids(races_data)
    
    if unmatched:
        print(f"WARNING: {len(unmatched)} races could not be matched:")
        for u in unmatched:
            print(f"  {u}")
    
    if not ids:
        print("ERROR: No races could be matched!")
        return None
    
    print(f"Matched {len(ids)}/{len(races_data)} races")
    preset = make_preset(name, ids)
    return preset


def cmd_list_presets():
    """List known presets."""
    print("Known uma.guide presets:")
    for key, info in KNOWN_PRESETS.items():
        print(f"  {key}: {info['name']} ({len(info['races'])} races)")


def cmd_process_races(races_data, name, save=False):
    """Process race data and optionally save."""
    preset = import_from_races_data(races_data, name=name)
    if not preset:
        return
    
    print(f"\nRace IDs ({len(preset['extra_race_list'])}):")
    print(json.dumps(preset["extra_race_list"]))
    
    if save:
        path = save_preset(preset)
        print(f"\nSaved to {path}")
    
    return preset


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Import uma.guide presets")
    parser.add_argument("--list", action="store_true", help="List known presets")
    parser.add_argument("--preset", help="Use a known preset by name")
    parser.add_argument("--url", help="Import from uma.guide share URL")
    parser.add_argument("--file", help="Import from JSON file with race data")
    parser.add_argument("--name", help="Preset name (defaults to auto-derived)")
    parser.add_argument("--save", action="store_true", help="Save preset to disk")
    
    args = parser.parse_args()
    
    if args.list:
        cmd_list_presets()
        return
    
    if args.preset:
        key = args.preset.lower().replace(" ", "-")
        if key not in KNOWN_PRESETS:
            print(f"Unknown preset: {args.preset}")
            print(f"Known: {', '.join(KNOWN_PRESETS.keys())}")
            return
        info = KNOWN_PRESETS[key]
        name = args.name or info["name"]
        cmd_process_races(info["races"], name, save=args.save)
        return
    
    if args.url:
        raw = decode_share_url(args.url)
        print(f"Raw encoded data: {raw}")
        print("\nNOTE: Direct URL decoding requires the uma.guide race catalog.")
        print("Use --preset for known presets, or extract race data manually.")
        return
    
    if args.file:
        data = json.loads(Path(args.file).read_text())
        name = args.name or "imported"
        cmd_process_races(data, name, save=args.save)
        return
    
    parser.print_help()


if __name__ == "__main__":
    main()
