import sys
import unittest
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

from career_bot.report import add_decision, new_report
from career_bot.scenarios.base import Decision


class TestCalibrationLogging(unittest.TestCase):
    def test_add_decision_records_pre_command_snapshot(self):
        report = new_report({"name": "x"}, scenario_id=1)
        state = {
            "data": {
                "chara_info": {"turn": 3, "speed": 100, "vital": 80, "max_vital": 100},
                "home_info": {
                    "command_info_array": [
                        {"command_type": 1, "command_id": 101, "failure_rate": 10, "params_inc_dec_info_array": [{"target_type": 1, "value": 12}]}
                    ]
                },
            }
        }
        dec = Decision("command", {"command_type": 1, "command_id": 101, "current_turn": 3}, "train")
        add_decision(report, state, dec)
        turn = report["turns"][0]
        self.assertIn("decision_state", turn)
        self.assertEqual(turn["decision_state"]["chara_info"]["turn"], 3)
        self.assertEqual(turn["decision_state"]["command_info_array"][0]["command_id"], 101)


if __name__ == "__main__":
    unittest.main()
