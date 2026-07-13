import hashlib
import struct

from scripts.probe_protocol_salt import find_md5_suffix_candidates


def make_metadata_string_literals(*values: bytes) -> tuple[bytes, int]:
    table_offset = 24
    table = bytearray()
    data = bytearray()
    for value in values:
        table += struct.pack("<ii", len(value), len(data))
        data += value
    data_offset = table_offset + len(table)
    header = struct.pack(
        "<Iiiiii",
        0xFAB11BAF,
        31,
        table_offset,
        len(table),
        data_offset,
        len(data),
    )
    return header + table + data, data_offset


def test_find_md5_suffix_candidates_finds_literal_salt_and_offset():
    probe = b"sweepy-protocol-probe"
    salt = b"co!=Y;(UQCGxJ_n82"
    metadata, data_offset = make_metadata_string_literals(b"unrelated", salt, b"after")
    digest = hashlib.md5(probe + salt).hexdigest()

    assert find_md5_suffix_candidates(metadata, probe, digest) == [
        (data_offset + len(b"unrelated"), salt)
    ]


def test_find_md5_suffix_candidates_returns_empty_for_plain_md5():
    probe = b"sweepy-protocol-probe"
    metadata, _ = make_metadata_string_literals(b"alpha", b"beta", b"gamma")
    digest = hashlib.md5(probe).hexdigest()

    assert find_md5_suffix_candidates(metadata, probe, digest) == []
