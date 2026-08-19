"""Succession affinity (相性 / current_succession_rank_point) calculation.

The career-start API echoes back `current_succession_rank_point`, which the
real client computes locally and the server validates. It equals the gametora
"compatibility" score for the inheritance triangle:

    affinity = chara_compat + race_compat

chara_compat: gametora's relation-group algorithm over master.mdb
    succession_relation / succession_relation_member.
race_compat: shared win-saddle trophies between each parent and its own two
grandparents, PLUS between the two parents. Shared G1 trophies count +3;
non-G1 trophies count +1 against a grandparent and +3 between the two direct
parents. Triple Crown etc. are their own saddle ids.

Verified: chara 97 + race 51 = 148 (parents 1210+264, trainee 100601).
"""

import sqlite3
from functools import lru_cache


def card_to_chara_id(card_id):
    """Trained-chara card_id (e.g. 100701) -> base chara_id (1007)."""
    return int(card_id) // 100


@lru_cache(maxsize=4)
def _load_relations(mdb_path):
    """Return (points: {relation_type: point}, groups: {relation_type: frozenset(chara_id)})."""
    db = sqlite3.connect(f"file:{mdb_path}?mode=ro", uri=True)
    try:
        points = {rt: p for rt, p in db.execute(
            "SELECT relation_type, relation_point FROM succession_relation")}
        members = {}
        for rt, cid in db.execute(
                "SELECT relation_type, chara_id FROM succession_relation_member"):
            members.setdefault(rt, set()).add(cid)
    finally:
        db.close()
    groups = {rt: frozenset(s) for rt, s in members.items()}
    return points, groups


@lru_cache(maxsize=4)
def _load_g1_saddles(mdb_path):
    """Return set of win_saddle ids flagged G1 (win_saddle_type=3)."""
    db = sqlite3.connect(f"file:{mdb_path}?mode=ro", uri=True)
    try:
        return {r[0] for r in db.execute(
            "SELECT id FROM single_mode_wins_saddle WHERE win_saddle_type = 3")}
    finally:
        db.close()


def chara_compat(mdb_path, trainee, p1, p2, p1_gp, p2_gp):
    """Gametora chara compatibility. p1_gp/p2_gp are (gpA, gpB) chara_id tuples."""
    points, groups = _load_relations(mdb_path)
    z, j = p1_gp
    x, y = p2_gp
    comp = 0
    for rt, pts in points.items():
        g = groups.get(rt)
        if not g:
            continue
        if p1 in g and p2 in g:
            comp += pts
        if p1 in g and trainee in g:
            comp += pts
            if z in g and z != trainee:
                comp += pts
            if j in g and j != trainee:
                comp += pts
        if p2 in g and trainee in g:
            comp += pts
            if x in g and x != trainee:
                comp += pts
            if y in g and y != trainee:
                comp += pts
    return comp


def race_compat(p1_saddles, p1_gp_saddles, p2_saddles, p2_gp_saddles, g1_saddle_ids):
    """Shared win-saddle trophies between parents and grandparents + parent↔parent.

    Each shared G1 trophy (win_saddle_type=3) counts +3. Other shared
    trophies count +1 against a grandparent; the direct parent pair counts
    every shared trophy as +3.
    g1_saddle_ids: set of saddle ids flagged as G1 in master.mdb.
    """
    def subtotal(parent, other, *, direct_parents=False):
        shared = set(parent or []) & set(other or [])
        if direct_parents:
            return len(shared) * 3
        g1_count = len(shared & set(g1_saddle_ids or []))
        return g1_count * 3 + (len(shared) - g1_count)

    p1 = p1_saddles or []
    p2 = p2_saddles or []
    score = 0
    for gp in (p1_gp_saddles or []):
        score += subtotal(p1, gp)
    for gp in (p2_gp_saddles or []):
        score += subtotal(p2, gp)
    score += subtotal(p1, p2, direct_parents=True)
    return score


def _pair_relation_score(mdb_path, first_chara_id, second_chara_id):
    """Return the base compatibility shared by one veteran and one direct parent."""
    if not first_chara_id or not second_chara_id:
        return 0
    points, groups = _load_relations(mdb_path)
    return sum(
        int(points or 0)
        for relation_type, points in points.items()
        if first_chara_id in groups.get(relation_type, ())
        and second_chara_id in groups.get(relation_type, ())
    )


def direct_relation_score(mdb_path, first_chara_id, second_chara_id):
    """Return base relation compatibility for two base character ids."""
    return _pair_relation_score(
        mdb_path,
        int(first_chara_id or 0),
        int(second_chara_id or 0),
    )


def _shared_g1_score(first_saddles, second_saddles, g1_saddle_ids):
    """uma.moe-style veteran race affinity: +3 per shared G1, non-G1 ignored."""
    shared = set(first_saddles or []) & set(second_saddles or []) & set(g1_saddle_ids or [])
    return len(shared) * 3


def project_displayed_veteran_affinity(
    mdb_path,
    *,
    trainee_card_id,
    parent1,
    parent2,
    planned_g1_saddle_ids,
):
    """Project uma.moe-style displayed affinity for a planned trainee run.

    The completed-veteran metric stays owned by ``calculate_veteran_affinity``.
    This helper only projects the same two direct-parent contributions before
    the trainee exists: base relation plus +3 for each planned G1 shared with
    each direct parent.
    """
    trainee_chara_id = card_to_chara_id(int(trainee_card_id or 0)) if trainee_card_id else 0
    parents = (parent1 or {}, parent2 or {})
    base = 0
    parent_chara_ids = []
    for parent in parents:
        card_id = int(parent.get("card_id") or 0)
        chara_id = card_to_chara_id(card_id) if card_id else 0
        parent_chara_ids.append(chara_id)
        base += _pair_relation_score(mdb_path, trainee_chara_id, chara_id)

    saddle_gains = {}
    for saddle_id in sorted({int(value) for value in (planned_g1_saddle_ids or set()) if int(value or 0) > 0}):
        gain = 0
        for parent in parents:
            if saddle_id in set(parent.get("win_saddle_id_array") or []):
                gain += 3
        if gain:
            saddle_gains[saddle_id] = gain
    planned_race = sum(saddle_gains.values())
    return {
        "total": base + planned_race,
        "base": base,
        "planned_race": planned_race,
        "saddle_gains": saddle_gains,
        "trainee": trainee_chara_id,
        "parents": parent_chara_ids,
    }


@lru_cache(maxsize=4)
def load_g1_saddle_program_map(mdb_path):
    """Return ``{program_id: {g1_saddle_ids}}`` from master-data race links.

    Some schemas expose a direct program id on ``single_mode_wins_saddle``.
    The current game schema instead stores up to eight ``race_instance_id_N``
    values, which are resolved through ``single_mode_program.race_instance_id``.
    Unknown schemas return an empty mapping rather than inventing affinity
    evidence.
    """
    db = sqlite3.connect(f"file:{mdb_path}?mode=ro", uri=True)
    try:
        column_rows = db.execute("PRAGMA table_info(single_mode_wins_saddle)").fetchall()
        columns = [str(row[1]) for row in column_rows]
        program_column = next(
            (name for name in ("race_program_id", "program_id") if name in columns),
            "",
        )
        result = {}
        if program_column:
            rows = db.execute(
                f"SELECT id, {program_column} FROM single_mode_wins_saddle "
                "WHERE win_saddle_type = 3"
            )
            for saddle_id, program_id in rows:
                if not saddle_id or not program_id:
                    continue
                result.setdefault(int(program_id), set()).add(int(saddle_id))
            return result

        instance_columns = sorted(
            (name for name in columns if name.startswith("race_instance_id_")),
            key=lambda name: int(name.rsplit("_", 1)[-1]),
        )
        if not instance_columns:
            return {}
        try:
            program_rows = db.execute(
                "SELECT id, race_instance_id FROM single_mode_program"
            ).fetchall()
        except sqlite3.OperationalError:
            return {}
        programs_by_instance = {}
        for program_id, race_instance_id in program_rows:
            if not program_id or not race_instance_id:
                continue
            programs_by_instance.setdefault(int(race_instance_id), set()).add(int(program_id))

        selected_columns = ", ".join(instance_columns)
        rows = db.execute(
            f"SELECT id, {selected_columns} FROM single_mode_wins_saddle "
            "WHERE win_saddle_type = 3"
        )
        for row in rows:
            saddle_id = int(row[0] or 0)
            if saddle_id <= 0:
                continue
            for raw_instance_id in row[1:]:
                race_instance_id = int(raw_instance_id or 0)
                if race_instance_id <= 0:
                    continue
                for program_id in programs_by_instance.get(race_instance_id, ()):
                    result.setdefault(program_id, set()).add(saddle_id)
        return result
    finally:
        db.close()


def calculate_veteran_affinity(mdb_path, veteran):
    """Score a completed veteran against its two direct inheritance parents.

    This is the per-veteran affinity shown by uma.moe: the veteran is the main
    character, direct lineage entries at position 10 and 20 are the two sides,
    and each side contributes base character compatibility plus shared G1 wins.
    """
    main_card_id = int((veteran or {}).get("card_id") or 0)
    main_chara_id = card_to_chara_id(main_card_id) if main_card_id else 0
    main_saddles = (veteran or {}).get("win_saddle_id_array") or []
    direct_by_position = {
        int(row.get("position_id") or 0): row
        for row in ((veteran or {}).get("succession_chara_array") or [])
        if isinstance(row, dict)
    }
    g1_saddle_ids = _load_g1_saddles(mdb_path)

    def side(position_id):
        row = direct_by_position.get(position_id) or {}
        card_id = int(row.get("card_id") or 0)
        chara_id = card_to_chara_id(card_id) if card_id else 0
        base = _pair_relation_score(mdb_path, main_chara_id, chara_id)
        race = _shared_g1_score(
            main_saddles,
            row.get("win_saddle_id_array") or [],
            g1_saddle_ids,
        )
        return {
            "position_id": position_id,
            "card_id": card_id,
            "base": base,
            "race": race,
            "total": base + race,
        }

    parent_1 = side(10)
    parent_2 = side(20)
    base = parent_1["base"] + parent_2["base"]
    race = parent_1["race"] + parent_2["race"]
    return {
        "total": base + race,
        "base": base,
        "race": race,
        "parent_1": parent_1,
        "parent_2": parent_2,
    }


def _parent_tree(parent):
    """Extract (chara_id, win_saddles, gp_chara_ids[2], gp_saddles[2]) from a
    trained-chara dict (as returned by load/index / boot data).

    Grandparents are the parent's own succession_chara_array entries at
    position_id 10 (親1) and 20 (親2).
    """
    chara = card_to_chara_id(parent["card_id"])
    saddles = parent.get("win_saddle_id_array", [])
    gp_by_pos = {}
    for sc in parent.get("succession_chara_array", []):
        gp_by_pos[sc.get("position_id")] = sc
    gp = [gp_by_pos.get(10), gp_by_pos.get(20)]
    gp_chara = [card_to_chara_id(g["card_id"]) if g else 0 for g in gp]
    gp_saddles = [(g.get("win_saddle_id_array", []) if g else []) for g in gp]
    return chara, saddles, gp_chara, gp_saddles


def calculate_affinity(mdb_path, trainee_card_id, parent1, parent2):
    """Full affinity. trainee_card_id is the card being trained; parent1/parent2
    are trained-chara dicts (must include card_id, win_saddle_id_array,
    succession_chara_array). Returns dict with total + breakdown."""
    trainee = card_to_chara_id(trainee_card_id)
    p1c, p1s, p1gp, p1gps = _parent_tree(parent1)
    p2c, p2s, p2gp, p2gps = _parent_tree(parent2)
    cc = chara_compat(mdb_path, trainee, p1c, p2c, tuple(p1gp), tuple(p2gp))
    g1_ids = _load_g1_saddles(mdb_path)
    rc = race_compat(p1s, p1gps, p2s, p2gps, g1_ids)
    return {
        "total": cc + rc,
        "chara_compat": cc,
        "race_compat": rc,
        "trainee": trainee,
        "p1": p1c, "p1_gp": p1gp,
        "p2": p2c, "p2_gp": p2gp,
    }
