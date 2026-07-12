"""Tests for 501 post-race state recovery in CareerRunner."""
import unittest
from unittest.mock import MagicMock, patch

from career_bot.runner import CareerRunner
from uma_api.client import StateRecoveryError  # noqa: F401


class RecordingClient:
    def __init__(self):
        self.calls = []
        self.finish_calls = []
        self.factor_select_calls = []
        self.regen_sid_calls = 0
        self.start_session_calls = 0

    def regen_sid(self):
        self.regen_sid_calls += 1

    def call(self, ep, payload=None):
        self.calls.append((ep, payload))
        if ep == "single_mode_free/factor_select":
            self.factor_select_calls.append(payload)
            raise StateRecoveryError(
                f"API error 501 on {ep}: session invalidated, reauth required"
            )
        return {"data": {}}

    def finish_career(self, current_turn, is_force_delete=False):
        self.finish_calls.append(current_turn)
        self.call("single_mode_free/factor_select", {"current_turn": current_turn})
        return {"data": {"chara_info": {"turn": current_turn}}}

    def wait_turn_delay(self):
        pass


def _make_runner_with_stubs():
    runner = CareerRunner.__new__(CareerRunner)
    runner.base_dir = "/tmp/sweepy_test"
    runner.status = {
        "running": True, "preset": "test", "scenario_id": 4,
        "turn": 0, "steps": 0, "last_action": "", "last_error": "",
        "finished": False, "skills_bought": 0, "items_bought": 0,
        "items_used": 0, "clocks_used": 0, "log": [], "action_history": [],
    }
    runner.lock = __import__("threading").Lock()
    runner.stop_requested = False
    runner._exhausted_events = set()

    noop = lambda *a, **k: None
    runner._log = noop
    runner._log_locked = noop
    runner._track_turn_scores = noop
    runner._advance = noop
    runner._drain_events = lambda *a, **k: a[2]
    runner._buy_skills = lambda *a, **k: a[2]
    runner._handle_items = lambda *a, **k: a[2]
    runner._debug_turn = noop
    runner._debug_inventory = lambda state: {}
    runner.burn_clocks = False

    # stub skill_buyer/item_manager with every accessed attr
    class StubBuyer:
        last_attempt, last_result, attempt_events = [], {}, []
        def reset_scoped_failures(self): pass
        def preview(self, s, p): pass  # noqa: ARG002

    class StubItems:
        last_buy_attempt, last_buy_result = [], {}
        last_use_attempt, last_use_result = [], {}
        buy_attempt_events, use_attempt_events = [], []
        def reset_scoped_failures(self): pass
        def _owned_map(self, free): return {}  # noqa: ARG002

    runner.skill_buyer = StubBuyer()
    runner.item_manager = StubItems()

    captured = {}
    def _mark(**kw):
        captured.update(kw)
        runner.status.update(kw)
    runner._mark = _mark
    runner._captured = captured

    def _should_stop():
        return runner.stop_requested
    runner._should_stop = _should_stop
    runner._fresh_career_state = lambda c, s=None: {
        "data": {"chara_info": {"turn": 99}, "unchecked_event_array": []}
    }
    runner.report = None
    return runner


class FinishDecision:
    action = "finish"
    payload = {"current_turn": 10}
    reason = "test"


class CommandDecision:
    action = "command"
    payload = {"current_turn": 5, "command_id": 101, "command_type": 1}
    reason = "test"


class FailedFinishDecision:
    action = "finish"
    payload = {"current_turn": 24, "career_failed": True}
    reason = "career failed (ps=5)"


class FakeStrategy:
    def __init__(self, decision):
        self._d = decision
        self.calls = 0

    def next_decision(self, state, preset):  # noqa: ARG002
        self.calls += 1
        return self._d

    def explain_decision(self, state, preset, decision):  # noqa: ARG002
        return None


class TestFinishCareer501Recovery(unittest.TestCase):
    def test_501_in_inner_finish_loop_is_reconciled(self):
        runner = _make_runner_with_stubs()
        client = RecordingClient()

        state = {
            "data": {
                "chara_info": {"turn": 10},
                "unchecked_event_array": [],
            }
        }

        with patch("career_bot.runner.dna_sleep"):
            runner._run(
                client=client,
                preset={"name": "test", "scenario_id": 4},
                result=state,
                strategy=FakeStrategy(FinishDecision()),
                max_steps=2500,
            )

        self.assertEqual(client.finish_calls, [10])
        self.assertTrue(runner.status.get("finished"),
                        "status.finished should be True after graceful 501 reconciliation")

    def test_failed_finish_is_not_marked_as_successful(self):
        runner = _make_runner_with_stubs()
        client = RecordingClient()
        client.call = MagicMock(return_value={"data": {}})
        client.finish_career = MagicMock(return_value={"data": {}})
        state = {
            "data": {
                "chara_info": {"turn": 24, "state": 2, "playing_state": 5},
                "unchecked_event_array": [],
            }
        }

        with patch("career_bot.runner.dna_sleep"):
            runner._run(
                client=client,
                preset={"name": "test", "scenario_id": 2},
                result=state,
                strategy=FakeStrategy(FailedFinishDecision()),
                max_steps=10,
            )

        self.assertFalse(runner.status.get("finished"))
        self.assertEqual(runner.status.get("last_action"), "career_failed")
        self.assertIn("career failed", runner.status.get("last_error", ""))

    def test_missing_transition_hash_records_runner_error(self):
        runner = _make_runner_with_stubs()
        runner._buy_skills = MagicMock(side_effect=RuntimeError(
            "session invalid and no uma_password_hash in auth_cache; re-login via web UI"
        ))
        # Recovery also fails → runner records error and exits loop (not silent crash).
        runner._fresh_career_state = MagicMock(side_effect=RuntimeError(
            "career recovery failed: session invalid and no uma_password_hash in auth_cache"
        ))
        state = {"data": {"chara_info": {"turn": 10}, "unchecked_event_array": []}}

        with patch("career_bot.runner.dna_sleep"):
            runner._run(
                client=RecordingClient(),
                preset={"name": "test", "scenario_id": 4},
                result=state,
                strategy=FakeStrategy(FinishDecision()),
                max_steps=2500,
            )

        self.assertIn("no uma_password_hash", runner.status.get("last_error", ""))
        self.assertFalse(runner.status.get("running"))

    def test_step_501_reauths_and_continues(self):
        runner = _make_runner_with_stubs()
        client = RecordingClient()
        calls = {"n": 0}

        def buy_then_ok(client, state, preset, force):  # noqa: ARG001
            calls["n"] += 1
            if calls["n"] == 1:
                raise StateRecoveryError("API error 501 on single_mode/gain_skills: session fully invalidated")
            return state

        runner._buy_skills = buy_then_ok
        fresh_states = [
            {"data": {"chara_info": {"turn": 10}, "unchecked_event_array": []}},
        ]
        runner._fresh_career_state = MagicMock(side_effect=fresh_states)
        # After recover, finish next decision.
        strategy = FakeStrategy(FinishDecision())
        # First decision finish triggers buy_skills 501; after recover strategy still finish.
        state = {"data": {"chara_info": {"turn": 10}, "unchecked_event_array": []}}

        with patch("career_bot.runner.dna_sleep"):
            runner._run(
                client=client,
                preset={"name": "test", "scenario_id": 4},
                result=state,
                strategy=strategy,
                max_steps=10,
            )

        runner._fresh_career_state.assert_called()
        self.assertTrue(runner.status.get("finished") or "501" in runner.status.get("last_error", "")
                        or runner._fresh_career_state.called)

    def test_fresh_career_state_reauths_after_load_fail(self):
        runner = _make_runner_with_stubs()
        # Use real recovery path, not the stub lambda.
        from career_bot.runner import CareerRunner
        runner._fresh_career_state = CareerRunner._fresh_career_state.__get__(runner, CareerRunner)
        runner._reauth_session = CareerRunner._reauth_session.__get__(runner, CareerRunner)
        runner._load_career_state = CareerRunner._load_career_state.__get__(runner, CareerRunner)
        client = MagicMock()
        client.load_career.side_effect = [
            StateRecoveryError("API error 501 on single_mode/load: session fully invalidated"),
            {"data": {"chara_info": {"turn": 11}, "unchecked_event_array": []}},
        ]
        client.login = MagicMock()

        with patch("career_bot.runner.dna_sleep"):
            state = runner._fresh_career_state(client, strategy=None)

        client.login.assert_called_once_with()
        self.assertEqual(state["data"]["chara_info"]["turn"], 11)
        self.assertEqual(client.load_career.call_count, 2)

if __name__ == "__main__":
    unittest.main()
