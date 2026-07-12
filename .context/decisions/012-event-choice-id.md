# ADR-012: Event choice_number uses gain_select_id_index

## Problem

Server event choices expose `gain_select_id_index`; sending position-only `select_index` can produce 205 when ids have gaps.

## Decision

Scenario choice helpers prefer:

```python
choice.get("gain_select_id_index", choice.get("select_index", 0))
```

Use `select_index` only for older payloads lacking `gain_select_id_index`.

## Consequences

Keep event choice behavior aligned across Mant and URA. Validate against captured event payloads and existing scenario/event tests; do not claim coverage from absent test files.
