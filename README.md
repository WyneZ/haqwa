# Haqwa

Haqwa turns plain English business policies into executable checks for software and AI workflows. Gemini helps interpret a policy and asks its owner about concrete event timelines. The confirmed answers become a versioned YAML spec. The checker then evaluates real events with deterministic Python; it does not call an LLM to decide pass or fail.

## Try it in 2 minutes

**Live demo:** https://haqwa-1020226488566.asia-southeast1.run.app — no sign-up, no key needed.

1. **Define.** Pick the *Online shop* example (or write your own policy in plain English).
   Haqwa's AI turns each sentence into a rule and asks you short Yes/No questions about
   the cases the policy leaves open. Your answers, not the AI, decide what the rule means.
   The rule's final meaning is shown in plain words before you confirm.
2. **Test.** Run a demo agent run (for example *payment times out after charging*), or
   upload your own event log as JSON.
3. **Results.** See which rules held and which broke, with the exact events that broke
   them. The verdict comes from Haqwa's deterministic checker; the AI explanation is
   advisory only.

**Optional — bring your own agent.** On the Test screen, open *Connect your own agent*,
create a private endpoint, and point any MCP client (Streamable HTTP) at it, or run
`uv run python examples/connect_agent.py --url "<endpoint>"` with your own model key.
Watch its tool calls live, then press *Check now*. Sessions are private, in memory and
expire after 30 minutes. See [Bring your own agent](#bring-your-own-agent).

**Run locally:** `uv sync && ./scripts/dev.sh` (needs `GEMINI_API_KEY` in `.env` for the
AI steps; the checker itself never calls an AI).

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

### Bring your own agent

Create a private shop session through the web API, then give your MCP agent the returned
`mcp_url` and `task`. The URL contains the session secret. After the agent finishes,
use `POST /api/v1/agent-sessions/{session_id}/check` as **Check now** with a sealed spec
to get the same `events` and `report` shape as `/runs`. Session status lists the
agent's tool calls. This is an additional path alongside scenarios, trace upload and
the local `haqwa live` commands.

```sh
curl -X POST http://localhost:8000/api/v1/agent-sessions \
  -H 'content-type: application/json' \
  -d '{"fault":"timeout_after_commit"}'
# Give your MCP client the returned mcp_url and task.
# Then POST {"spec": <contents of examples/shop/rules.spec.yaml as JSON>}
# to /api/v1/agent-sessions/<session_id>/check.
```

For a Gemini ADK client, install the demo group, set your own `GEMINI_API_KEY`, and run
`uv run python examples/connect_agent.py --url "<mcp_url>" --task "<task>"`.
The [generic MCP client config](examples/mcp_client_config.json) shows the Streamable
HTTP URL shape; adjust its keys to your client's format.

**Requirements**

1. Your agent must be an MCP client that supports Streamable HTTP. Stdio-only clients
   need a bridge such as `mcp-remote`.
2. It may act only through the shop tools Haqwa gives it. Actions done any other way
   are not checked.
3. Give it the task returned by the session API (and shown on the page). The task uses
   order `A-1`; the stale fault affects only `A-1`.
4. Do not tell your agent which fault is injected, or the test proves nothing.
5. Check it against shop rules, using the shop vocabulary.
6. A session lasts 30 minutes and allows 200 tool calls. Each IP can create 5 new
   sessions per minute.
7. The URL is a secret: anyone with it can call your session. Sessions live in memory
   and are lost on redeploy.
8. Your agent's model and its cost are yours; Haqwa makes no LLM call for this.
9. Use test data only; never real customer data.

## Evidence

The [recorded comparison](spikes/evidence/results/summary.md) used a log of 12 orders and
37 events, with two real violations. Gemini received the rule, the owner's decisions,
the event map, and the full log.

| | Gemini direct | Haqwa checker |
|---|---|---|
| Runs | 10 | 10 |
| Exactly right (all violations, no false alarms) | 10/10 | 10/10 |
| Violations caught | 20/20 | 20/20 |
| False alarms (allowed orders flagged) | 0 | 0 |
| Time per run (median) | 10.7 s | 0.1 ms |
| Tokens per run (median, in / out) | 3189.0 / 85.0 | 0 / 0 |
| Same answer every run | yes | yes |

On this log Gemini, given the rule and the full log, was also right 10/10. Haqwa's
checker gave the same answers in 0.1 ms with zero tokens, the same way every time,
and it runs offline in CI. The live MCP runs show where AI fails: the agent itself
broke the rule in 6/6 runs.

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
