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
