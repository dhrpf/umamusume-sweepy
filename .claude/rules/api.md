# Rule: API / Crypto / Frida / Device Spoofing

Paths: `uma_api/**`, `capture_dailies.py`, `launcher.py`

## Protocol

1. All wire payloads go through `pack()` / `unpack()` — construct the AES key per call, never reuse across SID.
2. SID regen: `make_sid(viewer_id, udid)` for first call, `next_sid(sid)` for subsequent. Never call `regen_sid()` inside a retry except after 208.
3. Proxy errors by code family: 205 (per-call transient), 208 (busy), 214 (res_ver stale), 217 (resource busy), 1055 (session stale). Never swallow 102/1503 — these are logic errors.
4. `response_code`/`result_code` live in `response.data_headers`, NOT top-level. Read via `res["data_headers"]["result_code"]`.
5. Auth header triplet: `SID`, `Device`, `ViewerID`, `APP-VER`, `RES-VER`. Missing any = immediate 102.

## Crypto Primitives

6. `sm5` = MD5 with the in-binary salt. Never substitute SHA or raw MD5.
7. AES key = last 32 bytes of the decoded server response body. IV = first 16 hex chars of udid (lowercase, no dashes).
8. `struct.pack('<I', len)` prefix before msgpack payload. Older captures may omit it — `_normalize_api_body` handles both.

## Device Spoofing

9. `get_hwid()` reads from `/sys/class/dmi/id/` on Linux, registry on Windows. Don't hard-code one path.
10. `get_gpu()` calls `lspci`. Never add a new GPU table entry without verifying `lspci -v` output first.
11. `get_os()` returns platform OS string; must match Unity format. Tweak regex, not the raw API strings.
12. `runtime_output_root()` walks up to the first `.git` parent. Don't cache after a chdir.

## API Schemas

Live schemas at `.context/api_schemas/` (symlink to `docs/api_schemas/`). Read `.context/api_schemas/index.md` for the endpoint list, then pull the relevant `.json`/`.md` per route when implementing or modifying any client call.

## Frida / Auth Capture

13. `FRIDARemote` env var selects remote vs local. Don't auto-detect when FRIDA_REMOTE set.
14. Auth capture timeout: `SWEEPY_AUTH_CAPTURE_TIMEOUT_SEC` (default 120/180). Don't lower without logs showing the game needs it.
15. frida-server must be running inside the Proton Wine prefix. Process appears as `S:\common\UmamusumePrettyDerby\UmamusumePrettyDerby.exe` in `frida-ps`; match by substring.
16. `capture_login()` → `auto_login_from_cache()` → `refresh_auth_before_serving()` is the startup waterfall. Reorder only if you know which step you're bypassing.
17. Pipe Frida console through stderr for watchpoints; keep stdout for JSON payload capture.
