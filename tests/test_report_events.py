import json

from career_bot.events import EventManager
from career_bot.report import add_api_call, get_turn, merge_turn, safe_int, turn_from_event


def test_safe_int_returns_default_for_invalid_values():
    assert safe_int("7") == 7
    assert safe_int("bad", default=9) == 9
    assert safe_int(None, default=5) == 0


def test_turn_from_event_prefers_payload_current_turn():
    event = {"turn": 3, "data": {"payload": {"current_turn": "12"}}}

    assert turn_from_event(event) == 12


def test_merge_turn_preserves_attempt_lists_and_updates_final_turn():
    report = {"turns": [{"turn": 2, "api_calls": [{"x": 1}], "skill_buy_attempts": [{"s": 1}]}]}

    row = merge_turn(report, {"turn": 2, "stats": {"fans": 123}, "api_calls": [{"x": 2}]})

    assert row["stats"] == {"fans": 123}
    assert row["api_calls"] == [{"x": 1}]
    assert row["skill_buy_attempts"] == [{"s": 1}]
    assert report["final_turn"] == 2


def test_get_turn_creates_sorted_turns():
    report = {"turns": [{"turn": 5}]}

    get_turn(report, 2)

    assert [row["turn"] for row in report["turns"]] == [2, 5]


def test_add_api_call_uses_request_payload_turn():
    report = {"turns": []}

    add_api_call(report, {"data": {"request_payload": {"current_turn": 8}}})

    assert report["turns"][0]["turn"] == 8
    assert report["final_turn"] == 8


def test_event_manager_uses_exact_outcome_choice(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "event_outcomes.json").write_text(
        json.dumps({"12345": {"outcomes": {"20": "good"}}}),
        encoding="utf-8",
    )
    manager = EventManager(tmp_path)

    assert manager.choose({"story_id": 12345, "event_contents_info": {"choice_array": [{"select_index": 10}, {"select_index": 20}]}}) == 1


def test_event_manager_falls_back_to_second_choice_when_no_data():
    manager = EventManager("/missing")

    assert manager.choose({"event_contents_info": {"choice_array": [{"select_index": 1}, {"select_index": 2}]}}) == 1
