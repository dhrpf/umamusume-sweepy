"""One-off: collect an expired ghost idle_single_mode career.

The runner parks a run in NEEDS_ATTENTION ("collection result is
ambiguous; end will not be retried") when idle_single_mode/end fails,
but its retry path only probes idle_single_mode/result which answers
217 for an expired window.  The slot then stays occupied (start -> 102).

This script logs in from the auth cache and calls idle_single_mode/end
directly, which is the call the runner refuses to retry.  Nothing else
is touched.  Prints the response summary.
"""
import json
import sys

from career_bot.delay import GateKeeper
from uma_api.client import (
    UmaClient,
    get_ticket,
    _steam_keyfile_path,
    runtime_output_root,
)


def main():
    cfg_path = runtime_output_root() / 'auth_cache.json'
    cfg = json.loads(cfg_path.read_text(encoding='utf-8'))
    username = cfg.get('steam_username', '')
    password = cfg.get('steam_password_seed', '')
    if not username or not _steam_keyfile_path(username).exists():
        print('No usable steam credentials in auth cache. Aborting.')
        return 1
    sid, tkt = get_ticket(username, password)
    cfg.update({'steam_id': sid, 'steam_session_ticket': tkt})
    raw = UmaClient(cfg, trace_enabled=True)
    client = GateKeeper(raw)
    if not client.login():
        print('Game login failed.')
        return 1

    res = client.call('load/index', {'adid': ''})
    info = (res.get('data') or {}).get('idle_single_mode_load_info') or {}
    light = info.get('single_mode_chara_light') or {}
    if not light:
        print('No ghost career in load/index — slot appears clear. Aborting.')
        return 1
    print('ghost window:', json.dumps({
        'single_mode_chara_id': light.get('single_mode_chara_id'),
        'card_id': light.get('card_id'),
        'scenario_id': light.get('scenario_id'),
        'start_time': info.get('start_time'),
        'end_time': info.get('end_time'),
        'playing_state': info.get('playing_state'),
    }))

    end = client.call('idle_single_mode/end', {})
    chara = (end.get('data') or {}).get('single_mode_chara_light') or \
            (end.get('data') or {}).get('chara_info') or {}
    print('end rc:', end.get('response_code'), 'result_code:',
          end.get('result_code'))
    print('chara:', json.dumps({
        k: chara.get(k)
        for k in ('single_mode_chara_id', 'card_id', 'turn', 'fans')
        if k in chara
    }))

    try:
        client.call('idle_single_mode/check_progress_log', {})
        print('progress_log: acked')
    except Exception as exc:
        print(f'progress_log: failed ({exc}) — slot may still be occupied')

    load2 = client.call('load/index', {'adid': ''})
    info2 = (load2.get('data') or {}).get('idle_single_mode_load_info') or {}
    print('post-end idle_single_mode_load_info:',
          json.dumps(info2.get('single_mode_chara_light')) or 'clear')
    return 0


if __name__ == '__main__':
    sys.exit(main())
