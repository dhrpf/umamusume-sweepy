"""Pure Grand Live lesson-board policy and server-state adapters."""

PERFORMANCE_NAMES = {
    1: "Dance",
    2: "Passion",
    3: "Vocal",
    4: "Visual",
    5: "Mental",
}
GREAT_SUCCESS_SONG_THRESHOLD = 3


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def offered_square_ids(live_data_set):
    rows = (live_data_set or {}).get("next_square_info_array") or []
    result = []
    for row in rows:
        if isinstance(row, dict):
            square_id = row.get("square_id", row.get("id"))
        else:
            square_id = row
        square_id = _as_int(square_id)
        if square_id > 0:
            result.append(square_id)
    return result


def _dict_performance_value(info, name):
    lower = name.lower()
    raw = info.get(lower)
    maximum = info.get(f"max_{lower}")
    if isinstance(raw, dict):
        maximum = raw.get("max_value", raw.get("max_num", maximum))
        raw = raw.get("value", raw.get("num", raw.get("amount")))
    if raw is None:
        raw = info.get(f"{lower}_num", info.get(name))
    if maximum is None:
        maximum = info.get(f"max_{lower}_num")
    return _as_int(raw), _as_int(maximum)


def performance_balances(live_data_set):
    live_data_set = live_data_set or {}
    info = live_data_set.get("live_performance_info")
    if info is None:
        info = live_data_set.get("performance_info_array")
    if info is None:
        info = live_data_set.get("performance_info")
    if info is None:
        info = live_data_set

    balances = {}
    maximums = {}
    if isinstance(info, dict):
        for perf_type, name in PERFORMANCE_NAMES.items():
            value, maximum = _dict_performance_value(info, name)
            numeric = info.get(str(perf_type), info.get(perf_type))
            if isinstance(numeric, dict):
                value = _as_int(
                    numeric.get("value", numeric.get("num", numeric.get("amount"))),
                    value,
                )
                maximum = _as_int(
                    numeric.get("max_value", numeric.get("max_num")),
                    maximum,
                )
            balances[name] = value
            maximums[name] = maximum
    elif isinstance(info, list):
        for row in info:
            if not isinstance(row, dict):
                continue
            perf_type = _as_int(
                row.get("performance_type", row.get("perf_type", row.get("id")))
            )
            name = PERFORMANCE_NAMES.get(perf_type)
            if not name:
                continue
            balances[name] = _as_int(
                row.get("value", row.get("num", row.get("amount")))
            )
            maximums[name] = _as_int(
                row.get("max_value", row.get("max_num"))
            )

    for name in PERFORMANCE_NAMES.values():
        balances.setdefault(name, 0)
        maximums.setdefault(name, 0)
    return balances, maximums


def credited_song_ids(live_data_set):
    songs = (live_data_set or {}).get("next_live_id_array") or []
    credited = set()
    for row in songs:
        if isinstance(row, dict):
            song_id = row.get("live_id", row.get("song_id", row.get("id")))
        else:
            song_id = row
        song_id = _as_int(song_id)
        if song_id > 0:
            credited.add(song_id)
    return credited


def credited_song_count(live_data_set):
    return len(credited_song_ids(live_data_set))


def _affordable(token_cost, balances):
    return all(
        balances.get(name, 0) >= _as_int(cost)
        for name, cost in (token_cost or {}).items()
    )


def select_lesson_pick(live_data_set, square_reference):
    """Return the safest deterministic affordable square, or None."""
    balances, maximums = performance_balances(live_data_set)
    candidates = []
    for square_id in offered_square_ids(live_data_set):
        row = (square_reference or {}).get(str(square_id))
        if not isinstance(row, dict):
            continue
        token_cost = row.get("token_cost")
        if not isinstance(token_cost, dict) or not _affordable(token_cost, balances):
            continue
        near_cap = bool(token_cost) and all(
            maximums.get(name, 0) > 0
            and balances.get(name, 0) / maximums[name] > 0.8
            for name in token_cost
        )
        candidates.append({
            "square_id": square_id,
            "row": row,
            "cost": sum(_as_int(value) for value in token_cost.values()),
            "near_cap_cost": near_cap,
        })

    if not candidates:
        return None

    safe = [candidate for candidate in candidates if not candidate["near_cap_cost"]]
    ranked = safe or candidates
    queued_song_ids = credited_song_ids(live_data_set)
    if len(queued_song_ids) < GREAT_SUCCESS_SONG_THRESHOLD:
        songs = [
            candidate
            for candidate in ranked
            if _as_int(candidate["row"].get("adds_song_live_id")) > 0
            and _as_int(candidate["row"].get("adds_song_live_id"))
            not in queued_song_ids
        ]
        if songs:
            ranked = songs
        else:
            skill_points = [
                candidate
                for candidate in ranked
                if candidate["row"].get("grants_sp")
            ]
            if skill_points:
                ranked = skill_points
    else:
        skill_points = [
            candidate
            for candidate in ranked
            if candidate["row"].get("grants_sp")
        ]
        if skill_points:
            ranked = skill_points

    return min(ranked, key=lambda candidate: (
        candidate["cost"],
        candidate["square_id"],
    ))
