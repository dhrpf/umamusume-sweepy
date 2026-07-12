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

        def __init__(self):
            self.payloads = []

        def race_entry(self, **payload):
            self.payloads.append(payload)
            raise Exception("API error 205 on race entry")

    runner = CareerRunner('/nonexistent')
    runner.race_planner = RacePlanner()
    runner._fresh_career_state = lambda client, strategy=None: {"data": {"chara_info": {"turn": 4}}}
    strategy = StrategyWithReject()

    client = Client()
    out = runner._race(
        client,
        {"data": {"chara_info": {"turn": 3}}},
        {"scenario_id": 1},
        {"program_id": 1001, "current_turn": 3, "_strategy": strategy},
    )

    assert runner.race_planner.rejected == [(3, 1001)]
    assert strategy.rejected == [1001]
    assert client.payloads[0]["retry_205"] == 0
    assert out["data"]["chara_info"]["turn"] == 4


def test_race_entry_205_tries_eligible_fallback_on_same_turn(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "race_map.json").write_text(
        __import__("json").dumps({
            "meta": {},
            "program": {
                "1001": {"name": "Blocked G1", "race_instance_id": 100001, "ground": 1, "distance": 1600},
                "4001": {"name": "Eligible Open", "race_instance_id": 400001, "ground": 1, "distance": 1600},
            },
            "instance": {},
        }),
        encoding="utf-8",
    )

    class Client:
        api_jitter = 0

        def __init__(self):
            self.entries = []

        def race_entry(self, **payload):
            self.entries.append(payload)
            if payload["program_id"] == 1001:
                raise Exception("API error 205 on race entry")
            return {"data": {"chara_info": {"turn": 24, "playing_state": 2}}}

        def race_start(self, **payload):
            return {"data": {}}

        def race_end(self, **payload):
            return {"data": {"chara_info": {"turn": 24, "playing_state": 4}}}

        def race_out(self, **payload):
            return {"data": {"chara_info": {"turn": 25, "playing_state": 1}}}

    runner = CareerRunner(tmp_path)
    runner.burn_clocks = False
    runner.status = {"scenario_id": 2, "turn": 24, "log": [], "clocks_used": 0}
    runner._parse_race_rank = lambda _response: 1
    fresh = {
        "data": {
            "chara_info": {
                "turn": 24,
                "fans": 652,
                "proper_ground_turf": 7,
                "proper_distance_mile": 7,
            },
            "home_info": {"command_info_array": [
                {"command_type": 4, "command_id": 401, "is_enable": 1},
            ]},
            "race_condition_array": [
                {"program_id": 1001},
                {"program_id": 4001},
            ],
        },
    }
    runner._fresh_career_state = lambda client, strategy=None: fresh

    client = Client()
    out = runner._race(
        client,
        fresh,
        {"scenario_id": 2},
        {"program_id": 1001, "current_turn": 24},
    )

    assert [entry["program_id"] for entry in client.entries] == [1001, 4001]
    assert all(entry["retry_205"] == 0 for entry in client.entries)
    assert out["data"]["chara_info"]["turn"] == 25


def test_race_result_is_reported_back_to_strategy():
    class Strategy:
        def __init__(self):
            self.results = []

        def record_race_result(self, program_id, rank):
            self.results.append((program_id, rank))

    class Client:
        api_jitter = 0

        def race_entry(self, **payload):
            return {"data": {"chara_info": {"turn": 12, "playing_state": 2}}}

        def race_start(self, **payload):
            return {"data": {}}

        def race_end(self, **payload):
            return {"data": {"chara_info": {"turn": 12, "playing_state": 4}}}

        def race_out(self, **payload):
            return {"data": {"chara_info": {"turn": 13, "playing_state": 1}}}

    runner = CareerRunner('/nonexistent')
    runner.burn_clocks = False
    runner.status = {"scenario_id": 2, "turn": 12, "log": [], "clocks_used": 0}
    runner._parse_race_rank = lambda _response: 2
    strategy = Strategy()

    runner._race(
        Client(),
        {"data": {"chara_info": {"turn": 12}, "home_info": {}}},
        {"scenario_id": 2},
        {"program_id": 1070, "current_turn": 12, "_strategy": strategy},
    )

    assert strategy.results == [(1070, 2)]


if __name__ == "__main__":
    unittest.main()
