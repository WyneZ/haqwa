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

**Status: DRAFT (2026-09-29, Track A proposal) — needs Track B agreement before lock.**

### Principles

- **Stateless.** The browser holds the draft spec and sends what each call needs. No database in the MVP; Firestore stays on the roadmap (hosted service).
- **The spec is a file.** Seal returns `rules.spec.yaml` for the owner to download and commit.
- **No business logic in `web/`.** Each endpoint calls one library function (`ai/` or `core/`) and returns its result.
- **Shapes follow C1/C2.** Rules, confirmed examples, events and reports use the C1/C2 JSON shapes. Gemini's wire format (`data: [{key, value}]`) never leaves `ai/`.
- **Gemini quota.** `clarify` and `explain` return cached answers for the demo rules (`"cached": true`). A Gemini 429 becomes HTTP 429 `{"error": "gemini_quota", "message": ...}`.
- **Types.** The React app generates its TypeScript types from FastAPI's OpenAPI schema (`/openapi.json`).
- **Question wording.** Every owner question asks "Is this allowed?". Yes → `violation: false`, No → `violation: true`.

### Endpoints

| # | Method + path | Calls | Screen |
|---|---|---|---|
| 1 | `POST /api/clarify` | `ai.clarify` (decision questions) + core canonical examples (confirmations) | 1 |
| 2 | `POST /api/answers` | `ai.clarify.apply_answers` (deterministic, no LLM) | 1 |
| 3 | `POST /api/seal` | `core.compile_spec` (self-test) | 1 |
| 4 | `GET /api/scenarios` | demo scenario list (Track B) | 2 |
| 5 | `POST /api/runs` | demo runner + `core.check` (Track B) | 2–3 |
| 6 | `POST /api/explain` | `ai.explain` (advisory only) | 3 |

**1. `POST /api/clarify`** — rule texts → parsed rules + owner questions

```json
// request
{"rules": ["A customer must not be charged twice for the same order."]}
// response
{"cached": true,
 "results": [
  {"source": "A customer must not be charged twice for the same order.",
   "status": "supported",
   "rule": {"id": "no-double-charge", "source": "...", "pattern": "at_most_once",
            "event": "charged", "per": "order_id"},
   "questions": [
     {"id": "d1", "kind": "decision",
      "text": "Is a second charge allowed after a refund?",
      "timeline": [{"event": "charged"}, {"event": "refunded"}, {"event": "charged"}],
      "if_yes": {"reset_after": "refunded"}},
     {"id": "c1", "kind": "confirmation",
      "text": "Is this allowed?",
      "timeline": [{"event": "charged"}, {"event": "charged"}],
      "expected_violation": true}
   ]},
  {"source": "Every order must have an invoice.", "status": "unsupported",
   "reason": "..."}
 ]}
```

**2. `POST /api/answers`** — one rule + the owner's Yes/No answers → updated rule

```json
// request
{"rule": {"id": "no-double-charge", "pattern": "at_most_once", "...": "..."},
 "answers": [{"question": {"id": "d1", "...": "..."}, "allowed": true},
             {"question": {"id": "c1", "...": "..."}, "allowed": false}]}
// response
{"rule": {"id": "no-double-charge", "...": "...",
          "except": [{"reset_after": "refunded"}],
          "confirmed_examples": [
            {"timeline": [{"event": "charged"}, {"event": "refunded"}, {"event": "charged"}], "violation": false},
            {"timeline": [{"event": "charged"}, {"event": "charged"}], "violation": true}]},
 "mismatches": []}
```
`mismatches` lists confirmation answers that contradict the pattern (e.g. the owner says reversed order is a violation for `never_after`). The UI then asks the owner to rewrite the rule; it is not sent to core.

**3. `POST /api/seal`** — full spec (+ optional event map) → compile + self-test

```json
// request
{"spec": {"version": 1, "rules": [ ... ]}, "event_map": null}
// 200
{"ok": true, "spec_yaml": "version: 1\nrules:\n  - id: no-double-charge\n ..."}
// 422
{"ok": false, "problems": ["..."],
 "failures": [{"rule_id": "no-double-charge", "timeline": [ ... ], "expected": false, "got": true}]}
```

**4. `GET /api/scenarios`**

```json
[{"id": "naive-timeout", "agent": "naive", "fault": "timeout_after_commit",
  "description": "Payment times out after commit; the naive agent retries"},
 {"id": "fixed-timeout", "agent": "fixed", "fault": "timeout_after_commit", "description": "..."}]
```

**5. `POST /api/runs`** — spec + scenario → events + report

```json
// request
{"spec": {"version": 1, "rules": [ ... ]}, "scenario_id": "naive-timeout"}
// response
{"events": [ /* C2 events */ ], "report": { /* core Report */ }}
```

**6. `POST /api/explain`** — one violation → plain-English explanation (advisory; never changes the verdict)

```json
// request
{"rule": { /* C1 rule */ }, "violation": { /* core Violation */ }}
// response
{"text": "The order was charged twice ...", "advisory": true, "cached": false}
```

### Needed from the library API (to agree with Track B)

- `canonical_examples(rule) -> [(timeline, expected_violation, label)]` in `core/` (agreed 2026-09-27), incl. the `within_time` calendar-hours confirmation.
- `list_scenarios()` and `run_scenario(scenario_id, spec) -> (events, Report)` in `demo/` or `adapters/`.

### Open C3 questions

1. ~~Who makes the rule `id` slug?~~ **Resolved 2026-09-29 (AGREED):** `core` suggests an id once for a new rule (`suggest_rule_id(text, existing_ids)`: keywords → `^[a-z0-9][a-z0-9-]*$`, `-2` suffix if taken); the owner may edit it; after that the id is stored in the spec and never regenerated (text edits keep the id).
2. Error shape for all endpoints: `{"error": code, "message": text}`?
3. `/api/runs` duration: the AgentProof run is synchronous — is it short enough (< 30 s) for one HTTP request?

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
