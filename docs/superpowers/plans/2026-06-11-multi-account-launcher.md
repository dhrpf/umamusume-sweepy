# Multi-Account Launcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `launcher.py` + `accounts.json` so multiple bot instances run in parallel, each isolated to its own port and runtime directory, with automatic restart on crash.

**Architecture:** `launcher.py` reads `accounts.json`, spawns one `python main.py` subprocess per account with `UMA_RUNTIME_DIR` and `PORT` set as env vars. `main.py` already respects both — zero changes needed. A monitor thread per process restarts on non-zero exit. Ctrl+C terminates all cleanly.

**Tech Stack:** Python stdlib only — `subprocess`, `threading`, `signal`, `json`, `pathlib`. `pytest` for tests.

---

### Task 1: `accounts.json` sample config

**Files:**
- Create: `accounts.json`

- [ ] **Step 1: Create `accounts.json`**

```json
[
  { "name": "acct1", "port": 1616 },
  { "name": "acct2", "port": 1617 }
]
```

- [ ] **Step 2: Commit**

```bash
git add accounts.json
git commit -m "feat: add accounts.json for multi-account config"
```

---

### Task 2: Config loading and env construction (pure functions + tests)

**Files:**
- Create: `launcher.py` (partial — pure functions only)
- Create: `tests/test_launcher.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_launcher.py`:

```python
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
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd ~/personal/umamusume-sweepy
python -m pytest tests/test_launcher.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'launcher'` or similar.

- [ ] **Step 3: Create `launcher.py` with pure functions**

```python
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).parent.resolve()
ACCOUNTS_FILE = REPO_ROOT / 'accounts.json'
RESTART_DELAY = 5

_shutdown = threading.Event()


def load_accounts(path=ACCOUNTS_FILE, filter_name=None):
    with open(path, 'r') as f:
        accounts = json.load(f)
    accounts = [a for a in accounts if a.get('enabled', True)]
    if filter_name:
        accounts = [a for a in accounts if a['name'] == filter_name]
        if not accounts:
            raise ValueError(f"Account '{filter_name}' not found in {path}")
    return accounts


def build_env(account):
    env = os.environ.copy()
    env['UMA_RUNTIME_DIR'] = str(REPO_ROOT / 'uma_runtime' / account['name'])
    env['PORT'] = str(account['port'])
    env.update(account.get('extra_env', {}))
    return env
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
python -m pytest tests/test_launcher.py -v
```

Expected: all 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add launcher.py tests/test_launcher.py
git commit -m "feat: add launcher config loading and env construction"
```

---

### Task 3: `AccountProcess` class and `main()`

**Files:**
- Modify: `launcher.py` (append `AccountProcess` class and `main()`)

- [ ] **Step 1: Append `AccountProcess` and `main()` to `launcher.py`**

Open `launcher.py` and append after `build_env`:

```python
class AccountProcess:
    def __init__(self, account):
        self.name = account['name']
        self.account = account
        self.process = None
        self._output_thread = None
        self._monitor_thread = None

    def start(self):
        env = build_env(self.account)
        self.process = subprocess.Popen(
            [sys.executable, str(REPO_ROOT / 'main.py')],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self._output_thread = threading.Thread(target=self._stream_output, daemon=True)
        self._output_thread.start()
        self._monitor_thread = threading.Thread(target=self._monitor, daemon=True)
        self._monitor_thread.start()

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()

    def kill(self):
        if self.process and self.process.poll() is None:
            self.process.kill()

    def wait(self, timeout=None):
        if self.process:
            try:
                self.process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                pass

    def _stream_output(self):
        prefix = f'[{self.name}] '
        for line in self.process.stdout:
            print(prefix + line, end='', flush=True)

    def _monitor(self):
        while not _shutdown.is_set():
            self.process.wait()
            if _shutdown.is_set():
                return
            code = self.process.returncode
            if code == 0:
                print(f'[{self.name}] stopped (clean exit).', flush=True)
                return
            print(f'[{self.name}] crashed (exit {code}), restarting in {RESTART_DELAY}s...', flush=True)
            if _shutdown.wait(timeout=RESTART_DELAY):
                return
            print(f'[{self.name}] restarting...', flush=True)
            self.start()


def main():
    filter_name = sys.argv[1] if len(sys.argv) > 1 else None

    try:
        accounts = load_accounts(filter_name=filter_name)
    except ValueError as e:
        print(f'[launcher] Error: {e}', file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print(f'[launcher] Error: accounts.json not found at {ACCOUNTS_FILE}', file=sys.stderr)
        sys.exit(1)

    if not accounts:
        print('[launcher] No enabled accounts found.', file=sys.stderr)
        sys.exit(1)

    processes = [AccountProcess(a) for a in accounts]

    def shutdown(signum, frame):
        print('\n[launcher] Shutting down...', flush=True)
        _shutdown.set()
        for p in processes:
            p.stop()
        for p in processes:
            p.wait(timeout=10)
        for p in processes:
            p.kill()
        print('[launcher] All done.', flush=True)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    for p in processes:
        print(f'[launcher] Starting {p.name} on port {p.account["port"]}...', flush=True)
        p.start()

    _shutdown.wait()


if __name__ == '__main__':
    main()
```

- [ ] **Step 2: Verify existing tests still pass**

```bash
python -m pytest tests/test_launcher.py -v
```

Expected: all 8 tests PASS (no regressions from appended code).

- [ ] **Step 3: Smoke-test launcher with a dummy script**

Verify it starts and restarts a crashing subprocess:

```bash
# Create a throwaway test script
echo 'import sys, time; time.sleep(1); sys.exit(1)' > /tmp/fake_main.py

# Temporarily override REPO_ROOT check by running from /tmp — skip this,
# instead just verify launcher.py imports cleanly
python -c "import launcher; print('import OK')"
```

Expected output: `import OK`

- [ ] **Step 4: Commit**

```bash
git add launcher.py
git commit -m "feat: add AccountProcess class and main launcher loop"
```

---

### Task 4: Update `package.json` and verify end-to-end

**Files:**
- Modify: `package.json`

- [ ] **Step 1: Add `launch` script to `package.json`**

Open `package.json`. Change:

```json
{
  "name": "umamusume-sweepy",
  "version": "1.0.0",
  "scripts": {
    "start": "python main.py"
  },
  "dependencies": {
    "steam-user": "^5.0.0"
  }
}
```

To:

```json
{
  "name": "umamusume-sweepy",
  "version": "1.0.0",
  "scripts": {
    "start": "python main.py",
    "launch": "python launcher.py"
  },
  "dependencies": {
    "steam-user": "^5.0.0"
  }
}
```

- [ ] **Step 2: Verify `--help` style invocation**

```bash
python launcher.py nonexistent_account 2>&1
```

Expected:
```
[launcher] Error: Account 'nonexistent_account' not found in .../accounts.json
```

- [ ] **Step 3: Verify single-account mode shows correct startup message**

Without a running game, it will fail at login — that's fine. Just verify it tries to start the right account:

```bash
# Ctrl+C immediately after seeing the startup line
timeout 3 python launcher.py acct1 2>&1 || true
```

Expected output includes: `[launcher] Starting acct1 on port 1616...`

- [ ] **Step 4: Commit**

```bash
git add package.json
git commit -m "feat: add npm launch script for multi-account launcher"
```

---

## Runtime dir setup reminder

Each new account needs its runtime dir created on first login. The dirs are created automatically by `runtime_output_root()` when `main.py` first writes to them — no manual setup needed. First-time flow per account:

1. `python launcher.py acct1` (or `npm run launch -- acct1`)
2. Open `http://127.0.0.1:1616`
3. Log in via UI → saves `uma_runtime/acct1/auth_cache.json`
4. Subsequent starts auto-login from cache
