# Haqwa

Haqwa turns plain English business policies into executable checks for software and AI workflows. Gemini helps interpret a policy and asks its owner about concrete event timelines. The confirmed answers become a versioned YAML spec. The checker then evaluates real events with deterministic Python; it does not call an LLM to decide pass or fail.

## Install and quickstart

Python 3.12 and [uv](https://docs.astral.sh/uv/) are required for development.

```sh
uv sync
uv run python -m haqwa.demo
uv run haqwa check examples/shop/rules.spec.yaml examples/shop/events.json --map examples/shop/events.map.yaml
```

These commands need no API key. To build the frontend and start the API on port 8000, run `scripts/dev.sh` from the repository root.

### Write your own policies (needs a Gemini key)

Set `GEMINI_API_KEY` in your environment, then run:

```sh
uv run haqwa init my-policies
uv run haqwa build my-policies/rules.haqwa --map my-policies/events.map.yaml --field order_id --field payment_type -o my-policies/rules.spec.yaml
```

`init` creates an English rules file and an event map. `build` calls Gemini to propose a rule, asks the policy owner about example timelines, then saves the confirmed spec. Use `--field` for each data field Gemini may mention. The event map supplies event names, not data fields. `build` exits 4 when Gemini quota is exhausted or the service is unavailable.

`check` exits 0 when no rule is violated, 1 for a violation, 2 for a spec or compile error, and 3 for a bad input file. Each rule result has status `pass` or `violation`. A `pass` with `checked_events == 0` appears as `[NOT TESTED]`: no event relevant to that rule occurred, and it still exits 0 if there are no violations. For example, a check of the shop events with an additional `must_precede` rule produces these report lines (excerpt):

```text
[VIOLATION] no-double-charge: A customer must not be charged twice for the same order.
  entity A-1: 'charged' happened 2 times with no refunded in between
[NOT TESTED] never-ship-after-cancel: Never ship an order after it was cancelled.
[PASS] charge-after-order: Charge only after an order exists.
RESULT: VIOLATION
```

## Spec format

The shop example lives at [`examples/shop/rules.spec.yaml`](examples/shop/rules.spec.yaml):

```yaml
version: 1
rules:
  - id: no-double-charge
    source: "A customer must not be charged twice for the same order."
    pattern: at_most_once
    event: charged
    per: order_id
    except:
      - reset_after: refunded
      - allow_if: {field: payment_type, op: eq, value: installment}
    confirmed_examples:
      - timeline: [{event: charged}, {event: charged}]
        violation: true
```

The rule id stays stable after sealing. Events are JSON objects with `event`, timezone-aware `ts`, and `data`. An optional `events.map.yaml` translates system names to rule names. Unknown mapped events are dropped. See [`docs/contracts.md`](docs/contracts.md) for the complete C1/C2 formats and proposed timeline offsets.

| Pattern | Meaning for each entity |
| --- | --- |
| `at_most_once` | An event occurs at most once. |
| `never_after` | Once `after` happened, `event` must never happen. |
| `must_precede` | `event` requires an earlier `requires`; one occurrence enables later events. |
| `within_time` | After `start`, `event` must occur within a positive calendar-time duration. |

| Exception | Semantics |
| --- | --- |
| `reset_after` | The named event clears the rule's prior state for that entity. |
| `allow_if` | A matching event is ignored by the rule; multiple conditions use OR. |

## Library API

```python
from haqwa import canonical_examples, check, compile_spec, load_events, load_spec, suggest_rule_id
from haqwa.adapters.pytest import assert_policies

spec = load_spec("examples/shop/rules.spec.yaml")
compiled = compile_spec(spec)
report = check(compiled, load_events("examples/shop/events.json"))
print(report.passed)

rule_id = suggest_rule_id("A customer must not be charged twice.", set())
examples = canonical_examples(spec.rules[0])
```

`compile_spec` self-tests every owner-confirmed timeline and raises `CompileError` on disagreement. `assert_policies` is available for pytest checks. `dump_spec` and `save_spec` write deterministic YAML while preserving the owner's rule order.

The demo includes six native scenarios:

| ID | Fault | Expected |
| --- | --- | --- |
| `payment_timeout_naive` | `timeout_after_commit` | violation |
| `payment_timeout_fixed` | `timeout_after_commit` | pass |
| `duplicate_webhook_naive` | `duplicate_event` | violation |
| `duplicate_webhook_fixed` | `duplicate_event` | pass |
| `stale_status_naive` | `stale_state` | violation |
| `stale_status_fixed` | `stale_state` | pass |

Recorded Gemini runs also appear in the demo when their files are present; replay does not call Gemini.

### Live agent over MCP (needs your Gemini key)

Haqwa can serve the shop tools over MCP, inject a real-world fault, record what an
unmodified agent commits, and check it. Install the demo dependencies, set
`GEMINI_API_KEY` in your environment, then run:

```sh
uv sync --group dev --group demo
uv run haqwa live run --fault timeout_after_commit --runs 3
uv run haqwa live run --fault stale_state --runs 3
```

- `timeout_after_commit`: the first charge commits, then the tool returns only
  `Request timed out`.
- `stale_state`: the order was already cancelled, but `get_order` reports it as paid.

Tool descriptions and errors are neutral; the agent sees only shop operations (no effect
ledger, no reset). Each run needs about 3–5 Gemini requests. On 2026-10-11 an unmodified
Gemini agent (`gemini-3.6-flash`, Google ADK) broke the policy in every run:

| Fault | Result | What the agent did |
| --- | --- | --- |
| `timeout_after_commit` | 3/3 violation | retried the charge (once with no key, twice adding a new idempotency key only on the retry) → charged twice |
| `stale_state` | 3/3 violation | shipped with `if_status="paid"` → rejected; then shipped again **without** the condition → shipped a cancelled order |

Runs are recorded by default (`--no-record` skips) and replay in the demo without Gemini.
To connect another MCP client, run `uv run haqwa live serve --fault timeout_after_commit`
and use the printed URL; the verdict prints when you stop the server.

## Architecture

```text
English rules -> ai/ Gemini clarification -> owner answers -> sealed YAML spec
                                                      |
JSON events -> optional event map -> core/ compiler + checker -> report
                                      ^
                                      |
                           CLI, pytest, demo, web API
```

The `core/` package is pure deterministic code and never imports `ai/`. The CLI and web API call library functions. The demo uses AgentProof faults and native agents to show a failing and corrected payment flow.

To record a Gemini run using your own `GEMINI_API_KEY`:

```sh
uv run --group demo python spikes/agentproof/record_stale.py --runs 1
```

Each trial makes a baseline and a faulted agent run (about twice the requests of one run). Only AgentProof effects are saved, without prompts or model outputs, as `gemini_<scenario>_run_<n>_<YYYY_MM_DD>.json`; the older `gemini_YYYY_MM_DD.json` name still works. The demo calculates a recording's expected verdict when a spec is supplied; otherwise it is `unknown`. `sample_native.json` is an offline fixture.

## Roadmap

Next steps include uploading event logs for checks and adding more demo scenarios, including one for `within_time`.
CI integration could run policy checks on saved traces.

## Web app

### Run the web API

From the repository root, run:

```sh
uv sync
uv run uvicorn web.api.main:app --reload
```

Open `http://localhost:8000/docs` for the API schema. The React build is served at `/` when `web/frontend/dist/` exists. Set `HAQWA_DEV_CORS=1` to allow a separate Vite server at `http://localhost:5173`. `GEMINI_API_KEY` is needed only for `/api/v1/clarify` and `/api/v1/explain`.
