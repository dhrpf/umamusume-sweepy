"""
Import a trainer's race plan, skill plan, and stat targets from uma.moe.

uma.moe encodes everything in `/api/v3/search?search_type=inheritance&trainer_id={id}`.
For the trainer 636946328733 the request returns a single record whose `inheritance`
block contains:

  * race_results          - list of "race result ids" the trainer's career ran.
                            These map to sweepy program_ids via `id // 100`.
                            Example: 8201 -> program 82 -> "Sapporo Kinen".
  * white_sparks          - list of factor ids the trainer's career produced.
                            Decoded via sweepy's `data/factor_map.json` which
                            already labels each factor as stat/aptitude/skill/
                            race/scenario/unique. Only "skill" and "unique"
                            entries are useful for the bot's learn_skill_list.
  * blue_sparks           - combined stat-factor stars across all 3 parents.
                            Factor ids are 3-digit `<stat_id><stars_combined>`
                            where stat_id is 1=Speed, 2=Stamina, 3=Power,
                            4=Guts, 5=Wit. Example: 208 -> 8 combined stars
                            of Stamina.
  * pink_sparks           - aptitude factors (surface/distance/running style).
                            4-digit `<aptitude_id><stars>`. Running style ids
                            are 31=Front, 32=Pace, 33=Late, 34=End.
  * green_sparks          - unique skill factors (one per parent).
  * main_parent_id        - chara id of the main parent (the trainee for THIS run).
  * parent_left_id / right_id - inheritance parents (irrelevant to plan, used for context).
  * support_card / *.support_card_id - the support card the trainer publishes for borrowing.

We turn this into a "preset patch" the rest of sweepy already understands:

  {
    "extra_race_list": [...sweepy program ids...],
    "learn_skill_list": [[ ...skill names sorted by hint priority... ]],
    "running_style": 1..4,
    "trainee_card_id": <chara_id>,
    "friend_card_id": <published support id>,
    "friend_viewer_id": <trainer id>,
    "min_stats": [SPD, STA, PWR, GUT, WIT],   # default from this trainer's blue sparks
    "max_stats": [SPD, STA, PWR, GUT, WIT],   # default 1200 each (no cap)
    "imported_from_trainer_id": "636946328733",
    "imported_trainer_name": "...",
    "imported_at": ISO8601 string,
  }

The actual write/merge into a preset file is done by the caller (api endpoint).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterable

from career_bot.presets import DEFAULT_RACE_COUNT_TARGET, stat_profile_for_style

UMA_MOE_BASE = "https://uma.moe/api/v3/search"
DEFAULT_TIMEOUT = 12.0
USER_AGENT = "sweepy-uma-moe-importer/1 (+local)"

RUNNING_STYLE_CODES = {31: 1, 32: 2, 33: 3, 34: 4}
RUNNING_STYLE_NAMES = {1: "Front Runner", 2: "Pace Chaser", 3: "Late Surger", 4: "End Closer"}
STAT_ID_NAMES = {1: "Speed", 2: "Stamina", 3: "Power", 4: "Guts", 5: "Wit"}
MANDATORY_FINALS_RACE_COUNT = 3

# Practical per-stat ceiling for an Uma. The game caps stats at 1200 with bonuses,
# so we use that as the "no cap" default for max_stats. We deliberately leave room
# above the trainer's observed sparks because parents inheriting at 600+ stars
# don't expose the absolute final stat values, only star factors.
NO_CAP_STAT = 1200


def _request_uma_moe(params: dict, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Send a GET to UMA_MOE_BASE with the given params and decode JSON."""
    query = urllib.parse.urlencode(params)
    url = f"{UMA_MOE_BASE}?{query}"
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"uma.moe HTTP {exc.code}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"uma.moe request failed: {exc.reason}") from exc

    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"uma.moe returned invalid JSON: {exc}") from exc


def fetch_trainer(trainer_id: str | int, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Call uma.moe v3 search filtered by trainer id and return the raw JSON.

    Raises:
        ValueError if trainer id is not numeric.
        LookupError if uma.moe returns 0 results for this trainer.
        RuntimeError for network/protocol failures.
    """
    tid = str(trainer_id or "").strip()
    if not tid.isdigit():
        raise ValueError(f"trainer_id must be a numeric string, got {trainer_id!r}")

    data = _request_uma_moe({
        "page": "0",
        "limit": "1",
        "search_type": "inheritance",
        "trainer_id": tid,
    }, timeout=timeout)
    items = data.get("items") or []
    if not items:
        raise LookupError(f"uma.moe has no inheritance record for trainer {tid}")
    return items[0]


# uma.moe's main_parent_id is the trainee's `card_id` with talent suffix
# (e.g. Mejiro McQueen base = 101301, alt = 101302). Their own /database UI
# affinity filter does NOT filter by trainee — it scores parent affinity —
# so passing a chara directly to the API is the only way to get a feed of
# trainers who actually trained that uma.
def search_trainers(
    chara_id: int | str,
    *,
    page: int = 0,
    limit: int = 15,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Return uma.moe's top trainers whose trainee matches the given chara id.

    Raises:
        ValueError if chara_id is not numeric or limit is out of range.
        RuntimeError for network/protocol failures.
    """
    try:
        chara_int = int(str(chara_id).strip())
    except (TypeError, ValueError):
        raise ValueError(f"chara_id must be numeric, got {chara_id!r}")
    if chara_int <= 0:
        raise ValueError(f"chara_id must be positive, got {chara_id!r}")

    limit_clamped = max(1, min(int(limit or 15), 50))
    page_clamped = max(0, int(page or 0))

    return _request_uma_moe({
        "page": str(page_clamped),
        "limit": str(limit_clamped),
        "search_type": "inheritance",
        "main_parent_id": str(chara_int),
    }, timeout=timeout)


def summarize_search_result(
    record: dict,
    chara_map: dict | None = None,
    support_list: dict | None = None,
    race_map: dict | None = None,
) -> dict[str, Any]:
    """Return a compact, JSON-safe summary of a uma.moe inheritance record.

    Used by the search UI to render a result card without needing the full
    factor decode. The trainer id is returned as a string to preserve uma.moe's
    own 12-digit format (which would otherwise risk float precision loss).
    """
    inh = record.get("inheritance") or {}
    raw_main_parent = inh.get("main_parent_id") or 0
    try:
        main_parent_id = int(raw_main_parent)
    except (TypeError, ValueError):
        main_parent_id = 0
    trainee_name = ""
    if isinstance(chara_map, dict) and main_parent_id:
        trainee_name = chara_map.get(str(main_parent_id)) or ""

    blue_stars_per_stat = decode_blue_stat_stars(inh)
    running_style = decode_running_style(inh) or 0
    race_plan = decode_race_plan(inh, race_map)
    g1_win_count = 0
    for race in race_plan:
        try:
            program_id = int(race.get("program_id") or 0)
        except (TypeError, ValueError):
            program_id = 0
        info = {}
        if isinstance(race_map, dict):
            info = (race_map.get("program") or {}).get(str(program_id), {})
        race_instance_id = str(info.get("race_instance_id") or "")
        if race_instance_id.startswith("1"):
            g1_win_count += 1

    support = record.get("support_card") or {}
    support_card_id = 0
    try:
        support_card_id = int(support.get("support_card_id") or 0)
    except (TypeError, ValueError):
        support_card_id = 0
    support_info = {}
    if isinstance(support_list, dict) and support_card_id:
        support_info = support_list.get(str(support_card_id)) or {}

    return {
        "trainer_id": str(record.get("account_id") or "").strip(),
        "trainer_name": str(record.get("trainer_name") or "").strip(),
        "follower_num": int(record.get("follower_num") or 0),
        "last_updated": str(record.get("last_updated") or ""),
        "inheritance_id": int(inh.get("inheritance_id") or 0),
        "main_parent_id": main_parent_id,
        "trainee_name": trainee_name,
        "parent_left_id": int(inh.get("parent_left_id") or 0),
        "parent_right_id": int(inh.get("parent_right_id") or 0),
        "parent_rank": int(inh.get("parent_rank") or 0),
        "score": int(inh.get("parent_rank") or inh.get("score") or 0),
        "parent_rarity": int(inh.get("parent_rarity") or 0),
        "affinity_score": int(inh.get("affinity_score") or 0),
        "win_count": int(inh.get("win_count") or 0),
        "g1_win_count": g1_win_count,
        "race_count": len(race_plan),
        "blue_stars_per_stat": blue_stars_per_stat,
        "blue_stars_sum": int(inh.get("blue_stars_sum") or sum(blue_stars_per_stat)),
        "pink_stars_sum": int(inh.get("pink_stars_sum") or 0),
        "white_stars_sum": int(inh.get("white_stars_sum") or 0),
        "running_style": running_style,
        "running_style_name": RUNNING_STYLE_NAMES.get(running_style, ""),
        "support_card_id": support_card_id,
        "support_card_name": support_info.get("name") or (f"Unknown ({support_card_id})" if support_card_id else ""),
        "support_card_type": support_info.get("type") or "",
        "support_card_rarity": support_info.get("rarity") or "",
        "support_limit_break_count": int(support.get("limit_break_count") or 0),
    }


def _factor_lookup(factor_map: dict | None) -> dict[int, dict[str, Any]]:
    """Build a {factor_id_int: {name, stars, category}} lookup."""
    out: dict[int, dict[str, Any]] = {}
    if not isinstance(factor_map, dict):
        return out
    for key, val in factor_map.items():
        try:
            fid = int(str(key).strip())
        except (TypeError, ValueError):
            continue
        if not isinstance(val, dict):
            continue
        out[fid] = {
            "name": str(val.get("name") or "").strip(),
            "stars": int(val.get("stars") or 0),
            "category": str(val.get("category") or ""),
        }
    return out


def _stat_index_for(factor_id: int) -> int | None:
    """Return 0..4 stat index for a blue/main_blue factor id, else None.

    Blue stat factors are 3-digit `<stat_id><stars>` where the leading digit
    is the stat id (1=Speed, 2=Stamina, 3=Power, 4=Guts, 5=Wit) and the
    trailing two digits are the star count. For individual parents stars
    are 1..3; in the combined blue_sparks list they can be summed up to 9.
    Examples: 101=Speed 1*, 202=Stamina 2*, 208=Stamina 8*.
    """
    if factor_id <= 0:
        return None
    base = factor_id // 100
    if base in (1, 2, 3, 4, 5):
        return base - 1
    return None


def decode_blue_stat_stars(inh: dict, key: str = "blue_sparks") -> list[int]:
    """Return summed star counts per stat slot [SPD, STA, PWR, GUT, WIT]."""
    out = [0, 0, 0, 0, 0]
    for fid in inh.get(key) or []:
        fid_int = int(fid or 0)
        idx = _stat_index_for(fid_int)
        if idx is None:
            continue
        stars = fid_int % 100
        out[idx] = max(out[idx], stars)
    return out


def decode_running_style(inh: dict) -> int | None:
    """Infer running style (1..4) from pink_sparks; return None if unclear.

    Pink aptitude factors are 4-digit `<aptitude_id><stars>` where the
    base code follows the master_data scheme: 31=Front, 32=Pace, 33=Late,
    34=End. We pick the strategy aptitude factor with the highest star count.
    """
    best = (0, None)
    for fid in inh.get("pink_sparks") or []:
        fid_int = int(fid or 0)
        base = fid_int // 100
        if base in RUNNING_STYLE_CODES:
            stars = fid_int % 100
            if stars > best[0]:
                best = (stars, RUNNING_STYLE_CODES[base])
    return best[1]


def decode_race_plan(inh: dict, race_map: dict | None = None) -> list[dict[str, Any]]:
    """Translate uma.moe race_results into sweepy program ids + display info.

    Each entry: {"program_id": int, "name": str, "month": int|None,
                 "half": int|None, "uma_moe_id": int, "known": bool}.
    Unknown entries (no match in race_map.program) are still returned with
    known=False so the UI can warn the user.
    """
    program_map = {}
    if isinstance(race_map, dict):
        raw_program = race_map.get("program") or {}
        for key, val in raw_program.items():
            try:
                pid = int(key)
            except (TypeError, ValueError):
                continue
            if isinstance(val, dict):
                program_map[pid] = val

    plan: list[dict[str, Any]] = []
    for raw in inh.get("race_results") or []:
        try:
            rid = int(raw)
        except (TypeError, ValueError):
            continue
        if rid <= 0:
            continue
        pid = rid // 100
        info = program_map.get(pid) or {}
        plan.append({
            "uma_moe_id": rid,
            "program_id": pid,
            "name": str(info.get("name") or ""),
            "month": info.get("month"),
            "half": info.get("half"),
            "ground": info.get("ground"),
            "distance": info.get("distance"),
            "known": bool(info),
        })
    return plan


def _race_grade_rank(entry: dict[str, Any], race_map: dict | None = None) -> int:
    program_id = int(entry.get("program_id") or 0)
    info = {}
    if isinstance(race_map, dict):
        info = (race_map.get("program") or {}).get(str(program_id), {})
    race_instance_id = str(info.get("race_instance_id") or "")
    if race_instance_id.startswith("1"):
        return 3
    if race_instance_id.startswith("2"):
        return 2
    if race_instance_id.startswith("3"):
        return 1
    return 0


def prune_race_plan_for_ug(
    plan: list[dict[str, Any]],
    race_map: dict | None = None,
    target_total_races: int = DEFAULT_RACE_COUNT_TARGET,
) -> list[dict[str, Any]]:
    """Keep the donor route shape but cap imported races for practical UG runs.

    uma.moe donor records often include every race from a whale/luck route. Sweepy
    then also runs the three mandatory Twinkle Star finals, so importing 39
    donor races becomes a 42-race career and starves training. Keep all G1s first,
    then G2/G3 by chronological donor order until the pre-finals budget is full.
    """
    known = [entry for entry in plan if entry.get("known")]
    target_pre_finals = max(30, int(target_total_races or DEFAULT_RACE_COUNT_TARGET) - MANDATORY_FINALS_RACE_COUNT)
    if len(known) <= target_pre_finals:
        return known

    indexed = list(enumerate(known))
    selected = []
    for _, entry in indexed:
        if _race_grade_rank(entry, race_map) >= 3:
            selected.append(entry)

    selected_ids = {id(entry) for entry in selected}
    remaining = [
        (idx, entry)
        for idx, entry in indexed
        if id(entry) not in selected_ids
    ]
    remaining.sort(key=lambda row: (-_race_grade_rank(row[1], race_map), row[0]))
    for _, entry in remaining:
        if len(selected) >= target_pre_finals:
            break
        selected.append(entry)

    selected_id_set = {id(entry) for entry in selected}
    return [entry for entry in known if id(entry) in selected_id_set]


SKILL_CATEGORIES_FOR_LEARN_LIST = {"skill", "unique"}


def decode_learned_factors(
    inh: dict,
    factor_map: dict | None,
    keys: Iterable[str] = ("white_sparks", "green_sparks"),
) -> list[dict[str, Any]]:
    """Return [{factor_id, stars, name, category}] for the given spark lists.

    Entries with no matching name in factor_map are still returned (with name
    == "" and category == "") so the UI can warn. Each factor is included only
    once even if it appears in multiple parents.
    """
    lookup = _factor_lookup(factor_map)
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for spark_key in keys:
        for fid_raw in inh.get(spark_key) or []:
            try:
                fid = int(fid_raw)
            except (TypeError, ValueError):
                continue
            if fid <= 0 or fid in seen:
                continue
            seen.add(fid)
            info = lookup.get(fid) or {}
            out.append({
                "factor_id": fid,
                "stars": info.get("stars", fid % 10),
                "name": info.get("name", ""),
                "category": info.get("category", ""),
                "source": spark_key,
            })
    return out


def decode_published_support(record: dict, support_list: dict | None = None) -> dict[str, Any] | None:
    """Pluck out the publicly shared support card from a uma.moe record."""
    sc = record.get("support_card") or {}
    sid_raw = sc.get("support_card_id")
    if not sid_raw:
        return None
    try:
        sid = int(sid_raw)
    except (TypeError, ValueError):
        return None
    info = {}
    if isinstance(support_list, dict):
        info = support_list.get(str(sid)) or {}
    return {
        "support_card_id": sid,
        "name": info.get("name") or f"Unknown ({sid})",
        "type": info.get("type") or "Unknown",
        "rarity": info.get("rarity") or "?",
        "limit_break_count": int(sc.get("limit_break_count") or 0),
        "experience": int(sc.get("experience") or 0),
    }


def decode_trainee(record: dict, chara_map: dict | None = None) -> dict[str, Any]:
    """Identify the trainee (uma being raised) from the main_parent_id field."""
    inh = record.get("inheritance") or {}
    raw_id = inh.get("main_parent_id") or 0
    try:
        cid = int(raw_id)
    except (TypeError, ValueError):
        cid = 0
    name = ""
    if isinstance(chara_map, dict) and cid:
        name = chara_map.get(str(cid)) or ""
    return {"card_id": cid, "name": name or (f"Unknown ({cid})" if cid else "")}


def build_preset_patch(
    record: dict,
    factor_map: dict | None = None,
    race_map: dict | None = None,
    chara_map: dict | None = None,
    support_list: dict | None = None,
) -> dict[str, Any]:
    """Produce a dict suitable for merging into an existing sweepy preset."""
    inh = record.get("inheritance") or {}
    trainer_id = str(record.get("account_id") or "").strip()
    trainer_name = str(record.get("trainer_name") or "").strip()

    plan = decode_race_plan(inh, race_map)
    selected_plan = prune_race_plan_for_ug(plan, race_map)
    factors = decode_learned_factors(inh, factor_map or {})
    blue_stars = decode_blue_stat_stars(inh)
    running_style = decode_running_style(inh) or 1
    trainee = decode_trainee(record, chara_map)
    support = decode_published_support(record, support_list)

    skill_names: list[str] = []
    seen_names: set[str] = set()
    for entry in factors:
        if entry.get("category") not in SKILL_CATEGORIES_FOR_LEARN_LIST:
            continue
        name = entry.get("name") or ""
        if not name or name in seen_names:
            continue
        seen_names.add(name)
        skill_names.append(name)

    inheritance_id = int(inh.get("inheritance_id") or 0)
    main_parent_card_id = int(inh.get("main_parent_id") or 0)

    return {
        "imported_from_trainer_id": trainer_id,
        "imported_trainer_name": trainer_name,
        "imported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "running_style": running_style,
        "running_style_name": RUNNING_STYLE_NAMES.get(running_style, ""),
        "trainee_card_id": trainee["card_id"],
        "trainee_name": trainee["name"],
        "friend_viewer_id": int(trainer_id) if trainer_id.isdigit() else 0,
        "friend_card_id": (support or {}).get("support_card_id", 0),
        "friend_support": support,
        # Rental parent prefill:
        #   * rental_chara_viewer_id is a best-effort guess that uma.moe's
        #     trainer_id matches the game's viewer_id. The /api/career/friends
        #     veteran picker confirms/overrides it.
        #   * rental_chara_id must be the GAME's trained_chara_id and is NOT
        #     equivalent to uma.moe's inheritance_id, so we leave it at 0 here
        #     and let the friend-veteran picker fill it in from live game data.
        #   * rental_chara_card_id / inheritance_id are kept as informational
        #     hints so the UI can highlight the matching veteran when present.
        "rental_chara_viewer_id": int(trainer_id) if trainer_id.isdigit() else 0,
        "rental_chara_id": 0,
        "rental_chara_card_id": main_parent_card_id,
        "uma_moe_inheritance_id": inheritance_id,
        "extra_race_list": [entry["program_id"] for entry in selected_plan],
        "extra_race_preview": selected_plan,
        "extra_race_original_count": len([entry for entry in plan if entry["known"]]),
        "extra_race_pruned_count": max(0, len([entry for entry in plan if entry["known"]]) - len(selected_plan)),
        "extra_race_unmatched_count": len([entry for entry in plan if not entry["known"]]),
        "learn_skill_list": [skill_names] if skill_names else [],
        "learn_skill_preview": factors,
        # Reference info, used by the UI to seed defaults
        "blue_stars_per_stat": blue_stars,
        "blue_stars_total": int(inh.get("blue_stars_sum") or sum(blue_stars)),
        "pink_stars_total": int(inh.get("pink_stars_sum") or 0),
        "white_stars_total": int(inh.get("white_stars_sum") or 0),
        "win_count": int(inh.get("win_count") or 0),
        # min_stats / max_stats default to the per-style breeding profile so
        # a fresh import is immediately useful. Users can override these from
        # the UI; the merge step preserves any existing user values.
        "min_stats_default": stat_profile_for_style(running_style, "min"),
        "max_stats_default": stat_profile_for_style(running_style, "max"),
    }


def merge_into_preset(existing: dict, patch: dict, *, overwrite_skills: bool = True,
                      overwrite_races: bool = True, overwrite_stats: bool = False) -> dict:
    """Return a copy of `existing` with the imported patch applied.

    Skill list and race list overwrite by default since uma.moe IS the source
    of truth being imported. The blacklist is preserved untouched.

    min_stats / max_stats behaviour:
      * If the existing preset has no stat targets, we seed them from the patch's
        style-aware defaults.
      * If the imported running_style differs from the existing one, the user's
        old stat targets are stale (they were tuned for a different style), so
        we re-seed from the new style profile.
      * Otherwise the user's hand-tuned targets are preserved.
      * Pass overwrite_stats=True to force re-seeding regardless.
    """
    out = dict(existing or {})

    if overwrite_races and patch.get("extra_race_list") is not None:
        out["extra_race_list"] = list(patch["extra_race_list"])
    if overwrite_skills and patch.get("learn_skill_list") is not None:
        out["learn_skill_list"] = [list(tier) for tier in patch["learn_skill_list"]]

    prior_style = int(out.get("running_style") or 0)
    patch_style = int(patch.get("running_style") or 0)

    for key in (
        "running_style",
        "trainee_card_id",
        "friend_viewer_id",
        "friend_card_id",
        "rental_chara_viewer_id",
        "rental_chara_id",
        "rental_chara_card_id",
        "uma_moe_inheritance_id",
        "imported_from_trainer_id",
        "imported_trainer_name",
        "imported_at",
    ):
        if key in patch and patch[key]:
            out[key] = patch[key]

    style_changed = patch_style and prior_style and patch_style != prior_style
    no_prior_stats = not (out.get("min_stats") or out.get("max_stats"))

    if overwrite_stats or style_changed or no_prior_stats:
        if patch.get("min_stats_default") is not None:
            out["min_stats"] = list(patch["min_stats_default"])
        if patch.get("max_stats_default") is not None:
            out["max_stats"] = list(patch["max_stats_default"])

    return out
