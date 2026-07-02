import pytest

pytest.importorskip('msgpack')

from career_bot.runner import CareerRunner
from career_bot.scenarios.base import Decision


def test_record_action_keeps_decision_metadata():
    runner = CareerRunner('/nonexistent')
    runner.report = {'turns': []}
    decision = Decision('command', {
        'command_type': 1,
        'command_id': 101,
        'command_group_id': 0,
        'select_id': 0,
        'current_turn': 7,
        'current_vital': 55,
        'decision_detail': {'score': 12.3},
        'decision_options': [{'score': 12.3}],
    }, 'Speed +30 sc=12.3')

    runner._record_action(decision, {'vital': 55, 'max_vital': 100})

    turn = runner.report['turns'][0]
    assert turn['decision_detail'] == {'score': 12.3}
    assert turn['decision_options'] == [{'score': 12.3}]
    assert runner.status['action_history'][0]['facility'] == 'Speed'


def test_command_api_payload_strips_decision_metadata():
    payload = {
        'command_type': 1,
        'command_id': 101,
        'current_turn': 7,
        'decision_detail': {'score': 12.3},
        'decision_options': [{'score': 12.3}],
    }
    payload.pop('decision_detail', None)
    payload.pop('decision_options', None)
    assert payload == {'command_type': 1, 'command_id': 101, 'current_turn': 7}
