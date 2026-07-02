import json
import sys
import tempfile
import unittest
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

from career_bot.mcts.calibration.extract import extract_from_log, extract_from_paths
from career_bot.mcts.calibration.fit import fit_params, write_params


def cmd(command_id=101, level=1, failure_rate=30, vital=-20):
    return {
        "command_type": 1,
        "command_id": command_id,
        "is_enable": 1,
        "failure_rate": failure_rate,
        "level": level,
        "params_inc_dec_info_array": [
            {"target_type": 1, "value": 10},
            {"target_type": 3, "value": 5},
            {"target_type": 11, "value": 4},
            {"target_type": 10, "value": vital},
        ],
    }


def res_call(endpoint, data, turn=1):
    return {"direction": "RES", "endpoint": endpoint, "turn": turn, "data": {"data": data}}


def make_log(scenario_id=1, event_between=False):
    pre = {
        "chara_info": {"turn": 1, "vital": 100, "max_vital": 100, "speed": 100, "stamina": 100, "power": 100, "guts": 100, "wiz": 100, "skill_point": 10},
        "home_info": {"command_info_array": [cmd(101, level=1, failure_rate=30, vital=-20)]},
        "unchecked_event_array": [],
    }
    post_exec = {
        "chara_info": {"turn": 1, "vital": 80, "max_vital": 100, "speed": 110, "stamina": 100, "power": 105, "guts": 100, "wiz": 100, "skill_point": 14},
        "home_info": {"command_info_array": [cmd(101, level=1, failure_rate=20, vital=-19)]},
        "unchecked_event_array": [{"event_id": 999}] if event_between else [],
    }
    post_check = {
        "chara_info": {"turn": 2, "vital": 80, "max_vital": 100, "speed": 110, "stamina": 100, "power": 105, "guts": 100, "wiz": 100, "skill_point": 14},
        "home_info": {"command_info_array": [cmd(101, level=2, failure_rate=20, vital=-19)]},
        "unchecked_event_array": [],
    }
    return {
        "scenario_id": scenario_id,
        "status": "done",
        "turns": [
            {
                "turn": 1,
                "current_command": {"command_type": 1, "command_id": 101, "current_turn": 1, "current_vital": 100},
                "api_calls": [
                    res_call("single_mode_free/check_event", pre, 1),
                    res_call("single_mode_free/exec_command", post_exec, 1),
                    res_call("single_mode_free/check_event", post_check, 2),
                ],
            }
        ],
    }


class TestMCTSCalibration(unittest.TestCase):
    def test_extract_filters_scenario_and_uses_forecast_primary(self):
        skipped = extract_from_log(make_log(scenario_id=2), scenario_id=1)
        self.assertEqual(skipped.logs_used, 0)

        data = extract_from_log(make_log(), scenario_id=1)
        self.assertEqual(data.logs_used, 1)
        self.assertEqual(len(data.training_samples), 1)
        sample = data.training_samples[0]
        self.assertEqual(sample.command_id, 101)
        self.assertEqual(sample.level, 1)
        self.assertEqual(sample.forecast_gains, (10.0, 0.0, 5.0, 0.0, 0.0, 4.0))
        self.assertEqual(sample.vital_delta, -20.0)
        self.assertEqual(sample.failure_rate, 0.30)
        self.assertEqual(sample.vital_ratio, 1.0)
        self.assertEqual(sample.actual_gains, (10.0, 0.0, 5.0, 0.0, 0.0, 4.0))

    def test_event_contaminated_turn_discards_actual_diff_only(self):
        data = extract_from_log(make_log(event_between=True), scenario_id=1)
        self.assertEqual(len(data.training_samples), 1)
        self.assertIsNone(data.training_samples[0].actual_gains)
        self.assertGreater(data.discarded_event_contaminated, 0)

    def test_fit_params_schema_and_confidence(self):
        extracted = extract_from_log(make_log(), scenario_id=1)
        params = fit_params([extracted], scenario_id=1)
        self.assertEqual(params["scenario_id"], 1)
        self.assertIn("101", params["training_gains"])
        self.assertIn("1", params["training_gains"]["101"])
        self.assertEqual(params["training_gains"]["101"]["1"], [10.0, 0.0, 5.0, 0.0, 0.0, 4.0])
        self.assertEqual(params["vital_cost"]["101"], 20.0)
        self.assertEqual(params["calibrated_from"], 1)
        self.assertEqual(params["confidence"], "disabled")
        self.assertIn("failure_curve", params)
        self.assertIn("level_up_counts", params)

    def test_extract_from_paths_and_write_params(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "career_log_fixture.json"
            p.write_text(json.dumps(make_log()))
            extracted = extract_from_paths([str(p)], scenario_id=1)
            self.assertEqual(extracted.logs_scanned, 1)
            self.assertEqual(extracted.logs_used, 1)
            out = Path(td) / "params.json"
            params = fit_params([extracted], scenario_id=1)
            write_params(params, out)
            loaded = json.loads(out.read_text())
            self.assertEqual(loaded["scenario_id"], 1)


if __name__ == "__main__":
    unittest.main()
