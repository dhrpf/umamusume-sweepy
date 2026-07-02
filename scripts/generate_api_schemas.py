#!/usr/bin/env python3
"""Generate compact API payload schemas from JSONL trace logs.

The generator streams input files line-by-line and keeps only aggregate
schema counters/examples in memory. It intentionally avoids retaining raw
payload records because trace logs may contain credentials.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import re
import shutil
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


SENSITIVE_KEYS = {
    "auth_key",
    "viewer_id",
    "udid",
    "steam_ticket",
    "steam_session_ticket",
    "steam_id",
    "device_id",
    "device_token",
    "sid",
    "dmm_viewer_id",
    "dmm_onetime_token",
    "ip_address",
}
SENSITIVE_KEY_SUBSTRINGS = (
    "token",
    "ticket",
    "auth",
    "secret",
    "sid",
    "session",
    "steam_id",
    "viewer_id",
    "udid",
    "device_id",
    "ip_address",
)

LONG_HEX_RE = re.compile(r"^[0-9a-fA-F]{32,}$")
JWT_LIKE_RE = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")
LONG_NUMERIC_ID_RE = re.compile(r"^\d{8,}$")
TOKEN_LIKE_KEY_RE = re.compile(r"^[A-Za-z0-9-]{64,}$")
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
IPV4_RE = re.compile(
    r"^(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)$"
)
SAFE_SLUG_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def slugify_endpoint(endpoint: str) -> str:
    """Return a filesystem-safe endpoint slug."""

    slug = str(endpoint).replace("/", "__")
    slug = SAFE_SLUG_RE.sub("_", slug)
    slug = slug.strip("_")
    return slug or "unknown"


def discover_files(paths: Iterable[str | Path]) -> list[Path]:
    """Resolve explicit files/dirs, or discover default API payload JSONL logs."""

    found: list[Path] = []
    input_paths = [Path(path) for path in paths]
    if not input_paths:
        input_paths = [Path.cwd() / "uma_runtime"]

    for path in input_paths:
        if path.is_file():
            if path.suffix == ".jsonl":
                found.append(path)
            continue
        if path.is_dir():
            if path.name == "uma_runtime":
                found.extend(path.glob("*/trace_logs/api_payloads/*.jsonl"))
            else:
                found.extend(path.rglob("*.jsonl"))

    return sorted(dict.fromkeys(found))


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _path_keys(path: str) -> set[str]:
    keys: set[str] = set()
    for part in path.replace("$.", "").split("."):
        cleaned = part.replace("[]", "").lower()
        if cleaned:
            keys.add(cleaned)
    return keys


def _last_path_key(path: str) -> str:
    return path.rsplit(".", 1)[-1].replace("[]", "").lower()


def _safe_dict_key_segment(key: Any) -> str:
    key_text = str(key)
    if LONG_NUMERIC_ID_RE.fullmatch(key_text):
        return "<id>"
    if (
        len(key_text) >= 80
        or LONG_HEX_RE.fullmatch(key_text)
        or JWT_LIKE_RE.fullmatch(key_text)
        or UUID_RE.fullmatch(key_text)
        or IPV4_RE.fullmatch(key_text)
        or TOKEN_LIKE_KEY_RE.fullmatch(key_text)
    ):
        return "<redacted_key>"
    return key_text


def _should_redact(path: str, value: Any) -> bool:
    if _path_keys(path) & SENSITIVE_KEYS:
        return True
    last_key = _last_path_key(path)
    if any(fragment in last_key for fragment in SENSITIVE_KEY_SUBSTRINGS):
        return True
    if isinstance(value, str):
        if len(value) >= 80:
            return True
        if JWT_LIKE_RE.fullmatch(value):
            return True
        if LONG_HEX_RE.fullmatch(value):
            return True
        if IPV4_RE.fullmatch(value):
            return True
    return False


def _example_value(path: str, value: Any) -> Any:
    if _should_redact(path, value):
        return "<redacted>"
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return None


@dataclass
class FieldStats:
    path: str
    parent_path: str
    types: set[str] = field(default_factory=set)
    seen_count: int = 0
    examples: list[Any] = field(default_factory=list)
    min_len: int | None = None
    max_len: int | None = None
    non_empty_count: int = 0

    def observe(self, value: Any) -> None:
        self.seen_count += 1
        self.types.add(_type_name(value))
        if isinstance(value, list):
            length = len(value)
            self.min_len = length if self.min_len is None else min(self.min_len, length)
            self.max_len = length if self.max_len is None else max(self.max_len, length)
            if length:
                self.non_empty_count += 1

        example = _example_value(self.path, value)
        if example is not None and example not in self.examples and len(self.examples) < 3:
            self.examples.append(example)

    def to_dict(self, parent_count: int) -> dict[str, Any]:
        item: dict[str, Any] = {
            "path": self.path,
            "types": sorted(self.types),
            "seen_count": self.seen_count,
            "parent_count": parent_count,
            "optional": self.seen_count < parent_count,
        }
        if "list" in self.types:
            item["min_len"] = self.min_len if self.min_len is not None else 0
            item["max_len"] = self.max_len if self.max_len is not None else 0
            item["non_empty_count"] = self.non_empty_count
        if self.examples:
            item["examples"] = self.examples
        return item


class DirectionSchema:
    def __init__(self) -> None:
        self.fields: dict[str, FieldStats] = {}
        self.parent_counts: defaultdict[str, int] = defaultdict(int)

    def observe(self, payload: Any) -> None:
        if isinstance(payload, dict):
            self._observe_dict(payload, "$", count_parent=True)
        else:
            self.parent_counts["$"] += 1
            field_stats = self._field("$", "$")
            field_stats.observe(payload)

    def flat_fields(self) -> list[dict[str, Any]]:
        output = []
        for path in sorted(self.fields):
            stat = self.fields[path]
            parent_count = self.parent_counts.get(stat.parent_path, stat.seen_count)
            output.append(stat.to_dict(parent_count))
        return output

    def _field(self, path: str, parent_path: str) -> FieldStats:
        existing = self.fields.get(path)
        if existing is None:
            existing = FieldStats(path=path, parent_path=parent_path)
            self.fields[path] = existing
        return existing

    def _observe_dict(self, value: dict[str, Any], parent_path: str, *, count_parent: bool) -> None:
        if count_parent:
            self.parent_counts[parent_path] += 1
        for key, child in value.items():
            key_text = _safe_dict_key_segment(key)
            child_path = f"{parent_path}.{key_text}" if parent_path != "$" else f"$.{key_text}"
            self._field(child_path, parent_path).observe(child)
            if isinstance(child, dict):
                self._observe_dict(child, child_path, count_parent=True)
            elif isinstance(child, list):
                self._observe_list(child, child_path)

    def _observe_list(self, value: list[Any], path: str) -> None:
        item_path = f"{path}[]"
        for child in value:
            self.parent_counts[item_path] += 1
            self._field(item_path, item_path).observe(child)
            if isinstance(child, dict):
                self._observe_dict(child, item_path, count_parent=False)
            elif isinstance(child, list):
                self._observe_list(child, item_path)


@dataclass
class EndpointSchema:
    endpoint: str
    slug: str
    counts: defaultdict[str, int] = field(default_factory=lambda: defaultdict(int))
    directions: dict[str, DirectionSchema] = field(default_factory=dict)

    def observe(self, direction: str, payload: Any) -> None:
        self.counts[direction] += 1
        schema = self.directions.setdefault(direction, DirectionSchema())
        schema.observe(payload)

    def to_dict(self) -> dict[str, Any]:
        direction_names = _ordered_directions(self.directions.keys())
        return {
            "endpoint": self.endpoint,
            "slug": self.slug,
            "counts": {direction: self.counts[direction] for direction in _ordered_directions(self.counts.keys())},
            "flat_fields": {
                direction: self.directions[direction].flat_fields()
                for direction in direction_names
            },
        }


def _ordered_directions(names: Iterable[str]) -> list[str]:
    names_set = set(names)
    ordered = [name for name in ("REQ", "RES") if name in names_set]
    ordered.extend(sorted(names_set - set(ordered)))
    return ordered


def _payload_from_record(record: dict[str, Any]) -> Any:
    if "data" in record:
        return record["data"]
    if "payload" in record:
        return {"payload": record["payload"]}
    return {}


def _assign_stable_slugs(endpoints: dict[str, EndpointSchema]) -> None:
    base_groups: defaultdict[str, list[str]] = defaultdict(list)
    for endpoint in endpoints:
        base_groups[slugify_endpoint(endpoint)].append(endpoint)

    proposed: dict[str, str] = {}
    for base, names in base_groups.items():
        sorted_names = sorted(names)
        if len(sorted_names) == 1:
            proposed[sorted_names[0]] = base
            continue
        for index, endpoint in enumerate(sorted_names, start=1):
            proposed[endpoint] = base if index == 1 else f"{base}_{index}"

    used: set[str] = set()
    for endpoint in sorted(endpoints):
        slug = proposed[endpoint]
        if slug in used:
            digest = hashlib.sha1(endpoint.encode("utf-8")).hexdigest()[:8]
            slug = f"{slugify_endpoint(endpoint)}_{digest}"
            suffix = 2
            while slug in used:
                slug = f"{slugify_endpoint(endpoint)}_{digest}_{suffix}"
                suffix += 1
        endpoints[endpoint].slug = slug
        used.add(slug)


def _safe_manifest_slug(value: Any) -> str | None:
    if not isinstance(value, str) or value in {"", ".", ".."}:
        return None
    if "/" in value or "\\" in value:
        return None
    return value


def _previous_generated_filenames(out_path: Path) -> set[str]:
    manifest_path = out_path / "schema_index.json"
    filenames = {"index.md", "schema_index.json"}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = {}
        for endpoint in manifest.get("endpoints", []) if isinstance(manifest, dict) else []:
            if isinstance(endpoint, dict):
                slug = _safe_manifest_slug(endpoint.get("slug"))
                if slug:
                    filenames.add(f"{slug}.md")
                    filenames.add(f"{slug}.json")
    return filenames


def _cleanup_previous_outputs(out_path: Path) -> None:
    for filename in _previous_generated_filenames(out_path):
        path = out_path / filename
        if path.is_file():
            path.unlink()


def _commit_staged_outputs(out_path: Path, staging_path: Path) -> None:
    out_path.mkdir(parents=True, exist_ok=True)
    backup_path = Path(tempfile.mkdtemp(prefix=f".{out_path.name}.bak.", dir=out_path.parent))
    staged_files = sorted((path for path in staging_path.iterdir() if path.is_file()), key=lambda path: path.name)
    staged_names = {path.name for path in staged_files}
    backup_names = sorted(_previous_generated_filenames(out_path) | staged_names)
    moved_names: list[str] = []
    try:
        for name in backup_names:
            target = out_path / name
            if target.is_file():
                target.replace(backup_path / name)

        for staged_file in staged_files:
            target = out_path / staged_file.name
            staged_file.replace(target)
            moved_names.append(staged_file.name)
    except Exception:
        for name in reversed(moved_names):
            target = out_path / name
            if target.is_file():
                target.unlink()
        for backup_file in sorted((path for path in backup_path.iterdir() if path.is_file()), key=lambda path: path.name):
            backup_file.replace(out_path / backup_file.name)
        raise
    finally:
        shutil.rmtree(backup_path, ignore_errors=True)


def _write_outputs_atomically(out_path: Path, endpoint_dicts: list[dict[str, Any]], index_data: dict[str, Any]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    staging_path = Path(tempfile.mkdtemp(prefix=f".{out_path.name}.tmp.", dir=out_path.parent))
    try:
        for endpoint_data in endpoint_dicts:
            slug = endpoint_data["slug"]
            (staging_path / f"{slug}.json").write_text(
                json.dumps(endpoint_data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            (staging_path / f"{slug}.md").write_text(
                _render_endpoint_markdown(endpoint_data),
                encoding="utf-8",
            )

        (staging_path / "schema_index.json").write_text(
            json.dumps(index_data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (staging_path / "index.md").write_text(_render_index_markdown(index_data), encoding="utf-8")

        _commit_staged_outputs(out_path, staging_path)
    finally:
        shutil.rmtree(staging_path, ignore_errors=True)


def generate(
    input_paths: Iterable[str | Path],
    out_dir: str | Path,
    max_files: int | None = None,
    max_lines: int | None = None,
) -> dict[str, Any]:
    """Stream trace JSONL files and write schema Markdown/JSON artifacts."""

    files = discover_files(input_paths)
    if max_files is not None:
        files = files[:max(0, max_files)]

    endpoints: dict[str, EndpointSchema] = {}
    valid_records = 0
    physical_lines = 0
    malformed_lines = 0
    files_read = 0

    for path in files:
        try:
            stream = path.open("r", encoding="utf-8", errors="replace")
        except OSError:
            continue
        files_read += 1
        with stream:
            for line in stream:
                if max_lines is not None and physical_lines >= max_lines:
                    break
                physical_lines += 1
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    malformed_lines += 1
                    continue
                if not isinstance(record, dict):
                    malformed_lines += 1
                    continue

                endpoint = str(record.get("endpoint") or "unknown")
                direction = str(record.get("direction") or "UNKNOWN").upper()
                endpoint_schema = endpoints.get(endpoint)
                if endpoint_schema is None:
                    endpoint_schema = EndpointSchema(endpoint=endpoint, slug=slugify_endpoint(endpoint))
                    endpoints[endpoint] = endpoint_schema
                endpoint_schema.observe(direction, _payload_from_record(record))
                valid_records += 1
        if max_lines is not None and physical_lines >= max_lines:
            break

    stats: dict[str, Any] = {
        "file_count": files_read,
        "line_count": valid_records,
        "malformed_line_count": malformed_lines,
        "endpoint_count": len(endpoints),
    }
    if not endpoints:
        return stats

    out_path = Path(out_dir)

    _assign_stable_slugs(endpoints)
    endpoint_dicts = [endpoints[name].to_dict() for name in sorted(endpoints)]
    index_data = {
        "generated_at": _dt.datetime.now(_dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "stats": stats,
        "endpoints": [
            {
                "endpoint": item["endpoint"],
                "slug": item["slug"],
                "counts": item["counts"],
            }
            for item in endpoint_dicts
        ],
    }
    _write_outputs_atomically(out_path, endpoint_dicts, index_data)

    return stats


def _escape_md(value: Any) -> str:
    text = str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _render_examples(field_data: dict[str, Any]) -> str:
    examples = field_data.get("examples") or []
    if not examples:
        return ""
    return ", ".join(_escape_md(json.dumps(example, ensure_ascii=False)) for example in examples)


def _render_endpoint_markdown(endpoint_data: dict[str, Any]) -> str:
    lines = [
        f"# {_escape_md(endpoint_data['endpoint'])}",
        "",
        f"- Slug: {endpoint_data['slug']}",
        f"- Counts: {json.dumps(endpoint_data['counts'], sort_keys=True)}",
        "",
    ]
    for direction in _ordered_directions(endpoint_data["flat_fields"].keys()):
        lines.extend(
            [
                f"## {direction}",
                "",
                "| Path | Types | Seen | Parent | Optional | Details | Examples |",
                "|---|---:|---:|---:|---:|---|---|",
            ]
        )
        fields = endpoint_data["flat_fields"][direction]
        if not fields:
            lines.append("| _(none)_ |  |  |  |  |  |  |")
        for field_data in fields:
            details = ""
            if "min_len" in field_data:
                details = (
                    f"len {field_data['min_len']}..{field_data['max_len']}; "
                    f"non-empty {field_data['non_empty_count']}"
                )
            lines.append(
                "| "
                + " | ".join(
                    [
                        _escape_md(field_data["path"]),
                        _escape_md(", ".join(field_data["types"])),
                        str(field_data["seen_count"]),
                        str(field_data["parent_count"]),
                        str(field_data["optional"]).lower(),
                        _escape_md(details),
                        _render_examples(field_data),
                    ]
                )
                + " |"
            )
        lines.append("")
    return "\n".join(lines)


def _render_index_markdown(index_data: dict[str, Any]) -> str:
    stats = index_data["stats"]
    lines = [
        "# API Schema Index",
        "",
        f"- Files read: {stats['file_count']}",
        f"- Trace records: {stats['line_count']}",
        f"- Malformed JSON lines: {stats['malformed_line_count']}",
        f"- Endpoints: {stats['endpoint_count']}",
        "",
        "| Endpoint | Slug | Counts |",
        "|---|---|---:|",
    ]
    for endpoint in index_data["endpoints"]:
        lines.append(
            "| "
            + " | ".join(
                [
                    _escape_md(endpoint["endpoint"]),
                    endpoint["slug"],
                    _escape_md(json.dumps(endpoint["counts"], sort_keys=True)),
                ]
            )
            + " |"
        )
    if not index_data["endpoints"]:
        lines.append("| _(none)_ |  |  |")
    lines.append("")
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate API schemas from JSONL payload traces.")
    parser.add_argument("paths", nargs="*", help="Input JSONL files or directories. Defaults to uma_runtime traces.")
    parser.add_argument("--out", default="docs/api_schemas", help="Output directory.")
    parser.add_argument("--max-files", type=int, default=None, help="Maximum input files to process.")
    parser.add_argument("--max-lines", type=int, default=None, help="Maximum physical JSONL lines to read.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    stats = generate(args.paths, args.out, max_files=args.max_files, max_lines=args.max_lines)
    if stats["line_count"] == 0:
        print("no trace records found", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
