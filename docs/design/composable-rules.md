# Composable rule engine

**Status: ACCEPTED (Hazel + Wyne).** The v2 AST, validator, interpreter, and v1 preset expansion are implemented on `trackb/rule-engine`. Existing `version: 1` specs, checkers, APIs, and behavior remain the production path. V2 is not wired into `check()` until after the hackathon submission.

## Goal and boundary

Express the four current patterns as presets of a small, closed set of nodes, then evaluate approved v2 rules with one deterministic interpreter. Add a node only when real policies justify it. A v2 rule retains the stable `id`, original English `source`, and entity key `per`:

```yaml
id: no-double-charge
source: A customer must not be charged twice for the same order.
per: order_id
version: 2
nodes:
  - {id: charges, type: select, event: charged, where: [], exclude: []}
  - {id: limit, type: count, of: charges, op: le, value: 1, since: []}
root: limit
```

The node list is flat, with references by id; there are no recursively nested node objects. This permits a simple JSON schema for a possible model output. The validator resolves references and rejects duplicate or unknown ids, cycles, a missing root, depth greater than three, unknown events or fields outside the supplied vocabulary, and type errors. In particular, `gt/ge/lt/le` and sums require declared numeric fields. It also rejects an empty `all_of`. No expression evaluation, dynamic code, or runtime randomness is involved.

| Node | Proposed fields and meaning |
| --- | --- |
| `select` | `{event, where: [Condition], exclude: [Condition]}` matches when the event name matches, all `where` conditions hold, and no `exclude` condition matches. A `Condition` has `{field, op, value}`. `where` supports `eq`, `ne`, `in` and numeric-only `gt`, `ge`, `lt`, `le`; `exclude` uses exactly v1 `matches()` semantics and ops `eq`, `ne`, `in`. A missing field fails a condition, so it does not exclude an event. |
| `count` | `{of: select-id, op: le\|lt\|eq\|ge, value: int, since: [event names]}` tests the count since the most recent reset event. For `le`/`lt`, each event exceeding the limit gets a finding. For `eq`/`ge`, a failed comparison at the end of the entity stream points at its last event; `eq` also reports immediately on each event that exceeds the target, without duplicating that finding at the end. |
| `none_after` | `{of: select-id, after: select-id, since: [...]}` forbids `of` after an `after` event in stream order. |
| `every_preceded_by` | `{of: select-id, by: select-id, since: [...]}` requires an earlier `by` for every `of`; one `by` can enable many later events. |
| `every_followed_within` | `{start: select-id, by: select-id, within: ISO-8601 duration, since: [...]}` requires each start to be followed within positive elapsed calendar time. |
| `sum_compare` | `{left: {of: select-id, field}, op, right: {of: select-id, field}}` compares final numeric sums over the entity stream, for example `sum(refunded.amount) <= sum(charged.amount)`. The comparison operator is one of `eq`, `ne`, `lt`, `le`, `gt`, `ge`. A missing or non-numeric field contributes 0. A failed comparison produces one finding at the entity's last event. |
| `field_compare` | `{of: select-id, a: field, op: eq\|ne, b: field}` compares two fields on each selected event, for example `approver != requester`. An event missing either field is skipped and produces no finding. |
| `all_of` | `{children: [node ids]}` is logical AND of nonempty child results. |

`select` is a reference target, not itself a pass/fail root. The flat form carries a `type` and unique `id` on every node. V2 validation also checks reference kinds, literal types, positive durations, and `per` against the field vocabulary. The validator rebuilds a bounded tree from `root`; unreachable nodes should be rejected so a sealed rule has one unambiguous meaning. For the depth limit, count nodes from root to leaf, including both endpoints.

## Four presets

These YAML fragments show the v2 rule body under the common `id`, `source`, `per`, `version: 2` envelope. The first is the plain form; reset and exemption mapping follows the examples. References in `of`, `after`, `by`, `start`, and `children` are node ids.

```yaml
# at_most_once(event: charged)
nodes:
  - {id: target, type: select, event: charged, where: [], exclude: []}
  - {id: rule, type: count, of: target, op: le, value: 1, since: []}
root: rule
```

```yaml
# never_after(event: shipped, after: cancelled)
nodes:
  - {id: target, type: select, event: shipped, where: [], exclude: []}
  - {id: trigger, type: select, event: cancelled, where: [], exclude: []}
  - {id: rule, type: none_after, of: target, after: trigger, since: []}
root: rule
```

```yaml
# must_precede(event: salary_paid, requires: timesheet_approved)
nodes:
  - {id: target, type: select, event: salary_paid, where: [], exclude: []}
  - {id: prerequisite, type: select, event: timesheet_approved, where: [], exclude: []}
  - {id: rule, type: every_preceded_by, of: target, by: prerequisite, since: []}
root: rule
```

```yaml
# within_time(start: leave_requested, event: leave_decided, within: PT48H)
nodes:
  - {id: start, type: select, event: leave_requested, where: [], exclude: []}
  - {id: finish, type: select, event: leave_decided, where: [], exclude: []}
  - {id: rule, type: every_followed_within, start: start, by: finish, within: PT48H, since: []}
root: rule
```

`reset_after: refunded` becomes `since: [refunded]` on the checking node; multiple reset names form one list. A reset event clears state before any other treatment of that event, even if the same event name appears in a select or an `allow_if` would match. For example, the shop count becomes:

```yaml
nodes:
  - {id: target, type: select, event: charged, where: [], exclude: [{field: payment_type, op: eq, value: installment}]}
  - {id: rule, type: count, of: target, op: le, value: 1, since: [refunded]}
root: rule
```

Every preset `allow_if` goes into `exclude` on **every** select, including a trigger, prerequisite, or start: v1 ignores any matching non-reset event. Multiple exclusions have OR semantics. Because `exclude` calls the v1 condition matcher, a missing field does not exclude the event; `in` and multiple `allow_if` conditions also preserve v1 behavior. The golden corpus and property tests have now established parity for all four presets.

## Finite traces, witnesses, and rollout

Use the existing pipeline: optional event-map translation, stable timestamp sort, then grouping by `data[per]`; events without the entity field are skipped. Order at equal timestamps is stable input order. `after` and `preceded_by` use stream order, not strict timestamp inequality. Resets are evaluated before exemptions. `count` uses the per-op witness rules above; `none_after` and `every_preceded_by` report every offending event. A completion event fulfils all open starts; one late completion produces one finding, based on the earliest overdue start. Completion exactly at its deadline passes. An open `every_followed_within` obligation produces a finding only if the **whole checked trace's** last timestamp is past its deadline, and that finding points at the entity's last event. Several overdue open starts yield one finding. The checker's existing `Finding(index, message)` shape and per-entity indices remain the witness contract; composed-rule messages also include the failing node id. Preset messages match the golden corpus; v1 checks remain the production path until phase 3.

Phase 2 proved identical findings against the old checkers for **12,114 golden corpus entries** and **4 × 300 differential property examples**, with **0 mismatches**. The property tests vary resets, `eq`/`ne`/`in` exemptions, missing fields, equal timestamps, and 1–3 entities. The old checkers remain in place under a strangler migration; v1 and v2 remain explicitly versioned, and neither silently changes the other. Clarification will offer presets first. The validator and existing confirmed-example self-test remain mandatory. A golden rule set will measure prompt accuracy; questions will use primitive-level templates with code-generated boundary examples, at most three decision questions per rule. A code-based AST-to-English renderer will show the policy owner the meaning without YAML.

The documented laptop budget is 10,000 events in under 100 ms. The phase 2 test evaluates each preset over 10,000 events across 1,000 entities and enforces a 1.0 s CI limit. These measured runs were:

| Preset | Local run | Owner rerun |
| --- | ---: | ---: |
| `at_most_once` | 5.8 ms | 5 ms |
| `never_after` | 9.8 ms | 8 ms |
| `must_precede` | 9.7 ms | 30 ms |
| `within_time` | 10.8 ms | 10 ms |

`sum_compare` uses **final totals**, not a comparison on every prefix: a refund logged before its charge can still satisfy the rule by the end of the entity stream. This is the phase 2 decision.

## Phase 3

- Decide whether the AST belongs in the C3 API and how to add it without changing existing requests.
- Choose the Gemini wire format for a flat v2 rule.
- Design the UI for composed rules and owner review of rendered meaning.
