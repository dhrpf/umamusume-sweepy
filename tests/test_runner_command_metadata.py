import pytest

pytest.importorskip('msgpack')

from career_bot.runner import CareerRunner
from career_bot.report import add_decision
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

    add_decision(runner.report, {"data": {"chara_info": {"turn": 7}}}, decision)
    runner._record_action(decision, {'vital': 55, 'max_vital': 100})

    turn = runner.report['turns'][0]
    assert turn['decision_detail'] == {'score': 12.3}
    assert turn['decision_options'] == [{'score': 12.3}]
    assert runner.status['action_history'][0]['facility'] == 'Speed'


def test_record_action_replaces_duplicate_history_row():
    runner = CareerRunner('/nonexistent')
    decision = Decision('command', {
        'command_type': 1,
        'command_id': 101,
        'current_turn': 7,
    }, 'first')

    runner._record_action(decision, {'vital': 55, 'max_vital': 100})
    runner._record_action(decision, {'vital': 44, 'max_vital': 100})

    assert len(runner.status['action_history']) == 1
    assert runner.status['action_history'][0]['stats']['hp'] == 44


def test_run_strips_decision_metadata_from_command_payload(monkeypatch, tmp_path):
    class Client:
        def __init__(self):
            self.payload = None

        def exec_command(self, **payload):
            self.payload = payload
            return {'data': {'chara_info': {'turn': 8}, 'home_info': {'command_info_array': []}}}

    class Strategy:
        def next_decision(self, state, preset):
            return Decision('command', {
                'command_type': 1,
                'command_id': 101,
                'current_turn': 7,
                'decision_detail': {'score': 12.3},
                'decision_options': [{'score': 12.3}],
            }, 'Speed +30 sc=12.3')

    import career_bot.runner as runner_module

    client = Client()
    runner = CareerRunner(tmp_path)
    runner.status['running'] = True
    runner.report = {'turns': []}
    runner._buy_skills = lambda client, state, preset, force: state
    monkeypatch.setattr(runner_module, 'write_report', lambda report, output_dir: tmp_path / 'career_log.json')

    runner._run(
        client,
        {'scenario_id': 1},
        {'data': {'chara_info': {'turn': 7}, 'home_info': {'command_info_array': []}}},
        Strategy(),
        max_steps=1,
    )

    assert client.payload == {'command_type': 1, 'command_id': 101, 'current_turn': 7}
