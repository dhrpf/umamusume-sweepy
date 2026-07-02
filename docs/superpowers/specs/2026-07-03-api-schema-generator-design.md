# API Payload Schema Generator Design

## Goal

Generate compact human and machine-readable request/response schema docs from captured Uma Musume API trace JSONL files, so agents can inspect endpoint formats without loading 1MB+ payloads.

## Context

Trace files live under uma_runtime/<account>/trace_logs/api_payloads/*.jsonl.

Each line is one JSON object:

- ts: unix timestamp
- direction: REQ, RES, or ERR
- endpoint: API path like single_mode_free/check_event
- data: request payload wrapper, response object, or error object
- req_id: optional request/response correlation id

The trace directory can be large; the inspected acct02 payload set has 167 JSONL files and about 1.7GB total data. The generator must stream line-by-line and never read all logs into memory.

## Architecture

Create one standalone script: scripts/generate_api_schemas.py.

The script is offline tooling only. It does not change UmaClient, runtime API calls, or captured payload format.

Inputs:

- default: uma_runtime/*/trace_logs/api_payloads/*.jsonl
- optional positional paths: file or directory roots
- optional --out docs/api_schemas
- optional --max-files N
- optional --max-lines N

Outputs:

- docs/api_schemas/index.md
- docs/api_schemas/schema_index.json
- docs/api_schemas/<endpoint_slug>.md
- docs/api_schemas/<endpoint_slug>.json

Endpoint slug rule: replace slash with double underscore, then replace non A-Za-z0-9_.- chars with underscore.

## Schema model

Group records by endpoint and direction.

For each group, infer a tree of fields:

- path: dot/bracket path, e.g. data.chara_info.turn, data.home_info.command_info_array[]
- types: sorted type set: null, bool, int, float, str, dict, list
- seen_count: number of records where the path exists
- parent_count: number of parent records inspected
- optional: seen_count < parent_count
- children: nested fields for dict/list items
- examples: at most three safe short scalar examples

List handling:

- merge all observed item shapes into one [] child node
- record min_len, max_len, and non_empty_count
- do not emit raw array contents

Type handling:

- bool is distinct from int
- int/float both preserved if both seen
- strings longer than 120 chars are summarized as <str len=N>
- bytes-like hex strings are summarized, not copied

## Redaction

Never write raw sensitive values to generated docs.

Redact examples for keys matching:

- auth_key
- viewer_id
- udid
- steam_ticket
- steam_session_ticket
- device_id
- device_token
- sid
- dmm_viewer_id
- dmm_onetime_token
- ip_address

Also redact suspicious values by pattern:

- long hex strings: length >= 32 and hex-only
- Steam ticket-like strings: length >= 80
- IPv4 addresses

Redacted values appear as <redacted>. Field names remain visible because they are needed for schema maintenance.

## Markdown format

index.md contains:

- generation timestamp
- scanned file count and line count
- endpoint table with REQ/RES/ERR counts
- links to per-endpoint markdown files

Each endpoint markdown contains:

- endpoint name
- counts by direction
- request schema section
- response schema section
- error schema section when present
- compact field tables with path, types, seen, optional, examples

## JSON format

schema_index.json contains:

- metadata: generated_at, input_paths, file_count, line_count
- endpoint list with direction counts and schema file names

Each endpoint JSON contains:

- metadata for that endpoint
- one schema tree per direction
- flattened field list for easy grep/agent use

## Error handling

Malformed JSONL lines are skipped and counted.

Unreadable files are skipped and reported.

If no trace records are found, the script exits non-zero with a short message.

Generated docs should still be useful when some files are corrupt.

## Testing

Add tests/test_generate_api_schemas.py with tiny synthetic JSONL fixtures.

Required checks:

- writes both markdown and JSON outputs
- groups by endpoint and direction
- infers optional fields and union types
- merges list item shapes
- redacts sensitive values and long token-like strings
- skips malformed JSONL lines while counting them

Run:

- rtk proxy pytest tests/test_generate_api_schemas.py -q
- rtk proxy pytest -q

## Non-goals

- no runtime validation yet
- no Pydantic/dataclass models yet
- no automatic edits to UmaClient
- no raw payload excerpts in docs
- no full line coverage target in this feature

Strict models can be added later after the schema output stabilizes.

## Approval

User selected approach C: generate both human-readable markdown and machine-readable JSON.
