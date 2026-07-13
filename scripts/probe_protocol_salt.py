#!/usr/bin/env python3
"""Recover Uma Musume's MD5 suffix (SALT) from the running client.

The running game is asked to evaluate Gallop.Cryptographer.MakeMd5 for a known
probe string. Printable strings from global-metadata.dat are then tested as the
suffix until the exact game digest is reproduced.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import time
from pathlib import Path

import frida


DEFAULT_PROBE = b"sweepy-protocol-probe"
DEFAULT_METADATA = (
    Path.home()
    / ".local/share/Steam/steamapps/common/UmamusumePrettyDerby"
    / "UmamusumePrettyDerby_Data/il2cpp_data/Metadata/global-metadata.dat"
)


def find_md5_suffix_candidates(
    metadata: bytes,
    probe: bytes,
    expected_digest: str,
    *,
    min_length: int = 4,
    max_length: int = 128,
) -> list[tuple[int, bytes]]:
    """Return metadata string literals that reproduce the game's MD5 result."""
    if len(metadata) < 24:
        return []

    signature, _version, table_offset, table_size, data_offset, data_size = struct.unpack_from(
        "<Iiiiii", metadata, 0
    )
    if signature != 0xFAB11BAF:
        return []
    if table_offset < 0 or table_size < 0 or data_offset < 0 or data_size < 0:
        return []
    if table_size % 8 != 0:
        return []
    if table_offset + table_size > len(metadata) or data_offset + data_size > len(metadata):
        return []

    expected = expected_digest.lower()
    matches: list[tuple[int, bytes]] = []
    literal_count = table_size // 8

    for index in range(literal_count):
        length, relative_offset = struct.unpack_from("<ii", metadata, table_offset + index * 8)
        if length < min_length or length > max_length or relative_offset < 0:
            continue
        start = data_offset + relative_offset
        end = start + length
        if start < data_offset or end > data_offset + data_size:
            continue
        candidate = metadata[start:end]
        if hashlib.md5(probe + candidate).hexdigest() == expected:
            matches.append((start, candidate))

    return matches


JS_TEMPLATE = r'''
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
const stringNew = nf("il2cpp_string_new", "pointer", ["pointer"]);
const stringLength = nf("il2cpp_string_length", "int", ["pointer"]);
const stringChars = nf("il2cpp_string_chars", "pointer", ["pointer"]);
const runtimeInvoke = nf(
    "il2cpp_runtime_invoke", "pointer", ["pointer", "pointer", "pointer", "pointer"]
);

function cString(value) {
    return value.isNull() ? "" : value.readUtf8String();
}

function managedString(value) {
    if (value.isNull()) return "";
    return stringChars(value).readUtf16String(stringLength(value));
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
            ) return klass;
        }
    }
    return ptr(0);
}

threadAttach(domainGet());
const cryptographer = findClass("umamusume.dll", "Gallop", "Cryptographer");
if (cryptographer.isNull()) throw new Error("Gallop.Cryptographer not found");

const method = classGetMethodFromName(
    cryptographer,
    Memory.allocUtf8String("MakeMd5"),
    1
);
if (method.isNull()) throw new Error("Gallop.Cryptographer.MakeMd5 not found");

const input = stringNew(Memory.allocUtf8String(__PROBE_JSON__));
const argv = Memory.alloc(Process.pointerSize);
argv.writePointer(input);
const exception = Memory.alloc(Process.pointerSize);
exception.writePointer(ptr(0));
const output = runtimeInvoke(method, ptr(0), argv, exception);

if (!exception.readPointer().isNull()) {
    send({type: "invoke_error", exception: exception.readPointer().toString()});
} else if (output.isNull()) {
    send({type: "invoke_error", error: "MakeMd5 returned null"});
} else {
    send({type: "digest", value: managedString(output)});
}
'''


def game_digest(remote: str, probe: bytes) -> str:
    try:
        probe_text = probe.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("probe must be ASCII") from exc

    device = frida.get_device_manager().add_remote_device(remote)
    process = next(
        (item for item in device.enumerate_processes() if "UmamusumePrettyDerby" in item.name),
        None,
    )
    if process is None:
        raise RuntimeError("UmamusumePrettyDerby.exe is not visible to Frida")

    session = device.attach(process.pid)
    result: dict[str, str] = {}
    try:
        source = JS_TEMPLATE.replace("__PROBE_JSON__", json.dumps(probe_text))
        script = session.create_script(source)

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

    if result.get("type") != "digest" or not result.get("value"):
        raise RuntimeError(result.get("error", "MakeMd5 probe failed"))
    return result["value"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--remote", default="127.0.0.1:27042")
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--probe", default=DEFAULT_PROBE.decode("ascii"))
    args = parser.parse_args()

    probe = args.probe.encode("ascii")
    digest = game_digest(args.remote, probe)
    metadata = args.metadata.expanduser().read_bytes()
    candidates = find_md5_suffix_candidates(metadata, probe, digest)

    output = {
        "probe": args.probe,
        "game_digest": digest,
        "metadata": str(args.metadata.expanduser()),
        "matches": [
            {
                "offset": offset,
                "offset_hex": hex(offset),
                "salt_ascii": candidate.decode("ascii", errors="backslashreplace"),
                "salt_hex": candidate.hex(),
                "length": len(candidate),
            }
            for offset, candidate in candidates
        ],
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if candidates else 1


if __name__ == "__main__":
    raise SystemExit(main())
