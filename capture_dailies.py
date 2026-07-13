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
from uma_api.client import unpack_request

TARGET = "UmamusumePrettyDerby"

_flags = {'--wait', '--no-response'}
ARGS = [a for a in sys.argv[1:] if a not in _flags]
WAIT_FOR_GAME = '--wait' in sys.argv[1:]
NO_RESPONSE = '--no-response' in sys.argv[1:]
OUTPUT = ARGS[0] if len(ARGS) > 0 else "captured_calls.json"
CLI_UDID = ARGS[1] if len(ARGS) > 1 else None

JS_CAPTURE = r"""
'use strict';
(function() {
    var buffers = {};
    var attached = {};
    var callId = 0;
    var lastReqEndpoint = {};  // key -> last request endpoint
    var _readBytes = 0, _readCount = 0;  // DIAG: read-hook delivery tally
    var _writeBytes = 0, _writeCount = 0;  // DIAG: write-hook delivery tally
    var _rawWriteCalls = 0, _rawReadCalls = 0;  // raw hook invocations (before filtering)
    setInterval(function() {
        send({type: '_diag', from: 'stats', endpoint: '', bodyLen: 0,
             raw_write: _rawWriteCalls, raw_read: _rawReadCalls,
             parsed_write: _writeCount, parsed_read: _readCount});
    }, 1000);
    var _writeDiag = 0, _writevDiag = 0, _slotDiagDone = false, _ifaceDumpDone = false;
    var _pinnedCallbacks = [];  // prevent GC of NativeCallback refs

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
            var body = text.substring(bodyStart, length > 0 ? bodyStart + length : buf.length);
            var teChunked = text.substring(0, headerEnd).match(/Transfer-Encoding:\s*chunked/i);
            if (teChunked) {
                var dechunked = '';
                var pos = 0;
                while (pos < body.length) {
                    var eol = body.indexOf('\r\n', pos);
                    if (eol < 0) break;
                    var size = parseInt(body.substring(pos, eol).split(';')[0], 16);
                    if (isNaN(size)) break;
                    pos = eol + 2;
                    if (size === 0) break;
                    if (pos + size > body.length) break;
                    dechunked += body.substring(pos, pos + size);
                    pos += size + 2;
                }
                if (dechunked.length > 0) body = dechunked;
            }
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
        var chunked = /Transfer-Encoding:\s*chunked/i.test(headers);
        var bodyStart = headerEnd + 4;
        var total = bodyStart + (length > 0 ? length : 0);

        // Wait for the full body (both requests AND responses) before emitting,
        // so TLS-fragmented chunks (header chunk, then raw body chunks with no
        // HTTP prefix) accumulate under this key instead of being discarded.
        if (chunked) {
            var pos = bodyStart;
            while (true) {
                var eol = buf.indexOf('\r\n', pos);
                if (eol < 0) { buffers[key] = buf; return; }
                var sizeText = buf.substring(pos, eol).split(';')[0];
                var size = parseInt(sizeText, 16);
                if (isNaN(size)) break;
                pos = eol + 2;
                if (size === 0) {
                    var end = buf.indexOf('\r\n\r\n', pos);
                    total = end >= 0 ? end + 4 : pos + 2;
                    if (buf.length < total) { buffers[key] = buf; return; }
                    break;
                }
                if (buf.length < pos + size + 2) { buffers[key] = buf; return; }
                pos += size + 2;
            }
        } else if (length > 0 && buf.length < total) {
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
        var rbHex = '';
        for (var bi = 0; bi < rb.length; bi++) rbHex += hex2(rb[bi]);
        if (!_slotDiagDone) send({type: '_diag', from: 'installFn', endpoint: installFn.toString() + ' bytes=' + rbHex, bodyLen: 0});
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

        if (!_ifaceDumpDone) {
            _ifaceDumpDone = true;
            send({type: '_diag', from: 'iface-dump', endpoint: 'start ptr=' + iface.toString(), bodyLen: 0});
            try {
                var gaBase = ga.base;
                var gaEnd = ga.base.add(ga.size);
                for (var fo = 0; fo <= 0x140; fo += Process.pointerSize) {
                    try {
                        var fp = iface.add(fo).readPointer();
                        if (!fp || fp.isNull()) continue;
                        var owner = '';
                        try {
                            var dm = Process.findModuleByAddress(fp);
                            if (dm) owner = dm.name + '+0x' + fp.sub(dm.base).toString(16);
                        } catch (e) {}
                        var inGa = (fp.compare(gaBase) >= 0 && fp.compare(gaEnd) < 0) ? 'GA+' + fp.sub(gaBase).toString(16) : owner;
                        send({type: '_diag', from: 'iface-field', endpoint: 'off=0x' + fo.toString(16) + ' ptr=' + fp.toString() + ' ' + inGa, bodyLen: 0});
                    } catch (e) {}
                }
            } catch (e) { send('[IFACE-DUMP-ERR] ' + e); }
        }

        var hookedTls = 0;
        var seen = 0;

        // Probe likely UnityTLS callback slots after game update.
        if (!_slotDiagDone) {
            _slotDiagDone = true;
            [0xc0, 0xc8, 0xd0, 0xd8, 0xe0, 0xe8, 0xf0].forEach(function(off) {
                try {
                    var p = iface.add(off).readPointer();
                    if (p && !p.isNull()) {
                        send({type: '_diag', from: 'tls-slot', endpoint: 'off=0x' + off.toString(16) + ' addr=' + p.toString(), bodyLen: 0});
                    }
                } catch (e) {}
            });
        }

        // --- Frida Interceptor.attach + install() interception ---
        // Interceptor.attach works; the stall was from game creating a NEW TLS
        // context. We intercept il2cpp_unity_install_unitytls_interface to hook
        // each new context's read/write callbacks as they're registered.

        var readOff = (typeof _noResponse !== 'undefined' && _noResponse) ? -1 : 0xe0;

        function hookFunction(addr, isRead) {
            if (!addr || addr.isNull()) return false;
            var key = 'int_' + addr.toString();
            if (attached[key]) return false;
            try {
                Interceptor.attach(addr, {
                    onEnter: function(args) {
                        if (isRead) _rawReadCalls++; else _rawWriteCalls++;
                        var len;
                        try { len = args[2].toInt32(); } catch(e) { len = -1; }
                        if (len <= 0 || len > 1048576 || args[1].isNull()) return;
                        this._key = args[0].toString();
                        this._bufPtr = args[1];
                        this._bufSize = len;
                        this._isRead = isRead;
                    },
                    onLeave: function(retVal) {
                        if (!this._bufPtr) return;
                        var bytesToRead;
                        if (this._isRead) {
                            bytesToRead = retVal.toInt32();
                            if (bytesToRead <= 0 || bytesToRead > this._bufSize) return;
                            _readBytes += bytesToRead; _readCount++;
                        } else {
                            var written = retVal.toInt32();
                            if (written <= 0) return;
                            bytesToRead = Math.min(written, this._bufSize);
                            _writeBytes += bytesToRead; _writeCount++;
                        }
                        try {
                            var bytes = this._bufPtr.readByteArray(bytesToRead);
                            var u8 = new Uint8Array(bytes);
                            var s = '';
                            for (var i = 0; i < u8.length; i++) s += String.fromCharCode(u8[i]);
                            bufferAppend(this._key, s);
                        } catch (e) {}
                    }
                });
                attached[key] = true;
                hookedTls++;
                send({type: '_diag', from: 'int-attach', endpoint: (isRead?'R':'W') + ' addr=' + addr, bodyLen: 0});
                return true;
            } catch(e) {
                send({type: '_diag', from: 'int-attach-err', endpoint: e.toString(), bodyLen: 0});
                return false;
            }
        }

        function hookIface(newIface) {
            if (!newIface || newIface.isNull()) return;
            var w = newIface.add(0xe8).readPointer();
            hookFunction(w, false);
            if (readOff > 0) {
                var r = newIface.add(readOff).readPointer();
                hookFunction(r, true);
            }
        }

        // Hook initial iface
        hookIface(iface);

        // Intercept install() to catch new contexts
        try {
            Interceptor.attach(realFn, {
                onEnter: function(args) {
                    var newIface = args[0];
                    send({type: '_diag', from: 'install-FIRE', endpoint: 'new iface=' + newIface, bodyLen: 0});
                    setTimeout(function() { hookIface(newIface); }, 50);
                }
            });
            send({type: '_diag', from: 'install-interceptor', endpoint: 'installed on ' + realFn, bodyLen: 0});
        } catch(e) {
            send({type: '_diag', from: 'install-interceptor-err', endpoint: e.toString(), bodyLen: 0});
        }

        // Periodic rescan: check if write pointer changed (new context)
        var lastWritePtr = iface.add(0xe8).readPointer();
        setInterval(function() {
            try {
                var cur = iface.add(0xe8).readPointer();
                if (!cur.equals(lastWritePtr)) {
                    send({type: '_diag', from: 'iface-changed', endpoint: lastWritePtr + ' -> ' + cur, bodyLen: 0});
                    lastWritePtr = cur;
                    hookIface(iface);
                }
            } catch(e) {}
        }, 200);

        // --- Socket-level hook (fallback) ---
        // Count ALL send/recv + WinHttp — diagnose what path game uses post-boot
        var _sockSendCalls = 0, _sockRecvCalls = 0, _winHttpSend = 0, _winHttpRecv = 0;
        function hookSockets(tag) {
            try {
                var ws2 = Process.getModuleByName('ws2_32.dll');
                var sendFn = ws2.getExportByName('send');
                var recvFn = ws2.getExportByName('recv');
                Interceptor.attach(sendFn, {
                    onEnter: function(args) {
                        _sockSendCalls++;
                        var len = args[2].toInt32();
                        if (len <= 0 || len > 65536 || args[1].isNull()) return;
                        try {
                            var u8 = new Uint8Array(args[1].readByteArray(Math.min(len, 256)));
                            var s = '';
                            for (var i = 0; i < u8.length; i++) s += String.fromCharCode(u8[i]);
                            if (s.indexOf('POST') === 0 || s.indexOf('GET') === 0 || s.indexOf('HTTP') === 0) {
                                _rawWriteCalls++;
                                bufferAppend('sock_W', s);
                            }
                        } catch(e) {}
                    }
                });
                Interceptor.attach(recvFn, {
                    onLeave: function(retVal) {
                        _sockRecvCalls++;
                        var len = retVal.toInt32();
                        if (len <= 0 || len > 65536) return;
                        try {
                            if (!this.buf || this.buf.isNull()) return;
                            var u8 = new Uint8Array(this.buf.readByteArray(Math.min(len, 8192)));
                            var s = '';
                            for (var i = 0; i < u8.length; i++) s += String.fromCharCode(u8[i]);
                            if (s.indexOf('HTTP') >= 0) {
                                _rawReadCalls++;
                                bufferAppend('sock_R', s);
                            }
                        } catch(e) {}
                    },
                    onEnter: function(args) { this.buf = args[1]; }
                });
                send({type: '_diag', from: 'sock-hook', endpoint: tag + ' ws2_32 hooked', bodyLen: 0});
            } catch(e) {
                send({type: '_diag', from: 'sock-hook-err', endpoint: tag + ' ' + e.toString(), bodyLen: 0});
            }
        }
        function hookWinHttp(tag) {
            try {
                var mod = Process.getModuleByName('winhttp.dll');
                var sendFn = mod.getExportByName('WinHttpSendRequest');
                var recvFn = mod.getExportByName('WinHttpReceiveResponse');
                if (sendFn) Interceptor.attach(sendFn, { onEnter: function() { _winHttpSend++; } });
                if (recvFn) Interceptor.attach(recvFn, { onEnter: function() { _winHttpRecv++; } });
                send({type: '_diag', from: 'winhttp-hook', endpoint: tag + ' winhttp hooked', bodyLen: 0});
            } catch(e) {
                send({type: '_diag', from: 'winhttp-err', endpoint: tag + ' ' + e.toString(), bodyLen: 0});
            }
        }
        // Try immediate attach
        hookSockets('init');
        hookWinHttp('init');
        // Also hook on module load (game may load ws2_32/winhttp later).
        // Frida 17 uses attachModuleObserver; the legacy module-load event API is unsupported.
        Process.attachModuleObserver({
            onAdded: function(mod) {
                if (mod.name === 'ws2_32.dll') hookSockets('load');
                if (mod.name === 'winhttp.dll') hookWinHttp('load');
            }
        });
        // --- DLL configure: push captured pointers to net_hook.dll ---
        // Hooks sockets/winhttp from inside the game process — immune to Frida stalls
        (function callDllConfigure() {
            var tries = 0;
            var iv = setInterval(function() {
                tries++;
                if (tries > 30) { clearInterval(iv); send({type: '_diag', from: 'dll-timeout', endpoint: 'no configure after 3s', bodyLen: 0}); return; }
                try {
                    var mod = Process.getModuleByName('net_hook.dll');
                    if (!mod) return;
                    var cfgFn = null;
                    var ex = mod.enumerateExports();
                    for (var i = 0; i < ex.length; i++) if (ex[i].name === 'configure') cfgFn = ex[i].address;
                    if (!cfgFn) return;
                    clearInterval(iv);
                    // read_addr, write_addr, rp=15, wp=15 (from previous Instruction.parse)
                    var rdPtr = iface.add(0xe0).readPointer();
                    var wrPtr = iface.add(0xe8).readPointer();
                    var result = new NativeFunction(cfgFn, 'int', ['pointer', 'pointer', 'int', 'int'])(rdPtr, wrPtr, 15, 15);
                    send({type: '_diag', from: 'dll-configure', endpoint: 'result=0x' + result.toString(16) + ' rd=' + rdPtr + ' wr=' + wrPtr, bodyLen: 0});
                } catch(e) { clearInterval(iv); send({type: '_diag', from: 'dll-configure-err', endpoint: e.toString(), bodyLen: 0}); }
            }, 100);
        })();
        if (hookedTls > 0) send({type: '_diag', from: 'hookTls', endpoint: 'hooked=' + hookedTls + ' seen=' + seen, bodyLen: 0});
        return hookedTls > 0;
    }

    var tlsDone = false;
    try {
        if (hookTls()) tlsDone = true;
    } catch(e) { send('[HOOK-ERR:init] ' + e); }
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
_diag_lock = threading.Lock()
_dll_stats = {}
_pending_events = []  # thread-safe queue for JS→Python data
_queue_lock = threading.Lock()

# Seed udid from CLI arg, or auth cache
if __name__ == "__main__" and CLI_UDID:
    known_udid = CLI_UDID
    print(f"[udid] from CLI: {known_udid}")
elif __name__ == "__main__":
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
        if calls:
            save()


_dll_last_counts = (0, 0, 0, 0, 0, 0)  # tls_w, tls_r, send, recv, httpsend, httprecv

def python_heartbeat_loop():
    global _dll_last_counts
    while not _shutdown.is_set():
        _shutdown.wait(timeout=2)
        if _shutdown.is_set():
            break
        # Drain net_hook.dll ring buffer — immune to Frida JS stalls
        _dll_drain_and_parse()
        age = time.time() - last_js_msg
        with _diag_lock:
            stats = dict(_dll_stats)
        # Read DLL counters to show which layer the game actually uses
        dll_info = ""
        if _dll_counts:
            try:
                c = _dll_counts()
                tls_w  = c & 0xFFF
                tls_r  = (c >> 12) & 0xFFF
                send_n = (c >> 24) & 0xFFF
                recv_n = (c >> 36) & 0xFFF
                hsend  = (c >> 48) & 0xFF
                hrecv  = (c >> 56) & 0xFF
                dll_info = f" | dll tls_w={tls_w} tls_r={tls_r} send={send_n} recv={recv_n} hs={send_n} hr={hrecv}"
                if (send_n + recv_n + tls_w) > sum(_dll_last_counts[:4]):
                    dll_info += " ⬆"
                _dll_last_counts = (tls_w, tls_r, send_n, recv_n, send_n, hrecv)
            except Exception:
                pass
        print(f"[PY-HB] alive calls={len(calls)} js_age={age:.1f}s "
              f"raw_w={stats.get('raw_write',0)} raw_r={stats.get('raw_read',0)} "
              f"parsed_w={stats.get('parsed_write',0)} parsed_r={stats.get('parsed_read',0)}{dll_info}",
              flush=True)


_dll_path = None
_dll_handle = None       # Frida handle for injected DLL script
_dll_configure = None    # NativeFunction: configure(rd, wr, rp, wp) -> int
_dll_drain = None        # NativeFunction: drain_buffer(buf, max) -> int
_dll_pending = None      # NativeFunction: pending_bytes() -> int
_dll_counts = None       # NativeFunction: get_counts() -> uint64
_dll_async_drain = False

def load_frida_script():
    global script, last_js_msg, _dll_handle
    global _dll_configure, _dll_drain, _dll_pending, _dll_counts, _dll_async_drain
    with script_lock:
        if script is not None:
            raise RuntimeError("Frida script already loaded; restart game + capture instead of layering hooks")
        last_js_msg = time.time()
        js_src = JS_CAPTURE
        if NO_RESPONSE:
            js_src = "var _noResponse = true;\n" + js_src
        else:
            js_src = "var _noResponse = false;\n" + js_src
        script = session.create_script(js_src)
        script.on('message', on_message)
        script.load()
        last_js_msg = time.time()
        # Inject net_hook.dll — copy into game folder, convert to Windows path for Wine
        try:
            import shutil
            game_dir = os.path.expanduser("~/.local/share/Steam/steamapps/common/UmamusumePrettyDerby")
            src_dll = os.path.join(os.path.dirname(__file__), 'native', 'net_hook.dll')
            dst_dll = os.path.join(game_dir, 'net_hook.dll')
            shutil.copy2(src_dll, dst_dll)
            # Wine maps Z:\<path-after-steam-dir> for Linux paths
            win_path = 'Z:' + game_dir.replace('/', '\\') + '\\' + 'net_hook.dll'
            _dll_path = win_path
            print(f"[dll-inject] copied, win_path={win_path}", flush=True)
            _try_inject_dll_module(win_path)
        except Exception as e:
            print(f"[dll-inject] setup failed: {e}", flush=True)

def _do_inject_dll(path):
    """Inject DLL and resolve exports. Called from heartbeat until success."""
    global _dll_configure, _dll_drain, _dll_pending, _dll_counts
    if _dll_configure:  # already done
        return
    try:
        # Module.load in main script via its eval
        mod = next((m for m in Process.enumerate() if m.name == 'net_hook.dll'), None)
        if not mod:
            return  # not loaded yet
        addrs = {e.name: e.address for e in mod.enumerate_exports()}
        print(f"[dll-inject] found net_hook.dll, exports: {list(addrs.keys())}", flush=True)
        if 'configure' in addrs:
            _dll_configure = NativeFunction(addrs['configure'], 'int',
                                            ['pointer', 'pointer', 'int', 'int'])
        if 'drain_buffer' in addrs:
            _dll_drain = NativeFunction(addrs['drain_buffer'], 'int', ['pointer', 'int'])
        if 'pending_bytes' in addrs:
            _dll_pending = NativeFunction(addrs['pending_bytes'], 'int', [])
        if 'get_counts' in addrs:
            _dll_counts = NativeFunction(addrs['get_counts'], 'uint64', [])
    except Exception as e:
        print(f"[dll-inject] resolve error: {e}", flush=True)

def _try_inject_dll_module(dll_path):
    """Inject via Frida Module.load in a standalone script that reports back."""
    global _dll_inject_script
    if _dll_inject_script is not None:
        return
    try:
        # Module.load needs absolute path; on Wine/Windows the path is what the game sees.
        # Frida's Module.load accepts host paths — Wine maps them via dosdevices.
        escaped = dll_path.replace('\\', '\\\\').replace("'", "\\'")
        src = (
            "try {"
            "  var h = Process.getModuleByName('net_hook.dll');"
            "  if (h) { send({type:'dll-inject-ok', payload: 'already-loaded ' + h.toString()}); }"
            "  else {"
            "    h = Module.load('" + escaped + "');"
            "    send({type:'dll-inject-ok', payload: 'loaded ' + h.toString()});"
            "  }"
            "} catch(e) {"
            "  send({type:'dll-inject-fail', payload: e.message + ' | ' + e.stack});"
            "}"
        )
        _dll_inject_script = session.create_script(src)
        _dll_inject_script.on('message', on_message)
        _dll_inject_script.load()
        print(f"[dll-inject] attempting load: {dll_path}", flush=True)
    except Exception as e:
        print(f"[dll-inject] script error: {e}", flush=True)

_dll_inject_script = None

def _dll_drain_and_parse():
    """Drain net_hook.dll ring buffer and feed chunks to bufferAppend."""
    if not (_dll_drain and _dll_pending):
        return
    try:
        pending = _dll_pending()
        if pending <= 0:
            return
        buf = Memory.alloc(max(pending, 4096))
        n = _dll_drain(buf, 4096)
        if n <= 0:
            return
        raw = buf.readByteArray(n)
        # Parse ring buffer chunks: [tag:1][len:4][payload:len]
        pos = 0
        mem = bytes(raw)
        while pos + 5 <= len(mem):
            tag = chr(mem[pos]); pos += 1
            ln = mem[pos] | (mem[pos+1]<<8) | (mem[pos+2]<<16) | (mem[pos+3]<<24); pos += 4
            if ln > 65536 or pos + ln > len(mem):
                break
            payload = mem[pos:pos+ln]; pos += ln
            # Forward to same bufferAppend path as Frida hooks (as text for HTTP-ish content)
            try:
                txt = payload.decode('latin-1')
                if tag in ('W', 'R', 'S', 'r', 'H'):
                    bufferAppend(tag, txt)
            except Exception:
                pass
    except Exception as e:
        print(f"[dll-drain] error: {e}", flush=True)


def js_watchdog_loop():
    global last_js_msg
    while not _shutdown.is_set():
        _shutdown.wait(timeout=5)
        if _shutdown.is_set():
            break
        if time.time() - last_js_msg > 12:
            print("[watchdog] JS silent >12s; no reload to avoid duplicate hooks. If capture is dead, restart game + capture.", flush=True)
            last_js_msg = time.time()


_source_display = {}
_next_source_id = 0


def source_id(src):
    global _next_source_id
    if src not in _source_display:
        _source_display[src] = _next_source_id
        _next_source_id += 1
    return _source_display[src]


def on_message(message, data):
    global known_udid, last_js_msg, _dll_inject_script
    last_js_msg = time.time()
    # Handle DLL injection ack (comes from standalone script)
    if message.get('type') == 'dll-inject-ok':
        print(f"[dll-inject] ok: {message.get('payload')}", flush=True)
        _do_inject_dll(_dll_path)
        return
    if message.get('type') == 'dll-inject-fail':
        print(f"[dll-inject] FAILED: {message.get('payload')}", flush=True)
        return

    if message.get('type') == 'error':
        print(f"[frida error] {message.get('description')}")
        return

    payload = message.get('payload') or {}
    if isinstance(payload, str):
        print(payload, flush=True)
        return
    pkt_type = payload.get('type')

    if pkt_type == '_diag':
        diag_from = payload.get('from','?')
        if diag_from == 'stats':
            with _diag_lock:
                _dll_stats.update(payload)
        else:
            print(f"[DIAG] {diag_from} endpoint={payload.get('endpoint','?')} bodyLen={payload.get('bodyLen',0)}", flush=True)
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
    global _cleaned_up, script
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

    threading.Timer(3.0, lambda: (print("[cleanup] force exit (detach hung)", flush=True), os._exit(1))).start()
    print("[cleanup] detaching Frida (3s timeout)...", flush=True)
    try:
        if script is not None:
            script.unload()
            script = None
    except Exception as e:
        print(f"[cleanup] script unload warning: {e}", flush=True)
    try:
        if session is not None:
            session.detach()
    except Exception as e:
        print(f"[cleanup] session detach warning: {e}", flush=True)

    print("[cleanup] done.", flush=True)
    os._exit(0)


device = None


def find_game_process():
    procs = device.enumerate_processes()
    match = [(p.pid, p.name) for p in procs if TARGET.lower() in p.name.lower()]
    return match[0] if match else None


def main():
    global device, session
    remote = os.environ.get('FRIDA_REMOTE', '')
    device = frida.get_device_manager().add_remote_device(remote) if remote else frida.get_local_device()

    start_wait = time.time()
    found = find_game_process()
    if not found and WAIT_FOR_GAME:
        print(f"[wait] waiting for {TARGET}...", flush=True)
        while not found:
            time.sleep(0.1)
            try:
                found = find_game_process()
            except Exception as e:
                # frida-server may still be starting; keep polling.
                if int((time.time() - start_wait) * 10) % 20 == 0:
                    print(f"[wait] device/process not ready: {e}", flush=True)

    if not found:
        print(f"Game not running. Launch it first, or use --wait.")
        sys.exit(1)

    pid, name = found
    print(f"Attaching to {name} (pid {pid}) after {time.time() - start_wait:.2f}s...")
    session = device.attach(pid)
    load_frida_script()
    mode = "requests only (--no-response)" if NO_RESPONSE else "requests + responses"
    print(f"Hooked ({mode}). DO your dailies in-game. Ctrl+C to stop.\n")
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


if __name__ == "__main__":
    main()
