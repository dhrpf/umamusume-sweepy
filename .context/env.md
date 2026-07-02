# Environment Var Reference

Each var — name, default, gated behavior, file ref.

| Var | Default | Gates | Ref |
|---|---|---|---|
| `UMA_MASTER_MDB` | unset | absolute path to `master.mdb`; bypasses compatdata + settings lookup | `career_bot/master_data.py:32,74` |
| `LOCALAPPDATA` | unset | Windows-only anchor for `%LOCALAPPDATA%\..\LocalLow\Cygames\Umamusume\master\master.mdb` | `career_bot/master_data.py:36` |
| `UMA_RUNTIME_DIR` | unset | runtime root: auth cache, bot logs, steam tickets | `career_bot/runner.py:32`, `uma_api/client.py:32`, `launcher.py:30` |
| `SWEEPY_DEBUG` | unset | extra debug logging in runner + URA strategy (truthy triggers) | `career_bot/runner.py:259,300`, `career_bot/scenarios/ura.py:280,732` |
| `UMA_PROCESS_NAME` | `UmamusumePrettyDerby.exe` | Frida process name/substring to attach | `main.py:28` |
| `PORT` | `1616` | FastAPI bind port | `main.py:180` |
| `SWEEPY_AUTH_CAPTURE_TIMEOUT_SEC` | `120` capture-login, `180` refresh-before-serving | seconds to wait for Frida TLS auth capture | `main.py:1565,1581,2529` |
| `FRIDA_REMOTE` | unset | remote Frida `host:port`; unset = local frida-server | `capture_dailies.py:877`, `main.py:1589,2556` |

## Semantics

- `UMA_MASTER_MDB` expanduser'd. Override when compatdata path moves between Steam updates.
- `UMA_RUNTIME_DIR` overrides `runtime_output_root()` (which otherwise walks up to first `.git` parent).
- `SWEEPY_DEBUG` is value-less: *presence* triggers. Never set `=0` expecting off.
- `UMA_PROCESS_NAME` is a *substring* match in `frida-ps` — use partial name to avoid Wine prefix path coupling.
- `FRIDA_REMOTE` vs local: client.py emits `FRIDARemote` env gate; never auto-detect when set (api.md rule 13).

## Common Overrides

Dev with non-standard Steam library:
```bash
UMA_MASTER_MDB="$HOME/.steam/root/steamapps/compatdata/3224770/pfx/..." python main.py
```

Debug a single URA run:
```bash
SWEEPY_DEBUG=1 python main.py
```

Remote Frida already running on another host:
```bash
FRIDA_REMOTE=10.0.0.5:27042 python main.py
```
