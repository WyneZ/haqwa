"""Deterministic interpreter for a validated v2 rule on one entity stream.

This is deliberately separate from the production v1 checkers. The caller sorts and
groups events, validates the rule, and passes the whole-trace end for time rules.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from pydantic import TypeAdapter

from .conditions import matches
from .events import Event
from .patterns.base import Finding
from .patterns.within_time import fmt_duration
from .rules_v2 import (
    AllOfNode,
    ConditionV2,
    CountNode,
    EveryFollowedWithinNode,
    EveryPrecededByNode,
    FieldCompareNode,
    NoneAfterNode,
    RuleV2,
    SelectNode,
    SumCompareNode,
)
from .spec import Condition

_DURATION = TypeAdapter(timedelta)
_ORDERED_OPS = {
    "lt": lambda left, right: left < right,
    "le": lambda left, right: left <= right,
    "eq": lambda left, right: left == right,
    "ne": lambda left, right: left != right,
    "gt": lambda left, right: left > right,
    "ge": lambda left, right: left >= right,
}


def _v1_condition(condition: ConditionV2) -> Condition:
    return Condition.model_validate(condition.model_dump())


def _numeric(value: Any) -> bool:
    return type(value) in (int, float)


def _where_matches(condition: ConditionV2, legacy: Condition | None, event: Event) -> bool:
    if legacy is not None:
        return matches(legacy, event)
    actual = event.data.get(condition.field)
    return _numeric(actual) and _ORDERED_OPS[condition.op](actual, condition.value)


def _select(node: SelectNode, events: list[Event]) -> list[bool]:
    where = [
        (condition, _v1_condition(condition) if condition.op in ("eq", "ne", "in") else None)
        for condition in node.where
    ]
    excluded = [_v1_condition(condition) for condition in node.exclude]
    return [
        event.event == node.event
        and all(_where_matches(condition, legacy, event) for condition, legacy in where)
        and not any(matches(condition, event) for condition in excluded)
        for event in events
    ]


def _reset_suffix(since: list[str], *, count: bool = False) -> str:
    if not since:
        return ""
    names = " / ".join(sorted(set(since)))
    return f" with no {names} in between" if count else f" (since the last '{names}')"


def evaluate_v2(
    rule: RuleV2, events: list[Event], trace_end: datetime | None = None
) -> list[Finding]:
    """Evaluate a validated rule over one entity's time-sorted events."""
    nodes = {node.id: node for node in rule.nodes}
    selected = {
        node.id: _select(node, events) for node in rule.nodes if isinstance(node, SelectNode)
    }
    last = len(events) - 1

    def evaluate(node_id: str) -> list[Finding]:
        node = nodes[node_id]
        if isinstance(node, CountNode):
            count = 0
            findings: list[Finding] = []
            target = nodes[node.of]
            assert isinstance(target, SelectNode)
            resets = set(node.since)
            for index, event in enumerate(events):
                if event.event in resets:
                    count = 0
                    continue
                if not selected[node.of][index]:
                    continue
                count += 1
                if node.op in ("le", "lt") and not _ORDERED_OPS[node.op](count, node.value):
                    findings.append(
                        Finding(
                            index,
                            f"'{target.event}' happened {count} times"
                            f"{_reset_suffix(node.since, count=True)}",
                        )
                    )
                elif node.op == "eq" and count > node.value:
                    findings.append(
                        Finding(index, f"'{target.event}' count {count} is not eq {node.value}")
                    )
            if last >= 0 and node.op in ("eq", "ge") and count < node.value:
                findings.append(
                    Finding(last, f"'{target.event}' count {count} is not {node.op} {node.value}")
                )
            return findings

        if isinstance(node, NoneAfterNode):
            armed = False
            findings = []
            target, trigger = nodes[node.of], nodes[node.after]
            assert isinstance(target, SelectNode) and isinstance(trigger, SelectNode)
            resets = set(node.since)
            for index, event in enumerate(events):
                if event.event in resets:
                    armed = False
                    continue
                if armed and selected[node.of][index]:
                    findings.append(
                        Finding(index, f"'{target.event}' happened after '{trigger.event}'")
                    )
                if selected[node.after][index]:
                    armed = True
            return findings

        if isinstance(node, EveryPrecededByNode):
            enabled = False
            findings = []
            target, prerequisite = nodes[node.of], nodes[node.by]
            assert isinstance(target, SelectNode) and isinstance(prerequisite, SelectNode)
            resets = set(node.since)
            for index, event in enumerate(events):
                if event.event in resets:
                    enabled = False
                    continue
                if selected[node.of][index] and not enabled:
                    findings.append(
                        Finding(
                            index,
                            f"'{target.event}' happened without an earlier "
                            f"'{prerequisite.event}'{_reset_suffix(node.since)}",
                        )
                    )
                if selected[node.by][index]:
                    enabled = True
            return findings

        if isinstance(node, EveryFollowedWithinNode):
            start, completion = nodes[node.start], nodes[node.by]
            assert isinstance(start, SelectNode) and isinstance(completion, SelectNode)
            window = _DURATION.validate_python(node.within)
            limit = fmt_duration(window)
            resets = set(node.since)
            open_starts: list[Event] = []
            findings = []
            for index, event in enumerate(events):
                if event.event in resets:
                    open_starts.clear()
                    continue
                if selected[node.by][index] and open_starts:
                    late = [opened for opened in open_starts if event.ts - opened.ts > window]
                    if late:
                        took = fmt_duration(event.ts - late[0].ts)
                        findings.append(
                            Finding(
                                index,
                                f"'{completion.event}' happened {took} after "
                                f"'{start.event}' (limit {limit})",
                            )
                        )
                    open_starts.clear()
                elif selected[node.start][index]:
                    open_starts.append(event)
            if open_starts and last >= 0:
                end = trace_end or events[last].ts
                if any(end - opened.ts > window for opened in open_starts):
                    findings.append(
                        Finding(
                            last,
                            f"'{completion.event}' did not happen within {limit} "
                            f"after '{start.event}'",
                        )
                    )
            return findings

        if isinstance(node, SumCompareNode):
            if last < 0:
                return []

            def total(select_id: str, field: str) -> int | float:
                return sum(
                    event.data[field]
                    for index, event in enumerate(events)
                    if selected[select_id][index]
                    and field in event.data
                    and _numeric(event.data[field])
                )

            left = total(node.left.of, node.left.field)
            right = total(node.right.of, node.right.field)
            if _ORDERED_OPS[node.op](left, right):
                return []
            return [
                Finding(
                    last,
                    f"sum of {node.left.of}.{node.left.field} ({left}) is not {node.op} "
                    f"sum of {node.right.of}.{node.right.field} ({right})",
                )
            ]

        if isinstance(node, FieldCompareNode):
            return [
                Finding(index, f"'{node.a}' is not {node.op} '{node.b}'")
                for index, event in enumerate(events)
                if selected[node.of][index]
                and node.a in event.data
                and node.b in event.data
                and not _ORDERED_OPS[node.op](event.data[node.a], event.data[node.b])
            ]

        assert isinstance(node, AllOfNode)
        combined = {
            (finding.index, f"[{child}] {finding.message}")
            for child in node.children
            for finding in evaluate(child)
        }
        return [Finding(index, message) for index, message in sorted(combined)]

    return evaluate(rule.root)
