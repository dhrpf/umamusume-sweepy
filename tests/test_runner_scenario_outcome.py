from career_bot.runner import CareerRunner
from career_bot.report import new_report


def _runner():
    runner = CareerRunner('/nonexistent')
    runner.race_planner.program = {
        2111: {"name": "URA Finale Semifinal", "race_instance_id": 910111},
        2531: {"name": "URA Finale Final", "race_instance_id": 920113},
    }
    return runner


def test_unity_semifinal_loss_is_finished_but_not_cleared():
    runner = _runner()
    state = {
        "data": {
            "chara_info": {"turn": 76, "state": 3, "playing_state": 5},
            "race_history": [
                {"turn": 76, "program_id": 2111, "result_rank": 3},
            ],
        },
    }

    outcome = runner._scenario_outcome(state, {"scenario_id": 2})

    assert outcome == {
        "scenario_result": "failed",
        "scenario_cleared": False,
        "failed_at": "URA Finale Semifinal",
        "result_rank": 3,
    }


def test_unity_final_win_is_cleared():
    runner = _runner()
    state = {
        "data": {
            "chara_info": {"turn": 78, "state": 3, "playing_state": 5},
            "race_history": [
                {"turn": 78, "program_id": 2531, "result_rank": 1},
            ],
        },
    }

    outcome = runner._scenario_outcome(state, {"scenario_id": 2})

    assert outcome["scenario_result"] == "cleared"
    assert outcome["scenario_cleared"] is True
    assert outcome["result_rank"] == 1
    assert outcome["failed_at"] is None


def test_unity_final_win_uses_cached_race_result_when_race_out_omits_history():
    runner = _runner()
    runner._last_race_result = {
        "turn": 78,
        "program_id": 2531,
        "result_rank": 1,
    }
    state = {
        "data": {
            "chara_info": {"turn": 78, "state": 3, "playing_state": 5},
        },
    }

    outcome = runner._scenario_outcome(state, {"scenario_id": 2})

    assert outcome["scenario_result"] == "cleared"
    assert outcome["scenario_cleared"] is True
    assert outcome["result_rank"] == 1


def test_new_report_tracks_transport_and_scenario_status_separately():
    report = new_report({"name": "Unity"}, scenario_id=2)

    assert report["status"] == "running"
    assert report["scenario_result"] == "running"
    assert report["scenario_cleared"] is False
