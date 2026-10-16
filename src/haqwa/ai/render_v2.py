"""Plain-English meaning of a v2 rule, written by code (no LLM).

The policy owner never reads YAML or node ids. Before a composed rule is sealed, the owner
reads this text and confirms it is what they meant. Because the text comes from the
validated `RuleV2` itself, not from Gemini, it cannot describe a rule different from the
one core will check. Wording is deterministic, so the same rule always reads the same way.

Pure functions only: no Gemini, no quota.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from pydantic import TypeAdapter

from haqwa.core.patterns.within_time import fmt_duration
from haqwa.core.rules_v2 import (
    AllOfNode,
    CountNode,
    EveryFollowedWithinNode,
    EveryPrecededByNode,
    FieldCompareNode,
    NoneAfterNode,
    RuleV2,
    SelectNode,
    SumCompareNode,
)

_DURATION: TypeAdapter[timedelta] = TypeAdapter(timedelta)

_COUNT_OP = {"le": "at most", "lt": "fewer than", "eq": "exactly", "ge": "at least"}
_COMPARE_OP = {
    "eq": "equal to",
    "ne": "different from",
    "lt": "less than",
    "le": "at most",
    "gt": "more than",
    "ge": "at least",
}
_COND_OP = {
    "eq": "is",
    "ne": "is not",
    "in": "is one of",
    "gt": "is more than",
    "ge": "is at least",
    "lt": "is less than",
    "le": "is at most",
}


def render_rule(rule: RuleV2) -> str:
    """The rule's meaning as English sentences, e.g.

    "For each order: there must be at most 1 charged event (charged events where payment
    type is installment are ignored; it starts again after each refunded event)."
    """
    nodes = {n.id: n for n in rule.nodes}
    return f"For each {_noun(rule.per)}: {_check(nodes[rule.root], nodes)}"


def _check(node: Any, nodes: dict[str, Any]) -> str:
    if isinstance(node, AllOfNode):
        parts = [_check(nodes[c], nodes).rstrip(".") for c in node.children]
        if len(parts) == 1:
            return parts[0] + "."
        listed = "; ".join(f"({i}) {p}" for i, p in enumerate(parts, start=1))
        return f"all of these must hold: {listed}."
    if isinstance(node, CountNode):
        text = (
            f"there must be {_COUNT_OP[node.op]} {node.value} {_events(nodes[node.of], node.value)}"
        )
        return _with_extras(text, [nodes[node.of]], node.since)
    if isinstance(node, NoneAfterNode):
        text = (
            f"once a {_events(nodes[node.after])} has happened, "
            f"a {_events(nodes[node.of])} must never happen"
        )
        return _with_extras(text, [nodes[node.of], nodes[node.after]], node.since)
    if isinstance(node, EveryPrecededByNode):
        text = (
            f"every {_events(nodes[node.of])} must come after an earlier {_events(nodes[node.by])}"
        )
        return _with_extras(text, [nodes[node.of], nodes[node.by]], node.since)
    if isinstance(node, EveryFollowedWithinNode):
        text = (
            f"every {_events(nodes[node.start])} must be followed by a "
            f"{_events(nodes[node.by])} within {_duration(node.within)}"
        )
        return _with_extras(text, [nodes[node.start], nodes[node.by]], node.since)
    if isinstance(node, SumCompareNode):
        left, right = nodes[node.left.of], nodes[node.right.of]
        text = (
            f"the total {_words(node.left.field)} of {_events(left, 2)} must be "
            f"{_COMPARE_OP[node.op]} the total {_words(node.right.field)} of {_events(right, 2)}"
        )
        return _with_extras(text, [left, right], [])
    if isinstance(node, FieldCompareNode):
        verb = "must equal" if node.op == "eq" else "must be different from"
        text = f"on every {_events(nodes[node.of])}, {_words(node.a)} {verb} {_words(node.b)}"
        return _with_extras(text, [nodes[node.of]], [])
    raise TypeError(f"cannot render node type {type(node).__name__}")


def _with_extras(text: str, selects: list[SelectNode], since: list[str]) -> str:
    """Append exemptions and resets as one parenthesis, so the main sentence stays short.

    An exemption shared by every event in the sentence is said once ("events where ...");
    otherwise it names its event.
    """
    extras: list[str] = []
    by_condition: dict[str, list[str]] = {}
    for select in selects:
        for cond in select.exclude:
            events = by_condition.setdefault(_condition(cond), [])
            if select.event not in events:
                events.append(select.event)
    all_events = {s.event for s in selects}
    for cond_text, events in by_condition.items():
        if len(all_events) > 1 and set(events) == all_events:
            extras.append(f"events where {cond_text} are ignored")
        else:
            names = " and ".join(_words(e) for e in events)
            extras.append(f"{names} events where {cond_text} are ignored")
    if since:
        resets = " or ".join(f"{_words(e)} event" for e in since)
        extras.append(f"it starts again after each {resets}")
    return f"{text} ({'; '.join(extras)})." if extras else f"{text}."


def _events(select: SelectNode, n: int = 1) -> str:
    """'charged event', '3 -> charged events', with any `where` filter after the noun."""
    noun = "event" if n == 1 else "events"
    text = f"{_words(select.event)} {noun}"
    if select.where:
        text += " where " + " and ".join(_condition(c) for c in select.where)
    return text


def _condition(cond: Any) -> str:
    value = cond.value
    if isinstance(value, list):
        shown = ", ".join(str(v) for v in value)
    elif isinstance(value, bool):
        shown = "true" if value else "false"
    else:
        shown = str(value)
    return f"{_words(cond.field)} {_COND_OP[cond.op]} {shown}"


def _duration(iso: str) -> str:
    d = _DURATION.validate_python(iso)
    seconds = int(d.total_seconds())
    if seconds and seconds % 3600 == 0:
        hours = seconds // 3600
        return "1 hour" if hours == 1 else f"{hours} hours"
    return fmt_duration(d)


def _words(name: str) -> str:
    return name.replace("_", " ").strip()


def _noun(per: str) -> str:
    return _words(per.removesuffix("_id")) or "item"
