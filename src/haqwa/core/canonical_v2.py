"""Boundary examples and separating witnesses for composable rules."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import product
from typing import Any

from pydantic import TypeAdapter

from .canonical import CanonicalExample
from .conditions import matches
from .events import Event, synthetic_timeline
from .patches_v2 import AddExcludeV2, AddResetV2, PatchV2, apply_patch_v2
from .rules_v2 import (
    AllOfNode,
    ConditionV2,
    CountNode,
    EveryFollowedWithinNode,
    EveryPrecededByNode,
    FieldCompareNode,
    NodeV2,
    NoneAfterNode,
    RuleV2,
    SelectNode,
    SumCompareNode,
)
from .rules_v2_eval import _select, check_v2
from .spec import Condition, TimelineEvent

_DURATION = TypeAdapter(timedelta)
_T0 = datetime(2000, 1, 1, tzinfo=UTC)
_TICK = "unrelated_event"


def _words(name: str) -> str:
    return name.replace("_", " ")


def _choices(conditions: list[ConditionV2], fixed: Any = None) -> list[Any]:
    values: list[Any] = []
    if fixed is not None:
        return [fixed]
    for condition in conditions:
        if condition.op == "in":
            values.extend(condition.value)
        elif condition.op in ("gt", "ge"):
            values.extend((condition.value + 1, condition.value))
        elif condition.op in ("lt", "le"):
            values.extend((condition.value - 1, condition.value))
        else:
            values.append(condition.value)
    values.extend(("other", "another", 0, 1, -1, 2, True, False))
    return [value for _, value in dict.fromkeys((type(value), value) for value in values)]


def _select_data(
    select: SelectNode,
    per: str,
    fixed: dict[str, Any] | None = None,
    force: ConditionV2 | None = None,
) -> dict[str, Any] | None:
    """Find small data satisfying the selector and, optionally, a patch condition."""
    fixed = fixed or {}
    fields = sorted({c.field for c in [*select.where, *select.exclude]} | set(fixed))
    if force is not None and force.field not in fields:
        fields.append(force.field)
    candidates = [
        _choices(
            [
                c
                for c in [*select.where, *select.exclude, *([force] if force else [])]
                if c.field == field
            ],
            fixed[field] if field in fixed else None,
        )
        for field in fields
    ]
    for choice in product(*candidates):
        data = {per: "example-1", **fixed, **dict(zip(fields, choice, strict=True))}
        event = Event(event=select.event, ts=_T0, data=data)
        if not _select(select, [event])[0]:
            continue
        if force is not None and not matches(Condition.model_validate(force.model_dump()), event):
            continue
        return data
    return None


def _item(
    select: SelectNode,
    per: str,
    at: timedelta,
    fixed: dict[str, Any] | None = None,
    force: ConditionV2 | None = None,
) -> TimelineEvent | None:
    data = _select_data(select, per, fixed, force)
    return TimelineEvent(event=select.event, data=data, at=at) if data is not None else None


def _candidate(
    label: str, *items: TimelineEvent | None
) -> tuple[str, tuple[TimelineEvent, ...]] | None:
    if any(item is None for item in items):
        return None
    return label, tuple(item for item in items if item is not None)


def _tick(at: timedelta, rule: RuleV2) -> TimelineEvent:
    used = {node.event for node in rule.nodes if isinstance(node, SelectNode)} | {
        event
        for node in rule.nodes
        if isinstance(
            node, (CountNode, NoneAfterNode, EveryPrecededByNode, EveryFollowedWithinNode)
        )
        for event in node.since
    }
    name = _TICK
    while name in used:
        name += "_other"
    return TimelineEvent(event=name, data={rule.per: "example-1"}, at=at)


def _node_candidates(
    rule: RuleV2,
    node: NodeV2,
    selects: dict[str, SelectNode],
    force: dict[str, ConditionV2] | None = None,
) -> list[tuple[str, tuple[TimelineEvent, ...]]]:
    force = force or {}
    per = rule.per
    zero, second = timedelta(0), timedelta(seconds=1)

    def item(select_id: str, at: timedelta, fixed: dict[str, Any] | None = None):
        return _item(selects[select_id], per, at, fixed, force.get(select_id))

    candidates: list[tuple[str, tuple[TimelineEvent, ...]] | None] = []
    if isinstance(node, CountNode):
        if node.op in ("le", "eq"):
            allowed, denied = node.value, node.value + 1
        elif node.op == "lt":
            allowed, denied = max(0, node.value - 1), node.value
        else:
            allowed, denied = node.value, node.value - 1
        event_name = _words(selects[node.of].event)
        for count in (allowed, denied):
            if count < 0:
                continue
            items = [item(node.of, second * i) for i in range(count)]
            candidates.append(
                _candidate(
                    f"{event_name.capitalize()} {count} time{'s' if count != 1 else ''}",
                    *(items or [_tick(zero, rule)]),
                )
            )
    elif isinstance(node, NoneAfterNode):
        target, trigger = _words(selects[node.of].event), _words(selects[node.after].event)
        candidates.extend(
            (
                _candidate(
                    f"{target.capitalize()} before {trigger}",
                    item(node.of, zero),
                    item(node.after, second),
                ),
                _candidate(
                    f"{target.capitalize()} after {trigger}",
                    item(node.after, zero),
                    item(node.of, second),
                ),
            )
        )
    elif isinstance(node, EveryPrecededByNode):
        target, prerequisite = _words(selects[node.of].event), _words(selects[node.by].event)
        candidates.extend(
            (
                _candidate(
                    f"{prerequisite.capitalize()} before {target}",
                    item(node.by, zero),
                    item(node.of, second),
                ),
                _candidate(
                    f"{target.capitalize()} before {prerequisite}",
                    item(node.of, zero),
                    item(node.by, second),
                ),
            )
        )
    elif isinstance(node, EveryFollowedWithinNode):
        window = _DURATION.validate_python(node.within)
        late = window + second
        start, finish = _words(selects[node.start].event), _words(selects[node.by].event)
        candidates.extend(
            (
                _candidate(
                    f"{finish.capitalize()} exactly at the deadline after {start}",
                    item(node.start, zero),
                    item(node.by, window),
                ),
                _candidate(
                    f"{finish.capitalize()} one second late after {start}",
                    item(node.start, zero),
                    item(node.by, late),
                ),
                _candidate(
                    f"{start.capitalize()} still open after its deadline",
                    item(node.start, zero),
                    _tick(late, rule),
                ),
                _candidate(
                    f"{finish.capitalize()} at the deadline, then time passes",
                    item(node.start, zero),
                    item(node.by, window),
                    _tick(late, rule),
                ),
            )
        )
    elif isinstance(node, SumCompareNode):
        left, right = node.left, node.right
        bases: set[int | float] = {1, 2}
        for side in (left, right):
            for condition in selects[side.of].where:
                if condition.field == side.field and type(condition.value) in (int, float):
                    bases.update((condition.value, condition.value + 1, condition.value - 1))
        for base in sorted(bases):
            for a, b in ((base, base), (base + 1, base), (base, base + 1)):
                candidates.append(
                    _candidate(
                        f"{_words(left.field).capitalize()} totals {a} and {b}",
                        item(left.of, zero, {left.field: a}),
                        item(right.of, second, {right.field: b}),
                    )
                )
    elif isinstance(node, FieldCompareNode):
        values: list[str | int | float] = ["same", "first", "second", 1, 2]
        for condition in selects[node.of].where:
            if condition.field in (node.a, node.b):
                if type(condition.value) in (int, float):
                    values.extend((condition.value - 1, condition.value, condition.value + 1))
                elif isinstance(condition.value, str):
                    values.append(condition.value)
                elif isinstance(condition.value, list):
                    values.extend(
                        value for value in condition.value if type(value) in (str, int, float)
                    )
        for value in values:
            candidates.append(
                _candidate(
                    f"{_words(node.a).capitalize()} and {_words(node.b)} are equal",
                    item(node.of, zero, {node.a: value, node.b: value}),
                )
            )
            for other in values:
                if other == value:
                    continue
                candidates.append(
                    _candidate(
                        f"{_words(node.a).capitalize()} and {_words(node.b)} differ",
                        item(node.of, zero, {node.a: value, node.b: other}),
                    )
                )
    elif isinstance(node, AllOfNode):
        nodes = {member.id: member for member in rule.nodes}
        for child in node.children:
            candidates.extend(_node_candidates(rule, nodes[child], selects, force))
    return [candidate for candidate in candidates if candidate is not None]


def _verdict(rule: RuleV2, timeline: tuple[TimelineEvent, ...]) -> bool:
    events = synthetic_timeline(
        ((item.event, item.data, item.at) for item in timeline), per=rule.per
    )
    return bool(check_v2(rule, events))


def canonical_examples_v2(rule: RuleV2) -> list[CanonicalExample]:
    """Return at most three boundary cards, with verdicts from the v2 checker."""
    nodes = {node.id: node for node in rule.nodes}
    selects = {node.id: node for node in rule.nodes if isinstance(node, SelectNode)}
    root = nodes[rule.root]
    if isinstance(root, AllOfNode):
        candidates = []
        for child_id in root.children:
            child_rule = rule.model_copy(update={"root": child_id})
            pair: dict[bool, tuple[str, tuple[TimelineEvent, ...]]] = {}
            for candidate in _node_candidates(rule, nodes[child_id], selects):
                pair.setdefault(_verdict(child_rule, candidate[1]), candidate)
                if len(pair) == 2:
                    break
            candidates.extend(pair.values())
    else:
        candidates = _node_candidates(rule, root, selects)
    examples: list[CanonicalExample] = []
    for label, timeline in candidates:
        verdict = _verdict(rule, timeline)
        if any(example.violation == verdict for example in examples) and len(examples) < 2:
            continue
        examples.append(CanonicalExample(label, timeline, verdict))
        if len(examples) == (3 if isinstance(root, AllOfNode) else 2):
            break
    return examples


def _insert_reset(
    timeline: tuple[TimelineEvent, ...], event: str, per: str
) -> list[tuple[TimelineEvent, ...]]:
    results = []
    for position in range(len(timeline) + 1):
        if position == 0:
            at = timedelta(0)
        elif position == len(timeline):
            at = timeline[-1].at + timedelta(seconds=1)
        else:
            at = timeline[position - 1].at + (timeline[position].at - timeline[position - 1].at) / 2
        reset = TimelineEvent(event=event, data={per: "example-1"}, at=at)
        results.append((*timeline[:position], reset, *timeline[position:]))
    return results


def make_example_v2(rule: RuleV2, patch: PatchV2 | dict[str, Any]) -> CanonicalExample | None:
    """Return a short timeline only when the patch changes the rule's verdict."""
    patched = apply_patch_v2(rule, patch)
    if patched == rule:
        return None
    parsed = TypeAdapter(PatchV2).validate_python(patch)
    nodes = {node.id: node for node in rule.nodes}
    selects = {node.id: node for node in rule.nodes if isinstance(node, SelectNode)}
    root = nodes[rule.root]
    force: dict[str, ConditionV2] = {}
    if isinstance(parsed, AddExcludeV2):
        condition = ConditionV2(
            field=parsed.condition.field,
            op=parsed.condition.op,
            value=getattr(parsed.condition, "values", None)
            or getattr(parsed.condition, "value", None),
        )
        force = dict.fromkeys(parsed.select_ids, condition)
    candidates = _node_candidates(rule, root, selects, force)
    if isinstance(parsed, AddResetV2):
        candidates = [
            (f"Reset at {parsed.event}", timeline)
            for _, base in candidates
            for timeline in _insert_reset(base, parsed.event, rule.per)
        ]
    for label, timeline in candidates:
        original_verdict = _verdict(rule, timeline)
        if original_verdict != _verdict(patched, timeline):
            return CanonicalExample(label, timeline, original_verdict)
    return None
