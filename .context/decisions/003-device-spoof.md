ADR-003: Device spoof — real hardware fields

Context
  API expects Unity client fingerprint (viewer_id, device=4, device_id, device_name, graphics_device_name, ip_address, platform_os_version, steam_id, steam_ticket).

Decision
  - `get_hwid()`: BIOS/DMI product name + board_vendor + machine-id → SHA-1 with seed string into device_id.
  - GPU: `lspci -mm` (Linux) or Windows Display Adapter registry.
  - OS: Unity-formatted string via regex tweak, not raw API override.
  - IP: UDP socket connect to 8.8.8.8.
  - All payloads carry these via `common()`.

Consequences
  - Hard-crash on missing DMI name (refuse to start).
  - `get_gpu()` calls `lspci` live — never hardcode GPU table.
  - `get_os()` tuned via regex, not modifying Unity format.

See: `uma_api/client.py:383-455,681-690`
