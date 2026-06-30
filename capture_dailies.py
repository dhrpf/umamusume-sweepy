#!/usr/bin/env python3
"""Frida-based Umamusume API call capture using Unity TLS interface hook.

Hooks il2cpp_unity_install_unitytls_interface to intercept ALL HTTP
requests/responses in plaintext BEFORE TLS encryption. Captures both
decrypted payloads (JSON) and raw encrypted bodies for later replay.

Usage:
    FRIDA_REMOTE=127.0.0.1:27042 ./capture_dailies.py output.json [udid]

If udid is provided, skips auth cache lookup — useful when game auth
isn't cached yet or you want to capture for a different account.
"""

import json
import os
import signal
import sys
import threading
import time

import frida

TARGET = "UmamusumePrettyDerby"

OUTPUT = sys.argv[1] if len(sys.argv) > 1 else "captured_calls.json"
CLI_UDID = sys.argv[2] if len(sys.argv) > 2 else None

JS_CAPTURE = r"""
'use strict';
(function() {
    var buffers = {};
    var attached = {};
    var callId = 0;
    var lastReqEndpoint = {};  // key -> last request endpoint
    var _readBytes = 0, _readCount = 0;  // DIAG: read-hook delivery tally
    var _writeBytes = 0, _writeCount = 0;  // DIAG: write-hook delivery tally

    function hex2(n) { return ('0' + (n & 255).toString(16)).slice(-2); }

    function uuidFromHex(h) {
        return h.substring(0,8)+'-'+h.substring(8,12)+'-'+h.substring(12,16)+'-'+h.substring(16,20)+'-'+h.substring(20);
    }

    function b64decode(s) {
        var chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
        var out = []; var buf = 0; var bits = 0;
        for (var i = 0; i < s.length; i++) {
            var c = s.charAt(i);
            if (c === '=') break;
            var idx = chars.indexOf(c);
            if (idx < 0) continue;
            buf = (buf << 6) | idx; bits += 6;
            if (bits >= 8) { bits -= 8; out.push((buf >> bits) & 255); }
        }
        return out;
    }

    function extractUdid(decoded, headerLen) {
        var blob1End = 4 + headerLen;
        if (decoded.length < blob1End) return null;
        var udidHex = '';
        for (var i = blob1End - 96; i < blob1End - 80; i++) udidHex += hex2(decoded[i]);
        if (udidHex.length !== 32) return null;
        return uuidFromHex(udidHex);
    }

    // Parse a complete HTTP request (plaintext before TLS)
    function parseHttp(buf, isRes, key) {
        var text = '';
        for (var i = 0; i < buf.length; i++) text += String.fromCharCode(buf[i]);

        if (isRes) {
            // Response: HTTP/1.1 200 OK
            var lm = text.match(/HTTP\/\d\.\d\s+(\d+)/);
            if (!lm) return false;
            var httpStatus = parseInt(lm[1], 10);
            var headerEnd = text.indexOf('\r\n\r\n');
            if (headerEnd < 0) return false;
            var bodyStart = headerEnd + 4;
            var clMatch = text.substring(0, headerEnd).match(/Content-Length:\s*(\d+)/i);
            var length = clMatch ? parseInt(clMatch[1], 10) : 0;
            // Partial body OK — emit what we have
            var body = text.substring(bodyStart, bodyStart + (length > 0 ? length : buf.length));
            // Get endpoint from last request on this key
            var endpoint = lastReqEndpoint[key] || '';
            var udid = null;
            var rawBytes = b64decode(body.trim());
            if (rawBytes.length >= 4) {
                var headerLen = rawBytes[0] | (rawBytes[1] << 8) | (rawBytes[2] << 16) | (rawBytes[3] << 24);
                if (headerLen >= 120 && headerLen <= 2048) udid = extractUdid(rawBytes, headerLen);
            }
            send({type: '_diag', from: 'parseHttp', endpoint: endpoint, bodyLen: body.trim().length});
            send({
                type: 'res',
                endpoint: endpoint,
                http_status: httpStatus,
                body: body.trim(),
                udid: udid,
                ts: Date.now()
            });
            return true;
        } else {
            // Request: POST /umamusume/{endpoint} HTTP/1.1
            var lm = text.match(/POST\s+\/umamusume\/(\S+)\s+HTTP/);
            if (!lm) return false;
            var endpoint = lm[1];
            lastReqEndpoint[key] = endpoint;
            var headerEnd = text.indexOf('\r\n\r\n');
            if (headerEnd < 0) return false;
            var bodyStart = headerEnd + 4;
            var clMatch = text.substring(0, headerEnd).match(/Content-Length:\s*(\d+)/i);
            var length = clMatch ? parseInt(clMatch[1], 10) : 0;
            if (length > 0 && buf.length < bodyStart + length) return false; // incomplete
            var body = text.substring(bodyStart, bodyStart + (length > 0 ? length : buf.length));
            var udid = null;
            var rawBytes = b64decode(body.trim());
            if (rawBytes.length >= 4) {
                var headerLen = rawBytes[0] | (rawBytes[1] << 8) | (rawBytes[2] << 16) | (rawBytes[3] << 24);
                if (headerLen >= 120 && headerLen <= 2048) udid = extractUdid(rawBytes, headerLen);
            }
            send({
                type: 'req',
                endpoint: endpoint,
                body: body.trim(),
                udid: udid,
                app_ver: '',
                res_ver: '',
                viewer_id: 0,
                ts: Date.now()
            });
            return true;
        }
    }

    function bufferAppend(key, chunk) {
        var buf = (buffers[key] || '') + chunk;
        if (buf.length > 2097152) buf = buf.substring(buf.length - 1048576);

        // Check for HTTP request or response start
        var reqStart = buf.indexOf('POST /umamusume/');
        var resStart = buf.indexOf('HTTP/1.');
        var useRes = false;
        var start = -1;

        if (reqStart >= 0 && (resStart < 0 || reqStart < resStart)) {
            start = reqStart;
            useRes = false;
        } else if (resStart >= 0) {
            start = resStart;
            useRes = true;
        } else {
            // No complete HTTP message yet — trim and wait
            buffers[key] = buf.slice(-4096);
            return;
        }

        if (start > 0) buf = buf.substring(start);
        var headerEnd = buf.indexOf('\r\n\r\n');
        if (headerEnd < 0) {
            buffers[key] = buf;
            return;
        }

        var headers = buf.substring(0, headerEnd);
        var clMatch = headers.match(/Content-Length:\s*(\d+)/i);
        var length = clMatch ? parseInt(clMatch[1], 10) : 0;
        var bodyStart = headerEnd + 4;
        var total = bodyStart + (length > 0 ? length : 0);

        // Wait for the full body (both requests AND responses) before emitting,
        // so TLS-fragmented chunks (header chunk, then raw body chunks with no
        // HTTP prefix) accumulate under this key instead of being discarded.
        if (length > 0 && buf.length < total) {
            buffers[key] = buf;
            return;
        }

        // We have a complete HTTP message (or partial response body — emit anyway)
        var rawBuf = [];
        for (var i = 0; i < buf.length; i++) rawBuf.push(buf.charCodeAt(i) || 0);
        if (parseHttp(rawBuf, useRes, key)) {
            buffers[key] = buf.length > total ? buf.substring(total) : '';
        } else {
            buffers[key] = buf;
        }
    }

    function hookTls() {
        var ga = Process.findModuleByName('GameAssembly.dll');
        if (!ga) return false;
        var installFn = ga.findExportByName('il2cpp_unity_install_unitytls_interface');
        if (!installFn) return false;
        var rb = new Uint8Array(installFn.readByteArray(16));
        var realFn = installFn;
        // Handle jmp/branch at start
        if (rb[0] === 0xe9) {
            var off = rb[1] | (rb[2] << 8) | (rb[3] << 16) | (rb[4] << 24);
            if (off > 0x7fffffff) off -= 0x100000000;
            realFn = installFn.add(5 + off);
            rb = new Uint8Array(realFn.readByteArray(16));
        }
        var globalPtr = null;
        if (rb[0] === 0x48 && rb[1] === 0x89 && rb[2] === 0x0d) {
            var disp = rb[3] | (rb[4] << 8) | (rb[5] << 16) | (rb[6] << 24);
            if (disp > 0x7fffffff) disp -= 0x100000000;
            globalPtr = realFn.add(7 + disp);
        }
        if (!globalPtr) return false;
        var iface = globalPtr.readPointer();
        if (!iface || iface.isNull()) return false;
        var hookedTls = 0;

        // Hook read/write callbacks from the TLS interface vtable
        // Keys: 0xd0=Write, 0xd8=Writev, 0xe0=Read, 0xe8=Handshake
        [0xd0, 0xd8, 0xe0, 0xe8].forEach(function(off) {
            var addr = iface.add(off).readPointer();
            if (!addr || addr.isNull()) return;
            var key = 'tls_' + addr.toString();
            if (attached[key]) return;
            try {
                var isRead = (off === 0xe0);
                Interceptor.attach(addr, {
                    onEnter: function(args) {
                        var len = args[2].toInt32();
                        if (len <= 0 || len > 1048576 || args[1].isNull()) return;
                        if (isRead) {
                            this._key = args[0].toString();
                            this._bufPtr = args[1];
                            this._bufSize = len;
                        } else {
                            // Write callback: data is in the buffer NOW
                            try {
                                var bytes = args[1].readByteArray(len);
                                var u8 = new Uint8Array(bytes);
                                var s = '';
                                for (var i = 0; i < u8.length; i++) s += String.fromCharCode(u8[i]);
                                _writeBytes += len; _writeCount++;
                                bufferAppend(args[0].toString(), s);
                            } catch (e) {}
                        }
                    },
                    onLeave: function(retVal) {
                        if (!isRead || !this._bufPtr) return;
                        // retVal IS the actual byte count read (>0); 0 = nothing ready
                        var bytesRead = retVal.toInt32();
                        if (bytesRead <= 0 || bytesRead > this._bufSize) return;
                        _readBytes += bytesRead; _readCount++;
                        try {
                            var bytes = this._bufPtr.readByteArray(bytesRead);
                            var u8 = new Uint8Array(bytes);
                            var s = '';
                            for (var i = 0; i < u8.length; i++) s += String.fromCharCode(u8[i]);
                            bufferAppend(this._key, s);
                        } catch (e) { send('[READ-ERR] ' + e); }
                    }
                });
                attached[key] = true;
                hookedTls++;
            } catch (e) {}
        });
        return hookedTls > 0;
    }

    var tlsDone = false;
    setInterval(function() {
        try {
            // Keep polling: Unity/network layer can rotate TLS callbacks after scene/load.
            // attached[key] prevents duplicate hooks for same function address.
            if (hookTls()) tlsDone = true;
        } catch(e) { send('[HOOK-ERR] ' + e); }
    }, 5000);

    // JS heartbeat disabled: Frida message spam can wedge long captures.
    // Python heartbeat remains active.
})();
"""

calls = []
known_udid = None
save_lock = threading.Lock()
script_lock = threading.Lock()
last_js_msg = time.time()
script = None
session = None
_shutdown = threading.Event()
_cleaned_up = False

# Seed udid from CLI arg, or auth cache
if CLI_UDID:
    known_udid = CLI_UDID
    print(f"[udid] from CLI: {known_udid}")
else:
    try:
        from uma_api.client import runtime_output_root
        _cache = runtime_output_root() / 'auth_cache.json'
        if _cache.exists():
            _cfg = json.loads(_cache.read_text())
            known_udid = _cfg.get('udid') or None
            if known_udid:
                print(f"[udid] loaded from cache: {known_udid}")
    except Exception as e:
        print(f"[udid] cache load failed: {e}")


def save():
    with save_lock:
        with open(OUTPUT, 'w', encoding='utf-8') as f:
            json.dump(calls, f, indent=2, ensure_ascii=False)
        print(f"\n[auto-save] {len(calls)} calls -> {OUTPUT}", flush=True)


def auto_save_loop():
    while not _shutdown.is_set():
        _shutdown.wait(timeout=30)
        if _shutdown.is_set():
            break
        with save_lock:
            if calls:
                save()


def python_heartbeat_loop():
    while not _shutdown.is_set():
        _shutdown.wait(timeout=10)
        if not _shutdown.is_set():
            age = time.time() - last_js_msg
            print(f"[PY-HB] alive calls={len(calls)} js_age={age:.1f}s", flush=True)


def load_frida_script():
    global script, last_js_msg
    with script_lock:
        # Do NOT unload old script here: unload can block if the Frida script is wedged.
        # Layer a fresh script instead; duplicate hooks are less bad than a dead capture.
        last_js_msg = time.time()
        script = session.create_script(JS_CAPTURE)
        script.on('message', on_message)
        script.load()
        last_js_msg = time.time()


def js_watchdog_loop():
    while not _shutdown.is_set():
        _shutdown.wait(timeout=5)
        if _shutdown.is_set():
            break
        if time.time() - last_js_msg > 12:
            print("[watchdog] JS silent >12s; reloading Frida script", flush=True)
            try:
                load_frida_script()
            except Exception as e:
                print(f"[watchdog] reload failed: {e}", flush=True)


_source_display = {}
_next_source_id = 0


def source_id(src):
    global _next_source_id
    if src not in _source_display:
        _source_display[src] = _next_source_id
        _next_source_id += 1
    return _source_display[src]


def on_message(message, data):
    global known_udid, last_js_msg
    last_js_msg = time.time()
    if message.get('type') == 'error':
        print(f"[frida error] {message.get('description')}")
        return

    payload = message.get('payload') or {}
    if isinstance(payload, str):
        print(payload, flush=True)
        return
    pkt_type = payload.get('type')

    if pkt_type == '_diag':
        print(f"[DIAG] {payload.get('from','?')} endpoint={payload.get('endpoint','?')} bodyLen={payload.get('bodyLen',0)}", flush=True)
        return

    if pkt_type not in ('req', 'res'):
        return

    endpoint = payload.get('endpoint', '?')
    body = payload.get('body', '')
    udid = payload.get('udid') or known_udid

    if udid and not known_udid:
        known_udid = udid
        print(f"[udid] {udid}")

    if pkt_type == 'req':
        decoded = None
        if udid and body:
            try:
                from uma_api.client import unpack_request
                decoded = unpack_request(body, udid)
            except Exception as e:
                decoded = f"ERR:{e}"
        decode_ok = decoded and not str(decoded).startswith('ERR:')
        entry = {
            'ts': payload.get('ts'),
            'dir': 'REQ',
            'endpoint': endpoint,
            'viewer_id': payload.get('viewer_id'),
            'app_ver': payload.get('app_ver'),
            'res_ver': payload.get('res_ver'),
            'decoded': decoded,
            'raw_body': body if not decode_ok else None,
        }
        with save_lock:
            calls.append(entry)
        if decode_ok:
            payload_str = json.dumps(decoded, ensure_ascii=False)
            if len(payload_str) > 8000:
                payload_str = payload_str[:8000] + "... [truncated]"
            print(f"\n>>> REQ {endpoint}", flush=True)
            print(payload_str, flush=True)
        else:
            print(f"\n>>> REQ {endpoint} [undecoded] body_len={len(body)}", flush=True)

    else:  # res
        decoded = None
        err_info = ''
        if udid and body:
            try:
                from uma_api.client import unpack as unpack_response
                decoded = unpack_response(body, udid)
                if decoded is None:
                    err_info = '(unpack returned None)'
            except Exception as e:
                decoded = f"ERR:{e}"
                err_info = f'({e})'
        decode_ok = decoded and not str(decoded).startswith('ERR:')
        entry = {
            'ts': payload.get('ts'),
            'dir': 'RES',
            'endpoint': endpoint,
            'http_status': payload.get('http_status'),
            'decoded': decoded,
            'raw_body': None if decode_ok else body,
        }
        with save_lock:
            calls.append(entry)
        if decode_ok:
            payload_str = json.dumps(decoded, ensure_ascii=False)
            if len(payload_str) > 8000:
                payload_str = payload_str[:8000] + "... [truncated]"
            print(f"\n<<< RES {endpoint} (HTTP {payload.get('http_status')})", flush=True)
            print(payload_str, flush=True)
        else:
            print(f"\n<<< RES {endpoint} (HTTP {payload.get('http_status')}) [undecoded] {err_info}".rstrip(), flush=True)


def cleanup(*_):
    global _cleaned_up
    if _cleaned_up:
        return
    _cleaned_up = True
    _shutdown.set()
    print("\n[cleanup] saving...", flush=True)
    try:
        with open(OUTPUT, 'w', encoding='utf-8') as f:
            json.dump(calls, f, indent=2, ensure_ascii=False)
        print(f"[cleanup] {len(calls)} calls -> {OUTPUT}", flush=True)
    except Exception as e:
        print(f"[cleanup] save error: {e}", flush=True)
    print("[cleanup] done.", flush=True)
    os._exit(0)


remote = os.environ.get('FRIDA_REMOTE', '')
device = frida.get_device_manager().add_remote_device(remote) if remote else frida.get_local_device()

procs = device.enumerate_processes()
match = [(p.pid, p.name) for p in procs if TARGET.lower() in p.name.lower()]
if not match:
    print(f"Game not running. Launch it first.")
    sys.exit(1)

pid, name = match[0]
print(f"Attaching to {name} (pid {pid})...")
session = device.attach(pid)
load_frida_script()
print("Hooked. DO your dailies in-game. Ctrl+C to stop.\n")
print("Format: >>> REQ endpoint = request payload, <<< RES endpoint = response payload\n")

# Auto-save every 30s + Python liveness heartbeat
threading.Thread(target=auto_save_loop, daemon=True).start()
threading.Thread(target=python_heartbeat_loop, daemon=True).start()
# Watchdog disabled: without JS heartbeat, silence is normal between network events.
# threading.Thread(target=js_watchdog_loop, daemon=True).start()

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

# Also save if Frida session detaches (game closes)
session.on('detached', lambda *_: cleanup())

while True:
    time.sleep(1)
