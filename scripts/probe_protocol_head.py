#!/usr/bin/env python3
"""Read-only Frida probe for Uma Musume's request-envelope prefix.

The probe attaches to Cute.Http.WWWRequest.Post and reports only:
- request URL path
- body length
- little-endian envelope header length
- the first 52 envelope bytes

It deliberately does not print SID, UDID, auth material, Steam tickets, or payloads.
"""

from __future__ import annotations

import argparse
import json
import time

import frida


JS_SOURCE = r'''
"use strict";

const gameAssembly = Process.getModuleByName("GameAssembly.dll");

function nativeFunction(name, returnType, argumentTypes) {
    return new NativeFunction(
        gameAssembly.getExportByName(name),
        returnType,
        argumentTypes
    );
}

const domainGet = nativeFunction("il2cpp_domain_get", "pointer", []);
const threadAttach = nativeFunction("il2cpp_thread_attach", "pointer", ["pointer"]);
const classGetMethodFromName = nativeFunction(
    "il2cpp_class_get_method_from_name",
    "pointer",
    ["pointer", "pointer", "int"]
);
const arrayLength = nativeFunction("il2cpp_array_length", "uint64", ["pointer"]);
const arrayHeaderSize = nativeFunction("il2cpp_array_object_header_size", "uint32", []);
const stringLength = nativeFunction("il2cpp_string_length", "int", ["pointer"]);
const stringChars = nativeFunction("il2cpp_string_chars", "pointer", ["pointer"]);

threadAttach(domainGet());

function readManagedString(value) {
    if (value.isNull()) return "";
    return stringChars(value).readUtf16String(stringLength(value));
}

function hex(bytes) {
    let result = "";
    for (let i = 0; i < bytes.length; i++) {
        result += ("0" + bytes[i].toString(16)).slice(-2);
    }
    return result;
}

// Runtime-reflected class address for Cute.Http.WWWRequest in the current process.
// The address is resolved again by the companion Python script before loading
// this source, so this placeholder is never used as-is.
const wwwRequestClass = ptr("__WWW_REQUEST_CLASS__");
const methodInfo = classGetMethodFromName(
    wwwRequestClass,
    Memory.allocUtf8String("Post"),
    3
);

if (methodInfo.isNull()) {
    throw new Error("Cute.Http.WWWRequest.Post was not found");
}

// In IL2CPP MethodInfo, the first pointer is the compiled method entry point.
const entryPoint = methodInfo.readPointer();
if (entryPoint.isNull()) {
    throw new Error("WWWRequest.Post has no compiled entry point");
}

Interceptor.attach(entryPoint, {
    onEnter(args) {
        try {
            const url = readManagedString(args[1]);
            const postData = args[2];
            if (postData.isNull()) return;

            const length = Number(arrayLength(postData));
            const data = postData.add(arrayHeaderSize());
            if (length < 56) {
                send({ type: "request", url, body_length: length, too_short: true });
                return;
            }

            const first = new Uint8Array(data.readByteArray(Math.min(length, 56)));
            const headerLength =
                first[0] |
                (first[1] << 8) |
                (first[2] << 16) |
                (first[3] << 24);

            send({
                type: "request",
                url,
                body_length: length,
                header_length: headerLength >>> 0,
                head_hex: hex(first.slice(4, 56))
            });
        } catch (error) {
            send({ type: "probe_error", error: String(error) });
        }
    }
});

send({ type: "ready", entry_point: entryPoint.toString() });
'''


CLASS_DISCOVERY_JS = r'''
"use strict";
const ga = Process.getModuleByName("GameAssembly.dll");
function nf(name, ret, args) {
    return new NativeFunction(ga.getExportByName(name), ret, args);
}
const domainGet = nf("il2cpp_domain_get", "pointer", []);
const threadAttach = nf("il2cpp_thread_attach", "pointer", ["pointer"]);
const domainGetAssemblies = nf(
    "il2cpp_domain_get_assemblies", "pointer", ["pointer", "pointer"]
);
const assemblyGetImage = nf("il2cpp_assembly_get_image", "pointer", ["pointer"]);
const imageGetName = nf("il2cpp_image_get_name", "pointer", ["pointer"]);
const imageGetClassCount = nf("il2cpp_image_get_class_count", "uint64", ["pointer"]);
const imageGetClass = nf("il2cpp_image_get_class", "pointer", ["pointer", "uint64"]);
const classGetName = nf("il2cpp_class_get_name", "pointer", ["pointer"]);
const classGetNamespace = nf("il2cpp_class_get_namespace", "pointer", ["pointer"]);

function cString(value) {
    return value.isNull() ? "" : value.readUtf8String();
}

function discoverClass() {
    const domain = domainGet();
    threadAttach(domain);
    const countPointer = Memory.alloc(Process.pointerSize);
    countPointer.writePointer(ptr(0));
    const assemblies = domainGetAssemblies(domain, countPointer);
    const count = Number(countPointer.readU64());

    for (let i = 0; i < count; i++) {
        const assembly = assemblies.add(i * Process.pointerSize).readPointer();
        const image = assemblyGetImage(assembly);
        if (image.isNull() || cString(imageGetName(image)) !== "Cute.Http.Assembly.dll") continue;

        const classCount = Number(imageGetClassCount(image));
        for (let j = 0; j < classCount; j++) {
            const klass = imageGetClass(image, j);
            if (klass.isNull()) continue;
            if (
                cString(classGetNamespace(klass)) === "Cute.Http" &&
                cString(classGetName(klass)) === "WWWRequest"
            ) {
                send({ type: "class", address: klass.toString() });
                return;
            }
        }
    }

    send({ type: "class_error", error: "Cute.Http.WWWRequest not found" });
}

discoverClass();
'''


def remote_device(address: str) -> frida.core.Device:
    return frida.get_device_manager().add_remote_device(address)


def game_process(device: frida.core.Device) -> frida.core.Process:
    for process in device.enumerate_processes():
        if "UmamusumePrettyDerby" in process.name:
            return process
    raise RuntimeError("UmamusumePrettyDerby.exe is not visible to Frida")


def discover_class(session: frida.core.Session) -> str:
    result: dict[str, str] = {}
    script = session.create_script(CLASS_DISCOVERY_JS)

    def on_message(message: dict, _data: bytes | None) -> None:
        if message.get("type") == "send":
            payload = message.get("payload") or {}
            result.update(payload)
        elif message.get("type") == "error":
            result.update(type="script_error", error=message.get("description", "unknown"))

    script.on("message", on_message)
    script.load()
    time.sleep(0.5)
    script.unload()

    if result.get("type") != "class" or not result.get("address"):
        raise RuntimeError(result.get("error", "WWWRequest class discovery failed"))
    return result["address"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--remote", default="127.0.0.1:27042")
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument(
        "--expected-head",
        default=(
            "6b20e2ab6c311330f761d737ce3f3025750850665eea58b6372f8d2f57501eb3"
            "44bdb7270a9067f5b63cd61f152cfb986cbfbf7a"
        ),
    )
    args = parser.parse_args()

    device = remote_device(args.remote)
    process = game_process(device)
    session = device.attach(process.pid)

    try:
        klass = discover_class(session)
        source = JS_SOURCE.replace("__WWW_REQUEST_CLASS__", klass)
        script = session.create_script(source)

        def on_message(message: dict, _data: bytes | None) -> None:
            if message.get("type") == "error":
                print(json.dumps({"type": "script_error", "error": message.get("description")}))
                return

            payload = message.get("payload") or {}
            if payload.get("type") == "request" and payload.get("head_hex"):
                payload["head_matches_expected"] = (
                    payload["head_hex"].lower() == args.expected_head.lower()
                )
            print(json.dumps(payload, ensure_ascii=False), flush=True)

        script.on("message", on_message)
        script.load()
        time.sleep(max(0.1, args.seconds))
        script.unload()
    finally:
        session.detach()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
