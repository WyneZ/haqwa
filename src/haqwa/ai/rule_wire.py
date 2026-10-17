"""Gemini wire format for v2 rules, and its strict translation into core's `RuleV2`.

Why a separate wire model: `core.rules_v2.RuleV2` is strict (frozen, extra="forbid",
`version: Literal[2]`, int/str unions). The Gemini Developer API schema converter rejects
some of that, and core must not bend to an LLM provider. So Gemini fills a wire shape made
for constrained decoding, and this module turns it into a `RuleV2` or a list of problems.
Nothing reaches core unless `validate_rule_v2` accepts it.

Design rules:
- Flat nodes with id references, never nested node objects (spike finding F4).
- One wire model PER node type, each with its required fields marked required. The schema
  Gemini receives is an `anyOf` of these, so constrained decoding cannot leave out a field
  the type needs. (G1 run 1, 2026-10-16: with a single all-optional node model, Gemini
  dropped `by` from every_followed_within and `op` from field_compare.)
- No `extra="forbid"` on wire models: it becomes `additionalProperties`, which the
  Developer API rejects. A field outside a type's model cannot be decoded anyway.
- Condition values travel as text. Fields in `Vocabulary.numeric_fields` become numbers
  here; closed-value fields are checked against `Vocabulary.field_values`.

Pure functions only: no Gemini call, no quota.
"""

from __future__ import annotations

from datetime import timedelta
from functools import lru_cache
from typing import Any, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter, create_model

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

CompareOp = Literal["eq", "ne", "lt", "le", "gt", "ge"]
_ID = Field(description="unique node id, e.g. 'charges' or 'n1'")
_SINCE = Field(default_factory=list, description="events that reset this check for the entity")


# ---- wire models (what Gemini fills) ----------------------------------------------------


class WireCondition(BaseModel):
    """`field op value` on one event, e.g. payment_type eq installment."""

    field: str = Field(description="data field name from the vocabulary")
    op: Literal["eq", "ne", "in", "gt", "ge", "lt", "le"]
    value: str | None = Field(
        default=None, description="single value as text, e.g. 'installment' or '100'"
    )
    values: list[str] = Field(default_factory=list, description="only for op 'in'")


class WireSelect(BaseModel):
    """Picks events by name; `where` filters them, `exclude` lists exemptions."""

    id: str = _ID
    type: Literal["select"]
    event: str = Field(description="event name")
    where: list[WireCondition] = Field(default_factory=list, description="every one must hold")
    exclude: list[WireCondition] = Field(
        default_factory=list, description="an event matching ANY of these is ignored"
    )


class WireCount(BaseModel):
    id: str = _ID
    type: Literal["count"]
    of: str = Field(description="select id")
    op: Literal["le", "lt", "eq", "ge"]
    value: int = Field(description="the limit, e.g. 1")
    since: list[str] = _SINCE


class WireNoneAfter(BaseModel):
    id: str = _ID
    type: Literal["none_after"]
    of: str = Field(description="select id of the forbidden event")
    after: str = Field(description="select id of the event that starts the ban")
    since: list[str] = _SINCE


class WireEveryPrecededBy(BaseModel):
    id: str = _ID
    type: Literal["every_preceded_by"]
    of: str = Field(description="select id of the event that needs a prerequisite")
    by: str = Field(description="select id of the prerequisite event")
    since: list[str] = _SINCE


class WireEveryFollowedWithin(BaseModel):
    id: str = _ID
    type: Literal["every_followed_within"]
    start: str = Field(description="select id of the event that starts the clock")
    by: str = Field(description="select id of the event that must follow")
    within_seconds: int = Field(
        description="time limit in seconds of elapsed calendar time, e.g. 24 hours = 86400"
    )
    since: list[str] = _SINCE


class WireSumCompare(BaseModel):
    id: str = _ID
    type: Literal["sum_compare"]
    left_of: str = Field(description="select id, left side")
    left_field: str = Field(description="numeric field summed on the left")
    op: CompareOp
    right_of: str = Field(description="select id, right side")
    right_field: str = Field(description="numeric field summed on the right")


class WireFieldCompare(BaseModel):
    id: str = _ID
    type: Literal["field_compare"]
    of: str = Field(description="select id")
    a: str = Field(description="first field")
    op: Literal["eq", "ne"]
    b: str = Field(description="second field")


class WireAllOf(BaseModel):
    id: str = _ID
    type: Literal["all_of"]
    children: list[str] = Field(description="ids of checking nodes that must all hold")


# Plain union -> JSON Schema `anyOf` (google-genai rejects oneOf + discriminator, see
# contracts.md Q5). The Literal `type` still lets Pydantic pick the right model.
WireNode = (
    WireSelect
    | WireCount
    | WireNoneAfter
    | WireEveryPrecededBy
    | WireEveryFollowedWithin
    | WireSumCompare
    | WireFieldCompare
    | WireAllOf
)
_NODE_ADAPTER: TypeAdapter[WireNode] = TypeAdapter(WireNode)
_DURATION: TypeAdapter[timedelta] = TypeAdapter(timedelta)


def wire_node(**fields: Any) -> WireNode:
    """Build the wire model for `fields["type"]` (fixtures, examples, tests)."""
    return _NODE_ADAPTER.validate_python(fields)


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


# ---- per-vocabulary schema (what Gemini actually receives) -----------------------------


def wire_schema(vocab: Vocabulary) -> type[WireRule]:
    """The WireRule schema for one vocabulary: names become string enums.

    Event names (select.event, since) come from `vocab.events`; field names (per,
    conditions, field_compare) from `vocab.fields`; summed fields from
    `vocab.numeric_fields`. Constrained decoding can then only emit names that exist, so
    invented names and corrupted strings ("refun d_requested", G1 run 2) cannot be decoded.
    A wrong-but-existing name is still possible; that is what the meaning check is for.

    `sum_compare` is left out when the vocabulary has no numeric field. The models are
    subclasses of the static wire models, so `to_rule_v2` handles them unchanged.
    """
    return _schema(tuple(vocab.events), tuple(vocab.fields), tuple(vocab.numeric_fields))


def _enum(values: tuple[str, ...]) -> Any:
    return Literal[values] if values else str  # Literal[("a", "b")] == Literal["a", "b"]


@lru_cache(maxsize=64)
def _schema(
    events: tuple[str, ...], fields: tuple[str, ...], numeric: tuple[str, ...]
) -> type[WireRule]:
    event, field, num = _enum(events), _enum(fields), _enum(numeric)
    since: Any = (list[event], Field(default_factory=list, description=_SINCE.description))

    cond = create_model(
        "WireCondition",
        __base__=WireCondition,
        field=(field, Field(description="data field name")),
    )
    select = create_model(
        "WireSelect",
        __base__=WireSelect,
        event=(event, Field(description="event name")),
        where=(list[cond], Field(default_factory=list, description="every one must hold")),
        exclude=(
            list[cond],
            Field(default_factory=list, description="an event matching ANY of these is ignored"),
        ),
    )
    nodes: list[Any] = [
        select,
        create_model("WireCount", __base__=WireCount, since=since),
        create_model("WireNoneAfter", __base__=WireNoneAfter, since=since),
        create_model("WireEveryPrecededBy", __base__=WireEveryPrecededBy, since=since),
        create_model("WireEveryFollowedWithin", __base__=WireEveryFollowedWithin, since=since),
        create_model(
            "WireFieldCompare",
            __base__=WireFieldCompare,
            a=(field, Field(description="first field")),
            b=(field, Field(description="second field")),
        ),
        WireAllOf,
    ]
    if numeric:
        nodes.append(
            create_model(
                "WireSumCompare",
                __base__=WireSumCompare,
                left_field=(num, Field(description="numeric field summed on the left")),
                right_field=(num, Field(description="numeric field summed on the right")),
            )
        )
    node_union: Any = Union[tuple(nodes)]  # noqa: UP007 (built at runtime)
    return create_model(
        "WireRule",
        __base__=WireRule,
        per=(field | None, Field(default=None, description="entity key field")),
        nodes=(list[node_union], Field(default_factory=list)),
    )


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
    # Required fields are enforced by the schema; an empty string still slips through.
    for name, value in node.model_dump().items():
        if value == "":
            problems.append(f"{where}: {name!r} is empty")

    if isinstance(node, WireSelect):
        return {
            "id": node.id,
            "type": "select",
            "event": node.event,
            "where": [_condition(c, f"{where}.where", vocab, problems) for c in node.where],
            "exclude": [_condition(c, f"{where}.exclude", vocab, problems) for c in node.exclude],
        }
    if isinstance(node, WireSumCompare):
        return {
            "id": node.id,
            "type": "sum_compare",
            "left": {"of": node.left_of, "field": node.left_field},
            "op": node.op,
            "right": {"of": node.right_of, "field": node.right_field},
        }
    if isinstance(node, WireEveryFollowedWithin):
        out = node.model_dump(exclude={"within_seconds"})
        if node.within_seconds <= 0:
            problems.append(f"{where}: within_seconds must be positive")
        out["within"] = iso_seconds(max(node.within_seconds, 1))
        return out
    # The other wire models carry exactly the core node's fields.
    return node.model_dump()


def iso_seconds(seconds: int) -> str:
    """Canonical ISO 8601 duration for whole seconds: 86400 -> 'PT24H', 5400 -> 'PT90M'."""
    if seconds % 3600 == 0:
        return f"PT{seconds // 3600}H"
    if seconds % 60 == 0:
        return f"PT{seconds // 60}M"
    return f"PT{seconds}S"


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


# ---- core -> wire (fixtures, few-shot prompt examples, round-trip tests) ---------------


def from_rule_v2(rule: RuleV2) -> WireRule:
    """The wire form of a core rule. `to_rule_v2(from_rule_v2(r), ...)` gives back `r`."""
    return WireRule(per=rule.per, root=rule.root, nodes=[_wire_node(n) for n in rule.nodes])


def _wire_node(node: Any) -> WireNode:
    if isinstance(node, SelectNode):
        return WireSelect(
            id=node.id,
            type="select",
            event=node.event,
            where=[_wire_condition(c) for c in node.where],
            exclude=[_wire_condition(c) for c in node.exclude],
        )
    if isinstance(node, SumCompareNode):
        return WireSumCompare(
            id=node.id,
            type="sum_compare",
            left_of=node.left.of,
            left_field=node.left.field,
            op=node.op,
            right_of=node.right.of,
            right_field=node.right.field,
        )
    if isinstance(node, EveryFollowedWithinNode):
        seconds = _DURATION.validate_python(node.within).total_seconds()
        return WireEveryFollowedWithin(
            id=node.id,
            type="every_followed_within",
            start=node.start,
            by=node.by,
            within_seconds=int(seconds),
            since=list(node.since),
        )
    if isinstance(
        node,
        (
            CountNode,
            NoneAfterNode,
            EveryPrecededByNode,
            FieldCompareNode,
            AllOfNode,
        ),
    ):
        return wire_node(**node.model_dump())
    raise TypeError(f"unknown node type: {type(node).__name__}")


def _wire_condition(cond: Any) -> WireCondition:
    if cond.op == "in":
        return WireCondition(field=cond.field, op="in", values=[_text(v) for v in cond.value])
    return WireCondition(field=cond.field, op=cond.op, value=_text(cond.value))


def _text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
