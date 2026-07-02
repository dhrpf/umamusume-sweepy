import json

import pytest

from scripts import generate_api_schemas as gen


def write_jsonl(path, records, malformed=False):
    lines = [json.dumps(record, ensure_ascii=False) for record in records]
    if malformed:
        lines.append("{not valid json")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_slugify_endpoint():
    assert gen.slugify_endpoint("single_mode_free/check_event") == "single_mode_free__check_event"
    assert gen.slugify_endpoint("odd endpoint/with spaces") == "odd_endpoint__with_spaces"


def test_generate_writes_markdown_and_json_with_redaction(tmp_path):
    trace = tmp_path / "payloads.jsonl"
    out_dir = tmp_path / "schemas"
    long_ticket = "A" * 90
    long_hex = "abcdef0123456789abcdef0123456789"

    write_jsonl(
        trace,
        [
            {
                "ts": 1.0,
                "direction": "REQ",
                "endpoint": "foo/bar",
                "req_id": "r1",
                "data": {
                    "payload": {
                        "viewer_id": 9561133755639,
                        "turn": 1,
                        "device_id": long_hex,
                        "items": [
                            {"id": 10, "name": "apple"},
                            {"id": "11", "extra": True},
                        ],
                    }
                },
            },
            {
                "ts": 2.0,
                "direction": "REQ",
                "endpoint": "foo/bar",
                "req_id": "r2",
                "data": {
                    "payload": {
                        "turn": None,
                        "items": [],
                    }
                },
            },
            {
                "ts": 3.0,
                "direction": "RES",
                "endpoint": "foo/bar",
                "req_id": "r1",
                "data": {
                    "response_code": 1,
                    "data": {
                        "status": "ok",
                        "ticket_like": long_ticket,
                    },
                    "data_headers": {
                        "sid": "secret-session-id",
                    },
                },
            },
        ],
        malformed=True,
    )

    stats = gen.generate([trace], out_dir)

    assert stats["file_count"] == 1
    assert stats["line_count"] == 3
    assert stats["malformed_line_count"] == 1
    assert (out_dir / "index.md").exists()
    assert (out_dir / "schema_index.json").exists()
    assert (out_dir / "foo__bar.md").exists()
    assert (out_dir / "foo__bar.json").exists()

    endpoint_doc = (out_dir / "foo__bar.md").read_text(encoding="utf-8")
    endpoint_json_text = (out_dir / "foo__bar.json").read_text(encoding="utf-8")
    assert "foo/bar" in endpoint_doc
    assert "$.payload.turn" in endpoint_doc
    assert "$.payload.items[].id" in endpoint_doc
    assert "<redacted>" in endpoint_doc
    assert "9561133755639" not in endpoint_doc
    assert long_ticket not in endpoint_doc
    assert long_hex not in endpoint_doc
    assert "secret-session-id" not in endpoint_doc
    assert "9561133755639" not in endpoint_json_text
    assert long_ticket not in endpoint_json_text
    assert long_hex not in endpoint_json_text
    assert "secret-session-id" not in endpoint_json_text

    sentinels = ["9561133755639", long_ticket, long_hex, "secret-session-id"]
    for generated in sorted(path for path in out_dir.rglob("*") if path.is_file()):
        text = generated.read_text(encoding="utf-8")
        for sentinel in sentinels:
            assert sentinel not in text, f"{sentinel!r} leaked in {generated.name}"

    endpoint = read_json(out_dir / "foo__bar.json")
    assert endpoint["endpoint"] == "foo/bar"
    assert endpoint["counts"] == {"REQ": 2, "RES": 1}

    fields = {field["path"]: field for field in endpoint["flat_fields"]["REQ"]}
    assert fields["$.payload.turn"]["types"] == ["int", "null"]
    assert fields["$.payload.turn"]["optional"] is False
    assert fields["$.payload.items[].id"]["types"] == ["int", "str"]
    assert fields["$.payload.items[].extra"]["optional"] is True
    assert fields["$.payload.items"]["min_len"] == 0
    assert fields["$.payload.items"]["max_len"] == 2


def test_redacts_generic_sensitive_keys_and_jwt_examples(tmp_path):
    trace = tmp_path / "payloads.jsonl"
    out_dir = tmp_path / "schemas"
    sensitive_values = {
        "access token": "access-token-value-should-not-leak",
        "token": "token-value-should-not-leak",
        "jwt": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.c2lnbmF0dXJl",
    }

    write_jsonl(
        trace,
        [
            {
                "direction": "REQ",
                "endpoint": "auth/test",
                "data": {
                    "payload": {
                        "access_token": sensitive_values["access token"],
                        "token": sensitive_values["token"],
                        "safe_name": "visible",
                        "safe_jwt_carrier": sensitive_values["jwt"],
                    }
                },
            }
        ],
    )

    gen.generate([trace], out_dir)

    endpoint_doc = (out_dir / "auth__test.md").read_text(encoding="utf-8")
    assert "$.payload.access_token" in endpoint_doc
    assert "$.payload.token" in endpoint_doc
    assert "$.payload.safe_jwt_carrier" in endpoint_doc
    assert "visible" in endpoint_doc
    for generated in sorted(path for path in out_dir.rglob("*") if path.is_file()):
        text = generated.read_text(encoding="utf-8")
        leaked = [label for label, value in sensitive_values.items() if value in text]
        assert leaked == [], f"sensitive examples leaked in {generated.name}: {leaked}"


def test_redacts_steam_id_value_but_preserves_field_name(tmp_path):
    trace = tmp_path / "payloads.jsonl"
    out_dir = tmp_path / "schemas"
    steam_id = "".join(["7656119", "8688173820"])
    write_jsonl(
        trace,
        [
            {
                "direction": "REQ",
                "endpoint": "steam/id",
                "data": {"payload": {"steam_id": steam_id, "visible": "ok"}},
            }
        ],
    )

    gen.generate([trace], out_dir)

    endpoint_doc = (out_dir / "steam__id.md").read_text(encoding="utf-8")
    assert "$.payload.steam_id" in endpoint_doc
    has_redacted_example = "<redacted>" in endpoint_doc
    assert has_redacted_example
    for generated in sorted(path for path in out_dir.rglob("*") if path.is_file()):
        text = generated.read_text(encoding="utf-8")
        leaked = steam_id in text
        assert not leaked, f"steam_id value leaked in {generated.name}"


def test_collapses_dynamic_dict_keys_without_leaking_values(tmp_path):
    trace = tmp_path / "payloads.jsonl"
    out_dir = tmp_path / "schemas"
    dynamic_keys = {
        "hex": "abcdef0123456789abcdef0123456789",
        "jwt": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJkeW4ifQ.c2ln",
        "uuid": "-".join(["123e4567", "e89b", "12d3", "a456", "426614174000"]),
        "numeric id": "9561133755639",
        "ip": "192.168.10.25",
        "long token": "tokenlikevalue" * 8,
    }

    write_jsonl(
        trace,
        [
            {
                "direction": "REQ",
                "endpoint": "dynamic/keys",
                "data": {
                    "payload": {
                        "map": {
                            dynamic_keys["hex"]: {"value": 1},
                            dynamic_keys["jwt"]: {"value": 2},
                            dynamic_keys["uuid"]: {"value": 3},
                            dynamic_keys["numeric id"]: {"value": 4},
                            dynamic_keys["ip"]: {"value": 5},
                            dynamic_keys["long token"]: {"value": 6},
                            "ordinary_field": {"value": 6},
                        },
                        "viewer_id": 12345,
                        "access_token": "field-name-preserved-but-value-redacted",
                        "token": "also-redacted",
                    }
                },
            }
        ],
    )

    gen.generate([trace], out_dir)

    endpoint = read_json(out_dir / "dynamic__keys.json")
    paths = {field["path"] for field in endpoint["flat_fields"]["REQ"]}
    assert "$.payload.map.<redacted_key>.value" in paths
    assert "$.payload.map.<id>.value" in paths
    assert "$.payload.map.ordinary_field.value" in paths
    assert "$.payload.viewer_id" in paths
    assert "$.payload.access_token" in paths
    assert "$.payload.token" in paths

    for generated in sorted(path for path in out_dir.rglob("*") if path.is_file()):
        text = generated.read_text(encoding="utf-8")
        leaked = [label for label, value in dynamic_keys.items() if value in text]
        assert leaked == [], f"dynamic keys leaked in {generated.name}: {leaked}"


def test_preserves_long_snake_case_api_field_names(tmp_path):
    trace = tmp_path / "payloads.jsonl"
    out_dir = tmp_path / "schemas"
    field_name = "single_mode_chara_effect_id_array"
    write_jsonl(
        trace,
        [
            {
                "direction": "REQ",
                "endpoint": "normal/field",
                "data": {field_name: [1, 2, 3]},
            }
        ],
    )

    gen.generate([trace], out_dir)

    endpoint = read_json(out_dir / "normal__field.json")
    paths = {field["path"] for field in endpoint["flat_fields"]["REQ"]}
    assert f"$.{field_name}" in paths
    assert "$.<redacted_key>" not in paths


def test_slug_collisions_are_stable_across_trace_order(tmp_path):
    out_a = tmp_path / "schemas_a"
    out_b = tmp_path / "schemas_b"
    trace_a = tmp_path / "a.jsonl"
    trace_b = tmp_path / "b.jsonl"
    first_order = [
        {"direction": "REQ", "endpoint": "same_slug", "data": {"payload": {"a": 1}}},
        {"direction": "REQ", "endpoint": "same slug", "data": {"payload": {"b": 2}}},
    ]
    second_order = list(reversed(first_order))
    write_jsonl(trace_a, first_order)
    write_jsonl(trace_b, second_order)

    gen.generate([trace_a], out_a)
    gen.generate([trace_b], out_b)

    slugs_a = {
        item["endpoint"]: item["slug"]
        for item in read_json(out_a / "schema_index.json")["endpoints"]
    }
    slugs_b = {
        item["endpoint"]: item["slug"]
        for item in read_json(out_b / "schema_index.json")["endpoints"]
    }
    assert slugs_a == slugs_b
    assert len(set(slugs_a.values())) == 2


def test_stale_generated_outputs_are_removed_from_manifest_only(tmp_path):
    out_dir = tmp_path / "schemas"
    old_trace = tmp_path / "old.jsonl"
    new_trace = tmp_path / "new.jsonl"
    keep_file = out_dir / "keep.md"
    out_dir.mkdir()
    keep_file.write_text("not generated\n", encoding="utf-8")
    write_jsonl(old_trace, [{"direction": "REQ", "endpoint": "old/one", "data": {"payload": {"a": 1}}}])
    write_jsonl(new_trace, [{"direction": "REQ", "endpoint": "new/two", "data": {"payload": {"b": 2}}}])

    gen.generate([old_trace], out_dir)
    assert (out_dir / "old__one.md").exists()
    assert (out_dir / "old__one.json").exists()

    gen.generate([new_trace], out_dir)

    assert (out_dir / "new__two.md").exists()
    assert (out_dir / "new__two.json").exists()
    assert not (out_dir / "old__one.md").exists()
    assert not (out_dir / "old__one.json").exists()
    assert keep_file.exists()


def test_no_record_run_preserves_existing_generated_outputs(tmp_path):
    out_dir = tmp_path / "schemas"
    old_trace = tmp_path / "old.jsonl"
    missing_trace = tmp_path / "missing.jsonl"
    write_jsonl(old_trace, [{"direction": "REQ", "endpoint": "old/one", "data": {"payload": {"a": 1}}}])
    gen.generate([old_trace], out_dir)

    before_index = (out_dir / "schema_index.json").read_text(encoding="utf-8")
    before_doc = (out_dir / "old__one.md").read_text(encoding="utf-8")

    stats = gen.generate([missing_trace], out_dir)

    assert stats["line_count"] == 0
    assert (out_dir / "old__one.md").read_text(encoding="utf-8") == before_doc
    assert (out_dir / "schema_index.json").read_text(encoding="utf-8") == before_index


def test_failed_new_generation_preserves_existing_outputs(tmp_path, monkeypatch):
    out_dir = tmp_path / "schemas"
    old_trace = tmp_path / "old.jsonl"
    new_trace = tmp_path / "new.jsonl"
    write_jsonl(old_trace, [{"direction": "REQ", "endpoint": "old/one", "data": {"payload": {"a": 1}}}])
    write_jsonl(new_trace, [{"direction": "REQ", "endpoint": "new/two", "data": {"payload": {"b": 2}}}])
    gen.generate([old_trace], out_dir)
    before_index = (out_dir / "schema_index.json").read_text(encoding="utf-8")
    before_doc = (out_dir / "old__one.md").read_text(encoding="utf-8")

    def fail_render(_endpoint_data):
        raise RuntimeError("render boom")

    monkeypatch.setattr(gen, "_render_endpoint_markdown", fail_render)
    with pytest.raises(RuntimeError):
        gen.generate([new_trace], out_dir)

    assert (out_dir / "old__one.md").read_text(encoding="utf-8") == before_doc
    assert (out_dir / "schema_index.json").read_text(encoding="utf-8") == before_index
    assert not (out_dir / "new__two.json").exists()


def test_failed_final_replace_restores_existing_outputs(tmp_path, monkeypatch):
    out_dir = tmp_path / "schemas"
    old_trace = tmp_path / "old.jsonl"
    new_trace = tmp_path / "new.jsonl"
    write_jsonl(old_trace, [{"direction": "REQ", "endpoint": "old/one", "data": {"payload": {"a": 1}}}])
    write_jsonl(new_trace, [{"direction": "REQ", "endpoint": "new/two", "data": {"payload": {"b": 2}}}])
    gen.generate([old_trace], out_dir)
    before_index = (out_dir / "index.md").read_text(encoding="utf-8")
    before_manifest = (out_dir / "schema_index.json").read_text(encoding="utf-8")
    before_endpoint_md = (out_dir / "old__one.md").read_text(encoding="utf-8")
    before_endpoint_json = (out_dir / "old__one.json").read_text(encoding="utf-8")

    path_class = type(out_dir)
    original_replace = path_class.replace

    def fail_final_replace(self, target):
        target_path = path_class(target)
        if target_path.parent == out_dir and target_path.name == "new__two.json":
            raise OSError("replace boom")
        return original_replace(self, target)

    monkeypatch.setattr(path_class, "replace", fail_final_replace)
    with pytest.raises(OSError):
        gen.generate([new_trace], out_dir)

    assert (out_dir / "index.md").read_text(encoding="utf-8") == before_index
    assert (out_dir / "schema_index.json").read_text(encoding="utf-8") == before_manifest
    assert (out_dir / "old__one.md").read_text(encoding="utf-8") == before_endpoint_md
    assert (out_dir / "old__one.json").read_text(encoding="utf-8") == before_endpoint_json
    assert not (out_dir / "new__two.json").exists()


def test_discover_files_accepts_file_dir_and_default_empty(tmp_path, monkeypatch):
    trace_dir = tmp_path / "uma_runtime" / "acct" / "trace_logs" / "api_payloads"
    trace_dir.mkdir(parents=True)
    trace = trace_dir / "one.jsonl"
    write_jsonl(
        trace,
        [
            {
                "direction": "REQ",
                "endpoint": "x/y",
                "data": {"payload": {"a": 1}},
            }
        ],
    )

    assert gen.discover_files([trace]) == [trace]
    assert gen.discover_files([trace_dir]) == [trace]

    monkeypatch.chdir(tmp_path)
    assert gen.discover_files([]) == [trace]


def test_main_returns_nonzero_when_no_records(tmp_path, capsys):
    out_dir = tmp_path / "out"
    rc = gen.main([str(tmp_path / "missing"), "--out", str(out_dir)])
    assert rc == 1
    captured = capsys.readouterr()
    assert "no trace records found" in captured.err.lower()
