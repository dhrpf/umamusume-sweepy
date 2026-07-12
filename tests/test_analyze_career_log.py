import contextlib
import io
import json

from scripts import analyze_career_log


def test_risky_training_uses_decision_snapshot_not_post_turn_commands(tmp_path):
    log_path = tmp_path / "career_log.json"
    log_path.write_text(json.dumps({
        "preset_name": "x",
        "scenario_id": 1,
        "status": "finished",
        "final_turn": 1,
        "turns": [{
            "turn": 1,
            "decision_state": {
                "chara_info": {"turn": 1, "vital": 80, "max_vital": 100},
                "command_info_array": [{
                    "command_type": 1,
                    "command_id": 101,
                    "failure_rate": 10,
                }],
            },
            "api_calls": [
                {
                    "direction": "REQ",
                    "endpoint": "single_mode/exec_command",
                    "data": {"payload": {"command_type": 1, "command_id": 101}},
                },
                {
                    "direction": "RES",
                    "endpoint": "single_mode/check_event",
                    "data": {"data": {
                        "chara_info": {"turn": 2, "vital": 10, "max_vital": 100},
                        "home_info": {"command_info_array": [{
                            "command_type": 1,
                            "command_id": 101,
                            "failure_rate": 90,
                        }]},
                    }},
                },
            ],
        }],
    }), encoding="utf-8")

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        analyze_career_log.analyze(str(log_path))

    assert "fail=90%" not in out.getvalue()


def test_analyzer_separates_normal_and_unity_team_races(tmp_path):
    log_path = tmp_path / "career_log.json"
    log_path.write_text(json.dumps({
        "preset_name": "URA Finale",
        "scenario_id": 2,
        "status": "finished",
        "final_turn": 24,
        "turns": [{
            "turn": 24,
            "api_calls": [
                {
                    "direction": "RES",
                    "endpoint": "single_mode_team/race_start",
                    "data": {"data": {"race_start_info": {"program_id": 100501}}},
                },
                {
                    "direction": "RES",
                    "endpoint": "single_mode_team/race_end",
                    "data": {"data": {
                        "race_history": [{"program_id": 100501, "result_rank": 1}],
                        "race_reward_info": {"gained_fans": 1000},
                    }},
                },
                {
                    "direction": "RES",
                    "endpoint": "single_mode_team/team_race_end",
                    "data": {"data": {"team_data_set": {
                        "team_info": {"team_rank": 30},
                        "team_race_history_array": [{
                            "race_num": 1,
                            "turn": 24,
                            "team_race_set_id": 306,
                            "result_state": 1,
                        }],
                    }}},
                },
                {
                    "direction": "RES",
                    "endpoint": "single_mode_team/team_race_out",
                    "data": {"data": {"tmp_team_rank": 22}},
                },
            ],
        }],
    }), encoding="utf-8")

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        analyze_career_log.analyze(str(log_path))

    text = out.getvalue()
    assert "Scenario:  2 (Unity Cup)" in text
    assert "NORMAL RACE RESULTS" in text
    assert "1/1 wins" in text
    assert "UNITY TEAM RACE RESULTS" in text
    assert "Turn 24: Team Race 1" in text
    assert "WIN" in text
    assert "Rank 30 → 22" in text
    assert "Overall: 2/2 wins" in text
    assert "2 race loss(es)" not in text


def test_analyzer_does_not_count_recreation_as_failed_training(tmp_path):
    log_path = tmp_path / "career_log.json"
    log_path.write_text(json.dumps({
        "preset_name": "x",
        "scenario_id": 2,
        "status": "finished",
        "final_turn": 1,
        "turns": [{
            "turn": 1,
            "api_calls": [
                {
                    "direction": "RES",
                    "endpoint": "single_mode_team/check_event",
                    "data": {"data": {"chara_info": {
                        "turn": 1,
                        "speed": 100,
                        "stamina": 100,
                        "power": 100,
                        "guts": 100,
                        "wiz": 100,
                    }}},
                },
                {
                    "direction": "REQ",
                    "endpoint": "single_mode_team/exec_command",
                    "data": {"payload": {"command_type": 3, "command_id": 0}},
                },
                {
                    "direction": "RES",
                    "endpoint": "single_mode_team/exec_command",
                    "data": {"data": {"chara_info": {
                        "turn": 2,
                        "speed": 100,
                        "stamina": 100,
                        "power": 100,
                        "guts": 100,
                        "wiz": 100,
                    }}},
                },
            ],
        }],
    }), encoding="utf-8")

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        analyze_career_log.analyze(str(log_path))

    text = out.getvalue()
    assert "Turn  1: type_3 training" not in text
    assert "failures out of" not in text
