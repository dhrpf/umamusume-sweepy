import pytest

from career_bot.grand_live_data import GrandLiveDataError
from career_bot.runner import CareerRunner, STRATEGIES
from career_bot.scenarios.grand_live import GrandLiveStrategy


REFERENCE = {
    "11001": {
        "square_type": 1,
        "name": "Steps",
        "reward": "Speed +5",
        "grants_sp": False,
        "token_cost": {"Dance": 10},
        "adds_song_live_id": None,
    },
    "11002": {
        "square_type": 1,
        "name": "Calls",
        "reward": "Stamina +5",
        "grants_sp": False,
        "token_cost": {"Passion": 10},
        "adds_song_live_id": None,
    },
}


def _live(board, *, dance=100, passion=100):
    return {
        "next_square_info_array": [
            {"square_id": square_id}
            for square_id in board
        ],
        "live_performance_info": {
            "dance": dance,
            "passion": passion,
            "max_dance": 200,
            "max_passion": 200,
        },
        "next_live_id_array": [],
    }


def _state(board=(11001,)):
    return {
        "data": {
            "chara_info": {
                "turn": 24,
                "playing_state": 10,
                "skill_point": 0,
            },
            "home_info": {
                "command_info_array": [{"command_type": 7, "command_id": 701}],
            },
            "unchecked_event_array": [],
            "live_data_set": _live(board),
        }
    }


class FakeClient:
    def __init__(self, square_responses=(), live_response=None, load_response=None):
        self.square_responses = list(square_responses)
        self.live_response = live_response or {"data": {}}
        self.load_response = load_response or {"data": {}}
        self.master_square_calls = []
        self.live_start_calls = []
        self.load_calls = []

    def master_square(self, square_id, current_turn):
        self.master_square_calls.append((square_id, current_turn))
        return self.square_responses.pop(0)

    def live_start(self, current_turn):
        self.live_start_calls.append(current_turn)
        return self.live_response

    def load_career(self, scenario_id):
        self.load_calls.append(scenario_id)
        return self.load_response


def test_lessons_merge_partial_responses(tmp_path):
    runner = CareerRunner(tmp_path)
    strategy = GrandLiveStrategy(square_reference=REFERENCE)
    state = _state()
    client = FakeClient([
        {"data": {"live_data_set": _live([11002], dance=90)}},
        {
            "data": {
                "chara_info": {"skill_point": 12},
                "live_data_set": _live([], dance=90, passion=90),
            }
        },
    ])

    result = runner._run_lessons(client, strategy, state)

    assert result["data"]["home_info"] == state["data"]["home_info"]
    assert result["data"]["chara_info"]["turn"] == 24
    assert result["data"]["chara_info"]["skill_point"] == 12
    assert client.master_square_calls == [(11001, 24), (11002, 24)]


def test_lessons_stop_at_sixty(tmp_path):
    runner = CareerRunner(tmp_path)
    strategy = GrandLiveStrategy(square_reference=REFERENCE)
    client = FakeClient([
        {"data": {"live_data_set": _live([11001])}}
        for _ in range(60)
    ])

    runner._run_lessons(client, strategy, _state())

    assert len(client.master_square_calls) == 60


def test_unknown_square_never_reaches_api(tmp_path):
    runner = CareerRunner(tmp_path)
    strategy = GrandLiveStrategy(square_reference=REFERENCE)
    client = FakeClient()

    result = runner._run_lessons(client, strategy, _state([99999]))

    assert result == _state([99999])
    assert client.master_square_calls == []


def test_live_start_merges_partial_response_and_marks_turn(tmp_path):
    runner = CareerRunner(tmp_path)
    strategy = GrandLiveStrategy(square_reference=REFERENCE)
    state = _state([])
    client = FakeClient(live_response={
        "data": {"live_data_set": {"next_live_id_array": []}},
    })

    result = runner._run_live(
        client,
        strategy,
        state,
        {"current_turn": 24},
    )

    assert client.live_start_calls == [24]
    assert result["data"]["chara_info"]["turn"] == 24
    assert strategy.next_decision(result, {"scenario_id": 3}).action == "state_poll"


def test_partial_merge_preserves_absent_and_none_but_replaces_empty_lists(tmp_path):
    runner = CareerRunner(tmp_path)
    old = _state()
    old["data"]["chara_info"]["motivation"] = 3
    old["data"]["unchecked_event_array"] = [{"event_id": 1}]

    merged = runner._merge_state(old, {
        "data": {
            "chara_info": {"motivation": None, "skill_point": 9},
            "unchecked_event_array": [],
        }
    })

    assert merged["data"]["home_info"] == old["data"]["home_info"]
    assert merged["data"]["chara_info"]["turn"] == 24
    assert merged["data"]["chara_info"]["motivation"] == 3
    assert merged["data"]["chara_info"]["skill_point"] == 9
    assert merged["data"]["unchecked_event_array"] == []


def test_missing_metadata_does_not_leave_runner_wedged(monkeypatch, tmp_path):
    class MissingGrandLiveStrategy:
        def __init__(self, race_planner):
            raise GrandLiveDataError("run generator")

    monkeypatch.setitem(STRATEGIES, 3, MissingGrandLiveStrategy)
    runner = CareerRunner(tmp_path)

    with pytest.raises(GrandLiveDataError, match="generator"):
        runner.start(
            client=None,
            preset={"name": "Grand Live", "scenario_id": 3},
            initial_result={"data": {}},
        )

    assert runner.status["running"] is False
    assert runner.thread is None


def test_state_poll_reloads_grand_live_and_merges(tmp_path):
    runner = CareerRunner(tmp_path)
    client = FakeClient(load_response={
        "data": {"chara_info": {"playing_state": 1}},
    })

    result = runner._poll_scenario_state(client, _state(), scenario_id=3)

    assert client.load_calls == [3]
    assert result["data"]["chara_info"]["turn"] == 24
    assert result["data"]["chara_info"]["playing_state"] == 1
