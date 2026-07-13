#!/usr/bin/env python3
"""Invoke Uma Musume's local request compressor without sending network traffic.

The script creates a tiny byte array inside the running IL2CPP process, calls
Gallop.HttpHelper.CompressRequest, and reports only envelope metadata and its
52-byte fixed prefix. It does not send the generated request anywhere.
"""

from __future__ import annotations

import argparse
import json
import time

import frida


JS_SOURCE = r'''
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
const classGetMethodFromName = nf(
    "il2cpp_class_get_method_from_name", "pointer", ["pointer", "pointer", "int"]
);
const getCorlib = nf("il2cpp_get_corlib", "pointer", []);
const classFromName = nf(
    "il2cpp_class_from_name", "pointer", ["pointer", "pointer", "pointer"]
);
const arrayNew = nf("il2cpp_array_new", "pointer", ["pointer", "uint64"]);
const arrayLength = nf("il2cpp_array_length", "uint64", ["pointer"]);
const arrayHeaderSize = nf("il2cpp_array_object_header_size", "uint32", []);
const runtimeInvoke = nf(
    "il2cpp_runtime_invoke", "pointer", ["pointer", "pointer", "pointer", "pointer"]
);

function cString(value) {
    return value.isNull() ? "" : value.readUtf8String();
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
            if (
                cString(classGetNamespace(klass)) === namespaceName &&
                cString(classGetName(klass)) === className
            ) {
                return klass;
            }
        }
    }
    return ptr(0);
}

function toHex(bytes) {
    let result = "";
    for (let i = 0; i < bytes.length; i++) {
        result += ("0" + bytes[i].toString(16)).slice(-2);
    }
    return result;
}

threadAttach(domainGet());

const helper = findClass("umamusume.dll", "Gallop", "HttpHelper");
if (helper.isNull()) throw new Error("Gallop.HttpHelper not found");

const method = classGetMethodFromName(
    helper,
    Memory.allocUtf8String("CompressRequest"),
    1
);
if (method.isNull()) throw new Error("CompressRequest not found");

const byteClass = classFromName(
    getCorlib(),
    Memory.allocUtf8String("System"),
    Memory.allocUtf8String("Byte")
);
if (byteClass.isNull()) throw new Error("System.Byte not found");

// Valid minimal MessagePack map: {"x": 1}
const inputBytes = [0x81, 0xa1, 0x78, 0x01];
const input = arrayNew(byteClass, inputBytes.length);
const headerSize = arrayHeaderSize();
const inputData = input.add(headerSize);
for (let i = 0; i < inputBytes.length; i++) inputData.add(i).writeU8(inputBytes[i]);

const argv = Memory.alloc(Process.pointerSize);
argv.writePointer(input);
const exception = Memory.alloc(Process.pointerSize);
exception.writePointer(ptr(0));
const output = runtimeInvoke(method, ptr(0), argv, exception);

if (!exception.readPointer().isNull()) {
    send({type: "invoke_error", exception: exception.readPointer().toString()});
} else if (output.isNull()) {
    send({type: "invoke_error", error: "CompressRequest returned null"});
} else {
    const length = Number(arrayLength(output));
    const data = output.add(headerSize);
    const sampleLength = Math.min(length, 256);
    const sample = new Uint8Array(data.readByteArray(sampleLength));
    send({type: "result", length, sample_hex: toHex(sample)});
}
'''


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--remote", default="127.0.0.1:27042")
    parser.add_argument(
        "--expected-head",
        default=(
            "6b20e2ab6c311330f761d737ce3f3025750850665eea58b6372f8d2f57501eb3"
            "44bdb7270a9067f5b63cd61f152cfb986cbfbf7a"
        ),
    )
    args = parser.parse_args()

    device = frida.get_device_manager().add_remote_device(args.remote)
    process = next(
        (p for p in device.enumerate_processes() if "UmamusumePrettyDerby" in p.name),
        None,
    )
    if process is None:
        raise RuntimeError("UmamusumePrettyDerby.exe is not visible to Frida")

    session = device.attach(process.pid)
    result: dict[str, object] = {}
    try:
        script = session.create_script(JS_SOURCE)

        def on_message(message: dict, _data: bytes | None) -> None:
            if message.get("type") == "send":
                result.update(message.get("payload") or {})
            else:
                result.update(type="script_error", error=message.get("description", "unknown"))

        script.on("message", on_message)
        script.load()
        time.sleep(1.0)
        script.unload()
    finally:
        session.detach()

    if result.get("type") != "result":
        print(json.dumps(result, ensure_ascii=False))
        return 1

    raw = bytes.fromhex(str(result["sample_hex"]))
    analysis: dict[str, object] = {
        "type": "result",
        "returned_length": result["length"],
        "sample_length": len(raw),
    }

    # CompressRequest currently returns ASCII Base64 bytes.
    import base64
    import struct

    try:
        decoded = base64.b64decode(raw, validate=False)
        analysis["decoded_sample_length"] = len(decoded)
        if len(decoded) >= 56:
            analysis["header_length"] = struct.unpack_from("<I", decoded, 0)[0]
            head = decoded[4:56].hex()
            analysis["head_hex"] = head
            analysis["head_matches_expected"] = head.lower() == args.expected_head.lower()
    except Exception as exc:  # pragma: no cover - diagnostic path
        analysis["decode_error"] = repr(exc)

    print(json.dumps(analysis, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
