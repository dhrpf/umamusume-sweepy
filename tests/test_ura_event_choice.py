import unittest

from career_bot.scenarios.ura import UraStrategy


class TestUraEventChoice(unittest.TestCase):
    def test_choice_uses_choice_array_position_not_select_index(self):
        strategy = UraStrategy({})
        event = {
            "event_contents_info": {
                "choice_array": [
                    {"select_index": 1, "gain_select_id_index": 5},
                    {"select_index": 1, "gain_select_id_index": 2},
                    {"select_index": 1, "gain_select_id_index": 3},
                ]
            }
        }

        self.assertEqual(strategy._choice(event), 5)

    def test_choice_gain_id_takes_precedence_over_select_index(self):
        strategy = UraStrategy({})
        event = {
            "event_contents_info": {
                "choice_array": [
                    {"gain_select_id_index": 7, "select_index": 1},
                ]
            }
        }

        self.assertEqual(strategy._choice(event), 7)

    def test_choice_with_stat_gain_returns_gain_index(self):
        strategy = UraStrategy({})
        event = {
            "event_contents_info": {
                "choice_array": [
                    {"select_index": 1, "gain_select_id_index": 5, "event_effect_array": []},
                    {"select_index": 2, "gain_select_id_index": 9, "event_effect_array": [{"effect_type": 1}]},
                ]
            }
        }

        self.assertEqual(strategy._choice(event), 9)


if __name__ == "__main__":
    unittest.main()
