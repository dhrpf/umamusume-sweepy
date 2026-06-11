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
