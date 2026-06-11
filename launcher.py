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
