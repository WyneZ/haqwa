# Haqwa Contracts

**Status: LOCKED (2026-09-25, both developers agreed — see docs/decisions.md).**
Changes after lock: both agree + a line in `docs/decisions.md`.

JSON Schemas generated from the code live in `docs/schemas/` (`spec`, `unsupported_rule`, `event`, `event_map`, `report`).
The Pydantic models in `src/haqwa/core/` are the source; the schemas are regenerated from them.

---

## C1 — Spec model (`core/spec.py`)

A sealed spec is `rules.spec.yaml`: `version: 1` + a list of rules. Every rule has:

| Field | Type | Meaning |
|---|---|---|
| `id` | slug `^[a-z0-9][a-z0-9-]*$`, unique | Stable rule id, e.g. `no-double-charge` |
| `source` | string | Original English rule text |
| `pattern` | one of the 4 below | Selects the rule shape (discriminator) |
| `per` | string | Entity key in event `data`, e.g. `order_id` |
| `except` | list, optional | `reset_after` / `allow_if` exceptions |
| `confirmed_examples` | list, optional | Owner's Yes/No answers; used as self-tests |

Unknown keys are rejected (typos fail loudly). The spec is immutable after loading.

### Patterns (pattern-specific fields)

| Pattern | Fields | Meaning (per entity) | Status |
|---|---|---|---|
| `at_most_once` | `event` | `event` happens at most once | implemented |
| `never_after` | `event`, `after` | once `after` happened, `event` must not happen | week 2 |
| `must_precede` | `event`, `requires` | `event` only if `requires` happened earlier | week 2 |
| `within_time` | `start`, `event`, `within` | after `start`, `event` must happen within `within` (seconds or ISO 8601, e.g. `PT24H`) | week 2 |

### Exceptions

| Exception | Form | Semantics |
|---|---|---|
| `reset_after` | `reset_after: refunded` | When this event happens for the entity, the rule forgets what it saw before |
| `allow_if` | `allow_if: {field, op, value}` | Events matching the condition are invisible to the rule. Multiple `allow_if` = OR |

Condition: `op` is `eq`, `ne` or `in` (`in` needs a list). A field missing from the event never matches (also for `ne`). Conditions are data, never evaluated as code.

### Confirmed examples

```yaml
confirmed_examples:
  - timeline: [{event: charged}, {event: refunded}, {event: charged}]
    violation: false
  - timeline:
      - {event: charged, data: {payment_type: installment}}
      - {event: charged, data: {payment_type: installment}}
    violation: false
```

Timeline items use the same `{event, data}` shape as C2 events (no `ts`; the self-test adds increasing timestamps and one synthetic entity id).

### Unsupported rules (not part of a sealed spec)

`UnsupportedRule {source, reason}` — what `ai/parse` returns when a rule fits no pattern ("not supported yet"). A sealed spec only contains supported rules.

---

## C2 — Event format (`core/events.py`)

```json
{"event": "PAYMENT_CAPTURED", "ts": "2026-10-01T10:00:45Z",
 "data": {"order_id": "A-1", "amount": 50}, "source_id": "evt_123"}
```

| Field | Type | Notes |
|---|---|---|
| `event` | non-empty string | System name before mapping; rule vocabulary after |
| `ts` | timezone-aware datetime | Naive timestamps are rejected |
| `data` | object | All other fields; rules read `data[per]` and `allow_if` fields here |
| `source_id` | string, optional | Id in the original system, for tracing |

Event files: a JSON array of events.

### Event map (`events.map.yaml`)

```yaml
version: 1
events:
  charged: [PAYMENT_CAPTURED]   # rule name -> one or more system names
  refunded: REFUND_ISSUED       # a single name is also fine
```

A system name may map to only one rule name. Events not in the map are dropped before checking. Without a map, event names are used as-is.

### Check pipeline

translate (map) → sort by `ts` (stable for equal timestamps) → group by `data[per]` (events without the key are skipped) → evaluate each rule per entity.

---

## Library API used by CLI and web (Track B)

```python
from haqwa import load_spec, load_event_map, load_events, compile_spec, check, format_text

compiled = compile_spec(spec, event_map)   # raises CompileError(problems, failures)
report = check(compiled, events, event_map)
report.passed; report.model_dump()          # JSON-ready
```

`compile_spec` fails if a pattern isn't implemented, a rule uses an event name not in the event map, or any confirmed example disagrees with the checker (`CompileError.failures` lists each example: expected vs got).

`Report` → `results[]: {rule_id, source, status: "pass"|"violation", violations[]}`;
`Violation` → `{rule_id, entity, message, timeline: Event[], offending_index}`.

---

## C3 — Web API (`web/`)

To be drafted together; Track A writes it. Suggested inputs/outputs from the core side:
- compile: spec (C1 JSON) + event map → ok, or `CompileError` problems/failures (show the failing example to the owner)
- check: spec + event map + events (C2 JSON) → `Report` JSON

---

## Open questions (decide before lock)

1. **`within_time` examples need time.** Timeline items have no time; add an optional offset such as `at: PT25H`?
2. **`within_time` at end of trace:** `start` seen, deadline not reached, no `event` yet — pass or "pending"?
3. **Events missing the `per` key** are skipped silently. Add a warning count to the report?
4. **Entity id types:** `"123"` and `123` are different entities today. Normalize to string?
5. **Gemini + discriminated union:** the spec schema uses `oneOf` + `discriminator`. Unverified whether Gemini structured output handles this well — Track A to test in the spike. Fallback: Gemini fills a flat draft model; `core/spec.py` validates it.
6. **Naming:** brief says `compile()`; code uses `compile_spec()` to avoid shadowing Python's built-in `compile`.
7. **Stubs:** instead of fixed-output stubs, `at_most_once` is real already; other patterns raise "not implemented yet" at compile until week 2.

Parking list (not in MVP): field renaming in the event map (e.g. `orderId` → `order_id`).
