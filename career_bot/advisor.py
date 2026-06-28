from __future__ import annotations

from copy import deepcopy

from career_bot.presets import stat_profile_for_style


STAT_LABELS = ("SPD", "STA", "PWR", "GUT", "WIT")
STAT_NAME_TO_INDEX = {
    "speed": 0,
    "spd": 0,
    "stamina": 1,
    "sta": 1,
    "power": 2,
    "pwr": 2,
    "guts": 3,
    "gut": 3,
    "wit": 4,
    "wisdom": 4,
    "wiz": 4,
}
SUPPORT_TYPE_TO_INDEX = {
    "Speed": 0,
    "Stamina": 1,
    "Power": 2,
    "Guts": 3,
    "Wisdom": 4,
    "Wit": 4,
}


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _support_type(info):
    return str((info or {}).get("type") or "")


def support_type_counts(support_ids, support_lookup):
    counts = [0] * 5
    for raw_id in support_ids or []:
        sid = str(raw_id)
        info = (support_lookup or {}).get(sid) or {}
        idx = SUPPORT_TYPE_TO_INDEX.get(_support_type(info))
        if idx is not None:
            counts[idx] += 1
    return counts


def deck_archetype(counts):
    counts = list(counts or [0, 0, 0, 0, 0])[:5]
    while len(counts) < 5:
        counts.append(0)
    if counts[3] >= 3:
        return "Guts meta"
    if counts[0] >= 2 and counts[2] >= 2:
        return "Speed/Power"
    if counts[0] >= 2 and counts[4] >= 2:
        return "Speed/Wit"
    if counts[4] >= 3:
        return "Wit sustain"
    if counts[0] >= 3:
        return "Speed stack"
    top = max(range(5), key=lambda idx: counts[idx])
    if counts[top] > 0:
        return f"{STAT_LABELS[top]} focus"
    return "Unknown"


def support_cards_from_ids(support_ids, support_lookup):
    cards = []
    for raw_id in support_ids or []:
        sid = str(raw_id)
        info = (support_lookup or {}).get(sid) or {}
        cards.append({
            "id": sid,
            "name": info.get("name") or f"Unknown ({sid})",
            "rarity": info.get("rarity") or "?",
            "type": info.get("type") or "Unknown",
        })
    return cards


def _stat_factor_index(factor):
    name = str((factor or {}).get("name") or "").lower()
    if (factor or {}).get("category") != "stat" and not name:
        return None
    for key, idx in STAT_NAME_TO_INDEX.items():
        if key in name:
            return idx
    return None


def _blue_stars_by_stat(factors):
    stars = [0] * 5
    for factor in factors or []:
        idx = _stat_factor_index(factor)
        if idx is None:
            continue
        stars[idx] += max(0, min(3, _safe_int(factor.get("stars"))))
    return stars


def score_parent_candidate(candidate, trainee_card_id=0, running_style=0):
    candidate = candidate or {}
    factors = candidate.get("factors") or []
    blue = _blue_stars_by_stat(factors)
    floors = stat_profile_for_style(running_style, "min")
    priority = [idx for idx, value in enumerate(floors) if value >= 900]
    if not priority:
        priority = [0, 2]

    score = 0.0
    reasons = []
    warnings = []
    for idx in priority:
        if blue[idx] >= 3:
            score += 32
            reasons.append(f"{STAT_LABELS[idx]} {blue[idx]} blue stars")
        elif blue[idx] > 0:
            score += 8 * blue[idx]
        else:
            warnings.append(f"missing {STAT_LABELS[idx]} blue")

    total_blue = sum(blue)
    score += min(24, total_blue * 2)
    rank_score = _safe_int(candidate.get("rank_score"))
    if rank_score:
        score += min(35, rank_score / 700)
        if rank_score >= 20000:
            reasons.append("UG-tier rank score")
    wins = _safe_int(candidate.get("wins"))
    if wins:
        score += min(12, wins / 3)
    rank = _safe_int(candidate.get("rank"))
    if rank >= 19:
        score += 12
    elif rank >= 15:
        score += 6

    lineage = [_safe_int(candidate.get("card_id"))]
    lineage.extend(_safe_int(v) for v in candidate.get("parent_card_ids") or [])
    if trainee_card_id and _safe_int(trainee_card_id) in lineage[:1]:
        score -= 80
        warnings.append("direct parent is same character as trainee")

    if not reasons and total_blue:
        reasons.append(f"{total_blue} total blue stars")
    if not reasons:
        reasons.append("rank/win fallback score")

    return {
        "score": round(score, 1),
        "blue_stars": blue,
        "reasons": reasons[:4],
        "warnings": warnings[:4],
    }


def recommend_parent_pool(owned_parents, friend_veterans, trainee_card_id=0, running_style=0):
    rows = []
    for parent in owned_parents or []:
        row = dict(parent)
        row["source"] = "owned"
        row["candidate_id"] = f"owned:{parent.get('instance_id') or parent.get('trained_chara_id') or ''}"
        row["advisor"] = score_parent_candidate({
            "card_id": parent.get("card_id"),
            "rank": parent.get("rank"),
            "rank_score": parent.get("rank_score"),
            "wins": ((parent.get("tree") or {}).get("self") or {}).get("wins", {}).get("total", 0),
            "factors": ((parent.get("tree") or {}).get("self") or {}).get("factors", []),
            "parent_card_ids": [
                ((parent.get("tree") or {}).get("p1") or {}).get("card_id"),
                ((parent.get("tree") or {}).get("p2") or {}).get("card_id"),
            ],
        }, trainee_card_id, running_style)
        rows.append(row)
    for vet in friend_veterans or []:
        row = dict(vet)
        row["source"] = "rental"
        row["candidate_id"] = f"rental:{vet.get('viewer_id')}:{vet.get('trained_chara_id')}"
        row["advisor"] = score_parent_candidate(vet, trainee_card_id, running_style)
        rows.append(row)
    rows.sort(key=lambda r: (r.get("advisor") or {}).get("score", 0), reverse=True)
    return rows


def prepare_runtime_preset(preset, parent_advice=None):
    """Return a run-only preset copy tuned from selected deck/parent context."""
    out = deepcopy(preset or {})
    counts = list(out.get("_deck_type_counts") or [0, 0, 0, 0, 0])[:5]
    while len(counts) < 5:
        counts.append(0)

    running_style = _safe_int(out.get("running_style"), 0)
    floors = list(out.get("min_stats") or stat_profile_for_style(running_style, "min"))
    floors = (floors + [0] * 5)[:5]
    notes = []

    archetype = deck_archetype(counts)
    out["_deck_archetype"] = archetype

    if counts[3] >= 3:
        floors[3] = max(floors[3], 1000)
        out["train_min_total_stat_gain"] = min(_safe_int(out.get("train_min_total_stat_gain"), 40), 34)
        notes.append("guts-meta deck: raised GUT floor and relaxed training threshold")
    elif counts[0] <= 1:
        out["train_min_total_stat_gain"] = min(_safe_int(out.get("train_min_total_stat_gain"), 40), 34)
        notes.append("low speed support count: relaxed training threshold")

    for idx, count in enumerate(counts):
        if count >= 3 and idx != 3:
            floors[idx] = max(floors[idx], 1000)

    selected = parent_advice or []
    blue = [0] * 5
    warnings = []
    for advice in selected:
        advisor = (advice or {}).get("advisor") or {}
        for idx, stars in enumerate(advisor.get("blue_stars") or []):
            blue[idx] += _safe_int(stars)
        warnings.extend(advisor.get("warnings") or [])

    for idx, stars in enumerate(blue[:5]):
        if stars >= 6 and floors[idx] > 0:
            floors[idx] = max(800, floors[idx] - 100)
        elif floors[idx] >= 900 and stars <= 1:
            floors[idx] = min(1200, floors[idx] + 50)

    out["min_stats"] = floors
    out["_runtime_advisor"] = {
        "deck_type_counts": counts,
        "deck_archetype": archetype,
        "parent_warnings": list(dict.fromkeys(warnings))[:6],
        "notes": notes,
    }
    return out
