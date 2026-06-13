"""
Capture all game API calls while you play manually.
Usage:
    FRIDA_REMOTE=127.0.0.1:27042 venv/bin/python capture_dailies.py [output.json]

Keep frida-server running in Wine. Launch the game. Run this script.
Do your dailies in-game. Ctrl+C to stop — calls saved to output file.
Prints decoded request and response payloads to console in real-time.
Auto-saves every 30s so you don't lose data on crash.
"""

import frida, json, os, sys, time, signal, threading
from pathlib import Path
from uma_api.client import unpack_request as _unpack_request, unpack as _unpack

def unpack_request(body, udid):
    result = _unpack_request(body, udid)
    if result is None:
        _unpack_request(body, udid, _debug=True)
    return result

def unpack_response(body, udid):
    """Decrypt a response body (same pack/unpack scheme)."""
    try:
        return _unpack(body, udid)
    except Exception as e:
        return f"ERR:{e}"

TARGET = "UmamusumePrettyDerby.exe"
OUTPUT = sys.argv[1] if len(sys.argv) > 1 else "captured_calls.json"

JS_CAPTURE = r'''
'use strict';
(function() {
    var buffers = {};
    var attached = {};

    // ---- utility ----
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

    // ---- request parsing (POST /umamusume/...) ----
    function parseReq(text) {
        if (text.indexOf('/umamusume/') < 0) return null;
        var em = text.match(/POST\s+\/umamusume\/([^\s]+)\s+HTTP/i);
        if (!em) return null;
        var endpoint = em[1];
        var vm = text.match(/(?:^|\r\n)(?:ViewerID|ViewerId):\s*(\d+)/i);
        var appVer = text.match(/(?:^|\r\n)APP-VER:\s*([^\r\n]+)/i);
        var resVer = text.match(/(?:^|\r\n)RES-VER:\s*([^\r\n]+)/i);
        var idx = text.indexOf('\r\n\r\n');
        if (idx < 0) return null;
        var body = text.substring(idx + 4).trim();
        if (!body) return null;

        var udid = null;
        var decoded = b64decode(body);
        if (decoded.length >= 4) {
            var headerLen = decoded[0]|(decoded[1]<<8)|(decoded[2]<<16)|(decoded[3]<<24);
            if (headerLen >= 120 && headerLen <= 2048) udid = extractUdid(decoded, headerLen);
        }

        return {
            type: 'req',
            endpoint: endpoint,
            viewer_id: vm ? parseInt(vm[1], 10) : null,
            app_ver: appVer ? appVer[1].trim() : null,
            res_ver: resVer ? resVer[1].trim() : null,
            body: body,
            udid: udid,
            ts: Date.now()
        };
    }

    // ---- response parsing (HTTP/1.1 ... /umamusume/...) ----
    function parseRes(text) {
        var lines = text.split('\r\n');
        var statusLine = lines[0] || '';
        // Match: HTTP/1.1 200 OK
        var sm = statusLine.match(/^HTTP\/\d+\.\d+\s+(\d+)/i);
        if (!sm) return null;
        var httpStatus = parseInt(sm[1], 10);

        // Find the endpoint in the response (echoed in body or via Content-Type/URL)
        var ep = '?';
        for (var i = 0; i < lines.length; i++) {
            var lc = lines[i].toLowerCase();
            // Some responses include the endpoint path
            var epm = lines[i].match(/\/umamusume\/([^\s\r\n]+)/i);
            if (epm) { ep = epm[1]; break; }
        }

        // Find empty line separating headers from body
        var headerEnd = text.indexOf('\r\n\r\n');
        if (headerEnd < 0) return null;
        var body = text.substring(headerEnd + 4).trim();
        if (!body) return null;

        var udid = null;
        var decoded = b64decode(body);
        if (decoded.length >= 4) {
            var headerLen = decoded[0]|(decoded[1]<<8)|(decoded[2]<<16)|(decoded[3]<<24);
            if (headerLen >= 120 && headerLen <= 2048) udid = extractUdid(decoded, headerLen);
        }

        return {
            type: 'res',
            endpoint: ep,
            http_status: httpStatus,
            body: body,
            udid: udid,
            ts: Date.now()
        };
    }

    // ---- chunk reassembly ----
    function parseChunk(key, chunk, parseFn, pktType) {
        var buf = (buffers[key] || '') + chunk;
        if (buf.length > 2097152) buf = buf.substring(buf.length - 1048576);

        // For req: look for 'POST /umamusume/' (exact path, avoid binary false positives)
        var marker = (pktType === 'req') ? 'POST /umamusume/' : 'HTTP/';
        var start = buf.indexOf(marker);
        if (start < 0) { buffers[key] = buf.slice(-4096); return; }
        if (start > 0) buf = buf.substring(start);

        var headerEnd = buf.indexOf('\r\n\r\n');
        if (headerEnd < 0) {
            buffers[key] = buf; return;
        }

        var headers = buf.substring(0, headerEnd);
        var isPost = headers.match(/^POST\s+\/umamusume\//);
        if (pktType === 'req' && !isPost) {
            // False POST match in binary data, discard and wait for real one
            buffers[key] = buf.slice(-4096);
            return;
        }
        var lm = headers.match(/Content-Length:\s*(\d+)/i);
        var length = lm ? parseInt(lm[1], 10) : 0;
        var total = headerEnd + 4 + length;
        if (length > 0 && buf.length < total) {
            // Waiting for body
            var epMatch = headers.match(/\/umamusume\/([^\s\r\n]+)/i);
            var ep = epMatch ? epMatch[1] : '?';
            if (buf.length > 4096) send({type: 'bufdiag', key: key, pktType: pktType, state: 'wait_body', ep: ep, len: buf.length, total: total, preview: buf.substring(0, 200).replace(/\n/g, '\\n').replace(/\r/g, '')});
            buffers[key] = buf; return;
        }

        var pkt = parseFn(length > 0 ? buf.substring(0, total) : buf);
        if (pkt) send(pkt);

        buffers[key] = buf.length > total ? buf.substring(total) : '';
    }

    // ---- hooking ----
    function hookTls() {
        var ga = Process.findModuleByName('GameAssembly.dll');
        if (!ga) return false;
        var installFn = ga.findExportByName('il2cpp_unity_install_unitytls_interface');
        if (!installFn) return false;
        var rb = new Uint8Array(installFn.readByteArray(16));
        var realFn = installFn;
        if (rb[0] === 0xe9) {
            var off = rb[1]|(rb[2]<<8)|(rb[3]<<16)|(rb[4]<<24);
            if (off > 0x7fffffff) off -= 0x100000000;
            realFn = installFn.add(5 + off);
            rb = new Uint8Array(realFn.readByteArray(16));
        }
        var globalPtr = null;
        if (rb[0]===0x48 && rb[1]===0x89 && rb[2]===0x0d) {
            var disp = rb[3]|(rb[4]<<8)|(rb[5]<<16)|(rb[6]<<24);
            if (disp > 0x7fffffff) disp -= 0x100000000;
            globalPtr = realFn.add(7 + disp);
        }
        if (!globalPtr) return false;
        var iface = globalPtr.readPointer();
        if (!iface || iface.isNull()) return false;
        var hooked = 0;

        // Write/send offsets (capture requests) - known to work
        [0xd0, 0xd8, 0xe0, 0xe8].forEach(function(off) {
            var addr = iface.add(off).readPointer();
            if (!addr || addr.isNull()) return;
            var key = 'w_' + addr.toString();
            if (attached[key]) return;
            try {
                Interceptor.attach(addr, {
                    onEnter: function(args) {
                        var len = args[2].toInt32();
                        if (len <= 0 || len > 1048576 || args[1].isNull()) return;
                        try {
                            var bytes = args[1].readByteArray(len);
                            var u8 = new Uint8Array(bytes);
                            var s = '';
                            for (var i = 0; i < u8.length; i++) s += String.fromCharCode(u8[i]);
                            // Log ALL outgoing data > 100 bytes that might be HTTP
                            if (len > 100) {
                                var preview = s.substring(0, 300).replace(/\n/g, '\\n').replace(/\r/g, '').substring(0, 250);
                                send({type: 'rawsend', len: len, preview: preview});
                            }
                            parseChunk(args[0].toString(), s, parseReq, 'req');
                        } catch(e) {}
                    }
                });
                attached[key] = true; hooked++;
            } catch(e) {}
        });

        // Read/recv offsets — use onLeave because the buffer is filled by the function
        var readCandidates = [0x00, 0x08, 0x10, 0x18, 0x20, 0x28, 0x30, 0x38,
                             0x40, 0x48, 0x50, 0x58, 0x60, 0x68, 0x70, 0x78,
                             0x80, 0x88, 0x90, 0x98, 0xa0, 0xa8, 0xb0, 0xb8,
                             0xc0, 0xc8];
        readCandidates.forEach(function(off) {
            var addr = iface.add(off).readPointer();
            if (!addr || addr.isNull()) return;
            var key = 'r_' + off.toString(16) + '_' + addr.toString();
            if (attached[key]) return;
            try {
                Interceptor.attach(addr, {
                    onEnter: function(args) {
                        // Store buffer pointer, size, and optional bytes_read ptr for onLeave
                        this.bufPtr = args[1];
                        this.bufSize = args[2].toInt32();
                        this.bytesReadPtr = args[3];
                    },
                    onLeave: function(retVal) {
                        if (!this.bufPtr || this.bufPtr.isNull()) return;
                        // Try return value as bytes_read
                        var bytesRead = retVal.toInt32();
                        if (bytesRead <= 0 || bytesRead > 1048576) {
                            // Try args[3] as pointer to bytes_read
                            if (this.bytesReadPtr && !this.bytesReadPtr.isNull()) {
                                try { bytesRead = this.bytesReadPtr.readU32(); } catch(e) {}
                            }
                        }
                        // Fallback: use bufsize (might over-read but better than nothing)
                        if (bytesRead <= 0 || bytesRead > 1048576)
                            bytesRead = this.bufSize;
                        if (bytesRead <= 0 || bytesRead > 1048576) return;
                        try {
                            var u8 = new Uint8Array(this.bufPtr.readByteArray(bytesRead));
                            var s = '';
                            for (var i = 0; i < u8.length; i++) s += String.fromCharCode(u8[i]);
                            if (s.indexOf('HTTP/') === 0 || s.indexOf('HTTP') >= 0) {
                                parseChunk('res_' + off.toString(16), s, parseRes, 'res');
                            }
                        } catch(e) {}
                    }
                });
                attached[key] = true; hooked++;
            } catch(e) {}
        });

        return hooked > 0;
    }

    var tlsDone = false;
    var timer = setInterval(function() {
        try { if (!tlsDone) tlsDone = hookTls(); if (tlsDone) clearInterval(timer); } catch(e) {}
    }, 1000);
})();
'''

calls = []
known_udid = None
save_lock = threading.Lock()
_shutdown = threading.Event()
_cleaned_up = False

# seed udid from auth cache so decryption works immediately
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


def on_message(message, data):
    global known_udid
    if message.get('type') == 'error':
        print(f"[frida error] {message.get('description')}")
        return
    payload = message.get('payload') or {}
    pkt_type = payload.get('type')
    if pkt_type == 'diag':
        print(f"[diag] {payload.get('msg')}", flush=True)
        return
    if pkt_type == 'rawsend':
        preview = payload.get('preview', '')
        # Only print non-umamusume data to find what we're missing
        if '/umamusume/' not in preview:
            print(f"[RAWSEND] len={payload.get('len')} preview={preview[:120]}", flush=True)
        return
    if pkt_type == 'bufdiag':
        s = payload.get('state', '')
        ep = payload.get('ep', '?')
        ln = payload.get('len', 0)
        tl = payload.get('total', 0)
        print(f"[BUFDIAG] {s} ep={ep} buf={ln} total={tl}", flush=True)
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
        # Decrypt the request body
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
            print(f"\n>>> REQ {endpoint} [undecoded]", flush=True)

    else:  # res
        # Decrypt the response body
        decoded = None
        if udid and body:
            try:
                decoded = unpack_response(body, udid)
            except Exception as e:
                decoded = f"ERR:{e}"
        decode_ok = decoded and not str(decoded).startswith('ERR:')
        entry = {
            'ts': payload.get('ts'),
            'dir': 'RES',
            'endpoint': endpoint,
            'http_status': payload.get('http_status'),
            'decoded': decoded,
            'raw_body': body if not decode_ok else None,
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
            print(f"\n<<< RES {endpoint} (HTTP {payload.get('http_status')}) [undecoded]", flush=True)


def cleanup(*_):
    global _cleaned_up
    if _cleaned_up:
        return
    _cleaned_up = True
    _shutdown.set()
    print("\n[cleanup] saving...", flush=True)
    try:
        # Write without lock to avoid deadlock with Frida callback thread
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
script = session.create_script(JS_CAPTURE)
script.on('message', on_message)
script.load()
print("Hooked. DO your dailies in-game. Ctrl+C to stop.\n")
print("Format: >>> REQ endpoint = request payload, <<< RES endpoint = response payload\n")

# Auto-save every 30s
threading.Thread(target=auto_save_loop, daemon=True).start()

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

# Also save if Frida session detaches (game closes)
session.on('detached', lambda *_: cleanup())

while True:
    time.sleep(1)
