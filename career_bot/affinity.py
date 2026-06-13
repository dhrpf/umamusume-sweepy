"""Succession affinity (相性 / current_succession_rank_point) calculation.

The career-start API echoes back `current_succession_rank_point`, which the
real client computes locally and the server validates. It equals the gametora
"compatibility" score for the inheritance triangle:

    affinity = chara_compat + race_compat

chara_compat: gametora's relation-group algorithm over master.mdb
    succession_relation / succession_relation_member.
race_compat: shared win-saddle trophies between each parent and its own two
    grandparents (combo trophies like Triple Crown are their own saddle ids,
    so each counts +1). The trainee is fresh (no wins) so contributes 0;
    parent<->parent shared wins do NOT count.

Verified against a live client capture: chara 113 + race 46 = 159.
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


def race_compat(p1_saddles, p1_gp_saddles, p2_saddles, p2_gp_saddles):
    """Shared win-saddle trophies between each parent and its own two grandparents.

    p1_gp_saddles / p2_gp_saddles are 2-element lists of win_saddle_id_array
    (one per grandparent). Each shared trophy id counts +1.
    """
    p1 = set(p1_saddles or [])
    p2 = set(p2_saddles or [])
    score = 0
    for gp in (p1_gp_saddles or []):
        score += len(p1 & set(gp or []))
    for gp in (p2_gp_saddles or []):
        score += len(p2 & set(gp or []))
    return score


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
    rc = race_compat(p1s, p1gps, p2s, p2gps)
    return {
        "total": cc + rc,
        "chara_compat": cc,
        "race_compat": rc,
        "trainee": trainee,
        "p1": p1c, "p1_gp": p1gp,
        "p2": p2c, "p2_gp": p2gp,
    }
