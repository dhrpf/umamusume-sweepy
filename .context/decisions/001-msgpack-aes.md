ADR-001: msgpack+AES-CBC over JSON/mjson

Context
  Game wire protocol; need auth + reversible format.

Decision
  msgpack body → struct.pack('<I', len) prefix + AES-256-CBC encrypt.
  Key = random 32 bytes embedded in response body tail. IV = first 16 hex chars of udid (lowercase, no dashes).
  sm5 = MD5 + binary salt `b'co!=Y;(UQCGxJ_n82'` for SID derivation.
    - first call: `sm5(viewer_id + udid)`
    - subsequent: `sm5(sid.encode())`

Consequences
  - Older captures omit the uint32 prefix → `_normalize_api_body` + try/except in `unpack()` handles both.
  - Server responses have plaintext prefix before msgpack stream → locate via `b'data_headers'` offset.
  - Never substitute SHA or raw MD5 for sm5.

See: `uma_api/client.py:159,204-214,228-310`
