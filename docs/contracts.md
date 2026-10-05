# Haqwa Contracts

**Status: LOCKED — C1 and C2 on 2026-09-25, C3 on 2026-09-28 (both developers agreed — see docs/decisions.md).**
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
| `never_after` | `event`, `after` | once `after` happened, `event` must not happen | implemented |
| `must_precede` | `event`, `requires` | `event` only if `requires` happened earlier (one `requires` enables any number of later `event`s) | implemented |
| `within_time` | `start`, `event`, `within` | after `start`, `event` must happen within `within` (calendar time; seconds or ISO 8601, e.g. `PT48H`; must be > 0) | implemented (end-of-trace per Q2 proposal) |

### Exceptions

| Exception | Form | Semantics |
|---|---|---|
| `reset_after` | `reset_after: refunded` | When this event happens for the entity, the rule forgets what it saw before. Reset events always reset (allow_if is not checked for them) |
| `allow_if` | `allow_if: {field, op, value}` | Other events matching the condition are ignored by the rule (not counted, do not trigger, do not violate). Multiple `allow_if` = OR |

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

Timeline items use the same `{event, data}` shape as C2 events (no `ts`; the self-test adds increasing timestamps and one synthetic entity id). An item may set `data.<per>` to put it on a different entity.

**PROPOSED (needs Track A agreement, Q1):** optional `at` on timeline items = ISO 8601 duration offset from the **first** item. If one item has `at`, all must; the first is `PT0S`; offsets never decrease. Without `at`, items are 1 s apart.

```yaml
  - timeline:
      - {event: refund_requested, at: PT0S}     # Fri 17:00
      - {event: refund_completed, at: PT65H}    # Mon 10:00
    violation: true
```

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

Week 2 additions:

```python
from haqwa import canonical_examples, suggest_rule_id, violates
from haqwa.demo import list_scenarios, run_scenario        # needs agentproof-sim==0.1.1
from haqwa.adapters.pytest import assert_policies

canonical_examples(rule)      # -> [CanonicalExample(label, timeline, violation)]; .as_confirmed(owner_says_allowed)
suggest_rule_id(text, existing_ids)   # deterministic slug; "-2", "-3" if taken; call once per new rule
violates(rule, timeline)      # -> bool, one rule on one C1 example timeline
list_scenarios()              # -> [{id, title, fault, agent, description, expected}]
run_scenario(id, spec)        # -> (events, Report); deterministic native agents, ~1 ms
```

Canonical examples per pattern (confirmation cards; "Is this allowed?" Yes = `violation: false`): core case, reversed order (two-event patterns), different entity; `within_time` also "exactly at the limit", "1 h late" and, when the window is under 65 h, "Fri 17:00 → Mon 10:00 (weekend counts)".

---

## C3 — Web API (`web/`)

**Status: LOCKED (2026-09-28, both developers agreed).**

### Principles

- **Stateless.** The browser holds the draft spec and sends what each call needs. No database in the MVP; Firestore stays on the roadmap (hosted service).
- **The spec is a file.** Seal returns `rules.spec.yaml` for the owner to download and commit.
- **No business logic in `web/`.** Each endpoint calls one library function (`ai/` or `core/`) and returns its result.
- **Shapes follow C1/C2.** Rules, confirmed examples, events and reports use the C1/C2 JSON shapes. Gemini's wire format (`data: [{key, value}]`) never leaves `ai/`.
- **Gemini quota.** `clarify` and `explain` return cached answers for the demo rules (`"cached": true`). A Gemini 429 becomes HTTP 429 with code `gemini_quota`.
- **Errors (AGREED 2026-09-28).** RFC 9457 Problem Details (`application/problem+json`: `type`, `title`, `status`, `detail`) plus a stable machine `code`. One code list in `core/errors.py`, shared by CLI and web.
- **Versioning (Track A).** All paths are under `/api/v1/` (shown below without the prefix).
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

### Needed from the library API (AGREED 2026-09-28)

- `canonical_examples(rule) -> [(timeline, expected_violation, label)]` in `core/` (agreed 2026-09-27), incl. the `within_time` calendar-hours confirmation.
- `list_scenarios()` and `run_scenario(scenario_id, spec) -> (events, Report)` in `demo/` or `adapters/`.

### C3 questions (all resolved)

1. ~~Who makes the rule `id` slug?~~ **Resolved 2026-09-29 (AGREED):** `core` suggests an id once for a new rule (`suggest_rule_id(text, existing_ids)`: keywords → `^[a-z0-9][a-z0-9-]*$`, `-2` suffix if taken); the owner may edit it; after that the id is stored in the spec and never regenerated (text edits keep the id).
2. **Error shape — AGREED 2026-09-28:** RFC 9457 + stable `code`, e.g.
   `{"type": "https://haqwa.dev/errors/gemini-quota", "title": "Gemini quota exceeded", "status": 429, "detail": "...", "code": "gemini_quota"}`.
   Codes live in `core/errors.py` (Track B): `compile_failed`, `invalid_spec`, …; Track A adds `gemini_quota`, `unsupported_rule` by request. CLI maps the same codes to exit codes.
3. **`/api/runs` — AGREED 2026-09-28:** start **synchronous** (one request returns events + report). In week 3 add **SSE streaming** on the same endpoint so the timeline appears live; the response shape stays "events + report". Async jobs (202 + poll) only on the roadmap, because they need storage. Needs from Track B: measured AgentProof run time, and a runner that can yield events one by one.

### Who does what (C3)

| Item | Code | Decides |
|---|---|---|
| `suggest_rule_id`, id freeze on load/dump | Track B (`core/spec.py`) | AGREED 2026-09-29 |
| id shown and editable on the Yes/No card | Track A (`web/ui`) | Track A |
| `core/errors.py` code list | Track B | both |
| RFC 9457 handler in FastAPI, UI error messages | Track A (`web/`) | both (C3) |
| CLI exit codes | Track B | Track B |
| `canonical_examples(rule)` | Track B (`core/`) | AGREED 2026-09-27 (shape: both) |
| `list_scenarios()`, `run_scenario()`, event generator for SSE | Track B (`demo/`/`adapters/`) | both |
| Endpoints 1–6, `/api/v1` prefix, SSE on the web side | Track A (`web/`) | both (C3) |
| Deterministic YAML dump | Track B | Track B |
To be drafted together; Track A writes it. Suggested inputs/outputs from the core side:
- compile: spec (C1 JSON) + event map → ok, or `CompileError` problems/failures (show the failing example to the owner)
- check: spec + event map + events (C2 JSON) → `Report` JSON

---

## Open questions (decide before lock)

1. **`within_time` examples need time.** PROPOSED by Track B (2026-09-30): optional `at` offset from the first item (see Confirmed examples). Implemented behind this proposal; rename is cheap until locked.
2. **`within_time` at end of trace.** PROPOSED by Track B (2026-09-30), option B: an open obligation is a violation only if the end of the checked trace (last event of any entity) is past its deadline; otherwise pass. No "pending" status.
3. **Events missing the `per` key** are skipped silently. Add a warning count to the report?
4. **Entity id types:** `"123"` and `123` are different entities today. Normalize to string?
5. ~~**Gemini + discriminated union.**~~ **Resolved 2026-09-28:** google-genai rejects `oneOf` + `discriminator`; Track A's Gemini wire schema uses a per-pattern `anyOf` union with C1 field names (spike v2), and `core/spec.py` still validates with its discriminated union. C1 unchanged.
6. **Naming:** brief says `compile()`; code uses `compile_spec()` to avoid shadowing Python's built-in `compile`.
7. **Stubs:** not needed any more — all 4 patterns are implemented (2026-09-30).

Parking list (not in MVP): field renaming in the event map (e.g. `orderId` → `order_id`).
