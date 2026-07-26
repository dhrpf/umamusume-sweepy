import copy

from career_bot.grand_live import select_lesson_pick


def _reference():
    return {
        "40000": {
            "square_type": 4,
            "name": "Song",
            "reward": "Training Skill Pt Gain +2",
            "grants_sp": True,
            "token_cost": {"Passion": 21, "Visual": 21},
            "adds_song_live_id": 1032,
        },
        "11006": {
            "square_type": 1,
            "name": "SP",
            "reward": "Skill Pts +5",
            "grants_sp": True,
            "token_cost": {"Dance": 10},
            "adds_song_live_id": None,
        },
        "11001": {
            "square_type": 1,
            "name": "Speed",
            "reward": "Speed +5",
            "grants_sp": False,
            "token_cost": {"Dance": 10},
            "adds_song_live_id": None,
        },
        "11002": {
            "square_type": 1,
            "name": "Stamina",
            "reward": "Stamina +5",
            "grants_sp": False,
            "token_cost": {"Passion": 16},
            "adds_song_live_id": None,
        },
    }


def _live(
    offered,
    *,
    dance=100,
    passion=100,
    vocal=100,
    visual=100,
    mental=100,
    maximum=200,
    songs=(),
):
    return {
        "next_square_info_array": [
            {"square_id": square_id} if index % 2 else square_id
            for index, square_id in enumerate(offered)
        ],
        "live_performance_info": {
            "dance": dance,
            "passion": passion,
            "vocal": vocal,
            "visual": visual,
            "mental": mental,
            "max_dance": maximum,
            "max_passion": maximum,
            "max_vocal": maximum,
            "max_visual": maximum,
            "max_mental": maximum,
        },
        "next_live_id_array": list(songs),
    }


def test_song_is_prioritized_until_three_are_queued():
    pick = select_lesson_pick(
        _live([11006, 40000, 11001], songs=[1001, 1002]),
        _reference(),
    )

    assert pick["square_id"] == 40000


def test_sp_then_cheapest_churn_after_song_threshold():
    reference = _reference()
    live = _live([11001, 11006, 11002], songs=[1001, 1002, 1003])

    assert select_lesson_pick(live, reference)["square_id"] == 11006

    reference["11006"]["grants_sp"] = False
    assert select_lesson_pick(live, reference)["square_id"] == 11001


def test_sp_is_second_priority_even_while_song_queue_is_short():
    pick = select_lesson_pick(
        _live([11006, 11001], songs=[]),
        _reference(),
    )

    assert pick["square_id"] == 11006


def test_non_song_board_churns_while_song_queue_is_short():
    pick = select_lesson_pick(
        _live([11002, 11001], songs=[]),
        _reference(),
    )

    assert pick["square_id"] == 11001


def test_already_queued_song_is_not_bought_again():
    pick = select_lesson_pick(
        _live([40000, 11006], songs=[1032]),
        _reference(),
    )

    assert pick["square_id"] == 11006


def test_unknown_and_unaffordable_squares_are_never_selected():
    assert select_lesson_pick(
        _live([99999, 11001], dance=0),
        _reference(),
    ) is None


def test_near_cap_colour_is_avoided_when_safe_alternative_exists():
    pick = select_lesson_pick(
        _live([11001, 11002], dance=90, passion=50, maximum=100),
        _reference(),
    )

    assert pick["square_id"] == 11002


def test_multicolour_square_is_safe_when_one_cost_colour_has_headroom():
    reference = _reference()
    reference["40000"]["token_cost"] = {"Dance": 10, "Passion": 10}
    pick = select_lesson_pick(
        _live(
            [40000, 11002],
            dance=90,
            passion=50,
            maximum=100,
            songs=[],
        ),
        reference,
    )

    assert pick["square_id"] == 40000


def test_near_cap_preference_is_omitted_without_capacity():
    live = _live([11001, 11002], dance=90, passion=50, maximum=0)

    assert select_lesson_pick(live, _reference())["square_id"] == 11001


def test_tie_break_is_total_cost_then_square_id():
    reference = copy.deepcopy(_reference())
    reference["11002"]["token_cost"] = {"Passion": 10}

    assert select_lesson_pick(
        _live([11002, 11001]),
        reference,
    )["square_id"] == 11001


def test_performance_array_shape_is_supported():
    live = {
        "next_square_info_array": [{"square_id": 11001}],
        "live_performance_info": [
            {"performance_type": 1, "value": 10, "max_value": 100},
        ],
        "next_live_id_array": [],
    }

    assert select_lesson_pick(live, _reference())["square_id"] == 11001
