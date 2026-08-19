from uma_api.client import get_raw_udid, pack, unpack_request


def test_unpack_request_uses_embedded_udid_when_cached_udid_is_stale():
    request_udid = "12345678-1234-5678-1234-567812345678"
    stale_udid = "87654321-4321-8765-4321-876543218765"
    payload = {"single_mode_start_request_common": {"scenario_id": 3}}
    body = pack(b"s" * 16, get_raw_udid(request_udid), None, payload, request_udid)

    assert unpack_request(body, stale_udid) == payload
