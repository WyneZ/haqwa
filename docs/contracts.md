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

- **Stateless spec and trace routes.** The browser holds the draft spec and sends what each call needs. No database in the MVP; Firestore stays on the roadmap (hosted service). Agent sessions are the in-memory exception described below.
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

### Track B library additions (2026-10-05)

`core/errors.py` exposes stable error codes and `to_problem()` for RFC 9457 responses. The `https://haqwa.dev/errors/` type URI is a placeholder until an error documentation site exists. `compile_failed` retains `CompileError.problems` and `.failures`. `dump_spec()` and `save_spec()` write deterministic YAML in owner rule order. `demo.iter_scenario()` yields C2 events followed by a report for the agreed SSE integration. The C1 `at` offset and `within_time` end-of-trace behavior remain PROPOSED.

Recorded demo files with invalid JSON or effect data raise `HaqwaError` with code `invalid_recording` (HTTP 422). `list_scenarios()` reports `expected: unknown` for recordings unless a spec is supplied, in which case it derives the expected verdict with the core checker.

### C3 implementation notes (2026-10-05)

- The API adds `invalid_request` (422), `gemini_quota` (429), `gemini_unavailable` (503), and `internal_error` (500) to the stable error codes.
- A Seal self-test failure returns the RFC 9457 problem body with `code: compile_failed`, `ok: false`, `problems`, and `failures` (HTTP 422).
- Fetch actual demo identifiers from `GET /api/v1/scenarios`; recorded runs report `expected: unknown` without a spec.
- `GET /healthz` is outside `/api/v1` for Cloud Run health checks.
- `POST /api/v1/clarify` and `POST /api/v1/explain` share an in-memory rate limiter:
  10 requests per client IP per rolling minute and 200 requests globally per rolling day
  by default. `HAQWA_RATE_PER_MIN` and `HAQWA_RATE_PER_DAY` configure the limits.
  Cloud Run's first `X-Forwarded-For` address identifies the client, falling back to the
  socket address. Excess requests return HTTP 429 RFC 9457 with stable code
  `rate_limited` and a retry delay in `detail`; this is distinct from `gemini_quota`.

### C3 trace additions (AGREED, 2026-10-11)

- `POST /api/v1/clarify` accepts optional `vocabulary` (`{events, fields, field_values}`),
  the same shape as `summary.vocabulary`. Omitted means the shop vocabulary;
  invalid vocabulary returns 422 `invalid_request`.
- `GET /api/v1/scenarios` items gain `kind: "scripted" | "recorded" | "live"`.
- `POST /api/v1/traces` accepts `{ "events": [/* C2 events */], "extra_events": ["payroll_run"] }`
  (`extra_events` is optional) and returns
  `{ "summary": TraceSummary }`. The summary contains the observed vocabulary,
  counts, time span, closed string values and likely `_id` entity fields.
  `summary.vocabulary.events` is the sorted union of observed event names and
  `extra_events`; `summary.event_counts` counts observed events only. The
  endpoint stores nothing. Requests over 5 MB return an `invalid_request` problem;
  traces over 10,000 events return `invalid_events`.
- `haqwa build RULES --trace EVENTS [--map MAP]` translates events through the
  optional map first, then uses the sorted union of the resulting rule-side names
  and declared map names for its vocabulary. This permits rules for declared
  events absent from the trace without exposing system-side event names.
- `POST /api/v1/runs` accepts exactly one of `scenario_id` or `events` with the
  existing `spec` and optional `event_map`. Uploaded events are parsed and checked
  by the core library; the response remains `{ "events": [...], "report": {...} }`.
  Existing scenario requests keep the same behavior.
  The same 5 MB request body limit applies to `/runs`.

### Agent sessions (AGREED, 2026-10-12)

These endpoints add a live MCP agent source without changing `/scenarios`, `/runs`,
`/traces`, or the local live CLI. All paths below have the `/api/v1` prefix.

| Method + path | Request | Response |
|---|---|---|
| `POST /agent-sessions` | `{"fault":"timeout_after_commit"\|"stale_state"}` | `{session_id, fault, mcp_url, task, expires_at}` |
| `GET /agent-sessions/{id}` | — | `{session_id, fault, expires_at, calls:[{tool, arguments, ok, error, at}]}` |
| `POST /agent-sessions/{id}/check` | `{spec, event_map?}` | Existing `RunResponse`: `{events, report}` |
| `DELETE /agent-sessions/{id}` | — | 204, no body |

`mcp_url` is absolute and contains a secret token:
`{base}/agent/timeout/mcp?session=<token>` or
`{base}/agent/stale/mcp?session=<token>`. The timeout mount exposes only
`create_order` and `charge_payment`; the stale mount exposes only `get_order`
and `ship_order`. Each session has a private shop world. The API builds `task`
from the matching live-agent task; `/check` converts that shop's effects to C2
events and uses the core compiler and checker for the verdict.

Sessions are in memory and expire after 1,800 seconds. Defaults are 20 concurrent
sessions, 200 tool calls per session, 5 creations per IP per rolling minute, and
100 creations globally per rolling day. The corresponding settings are
`HAQWA_AGENT_TTL_SECONDS`, `HAQWA_AGENT_MAX_SESSIONS`,
`HAQWA_AGENT_MAX_CALLS`, `HAQWA_AGENT_CREATE_PER_MIN`, and
`HAQWA_AGENT_CREATE_PER_DAY`. Expired sessions are swept on create and get;
redeploying loses all sessions. Keep Cloud Run at one instance while sessions are
in memory.

Unknown, expired, deleted or wrong-fault session tokens return the same neutral
MCP tool error, `Session not found or expired`; tool calls above the cap return
`Too many requests`. The HTTP API returns RFC 9457 `session_not_found` (404)
or `session_limit` (429). Excess session creation uses the existing
`rate_limited` code (429).

### C3 v2 — clarify and answers (DRAFT, 2026-10-16)

**DRAFT: Wyne must review these shapes.** On `feat/ai-rule-ast`, v2 replaces v1
inside the existing `/api/v1/clarify` and `/api/v1/answers` routes (Option A).
There is no `/api/v2`, feature flag, or alternate v1 implementation on this branch.
C1/C2 and the other routes remain unchanged in stage 1. The frontend needs a
separate stage 2 update and cannot consume these new shapes yet.

`VocabularyIn` is `{events, fields?, field_values?, numeric_fields?}`; omitted lists
default to `[]` and omitted `field_values` to `{}`. Numeric fields must be declared
fields and cannot also have closed value lists. Omitted vocabulary uses the shop
vocabulary, where `amount` is numeric. Use the same vocabulary for clarify and answers.

**`POST /api/v1/clarify` request:**

```json
{
  "rules": ["An order may be charged at most once."],
  "vocabulary": {
    "events": ["charged", "refunded"],
    "fields": ["order_id", "amount"],
    "field_values": {},
    "numeric_fields": ["amount"]
  }
}
```

**Response:**

```json
{
  "cached": false,
  "results": [{
    "source": "An order may be charged at most once.",
    "status": "supported",
    "rule": {
      "id": "charge-once", "source": "An order may be charged at most once.",
      "version": 2, "per": "order_id", "root": "check",
      "nodes": [
        {"id": "charges", "type": "select", "event": "charged", "where": [], "exclude": []},
        {"id": "check", "type": "count", "of": "charges", "op": "le", "value": 1, "since": []}
      ]
    },
    "meaning": "For each order: there must be at most 1 charged event.",
    "questions": [{
      "id": "d1", "kind": "decision",
      "text": "Is another charge allowed after a refund?",
      "why": "A refund may allow charging the order again.",
      "timeline": [{"event": "charged"}, {"event": "refunded"}, {"event": "charged"}],
      "patch": {"op": "add_reset", "node_id": "check", "event": "refunded"},
      "expected_violation": null
    }],
    "reason": null
  }]
}
```

Each source gets a stable suggested id once. Supported rules use `RuleV2`; their
meaning is generated by code. Unsupported items have `rule`, `meaning` and
`questions` set to `null`, plus a short `reason`. Parse errors and unusable Gemini
output affect that item; quota/unavailability retain the existing HTTP problems.
Top-level `cached` is true only when every parse and clarify answer came from cache;
an unsupported parse has no clarify call. An item error makes `cached` false.

Questions are `QuestionV2`: `{id, kind, text, why, timeline, patch,
expected_violation}`. Timelines have at least one C1 `TimelineEvent`. Decisions
retain their `d1..` ids and Gemini text/why, have a typed patch, and have
`expected_violation: null`. Confirmations get `c1..` ids, text `"Is this allowed?"`,
`why: null`, `patch: null`, and a boolean `expected_violation`. Decisions without
an example are omitted. Confirmation cards precede decision cards.

Patches are `add_reset {node_id, event}` or `add_exclude {select_ids, condition}`.
An exclusion condition is `{field, op: "eq"|"ne", value}` or
`{field, op: "in", values}`; `select_ids` and `values` are nonempty lists.

**`POST /api/v1/answers` request:**

```json
{
  "rule": {
    "id": "charge-once", "source": "An order may be charged at most once.",
    "version": 2, "per": "order_id", "root": "check",
    "nodes": [
      {"id": "charges", "type": "select", "event": "charged"},
      {"id": "check", "type": "count", "of": "charges", "op": "le", "value": 1}
    ]
  },
  "answers": [{
    "question": {
      "id": "c1", "kind": "confirmation", "text": "Is this allowed?",
      "why": null, "patch": null,
      "timeline": [{"event": "charged"}, {"event": "charged"}],
      "expected_violation": true
    },
    "allowed": false
  }]
}
```

**Response:**

```json
{
  "rule": {
    "id": "charge-once", "source": "An order may be charged at most once.",
    "version": 2, "per": "order_id", "root": "check",
    "nodes": [
      {"id": "charges", "type": "select", "event": "charged", "where": [], "exclude": []},
      {"id": "check", "type": "count", "of": "charges", "op": "le", "value": 1, "since": []}
    ]
  },
  "confirmed_examples": [{
    "timeline": [{"event": "charged"}, {"event": "charged"}], "violation": true
  }],
  "mismatches": []
}
```

Answers optionally accept `vocabulary` with the same defaults as clarify. No Gemini
call occurs. Yes means `violation: false`; a Yes decision applies its patch via the
core port. No keeps the rule. Duplicate patches and confirmed examples are skipped.
A confirmation answer opposite to its expected verdict adds a mismatch such as
`"c1: owner answered the opposite of 'not allowed'"` and is not recorded.
The resulting rule is validated against the vocabulary; invalid changes return a
422 `invalid_spec` problem. Inconsistent question bodies return HTTP 422.

Until B2, confirmed examples are returned **beside** the rule. The browser must keep
them and resend the complete answer history when recomputing them; they are not
persisted by this stateless endpoint. Opposite decision answers for the same timeline
remain separate evidence for a future core self-test.

**Stage 1 provisional ports:** `make_example` returns a timeline labelled
`PLACEHOLDER...`; it does not establish a separating witness. No confirmations are
generated until Track B supplies `canonical_examples_v2`. Applying a new Yes decision
returns RFC 9457 HTTP 501 with web-only code `not_implemented` and detail
`"core apply_patch_v2 not merged yet"`. No/confirmation-only answers can still succeed.
This flow is not ready for sealing. B5 replaces provisional functions in
`ai/core_v2_ports.py` only; B2 must move confirmed examples into `RuleV2`.

Patches are client input on this stateless endpoint, so before a Yes patch is
applied, `/answers` re-runs the same policy clarify uses (`patch_problems`: target
node types, vocabulary names, exemptions only on closed-value fields with listed
values). A rejected patch returns 422 `invalid_spec` and core is not called.

Track B review request (nice to have, not blocking): `validate_rule_v2` checks event,
field and numeric field names but not closed field values, so values already inside
an incoming rule (not added by a patch) are not checked against `field_values`.
Consider closed-value validation at the core boundary.
