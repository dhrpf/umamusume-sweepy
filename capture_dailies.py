"""
Capture all game API calls while you play manually.
Usage:
    FRIDA_REMOTE=127.0.0.1:27042 venv/bin/python capture_dailies.py [output.json]

Keep frida-server running in Wine. Launch the game. Run this script.
Do your dailies in-game. Ctrl+C to stop — calls saved to output file.
"""

import frida, json, os, sys, time, signal
from pathlib import Path
from uma_api.client import unpack_request as _unpack_request

def unpack_request(body, udid):
    result = _unpack_request(body, udid)
    if result is None:
        _unpack_request(body, udid, _debug=True)
    return result

TARGET = "UmamusumePrettyDerby.exe"
OUTPUT = sys.argv[1] if len(sys.argv) > 1 else "captured_calls.json"

JS_CAPTURE = r'''
'use strict';
(function() {
    var buffers = {};
    var attached = {};
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
    function parseHttp(text) {
        if (text.indexOf('/umamusume/') < 0) return;
        var em = text.match(/POST\s+\/umamusume\/([^\s]+)\s+HTTP/i);
        if (!em) return;
        var endpoint = em[1];
        var vm = text.match(/(?:^|\r\n)(?:ViewerID|ViewerId):\s*(\d+)/i);
        var appVer = text.match(/(?:^|\r\n)APP-VER:\s*([^\r\n]+)/i);
        var resVer = text.match(/(?:^|\r\n)RES-VER:\s*([^\r\n]+)/i);
        var idx = text.indexOf('\r\n\r\n');
        if (idx < 0) return;
        var body = text.substring(idx + 4).trim();
        if (!body) return;

        var udid = null;
        var decoded = b64decode(body);
        if (decoded.length >= 4) {
            var headerLen = decoded[0]|(decoded[1]<<8)|(decoded[2]<<16)|(decoded[3]<<24);
            if (headerLen >= 120 && headerLen <= 2048) udid = extractUdid(decoded, headerLen);
        }

        send({
            type: 'call',
            endpoint: endpoint,
            viewer_id: vm ? parseInt(vm[1], 10) : null,
            app_ver: appVer ? appVer[1].trim() : null,
            res_ver: resVer ? resVer[1].trim() : null,
            body: body,
            udid: udid,
            ts: Date.now()
        });
    }
    function parseChunk(key, chunk) {
        var buf = (buffers[key] || '') + chunk;
        if (buf.length > 2097152) buf = buf.substring(buf.length - 1048576);
        var start = buf.indexOf('POST ');
        if (start < 0) { buffers[key] = buf.slice(-4096); return; }
        if (start > 0) buf = buf.substring(start);
        var headerEnd = buf.indexOf('\r\n\r\n');
        if (headerEnd < 0) { buffers[key] = buf; return; }
        var headers = buf.substring(0, headerEnd);
        var lm = headers.match(/Content-Length:\s*(\d+)/i);
        var length = lm ? parseInt(lm[1], 10) : 0;
        var total = headerEnd + 4 + length;
        if (length > 0 && buf.length < total) { buffers[key] = buf; return; }
        parseHttp(length > 0 ? buf.substring(0, total) : buf);
        buffers[key] = buf.length > total ? buf.substring(total) : '';
    }
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
        [0xd0, 0xd8, 0xe0, 0xe8].forEach(function(off) {
            var addr = iface.add(off).readPointer();
            if (!addr || addr.isNull()) return;
            var key = 'tls_' + addr.toString();
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
                            parseChunk(args[0].toString(), s);
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

def on_message(message, data):
    global known_udid
    if message.get('type') == 'error':
        print(f"[frida error] {message.get('description')}")
        return
    payload = message.get('payload') or {}
    if payload.get('type') != 'call':
        return

    endpoint = payload.get('endpoint', '?')
    body = payload.get('body', '')
    udid = payload.get('udid') or known_udid

    if udid and not known_udid:
        known_udid = udid
        print(f"[udid] {udid}")

    decoded = None
    if udid and body:
        try:
            decoded = unpack_request(body, udid)
        except Exception as e:
            decoded = f"ERR:{e}"

    decode_ok = decoded and not str(decoded).startswith('ERR:')
    entry = {
        'ts': payload.get('ts'),
        'endpoint': endpoint,
        'viewer_id': payload.get('viewer_id'),
        'app_ver': payload.get('app_ver'),
        'res_ver': payload.get('res_ver'),
        'decoded': decoded,
        'raw_body': body if not decode_ok else None,
    }
    calls.append(entry)
    status = 'ok' if decode_ok else 'raw'
    print(f"  -> {endpoint} [{status}]")


def save():
    with open(OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(calls, f, indent=2, ensure_ascii=False)
    print(f"\nSaved {len(calls)} calls to {OUTPUT}")


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
print("Hooked. Do your dailies in-game. Ctrl+C to stop.\n")

signal.signal(signal.SIGINT, lambda *_: (save(), session.detach(), sys.exit(0)))
while True:
    time.sleep(1)
