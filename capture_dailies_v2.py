#!/usr/bin/env python3
"""Managed-boundary Uma Musume request/response capture.

Hooks Cute.Http.WWWRequest.Post and WWWRequest.get_bytes through IL2CPP.
Unlike capture_dailies.py, this does not parse a long-lived TLS byte stream,
inject a DLL, or rescan rotating UnityTLS callback slots.

Usage:
    FRIDA_REMOTE=127.0.0.1:27042 \
      venv/bin/python capture_dailies_v2.py output.json [udid] [--wait]
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any

import frida

from uma_api.client import runtime_output_root, unpack, unpack_request

TARGET = "UmamusumePrettyDerby"
FLAGS = {"--wait", "--no-response"}
ARGS = [arg for arg in sys.argv[1:] if arg not in FLAGS]
WAIT_FOR_GAME = "--wait" in sys.argv[1:]
NO_RESPONSE = "--no-response" in sys.argv[1:]
OUTPUT = Path(ARGS[0] if ARGS else "captured_calls_v2.json")
CLI_UDID = ARGS[1] if len(ARGS) > 1 else None

JS_CAPTURE = r'''
"use strict";

const ga = Process.getModuleByName("GameAssembly.dll");
function nf(name, ret, args) {
    return new NativeFunction(ga.getExportByName(name), ret, args);
}

const domainGet = nf("il2cpp_domain_get", "pointer", []);
const threadAttach = nf("il2cpp_thread_attach", "pointer", ["pointer"]);
const domainGetAssemblies = nf("il2cpp_domain_get_assemblies", "pointer", ["pointer", "pointer"]);
const assemblyGetImage = nf("il2cpp_assembly_get_image", "pointer", ["pointer"]);
const imageGetName = nf("il2cpp_image_get_name", "pointer", ["pointer"]);
const imageGetClassCount = nf("il2cpp_image_get_class_count", "uint64", ["pointer"]);
const imageGetClass = nf("il2cpp_image_get_class", "pointer", ["pointer", "uint64"]);
const classGetName = nf("il2cpp_class_get_name", "pointer", ["pointer"]);
const classGetNamespace = nf("il2cpp_class_get_namespace", "pointer", ["pointer"]);
const classGetMethodFromName = nf("il2cpp_class_get_method_from_name", "pointer", ["pointer", "pointer", "int"]);
const stringChars = nf("il2cpp_string_chars", "pointer", ["pointer"]);
const stringLength = nf("il2cpp_string_length", "int", ["pointer"]);
const arrayLength = nf("il2cpp_array_length", "uint64", ["pointer"]);
const arrayHeaderSize = nf("il2cpp_array_object_header_size", "uint32", []);

function cString(ptrValue) {
    return ptrValue.isNull() ? "" : ptrValue.readUtf8String();
}

function managedString(value) {
    if (value.isNull()) return "";
    const length = stringLength(value);
    if (length <= 0 || length > 16384) return "";
    return stringChars(value).readUtf16String(length);
}

function readByteArray(value, maxLength) {
    if (value.isNull()) return null;
    const length = Number(arrayLength(value));
    if (length < 0 || length > maxLength) return null;
    const data = value.add(arrayHeaderSize()).readByteArray(length);
    return {length: length, data: data};
}

function findClass(imageName, namespaceName, className) {
    const countPointer = Memory.alloc(Process.pointerSize);
    countPointer.writePointer(ptr(0));
    const assemblies = domainGetAssemblies(domainGet(), countPointer);
    const assemblyCount = Number(countPointer.readU64());

    for (let i = 0; i < assemblyCount; i++) {
        const assembly = assemblies.add(i * Process.pointerSize).readPointer();
        const image = assemblyGetImage(assembly);
        if (image.isNull() || cString(imageGetName(image)) !== imageName) continue;

        const classCount = Number(imageGetClassCount(image));
        for (let j = 0; j < classCount; j++) {
            const klass = imageGetClass(image, j);
            if (klass.isNull()) continue;
            if (cString(classGetNamespace(klass)) === namespaceName &&
                cString(classGetName(klass)) === className) {
                return klass;
            }
        }
    }
    return ptr(0);
}

function methodAddress(klass, name, argc) {
    const method = classGetMethodFromName(klass, Memory.allocUtf8String(name), argc);
    if (method.isNull()) throw new Error(name + " not found");
    // MethodInfo begins with Il2CppMethodPointer on this IL2CPP build.
    const address = method.readPointer();
    if (address.isNull()) throw new Error(name + " has null method pointer");
    return address;
}

function endpointFromUrl(url) {
    const marker = "/api/";
    const index = url.indexOf(marker);
    if (index >= 0) return url.slice(index + marker.length).split("?")[0];
    try {
        return url.split("/").filter(Boolean).slice(-2).join("/");
    } catch (_) {
        return url;
    }
}

threadAttach(domainGet());

const klass = findClass("Cute.Http.Assembly.dll", "Cute.Http", "WWWRequest");
if (klass.isNull()) throw new Error("Cute.Http.WWWRequest not found");

const postAddress = methodAddress(klass, "Post", 3);
const bytesAddress = methodAddress(klass, "get_bytes", 0);
const active = new Map();
const lastResponseFingerprint = new Map();

Interceptor.attach(postAddress, {
    onEnter(args) {
        try {
            const selfKey = args[0].toString();
            const url = managedString(args[1]);
            const body = readByteArray(args[2], 16 * 1024 * 1024);
            if (!body || !url) return;

            const endpoint = endpointFromUrl(url);
            active.set(selfKey, {endpoint: endpoint, url: url, ts: Date.now() / 1000});
            send({type: "req", endpoint: endpoint, url: url, ts: Date.now() / 1000,
                  length: body.length, self: selfKey}, body.data);
        } catch (e) {
            send({type: "diag", where: "Post", error: e.message});
        }
    }
});

Interceptor.attach(bytesAddress, {
    onEnter(args) {
        this.selfKey = args[0].toString();
    },
    onLeave(retval) {
        try {
            if (retval.isNull()) return;
            const meta = active.get(this.selfKey);
            if (!meta) return;
            const body = readByteArray(retval, 32 * 1024 * 1024);
            if (!body || body.length === 0) return;

            // get_bytes may be read repeatedly by game code. Suppress exact repeats
            // using a cheap length + edge-byte fingerprint inside the target.
            const bytes = new Uint8Array(body.data);
            let fp = body.length + ":";
            const limit = Math.min(16, bytes.length);
            for (let i = 0; i < limit; i++) fp += bytes[i].toString(16) + ".";
            for (let i = Math.max(limit, bytes.length - 16); i < bytes.length; i++) {
                fp += bytes[i].toString(16) + ".";
            }
            if (lastResponseFingerprint.get(this.selfKey) === fp) return;
            lastResponseFingerprint.set(this.selfKey, fp);

            send({type: "res", endpoint: meta.endpoint, url: meta.url,
                  ts: Date.now() / 1000, length: body.length, self: this.selfKey}, body.data);
        } catch (e) {
            send({type: "diag", where: "get_bytes", error: e.message});
        }
    }
});

send({type: "ready", post: postAddress.toString(), get_bytes: bytesAddress.toString()});
'''

calls: list[dict[str, Any]] = []
known_udid: str | None = CLI_UDID
save_lock = threading.Lock()
shutdown = threading.Event()
cleaned_up = False
script_ready = threading.Event()
script_failed = threading.Event()
session: frida.core.Session | None = None
script: frida.core.Script | None = None


def load_cached_udid() -> str | None:
    try:
        cache = runtime_output_root() / "auth_cache.json"
        if not cache.exists():
            return None
        config = json.loads(cache.read_text(encoding="utf-8"))
        value = config.get("udid")
        return str(value) if value else None
    except Exception as exc:
        print(f"[udid] cache load failed: {exc}", flush=True)
        return None


def atomic_save() -> None:
    with save_lock:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        temporary = OUTPUT.with_suffix(OUTPUT.suffix + ".tmp")
        temporary.write_text(
            json.dumps(calls, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        os.replace(temporary, OUTPUT)
    print(f"[save] {len(calls)} calls -> {OUTPUT}", flush=True)


def autosave_loop() -> None:
    while not shutdown.wait(15):
        if calls:
            atomic_save()


def short_json(value: Any, limit: int = 8000) -> str:
    rendered = json.dumps(value, ensure_ascii=False, default=str)
    return rendered if len(rendered) <= limit else rendered[:limit] + "... [truncated]"


def append_entry(entry: dict[str, Any]) -> None:
    with save_lock:
        calls.append(entry)


def handle_request(meta: dict[str, Any], body: bytes) -> None:
    decoded: Any = None
    error: str | None = None
    if known_udid:
        try:
            decoded = unpack_request(body, known_udid)
        except Exception as exc:
            error = str(exc)

    entry = {
        "ts": meta.get("ts"),
        "dir": "REQ",
        "endpoint": meta.get("endpoint", "?"),
        "decoded": decoded,
        "decode_error": error,
        "raw_body": None if decoded is not None else body.decode("latin-1", errors="replace"),
    }
    append_entry(entry)
    status = "" if decoded is not None else " [undecoded]"
    print(f"\n>>> REQ {entry['endpoint']}{status}", flush=True)
    if decoded is not None:
        print(short_json(decoded), flush=True)
    elif error:
        print(error, flush=True)


def handle_response(meta: dict[str, Any], body: bytes) -> None:
    decoded: Any = None
    error: str | None = None
    if known_udid:
        try:
            decoded = unpack(body, known_udid)
        except Exception as exc:
            error = str(exc)

    entry = {
        "ts": meta.get("ts"),
        "dir": "RES",
        "endpoint": meta.get("endpoint", "?"),
        "decoded": decoded,
        "decode_error": error,
        "raw_body": None if decoded is not None else body.decode("latin-1", errors="replace"),
    }
    append_entry(entry)
    status = "" if decoded is not None else " [undecoded]"
    print(f"\n<<< RES {entry['endpoint']}{status}", flush=True)
    if decoded is not None:
        print(short_json(decoded), flush=True)
    elif error:
        print(error, flush=True)


def on_message(message: dict[str, Any], data: bytes | None) -> None:
    if message.get("type") == "error":
        print(f"[frida error] {message.get('description')}", flush=True)
        script_failed.set()
        return

    meta = message.get("payload") or {}
    event_type = meta.get("type")
    if event_type == "ready":
        script_ready.set()
        print(
            f"[ready] WWWRequest.Post={meta.get('post')} "
            f"get_bytes={meta.get('get_bytes')}",
            flush=True,
        )
        return
    if event_type == "diag":
        print(f"[diag] {meta.get('where')}: {meta.get('error')}", flush=True)
        return
    if data is None:
        return
    if event_type == "req":
        handle_request(meta, bytes(data))
    elif event_type == "res" and not NO_RESPONSE:
        handle_response(meta, bytes(data))


def cleanup(*_: object) -> None:
    global cleaned_up, script
    if cleaned_up:
        return
    cleaned_up = True
    shutdown.set()
    try:
        atomic_save()
    except Exception as exc:
        print(f"[cleanup] save failed: {exc}", flush=True)
    try:
        if script is not None:
            script.unload()
            script = None
    except Exception as exc:
        print(f"[cleanup] script unload warning: {exc}", flush=True)
    try:
        if session is not None:
            session.detach()
    except Exception as exc:
        print(f"[cleanup] detach warning: {exc}", flush=True)


def find_process(device: frida.core.Device) -> tuple[int, str] | None:
    for process in device.enumerate_processes():
        if TARGET.lower() in process.name.lower():
            return process.pid, process.name
    return None


def main() -> int:
    global known_udid, session, script

    if not known_udid:
        known_udid = load_cached_udid()
    if known_udid:
        print(f"[udid] loaded ({hashlib.sha256(known_udid.encode()).hexdigest()[:8]})", flush=True)
    else:
        print("[udid] unavailable; capture will be saved but not decoded", flush=True)

    remote = os.environ.get("FRIDA_REMOTE", "")
    device = (
        frida.get_device_manager().add_remote_device(remote)
        if remote
        else frida.get_local_device()
    )

    found = find_process(device)
    if not found and WAIT_FOR_GAME:
        print(f"[wait] waiting for {TARGET}...", flush=True)
        while not found:
            time.sleep(0.25)
            try:
                found = find_process(device)
            except Exception:
                continue

    if not found:
        print("Game not running. Launch it first, or use --wait.", flush=True)
        return 1

    pid, name = found
    print(f"Attaching to {name} (pid {pid})...", flush=True)
    session = device.attach(pid)
    script = session.create_script(JS_CAPTURE)
    script.on("message", on_message)
    script.load()
    if not script_ready.wait(3):
        if script_failed.is_set():
            print("Managed hook initialization failed.", flush=True)
        else:
            print("Managed hook did not report ready within 3 seconds.", flush=True)
        cleanup()
        return 1

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)
    session.on("detached", lambda *_: cleanup())
    threading.Thread(target=autosave_loop, daemon=True).start()

    mode = "requests only" if NO_RESPONSE else "requests + responses"
    print(f"Hooked managed HTTP boundary ({mode}). Ctrl+C to stop.", flush=True)
    try:
        while not shutdown.wait(1):
            pass
    finally:
        cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
