import json
import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

from career_bot.mcts.core.config import MCTSConfig
from career_bot.mcts.core.state import Action, GameState
from career_bot.mcts.sim.ura import UraSimulator


PARAMS = {
    "scenario_id": 1,
    "training_gains": {
        "101": {"1": [10, 0, 0, 0, 0, 4], "2": [20, 0, 0, 0, 0, 5]},
        "102": {"1": [0, 10, 0, 0, 0, 4]},
        "103": {"1": [0, 0, 10, 0, 0, 4]},
        "105": {"1": [0, 0, 0, 10, 0, 4]},
        "106": {"1": [0, 0, 0, 0, 10, 4]},
    },
    "vital_cost": {"101": 20, "102": 18, "103": 19, "105": 22, "106": 0},
    "failure_curve": [[1.0, 0.0], [0.5, 0.15], [0.1, 0.50]],
    "rest_recovery": 45,
    "outing_recovery": 35,
    "outing_motivation_chance": 1.0,
    "bond_per_interaction": 7,
    "level_up_counts": {"101": [1, 3, 5, 7]},
    "calibrated_from": 20,
    "calibrated_at": "2026-07-01",
}


def write_params(payload):
    tmp = tempfile.NamedTemporaryFile("w", delete=False, suffix=".json")
    json.dump(payload, tmp)
    tmp.close()
    return tmp.name


def make_state(**overrides):
    base = dict(
        turn=1,
        speed=100.0,
        stamina=100.0,
        power=100.0,
        guts=100.0,
        wiz=100.0,
        vital=50.0,
        max_vital=100.0,
        motivation=3,
        fans=1000.0,
        skill_points=100.0,
        training_levels=(1, 1, 1, 1, 1),
        bonds=(),
        learned_skills=frozenset(),
        training_counts=(0, 0, 0, 0, 0),
        available_actions=(),
    )
    base.update(overrides)
    return GameState(**base)


class ZeroRng:
    def random(self):
        return 0.0


class OneRng:
    def random(self):
        return 1.0


class TestUraSimulator(unittest.TestCase):
    def test_load_params_confidence_thresholds(self):
        high = UraSimulator(params_path=write_params(PARAMS), scenario_id=1)
        self.assertTrue(high.enabled)
        self.assertEqual(high.confidence, "high")

        mid_payload = dict(PARAMS, calibrated_from=15)
        mid = UraSimulator(params_path=write_params(mid_payload), scenario_id=1)
        self.assertTrue(mid.enabled)
        self.assertEqual(mid.confidence, "warning")

        low_payload = dict(PARAMS, calibrated_from=9)
        low = UraSimulator(params_path=write_params(low_payload), scenario_id=1)
        self.assertFalse(low.enabled)
        self.assertEqual(low.confidence, "disabled")

    def test_missing_corrupt_wrong_scenario_disable(self):
        missing = UraSimulator(params_path="/tmp/no-such-mcts-params.json", scenario_id=1)
        self.assertFalse(missing.enabled)

        bad_path = write_params({"not": object().__class__.__name__})
        Path(bad_path).write_text("{bad json")
        corrupt = UraSimulator(params_path=bad_path, scenario_id=1)
        self.assertFalse(corrupt.enabled)

        wrong = UraSimulator(params_path=write_params(dict(PARAMS, scenario_id=99)), scenario_id=1)
        self.assertFalse(wrong.enabled)

    def test_generate_actions(self):
        sim = UraSimulator(params_path=write_params(PARAMS), scenario_id=1)
        actions = sim.generate_actions(make_state(vital=100, training_levels=(1, 1, 1, 1, 1)))
        self.assertEqual(len(actions), 7)
        self.assertEqual([a.action_type for a in actions[:5]], ["train"] * 5)
        self.assertEqual(actions[-2].action_type, "rest")
        self.assertEqual(actions[-1].action_type, "outing")
        self.assertEqual(actions[0].failure_rate, 0.0)
        self.assertEqual(actions[0].vital_delta, -20.0)

    def test_simulate_success_failure_expected_value(self):
        sim = UraSimulator(params_path=write_params(PARAMS), scenario_id=1)
        action = Action("train", 0, (10, 0, 0, 0, 0, 4), -20, 0.5, 2, 1, 101, 0)

        success = sim.simulate_action(make_state(), action, OneRng())
        self.assertEqual(success.turn, 2)
        self.assertEqual(success.speed, 110.0)
        self.assertEqual(success.skill_points, 104.0)
        self.assertEqual(success.vital, 30.0)
        self.assertEqual(success.training_counts[0], 1)

        failure = sim.simulate_action(make_state(), action, ZeroRng())
        self.assertEqual(failure.turn, 2)
        self.assertLessEqual(failure.speed, 100.0)
        self.assertLess(failure.vital, 50.0)

        ev = UraSimulator(params_path=write_params(PARAMS), scenario_id=1, config=MCTSConfig(use_expected_value=True))
        with patch("random.random", side_effect=AssertionError("global random used")):
            expected = ev.simulate_action(make_state(), action, random.Random(1))
        self.assertEqual(expected.speed, 105.0)
        self.assertEqual(expected.skill_points, 102.0)

    def test_failure_curve_interpolation(self):
        sim = UraSimulator(params_path=write_params(PARAMS), scenario_id=1)
        self.assertEqual(sim.failure_rate_for_vital_ratio(1.0), 0.0)
        self.assertAlmostEqual(sim.failure_rate_for_vital_ratio(0.5), 0.15)
        self.assertEqual(sim.failure_rate_for_vital_ratio(0.1), 0.50)
        self.assertGreater(sim.failure_rate_for_vital_ratio(0.3), 0.15)

    def test_level_up_counts_drive_training_level(self):
        sim = UraSimulator(params_path=write_params(PARAMS), scenario_id=1)
        state = make_state(training_counts=(1, 0, 0, 0, 0), training_levels=(1, 1, 1, 1, 1))
        actions = sim.generate_actions(state)
        self.assertEqual(actions[0].stat_gains[0], 20.0)

    def test_evaluate(self):
        sim = UraSimulator(params_path=write_params(PARAMS), scenario_id=1)
        preset = {"expect_attribute": [100, 100, 100, 100, 100]}
        score = sim.evaluate(make_state(speed=120, skill_points=2000, fans=500000), preset)
        self.assertGreater(score, 1.0)
        low = sim.evaluate(make_state(speed=50, stamina=50, power=50, guts=50, wiz=50), preset)
        self.assertLess(low, score)

    def test_terminal(self):
        sim = UraSimulator(params_path=write_params(PARAMS), scenario_id=1)
        self.assertFalse(sim.is_terminal(make_state(turn=77)))
        self.assertTrue(sim.is_terminal(make_state(turn=78)))


if __name__ == "__main__":
    unittest.main()
