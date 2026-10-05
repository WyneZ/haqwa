# Haqwa

Haqwa turns plain English business policies into executable checks for software and AI workflows. Gemini helps interpret a policy and asks its owner about concrete event timelines. The confirmed answers become a versioned YAML spec. The checker then evaluates real events with deterministic Python; it does not call an LLM to decide pass or fail.

## Install and quickstart

Python 3.12 and [uv](https://docs.astral.sh/uv/) are required for development.

```sh
uv sync
uv run python -m haqwa.demo
uv run haqwa init my-policies
uv run haqwa build my-policies/rules.haqwa --map my-policies/events.map.yaml --field order_id --field payment_type -o my-policies/rules.spec.yaml
uv run haqwa check examples/shop/rules.spec.yaml examples/shop/events.json --map examples/shop/events.map.yaml
uv run haqwa check examples/shop/rules.spec.yaml examples/shop/events.json --map examples/shop/events.map.yaml --json
```

`init` creates an English rules file and an event map. `build` calls Gemini to propose a rule, asks the policy owner whether example timelines are allowed, then compiles and saves the confirmed spec. The terminal shows each timeline's event names, data values and time offsets before asking for an answer. Set `GEMINI_API_KEY` in the environment for `build`; `check` and the demo need no key. Use `--field` for each data field Gemini may mention. The event map supplies event names but does not define data fields. `check` exits 0 for pass, 1 for violation, 2 for a spec or compile error, and 3 for a bad input file. `build` exits 4 when Gemini quota is exhausted or the service is unavailable.

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

To record a Gemini agent run, run the ADK spike with your own environment key and `--save-effects src/haqwa/demo/recordings/gemini_YYYY_MM_DD.json`. The demo discovers files with that name and replays only their AgentProof effects. A recorded scenario's expected verdict is calculated from the spec when one is supplied; otherwise it is `unknown`. The committed `sample_native.json` is an offline test fixture, not a Gemini run.

## Roadmap

The MVP supports four patterns, two exceptions, CLI checks, a demo, and a web flow. Future work may add event adapters, monitoring, and broader policy shapes. See [`CODEX_TASKS.md`](CODEX_TASKS.md) for the current task list.

## Web app
