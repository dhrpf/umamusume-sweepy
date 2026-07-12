# Environment Var Reference

| Variable | Default | Purpose | Source |
|---|---|---|---|
| `UMA_MASTER_MDB` | unset | Override `master.mdb` location | `career_bot.master_data` |
| `LOCALAPPDATA` | unset | Windows master-data discovery anchor | `career_bot.master_data` |
| `UMA_RUNTIME_DIR` | unset | Runtime root for auth cache, reports, trace logs, Steam refresh tokens | `main.py`, `UmaClient`, runner/report paths |
| `SWEEPY_DEBUG` | unset | Extra runner and strategy debug logging | runner, URA strategy |
| `UMA_PROCESS_NAME` | `UmamusumePrettyDerby.exe` | Frida target process substring | `main.py` |
| `PORT` | `1616` | FastAPI bind port | `main.py` |
| `SWEEPY_AUTH_CAPTURE_TIMEOUT_SEC` | capture/login defaults | Frida auth-capture deadline | `main.py` |
| `FRIDA_REMOTE` | unset | Remote Frida `host:port`; unset uses local path | capture/login flow |

## Rules

- `UMA_RUNTIME_DIR` changes `runtime_output_root()`. It controls `auth_cache.json`, bot logs, Steam refresh tokens, and other runtime artifacts in `main.py`, `UmaClient`, and runner/report code.
- `UMA_MASTER_MDB` wins over automatic Proton/Windows discovery. Confirm file mtime after game patch.
- `FRIDA_REMOTE` is explicit. Never auto-detect a different Frida mode when it is set.
- `SWEEPY_DEBUG` is truthy-by-presence; unset it to disable.

## Examples

```bash
UMA_MASTER_MDB="$HOME/path/to/master.mdb" python main.py
FRIDA_REMOTE=10.0.0.5:27042 python main.py
UMA_RUNTIME_DIR="$HOME/.local/share/sweepy-runtime" python main.py
```
