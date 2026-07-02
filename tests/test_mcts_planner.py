import sys
import unittest
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

from career_bot.mcts.core.config import MCTSConfig
from career_bot.mcts.core.planner import MCTSPlanner
from career_bot.mcts.core.state import Action, GameState
from career_bot.mcts.sim.base import SimulatorBase


class TinySim(SimulatorBase):
    def __init__(self):
        self.actions = (
            Action("train", 0, (1, 0, 0, 0, 0, 0), -10, 0.0, 0, 1, 101, 0),
            Action("train", 1, (5, 0, 0, 0, 0, 0), -10, 0.0, 0, 1, 102, 0),
            Action("rest", 0, (0, 0, 0, 0, 0, 0), 50, 0.0, 0, 7, 701, 0),
        )

    def generate_actions(self, state):
        return self.actions

    def simulate_action(self, state, action, rng):
        return GameState(
            turn=state.turn + 1,
            speed=state.speed + action.stat_gains[0],
            stamina=state.stamina,
            power=state.power,
            guts=state.guts,
            wiz=state.wiz,
            vital=max(0, min(state.max_vital, state.vital + action.vital_delta)),
            max_vital=state.max_vital,
            motivation=state.motivation,
            fans=state.fans,
            skill_points=state.skill_points,
            available_actions=(),
        )

    def is_terminal(self, state):
        return state.turn >= 3

    def evaluate(self, state, preset):
        return state.speed


def make_state(**kw):
    base = dict(
        turn=1,
        speed=0.0,
        stamina=0.0,
        power=0.0,
        guts=0.0,
        wiz=0.0,
        vital=100.0,
        max_vital=100.0,
        motivation=3,
        fans=0.0,
        skill_points=0.0,
        training_levels=(1, 1, 1, 1, 1),
        bonds=(),
        learned_skills=frozenset(),
        training_counts=(0, 0, 0, 0, 0),
        available_actions=(),
    )
    base.update(kw)
    return GameState(**base)


class TestMCTSPlanner(unittest.TestCase):
    def test_search_prefers_higher_value_action(self):
        planner = MCTSPlanner(TinySim(), MCTSConfig(max_simulations=30, time_budget_sec=0, rollout_depth=1, rng_seed=1))
        result = planner.search(make_state())
        self.assertIsNotNone(result.action)
        self.assertEqual(result.action.command_id, 102)
        self.assertEqual(result.simulations, 30)

    def test_rollout_policy_rests_low_vital(self):
        planner = MCTSPlanner(TinySim(), MCTSConfig(rest_vital_ratio=0.3))
        action = planner._rollout_policy(make_state(vital=10), TinySim().actions)
        self.assertEqual(action.action_type, "rest")

    def test_search_filters_unsafe_root_training(self):
        sim = TinySim()
        sim.actions = (
            Action("train", 0, (1000, 0, 0, 0, 0, 0), -20, 0.30, 0, 1, 101, 0),
            Action("rest", 0, (0, 0, 0, 0, 0, 0), 50, 0.0, 0, 7, 701, 0),
        )
        planner = MCTSPlanner(sim, MCTSConfig(max_simulations=10, time_budget_sec=0, rollout_depth=1, rng_seed=1))
        result = planner.search(make_state(vital=40))
        self.assertEqual(result.action.action_type, "rest")


if __name__ == "__main__":
    unittest.main()
