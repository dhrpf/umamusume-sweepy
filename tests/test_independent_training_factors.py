from career_bot.independent_training.factors import (
    choose_factor_candidate,
    normalize_factor_candidates,
)


FACTOR_MAP = {
    "2301": {"category": "aptitude", "name": "Dirt", "stars": 1},
    "2302": {"category": "aptitude", "name": "Dirt", "stars": 2},
    "301": {"category": "stat", "name": "Power", "stars": 1},
    "303": {"category": "stat", "name": "Power", "stars": 3},
}
TARGETS = [
    {"category": "pink", "name": "dirt", "minimum_stars": 2},
    {"category": "blue", "name": "power", "minimum_stars": 2},
]


def candidate(lottery_id, factor_ids):
    return {
        "lottery_id": lottery_id,
        "factor_info_array": [
            {"factor_id": value, "level": 0} for value in factor_ids
        ],
    }


def test_candidate_evaluates_only_its_own_factor_array():
    rows = normalize_factor_candidates(
        [candidate(1, [2302, 301])], FACTOR_MAP, TARGETS
    )
    assert rows[0]["matched_targets"] == 1
    assert rows[0]["capped_star_sum"] == 3
    assert rows[0]["all_targets_matched"] is False


def test_reroll_candidate_wins_when_it_satisfies_more_targets():
    rows = normalize_factor_candidates(
        [candidate(1, [2301, 301]), candidate(2, [2302, 303])],
        FACTOR_MAP,
        TARGETS,
    )
    assert rows[1]["all_targets_matched"] is True
    assert choose_factor_candidate(rows)["lottery_id"] == 2


def test_tie_keeps_original_candidate():
    rows = normalize_factor_candidates(
        [candidate(1, [2302, 301]), candidate(2, [2302, 301])],
        FACTOR_MAP,
        TARGETS,
    )
    assert choose_factor_candidate(rows)["lottery_id"] == 1
