"""Gemini wire format for v2 rules, and its strict translation into core's `RuleV2`.

Why a separate wire model: `core.rules_v2.RuleV2` is strict (frozen, extra="forbid",
`version: Literal[2]`, int/str unions). The Gemini Developer API schema converter rejects
some of that, and core must not bend to an LLM provider. So Gemini fills one flat,
forgiving node shape (spike `spikes/rule_ast`, shape S3), and this module turns it into a
`RuleV2` or a list of problems. Nothing reaches core unless `validate_rule_v2` accepts it.

Design rules:
- Flat nodes with id references, never nested node objects (spike finding F4).
- Every node uses the same model; `type` says which fields matter. A non-empty field that
  does not belong to the node's type is a problem, not silently dropped: it means Gemini
  misread the rule, and the owner should see that rather than a quietly different rule.
- Condition values travel as text. Fields in `Vocabulary.numeric_fields` become numbers
  here; closed-value fields are checked against `Vocabulary.field_values`.

Pure functions only: no Gemini call, no quota.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

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
    validate_rule_v2,
)
from haqwa.core.spec import UnsupportedRule

from .parse import ParseError
from .vocab import Vocabulary

NodeType = Literal[
    "select",
    "count",
    "none_after",
    "every_preceded_by",
    "every_followed_within",
    "sum_compare",
    "field_compare",
    "all_of",
]
CompareOp = Literal["eq", "ne", "lt", "le", "gt", "ge"]


# ---- wire models (what Gemini fills) ----------------------------------------------------


class WireCondition(BaseModel):
    """`field op value` on one event, e.g. payment_type eq installment."""

    field: str = Field(description="data field name from the vocabulary")
    op: Literal["eq", "ne", "in", "gt", "ge", "lt", "le"]
    value: str | None = Field(
        default=None, description="single value as text, e.g. 'installment' or '100'"
    )
    values: list[str] = Field(default_factory=list, description="only for op 'in'")


class WireNode(BaseModel):
    """One node. Fill only the fields its `type` uses; leave the rest null or empty."""

    id: str = Field(description="unique node id, e.g. 'charges' or 'n1'")
    type: NodeType
    # select
    event: str | None = Field(default=None, description="select: event name")
    where: list[WireCondition] = Field(default_factory=list, description="select: must hold")
    exclude: list[WireCondition] = Field(
        default_factory=list, description="select: events matching any of these are ignored"
    )
    # references to select nodes
    of: str | None = Field(
        default=None,
        description="count/none_after/every_preceded_by/field_compare: select id",
    )
    after: str | None = Field(default=None, description="none_after: select id of the trigger")
    by: str | None = Field(
        default=None, description="every_preceded_by/every_followed_within: select id"
    )
    start: str | None = Field(default=None, description="every_followed_within: select id")
    # parameters
    op: CompareOp | None = Field(
        default=None, description="count (le/lt/eq/ge), sum_compare, field_compare (eq/ne)"
    )
    value: int | None = Field(default=None, description="count: the limit, e.g. 1")
    within: str | None = Field(
        default=None, description="every_followed_within: ISO 8601 duration, e.g. 'PT48H'"
    )
    since: list[str] = Field(
        default_factory=list, description="count/none_after/every_*: events that reset the rule"
    )
    left_of: str | None = Field(default=None, description="sum_compare: select id, left side")
    left_field: str | None = Field(default=None, description="sum_compare: numeric field, left")
    right_of: str | None = Field(default=None, description="sum_compare: select id, right side")
    right_field: str | None = Field(default=None, description="sum_compare: numeric field, right")
    a: str | None = Field(default=None, description="field_compare: first field")
    b: str | None = Field(default=None, description="field_compare: second field")
    children: list[str] = Field(default_factory=list, description="all_of: checking node ids")


class WireRule(BaseModel):
    """Gemini's answer for one rule: a flat node list and the root node id."""

    per: str | None = Field(default=None, description="entity key field, e.g. 'order_id'")
    root: str | None = Field(default=None, description="id of the node that decides pass/fail")
    nodes: list[WireNode] = Field(default_factory=list)
    unsupported_reason: str | None = Field(
        default=None,
        description="set ONLY if no combination of nodes can express the rule; then leave "
        "per, root and nodes empty",
    )


# Which wire attributes each node type needs, and which it may use. Everything else on
# that node must stay null/empty.
_REQUIRED: dict[str, tuple[str, ...]] = {
    "select": ("event",),
    "count": ("of", "op", "value"),
    "none_after": ("of", "after"),
    "every_preceded_by": ("of", "by"),
    "every_followed_within": ("start", "by", "within"),
    "sum_compare": ("left_of", "left_field", "op", "right_of", "right_field"),
    "field_compare": ("of", "a", "op", "b"),
    "all_of": ("children",),
}
_OPTIONAL: dict[str, tuple[str, ...]] = {
    "select": ("where", "exclude"),
    "count": ("since",),
    "none_after": ("since",),
    "every_preceded_by": ("since",),
    "every_followed_within": ("since",),
    "sum_compare": (),
    "field_compare": (),
    "all_of": (),
}
_CONTENT_FIELDS = tuple(name for name in WireNode.model_fields if name not in ("id", "type"))


# ---- wire -> core -----------------------------------------------------------------------


def to_rule_v2(
    wire: WireRule, *, rule_id: str, source: str, vocab: Vocabulary
) -> RuleV2 | UnsupportedRule:
    """Translate Gemini's wire rule into a validated core `RuleV2`, or an `UnsupportedRule`.

    Args:
        wire: Gemini's answer.
        rule_id: Stable rule id chosen by core/the owner, never by Gemini.
        source: The owner's original English rule text.
        vocab: Allowed events and fields, including `numeric_fields`.

    Raises:
        ParseError: every problem found, from this translation and from
            `core.rules_v2.validate_rule_v2`.
    """
    if wire.unsupported_reason:
        if wire.nodes or wire.root or wire.per:
            raise ParseError(["unsupported_reason is set, but nodes/root/per are not empty"])
        return UnsupportedRule(source=source, reason=wire.unsupported_reason)

    problems: list[str] = []
    if not wire.per:
        problems.append("per: missing")
    if not wire.root:
        problems.append("root: missing")
    if not wire.nodes:
        problems.append("nodes: empty")

    nodes = [_node(n, vocab, problems) for n in wire.nodes]
    if problems:
        raise ParseError(problems)

    data: dict[str, Any] = {
        "id": rule_id,
        "source": source,
        "per": wire.per,
        "version": 2,
        "nodes": nodes,
        "root": wire.root,
    }
    core_problems = validate_rule_v2(data, vocab.events, vocab.fields, vocab.numeric_fields)
    if core_problems:
        raise ParseError(core_problems)
    return RuleV2.model_validate(data)


def _node(node: WireNode, vocab: Vocabulary, problems: list[str]) -> dict[str, Any]:
    where = f"{node.id} ({node.type})"
    required = _REQUIRED[node.type]
    allowed = set(required) | set(_OPTIONAL[node.type])
    for name in required:
        if _empty(getattr(node, name)):
            problems.append(f"{where}: missing {name!r}")
    stray = [n for n in _CONTENT_FIELDS if n not in allowed and not _empty(getattr(node, n))]
    if stray:
        problems.append(f"{where}: fields {stray} do not belong to a {node.type} node")

    out: dict[str, Any] = {"id": node.id, "type": node.type}
    if node.type == "select":
        out["event"] = node.event
        out["where"] = [_condition(c, f"{where}.where", vocab, problems) for c in node.where]
        out["exclude"] = [_condition(c, f"{where}.exclude", vocab, problems) for c in node.exclude]
    elif node.type == "sum_compare":
        out["left"] = {"of": node.left_of, "field": node.left_field}
        out["op"] = node.op
        out["right"] = {"of": node.right_of, "field": node.right_field}
    else:
        for name in allowed:
            out[name] = getattr(node, name)
    return out


def _condition(
    cond: WireCondition, where: str, vocab: Vocabulary, problems: list[str]
) -> dict[str, Any]:
    if cond.op == "in":
        if not cond.values or cond.value is not None:
            problems.append(f"{where}: op 'in' needs 'values' and no 'value'")
        raw: list[str] = list(cond.values)
    else:
        if cond.value is None or cond.values:
            problems.append(f"{where}: op {cond.op!r} needs 'value' and no 'values'")
        raw = [cond.value] if cond.value is not None else []

    if cond.field in vocab.numeric_fields:
        converted: list[Any] = []
        for text in raw:
            number = _number(text)
            if number is None:
                problems.append(f"{where}: {cond.field!r} needs a number, got {text!r}")
            converted.append(number)
    else:
        if msg := vocab.value_problem(cond.field, ",".join(raw), where):
            problems.append(msg)
        converted = raw

    value: Any = converted if cond.op == "in" else (converted[0] if converted else None)
    return {"field": cond.field, "op": cond.op, "value": value}


def _number(text: str) -> int | float | None:
    try:
        return int(text)
    except ValueError:
        pass
    try:
        number = float(text)
    except ValueError:
        return None
    return number if number == number and abs(number) != float("inf") else None


def _empty(value: Any) -> bool:
    return value is None or value == [] or value == ""


# ---- core -> wire (fixtures, few-shot prompt examples, round-trip tests) ---------------


def from_rule_v2(rule: RuleV2) -> WireRule:
    """The wire form of a core rule. `to_rule_v2(from_rule_v2(r), ...)` gives back `r`."""
    return WireRule(per=rule.per, root=rule.root, nodes=[_wire_node(n) for n in rule.nodes])


def _wire_node(node: Any) -> WireNode:
    if isinstance(node, SelectNode):
        return WireNode(
            id=node.id,
            type="select",
            event=node.event,
            where=[_wire_condition(c) for c in node.where],
            exclude=[_wire_condition(c) for c in node.exclude],
        )
    if isinstance(node, SumCompareNode):
        return WireNode(
            id=node.id,
            type="sum_compare",
            left_of=node.left.of,
            left_field=node.left.field,
            op=node.op,
            right_of=node.right.of,
            right_field=node.right.field,
        )
    if isinstance(
        node,
        (
            CountNode,
            NoneAfterNode,
            EveryPrecededByNode,
            EveryFollowedWithinNode,
            FieldCompareNode,
            AllOfNode,
        ),
    ):
        return WireNode.model_validate(node.model_dump())
    raise TypeError(f"unknown node type: {type(node).__name__}")


def _wire_condition(cond: Any) -> WireCondition:
    if cond.op == "in":
        return WireCondition(field=cond.field, op="in", values=[_text(v) for v in cond.value])
    return WireCondition(field=cond.field, op=cond.op, value=_text(cond.value))


def _text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
