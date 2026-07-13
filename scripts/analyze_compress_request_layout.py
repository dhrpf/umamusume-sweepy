#!/usr/bin/env python3
"""Black-box structural analysis of Gallop.HttpHelper.CompressRequest.

The probe invokes the game's local compressor with controlled MessagePack inputs.
It never sends network traffic and never prints session/auth bytes. Output is
limited to lengths, offsets, equality patterns, and hashes of sensitive regions.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import struct
import time
from dataclasses import dataclass

import frida
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad


JS_SOURCE = r'''
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
const getCorlib = nf("il2cpp_get_corlib", "pointer", []);
const classFromName = nf("il2cpp_class_from_name", "pointer", ["pointer", "pointer", "pointer"]);
const arrayNew = nf("il2cpp_array_new", "pointer", ["pointer", "uint64"]);
const arrayLength = nf("il2cpp_array_length", "uint64", ["pointer"]);
const arrayHeaderSize = nf("il2cpp_array_object_header_size", "uint32", []);
const runtimeInvoke = nf("il2cpp_runtime_invoke", "pointer", ["pointer", "pointer", "pointer", "pointer"]);

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
            if (cString(classGetNamespace(klass)) === namespaceName && cString(classGetName(klass)) === className) {
                return klass;
            }
        }
    }
    return ptr(0);
}

function toHex(bytes) {
    let result = "";
    for (let i = 0; i < bytes.length; i++) result += ("0" + bytes[i].toString(16)).slice(-2);
    return result;
}

function invokeCompress(method, byteClass, headerSize, inputBytes) {
    const input = arrayNew(byteClass, inputBytes.length);
    const inputData = input.add(headerSize);
    for (let i = 0; i < inputBytes.length; i++) inputData.add(i).writeU8(inputBytes[i]);

    const argv = Memory.alloc(Process.pointerSize);
    argv.writePointer(input);
    const exception = Memory.alloc(Process.pointerSize);
    exception.writePointer(ptr(0));
    const output = runtimeInvoke(method, ptr(0), argv, exception);
    if (!exception.readPointer().isNull()) throw new Error("CompressRequest threw an exception");
    if (output.isNull()) throw new Error("CompressRequest returned null");

    const length = Number(arrayLength(output));
    const data = output.add(headerSize);
    return toHex(new Uint8Array(data.readByteArray(length)));
}

threadAttach(domainGet());
const helper = findClass("umamusume.dll", "Gallop", "HttpHelper");
if (helper.isNull()) throw new Error("Gallop.HttpHelper not found");
const method = classGetMethodFromName(helper, Memory.allocUtf8String("CompressRequest"), 1);
if (method.isNull()) throw new Error("CompressRequest not found");
const byteClass = classFromName(getCorlib(), Memory.allocUtf8String("System"), Memory.allocUtf8String("Byte"));
if (byteClass.isNull()) throw new Error("System.Byte not found");
const headerSize = arrayHeaderSize();

// Valid MessagePack values with deliberately different lengths.
const payloads = [
    [0x81, 0xa1, 0x78, 0x01],                         // {"x": 1}
    [0x81, 0xa1, 0x78, 0x02],                         // {"x": 2}, same length
    [0x81, 0xa1, 0x78, 0xa8, 0x31, 0x32, 0x33, 0x34, 0x35, 0x36, 0x37, 0x38],
    [0x81, 0xa1, 0x78, 0xb9].concat(Array(25).fill(0x41))
];

const outputs = payloads.map(p => invokeCompress(method, byteClass, headerSize, p));
send({
    type: "result",
    payload_lengths: payloads.map(p => p.length),
    payloads_hex: payloads.map(p => toHex(p)),
    outputs_hex: outputs
});
'''


@dataclass(frozen=True)
class Envelope:
    encoded_length: int
    decoded: bytes
    header_length: int

    @property
    def body_offset(self) -> int:
        return 4 + self.header_length

    @property
    def body(self) -> bytes:
        return self.decoded[self.body_offset :]


def parse_envelope(encoded: bytes) -> Envelope:
    decoded = base64.b64decode(encoded, validate=True)
    if len(decoded) < 4:
        raise ValueError("decoded envelope too short")
    header_length = struct.unpack_from("<I", decoded, 0)[0]
    if 4 + header_length > len(decoded):
        raise ValueError("header length exceeds decoded envelope")
    return Envelope(len(encoded), decoded, header_length)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def equality_runs(values: list[bytes]) -> list[dict[str, int | bool]]:
    width = min(map(len, values))
    stable = [len({value[i] for value in values}) == 1 for i in range(width)]
    runs: list[dict[str, int | bool]] = []
    start = 0
    for i in range(1, width + 1):
        if i == width or stable[i] != stable[start]:
            runs.append({"start": start, "end": i, "stable": stable[start]})
            start = i
    return runs


def analyze(payloads: list[bytes], envelopes: list[Envelope]) -> dict[str, object]:
    header_lengths = {env.header_length for env in envelopes}
    if len(header_lengths) != 1:
        raise ValueError(f"header length changed across calls: {sorted(header_lengths)}")
    header_length = envelopes[0].header_length
    headers = [env.decoded[4 : 4 + header_length] for env in envelopes]

    # Protocol hypothesis inherited from the Python client. We report only
    # equality and hashes, never the values themselves.
    regions = {
        "fixed_head": (0, 52),
        "sid_candidate": (52, 68),
        "udid_candidate": (68, 84),
        "random_candidate": (84, 116),
        "auth_candidate": (116, header_length),
    }
    region_summary: dict[str, object] = {}
    for name, (start, end) in regions.items():
        chunks = [header[start:end] for header in headers]
        region_summary[name] = {
            "start_in_header": start,
            "end_in_header": end,
            "length": end - start,
            "stable_across_calls": len(set(chunks)) == 1,
            "sha256_prefixes": sorted({digest(chunk) for chunk in chunks}),
        }

    body_rows = []
    for payload, env, header in zip(payloads, envelopes, headers, strict=True):
        body = env.body
        ciphertext = body[:-32]
        key = body[-32:]
        ciphertext_length = len(ciphertext)

        # The Python client derives the CBC IV from the first 16 characters of
        # the lowercase, dashless UDID. Header bytes 68:84 are the raw 16-byte
        # UDID, so its hex representation reconstructs that source string.
        raw_udid = header[68:84]
        iv = raw_udid.hex()[:16].encode("ascii")
        decrypted = unpad(AES.new(key, AES.MODE_CBC, iv).decrypt(ciphertext), 16)
        declared_length = struct.unpack_from("<I", decrypted, 0)[0]
        recovered_payload = decrypted[4:]

        body_rows.append(
            {
                "payload_length": len(payload),
                "encoded_length": env.encoded_length,
                "decoded_length": len(env.decoded),
                "header_length": env.header_length,
                "body_offset": env.body_offset,
                "body_length": len(body),
                "ciphertext_length_if_key_tail_32": ciphertext_length,
                "ciphertext_block_aligned": ciphertext_length % 16 == 0,
                "tail_32_changes_per_call": True,
                "iv_rule": "ascii(raw_udid.hex()[:16])",
                "decrypted_length_prefix": declared_length,
                "decrypted_payload_matches_input": recovered_payload == payload,
                "length_prefix_matches_payload": declared_length == len(payload),
            }
        )

    return {
        "header_length": header_length,
        "decoded_absolute_offsets": {
            "length_prefix": [0, 4],
            "fixed_head": [4, 56],
            "sid_candidate": [56, 72],
            "udid_candidate": [72, 88],
            "random_candidate": [88, 120],
            "auth_candidate": [120, 4 + header_length],
            "encrypted_body": [4 + header_length, "decoded_end_minus_32"],
            "key_candidate": ["decoded_end_minus_32", "decoded_end"],
        },
        "header_equality_runs": equality_runs(headers),
        "regions": region_summary,
        "body_samples": body_rows,
        "body_tail_32_unique": len({env.body[-32:] for env in envelopes}) == len(envelopes),
        "same_length_payload_ciphertexts_differ": envelopes[0].body[:-32] != envelopes[1].body[:-32],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--remote", default="127.0.0.1:27042")
    args = parser.parse_args()

    device = frida.get_device_manager().add_remote_device(args.remote)
    process = next((p for p in device.enumerate_processes() if "UmamusumePrettyDerby" in p.name), None)
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
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    payloads = [bytes.fromhex(value) for value in result["payloads_hex"]]
    envelopes = [parse_envelope(bytes.fromhex(value)) for value in result["outputs_hex"]]
    print(json.dumps(analyze(payloads, envelopes), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
