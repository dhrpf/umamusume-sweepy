import json
import os
import pytest
from pathlib import Path


def test_load_accounts_returns_all(tmp_path):
    cfg = tmp_path / 'accounts.json'
    cfg.write_text(json.dumps([
        {'name': 'acct1', 'port': 1616},
        {'name': 'acct2', 'port': 1617},
    ]))
    import launcher
    result = launcher.load_accounts(cfg)
    assert len(result) == 2
    assert result[0]['name'] == 'acct1'
    assert result[1]['name'] == 'acct2'


def test_load_accounts_filter_by_name(tmp_path):
    cfg = tmp_path / 'accounts.json'
    cfg.write_text(json.dumps([
        {'name': 'acct1', 'port': 1616},
        {'name': 'acct2', 'port': 1617},
    ]))
    import launcher
    result = launcher.load_accounts(cfg, filter_name='acct2')
    assert len(result) == 1
    assert result[0]['name'] == 'acct2'


def test_load_accounts_filter_not_found_raises(tmp_path):
    cfg = tmp_path / 'accounts.json'
    cfg.write_text(json.dumps([{'name': 'acct1', 'port': 1616}]))
    import launcher
    with pytest.raises(ValueError, match="Account 'nope' not found"):
        launcher.load_accounts(cfg, filter_name='nope')


def test_load_accounts_skips_disabled(tmp_path):
    cfg = tmp_path / 'accounts.json'
    cfg.write_text(json.dumps([
        {'name': 'acct1', 'port': 1616, 'enabled': False},
        {'name': 'acct2', 'port': 1617},
    ]))
    import launcher
    result = launcher.load_accounts(cfg)
    assert len(result) == 1
    assert result[0]['name'] == 'acct2'


def test_build_env_sets_runtime_dir():
    import launcher
    account = {'name': 'acct1', 'port': 1616}
    env = launcher.build_env(account)
    expected = str(launcher.REPO_ROOT / 'uma_runtime' / 'acct1')
    assert env['UMA_RUNTIME_DIR'] == expected


def test_build_env_sets_port_as_string():
    import launcher
    account = {'name': 'acct1', 'port': 1616}
    env = launcher.build_env(account)
    assert env['PORT'] == '1616'


def test_build_env_applies_extra_env():
    import launcher
    account = {'name': 'acct1', 'port': 1616, 'extra_env': {'FRIDA_REMOTE': '127.0.0.1:27042'}}
    env = launcher.build_env(account)
    assert env['FRIDA_REMOTE'] == '127.0.0.1:27042'


def test_build_env_inherits_os_env(monkeypatch):
    import launcher
    monkeypatch.setenv('SOME_EXISTING_VAR', 'hello')
    account = {'name': 'acct1', 'port': 1616}
    env = launcher.build_env(account)
    assert env['SOME_EXISTING_VAR'] == 'hello'
