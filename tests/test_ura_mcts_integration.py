from career_bot.mcts.core.config import MCTSConfig
from career_bot.mcts.core.planner import SearchResult
from career_bot.mcts.core.state import Action
from career_bot.scenarios.ura import UraStrategy


class FakePlanner:
    config = MCTSConfig(max_simulations=123)

    def __init__(self):
        self.root = None

    def search(self, root):
        self.root = root
        return SearchResult(
            Action("train", 0, (12, 0, 0, 0, 0, 0), -20, 0.0, 0, 1, 101, 0),
            1.25,
            123,
            {0: 123},
        )


def test_mcts_receives_training_counts_and_logs_detail():
    strategy = UraStrategy()
    planner = FakePlanner()
    strategy._mcts_planner = planner
    strategy._ensure_mcts = lambda preset: planner
    strategy._training_counts = {101: 2, 601: 1}
    state = {"data": {
        "chara_info": {
            "turn": 41,
            "speed": 100,
            "stamina": 100,
            "power": 100,
            "guts": 100,
            "wiz": 100,
            "vital": 80,
            "max_vital": 100,
            "motivation": 5,
            "fans": 9999,
        },
        "home_info": {"command_info_array": [
            {
                "command_type": 1,
                "command_id": 101,
                "command_group_id": 1,
                "is_enable": 1,
                "failure_rate": 0,
                "params_inc_dec_info_array": [{"target_type": 1, "value": 12}, {"target_type": 10, "value": -20}],
            }
        ]},
        "race_history": [],
    }}

    decision = strategy.next_decision(state, {"use_mcts": True})

    assert decision.reason == "MCTS[train] idx=0 sim=123"
    assert planner.root.training_counts[0] == 3
    assert strategy._training_counts[101] == 3
    assert decision.payload["decision_detail"]["mcts"]["score"] == 1.25
    assert decision.payload["decision_detail"]["mcts"]["visits"] == {0: 123}
