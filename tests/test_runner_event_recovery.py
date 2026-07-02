import unittest

from career_bot.runner import CareerRunner


class Strategy:
    def _choice(self, event):
        return 1


class Client:
    def __init__(self):
        self.calls = 0
        self.refreshed = False

    def check_event(self, **payload):
        self.calls += 1
        raise Exception('API error 217 on single_mode/check_event: stale event')

    def load_career(self, scenario_id=1):
        self.refreshed = True
        return {"data": {"chara_info": {"turn": 3}, "unchecked_event_array": []}}


class TestRunnerEventRecovery(unittest.TestCase):
    def test_drain_events_recovers_from_217_by_refreshing_state(self):
        runner = CareerRunner.__new__(CareerRunner)
        runner.status = {"turn": 3, "scenario_id": 1}
        runner.skill_buyer = type("X", (), {"reset_scoped_failures": lambda self: None})()
        runner.item_manager = type("X", (), {"reset_scoped_failures": lambda self: None})()
        runner._log = lambda *a, **k: None

        client = Client()
        state = {"data": {"chara_info": {"turn": 3}, "unchecked_event_array": [{"event_id": 123, "chara_id": 456}]}}

        out = runner._drain_events(client, Strategy(), state)

        self.assertTrue(client.refreshed)
        self.assertEqual(client.calls, 1)
        self.assertEqual(out["data"]["unchecked_event_array"], [])


if __name__ == "__main__":
    unittest.main()
