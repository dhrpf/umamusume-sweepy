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

        self.assertEqual(strategy._choice(event), 1)

    def test_choice_number_key_still_takes_precedence(self):
        strategy = UraStrategy({})
        event = {
            "event_contents_info": {
                "choice_array": [
                    {"choice_number": 7, "select_index": 1},
                ]
            }
        }

        self.assertEqual(strategy._choice(event), 7)


if __name__ == "__main__":
    unittest.main()
