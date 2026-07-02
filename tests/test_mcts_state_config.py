import json
import random
import sys
import unittest
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

from career_bot.mcts.core.config import MCTSConfig
from career_bot.mcts.core.state import Action, GameState


class TestMCTSStateConfig(unittest.TestCase):
    def test_config_defaults(self):
        cfg = MCTSConfig.from_preset({})
        self.assertEqual(cfg.time_budget_sec, 5.0)
        self.assertEqual(cfg.max_simulations, 1000)
        self.assertEqual(cfg.explore_weight, 1.41)
        self.assertEqual(cfg.widening_alpha, 0.5)
        self.assertEqual(cfg.rollout_depth, 15)
        self.assertEqual(cfg.rest_vital_ratio, 0.3)
        self.assertEqual(cfg.overshoot_penalty, 0.3)
        self.assertEqual(cfg.shortfall_exponent, 2.0)
        self.assertIsNone(cfg.rng_seed)
        self.assertFalse(cfg.use_expected_value)

    def test_config_overrides_known_fields(self):
        cfg = MCTSConfig.from_preset({"mcts_config": {"time_budget_sec": 0.25, "rollout_depth": 7}})
        self.assertEqual(cfg.time_budget_sec, 0.25)
        self.assertEqual(cfg.rollout_depth, 7)
        self.assertEqual(cfg.max_simulations, 1000)

    def test_config_ignores_unknown_fields(self):
        cfg = MCTSConfig.from_preset({"mcts_config": {"not_a_field": 123}})
        self.assertFalse(hasattr(cfg, "not_a_field"))

    def test_action_fraction_failure_and_vital_sign(self):
        train = Action("train", 0, (1, 2, 3, 4, 5, 6), -20, 0.30, 2)
        rest = Action("rest", 0, (0, 0, 0, 0, 0, 0), 45, 0.0, 0)
        self.assertEqual(train.failure_rate, 0.30)
        self.assertLess(train.vital_delta, 0)
        self.assertGreater(rest.vital_delta, 0)

    def test_from_api_extracts_numbers_actions_and_digest(self):
        api_state = {
            "data": {
                "chara_info": {
                    "turn": 12,
                    "speed": 101,
                    "stamina": 102,
                    "power": 103,
                    "guts": 104,
                    "wiz": 105,
                    "vital": 55,
                    "max_vital": 100,
                    "motivation": 4,
                    "fans": 1234,
                    "skill_point": 88,
                    "skill_array": [{"skill_id": 11}, {"skill_id": 22}],
                },
                "home_info": {
                    "command_info_array": [
                        {
                            "command_type": 1,
                            "command_id": 101,
                            "command_group_id": 10,
                            "is_enable": 1,
                            "failure_rate": 30,
                            "params_inc_dec_info_array": [
                                {"target_type": 1, "value": 12},
                                {"target_type": 2, "value": 3},
                                {"target_type": 3, "value": 4},
                                {"target_type": 4, "value": 5},
                                {"target_type": 5, "value": 6},
                                {"target_type": 11, "value": 7},
                                {"target_type": 10, "value": -20},
                            ],
                            "support_card_array": [{"support_card_id": 1}, {"support_card_id": 2}],
                        },
                        {"command_type": 7, "command_id": 701, "command_group_id": 70, "is_enable": 1},
                        {"command_type": 3, "command_id": 301, "command_group_id": 30, "is_enable": 1},
                        {"command_type": 2, "command_id": 201, "is_enable": 1},
                        {"command_type": 1, "command_id": 102, "is_enable": 0},
                    ]
                },
            }
        }
        state = GameState.from_api(api_state, training_counts=(1, 2, 3, 4, 5))
        self.assertEqual(state.turn, 12)
        self.assertEqual(state.speed, 101.0)
        self.assertEqual(state.skill_points, 88.0)
        self.assertEqual(state.training_counts, (1, 2, 3, 4, 5))
        self.assertEqual(state.learned_skills, frozenset({11, 22}))
        self.assertEqual(len(state.available_actions), 3)
        train = state.available_actions[0]
        self.assertEqual(train.action_type, "train")
        self.assertEqual(train.index, 0)
        self.assertEqual(train.stat_gains, (12.0, 3.0, 4.0, 5.0, 6.0, 7.0))
        self.assertEqual(train.vital_delta, -20.0)
        self.assertEqual(train.failure_rate, 0.30)
        self.assertEqual(train.partner_count, 2)
        self.assertEqual(train.command_type, 1)
        self.assertEqual(train.command_id, 101)
        self.assertEqual(train.command_group_id, 10)
        self.assertEqual(state.available_actions[1].action_type, "rest")
        self.assertEqual(state.available_actions[2].action_type, "outing")
        self.assertEqual(state.stable_digest(), state.stable_digest())
        json.dumps(state.to_dict(), sort_keys=True)


if __name__ == "__main__":
    unittest.main()
