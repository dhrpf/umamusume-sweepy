"""Pure Trackblazer policy constants shared by item / race / event logic.

These intentionally contain NO OCR or Icarus-specific engine concepts —
algorithmic part of Trackblazer policy translated onto Pre-Icarus's native
game-state payloads.
"""
# ── Shop tier tiers (lower = bought first) ──────────────────────────
TRACKBLAZER_SHOP_TIERS = {
    # Tier 1: race / training economy spine + emergency protection.
    "good_luck_charm": 1,
    "master_cleat_hammer": 1,
    "artisan_cleat_hammer": 1,
    "glow_sticks": 1,
    "royal_kale_juice": 1,
    "grilled_carrots": 1,
    "rich_hand_cream": 1,
    "miracle_cure": 1,
    # Tier 2: direct stats, scrolls / manuals, low-value notepads.
    "speed_scroll": 2,
    "stamina_scroll": 2,
    "power_scroll": 2,
    "guts_scroll": 2,
    "wit_scroll": 2,
    "speed_manual": 2,
    "stamina_manual": 2,
    "power_manual": 2,
    "guts_manual": 2,
    "wit_manual": 2,
    # Tier 3: recovery / mood stabilizers.
    "vita_65": 3,
    "vita_40": 3,
    "vita_20": 3,
    "berry_sweet_cupcake": 3,
    "plain_cupcake": 3,
    # Tier 4: training-effect items.
    "empowering_megaphone": 4,
    "motivating_megaphone": 4,
    "coaching_megaphone": 4,
    "reset_whistle": 4,
    "speed_ankle_weights": 4,
    "stamina_ankle_weights": 4,
    "power_ankle_weights": 4,
    "guts_ankle_weights": 4,
    # Tier 5: condition cures Trackblazer-critical ones above.
    "fluffy_pillow": 5,
    "pocket_planner": 5,
    "smart_scale": 5,
    "aroma_diffuser": 5,
    "practice_drills_dvd": 5,
    # Tier 6: permanent facility gains.
    "speed_training_application": 6,
    "stamina_training_application": 6,
    "power_training_application": 6,
    "guts_training_application": 6,
    "wit_training_application": 6,
}

# Grade ranking (higher = more valuable race).
GRADE_RANK = {
    "G1": 5, "G2": 4, "G3": 3, "OP": 2, "PRE-OP": 1,
    "800": 0, "900": 0, "CLIMAX": 6,
}
DEFAULT_HAMMER_COST = 35
DEFAULT_GLOW_STICK_COST = 60
DEFAULT_VITA_20_COST = 3
DEFAULT_VITA_40_COST = 6
DEFAULT_VITA_65_COST = 10
DEFAULT_ROYAL_KALE_JUICE_COST = 40
DEFAULT_BERRY_SWEET_CUPCAKE_COST = 15
DEFAULT_PLAIN_CUPCAKE_COST = 10
DEFAULT_GOOD_LUCK_CHARM_COST = 45

DEFAULT_LOW_MOOD_ITEM_GAIN_FLOOR = 15
RACE_ITEM_CONSERVATION_START_TURN = 25
TRACKBLAZER_FINALE_RACE_TURNS = (74, 76, 78)
TRACKBLAZER_FINAL_RACE_TURN = 78

# Year-end race handling (rest-exempt / energy-waste turn sets).
YEAR_END_REST_EXEMPT_TURNS = frozenset({23, 24, 47, 48, 71, 72})
YEAR_END_ENERGY_WASTE_TURNS = frozenset({24, 48, 72})

# Training-failure (irregular) threshold by year phase.
DEFAULT_IRREGULAR_TRAINING_MIN_MAIN_GAIN = 15
TRAINING_LEVEL_BOOST_THRESHOLD = 25
MAIN_STAT_THRESHOLD = {0: 20, 1: 18, 2: 16, 3: 12, 4: 8}

# Bond / friendship scoring defaults (overridable via mant_config).
REL_VALUE_ORANGE = 0.4     # bond <  60
REL_VALUE_GREEN = 0.3      # bond >= 60
REL_VALUE_BLUE = 0.15      # bond >= 80
REL_DIMINISH = 0.5
REL_EARLY_GAME = 1.3

# Training score weighting between stat / relationship / misc.
STAT_WEIGHT_WITH_BARS = 0.6
REL_WEIGHT_WITH_BARS = 0.15
MISC_WEIGHT = 0.3

# Skill-hint bonus (planned-learning boost).
SKILL_HINT_PER = 10.0
SKILL_HINT_OVERRIDE = 10000.0

# Rainbow-friendship multiplier.
RAINBOW_MULT_ENABLED = 2.0
RAINBOW_MULT_DISABLED = 1.5
ANTICIPATORY_MIN_FILL = 50.0
ANTICIPATORY_COEFF = 0.2
ANTICIPATORY_CAP = 1.0

# Per-rank level-training multiplier table.
RANK_LEVEL_BOOST_FACTOR = {
    0: 0.6, 1: 0.4, 2: 0.3, 3: 0.25, 4: 0.2,
}
PER_LEVEL_BOOST_CAP = 0.5
RAINBOW_MIN_GREEN_BARS = 4
MINIMUM_STAT_GAIN_MULTIPLIER = 0.15
RAINBOW_ATTENUATE_FLOOR = 0.25
NEAR_RAINBOW_BONUS_PER_PARTNER = 0.15
NEAR_RAINBOW_BONUS_CAP = 0.6
SUMMER_PRIORITY_BONUS_BY_RANK = (0.18, 0.10, 0.05)

# Race selection weights.
RACE_SELECTION_GRADE_WEIGHT = 100000
RACE_SELECTION_RIVAL_WEIGHT = 10000000
RACE_SELECTION_DISTANCE_WEIGHT = 10000
RACE_SELECTION_SURFACE_WEIGHT = 5000
RACE_SELECTION_APTITUDE_WEIGHT = 100

SMART_SOLVER_TRAIN_LOCK_DEFAULT = True

# Event-choice parity bonuses.
EVENT_CHAIN_UNLOCK_BONUS = 1000
EVENT_CHAIN_END_PENALTY = -300
EVENT_RANDOM_PENALTY = -10
EVENT_RANDOM_PARTIAL_BONUS = 50
EVENT_SKILL_HINT_BONUS = 25

# Grade normalization (legacy race_instance_id decoding).
CLIMAX_GRADES = {"CLIMAX", "CLIMAX_1", "CLIMAX_2", "CLIMAX_3", "CLIMAX_4"}
FINALE_STAT_BONUS_PER_RACE = 15
STAT_CAP = 1200
TRAINING_LEVEL_UP = 4


def normalize_grade(value):
    text = str(value or "").strip().upper()
    if text in GRADE_RANK:
        return text
    if text.startswith(("CLIMAX", "9")):
        return "CLIMAX"
    if text.startswith("8"):
        return "G1"
    if text.startswith("7"):
        return "G2"
    if text.startswith("6"):
        return "G3"
    return text


def is_year_end_rest_exempt(turn):
    """True on year-end wrap-up race turns (Hopeful / Arima / finale)."""
    return int(turn or 0) in YEAR_END_REST_EXEMPT_TURNS


def is_year_end_energy_waste(turn):
    """True on the *last training turn* of each year — energy banked here is
    wasted because the year wraps immediately after."""
    return int(turn or 0) in YEAR_END_ENERGY_WASTE_TURNS
