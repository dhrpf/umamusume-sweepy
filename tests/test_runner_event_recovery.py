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


def test_drain_events_retries_alternate_choice_after_217():
    class RetryClient:
        def __init__(self):
            self.choices = []

        def check_event(self, **payload):
            self.choices.append(payload["choice_number"])
            if payload["choice_number"] == 1:
                raise Exception("API error 217 on single_mode/check_event: stale event")
            return {"data": {"chara_info": {"turn": 3}, "unchecked_event_array": []}}

    runner = CareerRunner.__new__(CareerRunner)
    runner.status = {"turn": 3, "scenario_id": 1}
    runner._log = lambda *a, **k: None
    state = {
        "data": {
            "chara_info": {"turn": 3},
            "unchecked_event_array": [{
                "event_id": 123,
                "chara_id": 456,
                "event_contents_info": {
                    "choice_array": [
                        {"select_index": 1},
                        {"select_index": 2},
                    ]
                },
            }],
        }
    }

    out = runner._drain_events(RetryClient(), Strategy(), state)

    assert out["data"]["unchecked_event_array"] == []


def test_fresh_career_state_falls_back_to_hard_reset_after_retries(monkeypatch):
    import career_bot.runner as runner_module

    class Client:
        def __init__(self):
            self.loads = 0
            self.regen_sids = 0
            self.start_sessions = 0
            self.hard_reset_called = False

        def regen_sid(self):
            self.regen_sids += 1

        def call(self, ep, payload=None):
            if ep == "tool/start_session":
                self.start_sessions += 1
                return {"data": {}}
            raise Exception("Network error")

        def load_career(self, scenario_id=1):
            self.loads += 1
            raise Exception("Network error")

        def hard_reset(self):
            self.hard_reset_called = True
            return {"data": {"chara_info": {"turn": 9}}}

    runner = CareerRunner.__new__(CareerRunner)
    runner.status = {"scenario_id": 1}
    monkeypatch.setattr(runner_module, "dna_sleep", lambda *a, **k: None)

    client = Client()
    out = runner._fresh_career_state(client)

    assert client.loads == 8
    assert client.regen_sids == 7
    assert client.start_sessions == 7
    assert client.hard_reset_called is True
    assert out["data"]["chara_info"]["turn"] == 9


def test_race_entry_205_rejects_race_and_refreshes_state():
    class RacePlanner:
        def __init__(self):
            self.rejected = []

        def reject(self, turn, program_id):
            self.rejected.append((turn, program_id))

    class StrategyWithReject:
        def __init__(self):
            self.rejected = []

        def reject_race(self, program_id):
            self.rejected.append(program_id)

    class Client:
        api_jitter = 0

        def race_entry(self, **payload):
            raise Exception("API error 205 on race entry")

    runner = CareerRunner('/nonexistent')
    runner.race_planner = RacePlanner()
    runner._fresh_career_state = lambda client, strategy=None: {"data": {"chara_info": {"turn": 4}}}
    strategy = StrategyWithReject()

    out = runner._race(
        Client(),
        {"data": {"chara_info": {"turn": 3}}},
        {"scenario_id": 1},
        {"program_id": 1001, "current_turn": 3, "_strategy": strategy},
    )

    assert runner.race_planner.rejected == [(3, 1001)]
    assert strategy.rejected == [1001]
    assert out["data"]["chara_info"]["turn"] == 4


if __name__ == "__main__":
    unittest.main()
