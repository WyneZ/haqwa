"""Proposed v2 rule AST and static validation. Not wired into v1 checking."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from datetime import timedelta
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from .examples import ConfirmedExample


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


Scalar = str | int | float | bool
CompareOp = Literal["eq", "ne", "lt", "le", "gt", "ge"]


class ConditionV2(_Strict):
    field: str = Field(min_length=1)
    op: Literal["eq", "ne", "in", "gt", "ge", "lt", "le"]
    value: Scalar | list[Scalar]

    @model_validator(mode="after")
    def _valid_value(self) -> ConditionV2:
        if self.op == "in":
            if not isinstance(self.value, list):
                raise ValueError("'in' needs a list value")
        elif isinstance(self.value, list):
            raise ValueError(f"'{self.op}' needs a scalar value")
        if self.op in ("gt", "ge", "lt", "le") and (
            type(self.value) not in (int, float)
            or (isinstance(self.value, float) and not math.isfinite(self.value))
        ):
            raise ValueError(f"'{self.op}' needs a finite numeric value")
        return self


class SelectNode(_Strict):
    id: str = Field(min_length=1)
    type: Literal["select"]
    event: str = Field(min_length=1)
    where: list[ConditionV2] = Field(default_factory=list)
    exclude: list[ConditionV2] = Field(default_factory=list)

    @model_validator(mode="after")
    def _exclude_uses_v1_ops(self) -> SelectNode:
        if any(condition.op not in ("eq", "ne", "in") for condition in self.exclude):
            raise ValueError("exclude supports only v1 condition ops: eq, ne, in")
        return self


class CountNode(_Strict):
    id: str = Field(min_length=1)
    type: Literal["count"]
    of: str = Field(min_length=1)
    op: Literal["le", "lt", "eq", "ge"]
    value: int = Field(ge=0)
    since: list[str] = Field(default_factory=list)


class NoneAfterNode(_Strict):
    id: str = Field(min_length=1)
    type: Literal["none_after"]
    of: str = Field(min_length=1)
    after: str = Field(min_length=1)
    since: list[str] = Field(default_factory=list)


class EveryPrecededByNode(_Strict):
    id: str = Field(min_length=1)
    type: Literal["every_preceded_by"]
    of: str = Field(min_length=1)
    by: str = Field(min_length=1)
    since: list[str] = Field(default_factory=list)


_DURATION = TypeAdapter(timedelta)


class EveryFollowedWithinNode(_Strict):
    id: str = Field(min_length=1)
    type: Literal["every_followed_within"]
    start: str = Field(min_length=1)
    by: str = Field(min_length=1)
    within: str
    since: list[str] = Field(default_factory=list)

    @field_validator("within")
    @classmethod
    def _positive_iso_duration(cls, value: str) -> str:
        if not value.startswith("P"):
            raise ValueError("within must be an ISO-8601 duration")
        try:
            duration = _DURATION.validate_python(value)
        except ValidationError as exc:
            raise ValueError("within must be an ISO-8601 duration") from exc
        if duration <= timedelta(0):
            raise ValueError("within must be positive")
        return value


class SumSide(_Strict):
    of: str = Field(min_length=1)
    field: str = Field(min_length=1)


class SumCompareNode(_Strict):
    id: str = Field(min_length=1)
    type: Literal["sum_compare"]
    left: SumSide
    op: CompareOp
    right: SumSide


class FieldCompareNode(_Strict):
    id: str = Field(min_length=1)
    type: Literal["field_compare"]
    of: str = Field(min_length=1)
    a: str = Field(min_length=1)
    op: Literal["eq", "ne"]
    b: str = Field(min_length=1)


class AllOfNode(_Strict):
    id: str = Field(min_length=1)
    type: Literal["all_of"]
    children: list[str]


NodeV2 = Annotated[
    SelectNode
    | CountNode
    | NoneAfterNode
    | EveryPrecededByNode
    | EveryFollowedWithinNode
    | SumCompareNode
    | FieldCompareNode
    | AllOfNode,
    Field(discriminator="type"),
]


class RuleV2(_Strict):
    id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9-]*$")
    source: str = Field(min_length=1)
    per: str = Field(min_length=1)
    version: Literal[2]
    nodes: list[NodeV2]
    root: str = Field(min_length=1)
    confirmed_examples: list[ConfirmedExample] = Field(default_factory=list)


def _references(node: NodeV2) -> list[tuple[str, str]]:
    """Return (role, node id) pairs, including references with required node kinds."""
    if isinstance(node, CountNode):
        return [("of", node.of)]
    if isinstance(node, NoneAfterNode):
        return [("of", node.of), ("after", node.after)]
    if isinstance(node, EveryPrecededByNode):
        return [("of", node.of), ("by", node.by)]
    if isinstance(node, EveryFollowedWithinNode):
        return [("start", node.start), ("by", node.by)]
    if isinstance(node, SumCompareNode):
        return [("left.of", node.left.of), ("right.of", node.right.of)]
    if isinstance(node, FieldCompareNode):
        return [("of", node.of)]
    if isinstance(node, AllOfNode):
        return [("children", child) for child in node.children]
    return []


def _has_cycle(graph: dict[str, list[str]]) -> bool:
    done: set[str] = set()
    for start in graph:
        if start in done:
            continue
        active = {start}
        stack = [(start, iter(graph[start]))]
        while stack:
            current, children = stack[-1]
            try:
                child = next(children)
            except StopIteration:
                stack.pop()
                active.remove(current)
                done.add(current)
                continue
            if child in active:
                return True
            if child in graph and child not in done:
                active.add(child)
                stack.append((child, iter(graph[child])))
    return False


def validate_rule_v2(
    rule: RuleV2 | Mapping[str, Any],
    vocab_events: Iterable[str] | None = None,
    vocab_fields: Iterable[str] | None = None,
    numeric_fields: Iterable[str] | None = None,
    *,
    field_values: Mapping[str, Iterable[str]] | None = None,
) -> list[str]:
    """Return model, graph, and supplied-vocabulary problems; empty means valid.

    ``field_values`` optionally checks conditions against closed value sets.
    """
    if not isinstance(rule, RuleV2):
        try:
            rule = RuleV2.model_validate(rule)
        except ValidationError as exc:
            return [f"{'.'.join(map(str, error['loc']))}: {error['msg']}" for error in exc.errors()]

    problems: list[str] = []
    events = set(vocab_events) if vocab_events is not None else None
    fields = set(vocab_fields) if vocab_fields is not None else None
    numeric = set(numeric_fields) if numeric_fields is not None else None
    closed_values = (
        {field: set(values) for field, values in field_values.items()}
        if field_values is not None
        else {}
    )
    if fields is not None and rule.per not in fields:
        problems.append(f"unknown entity field {rule.per!r}")
    ids = [node.id for node in rule.nodes]
    duplicates = sorted({node_id for node_id in ids if ids.count(node_id) > 1})
    if duplicates:
        problems.append(f"duplicate node ids: {duplicates}")
        return problems
    nodes = {node.id: node for node in rule.nodes}
    if rule.root not in nodes:
        problems.append(f"root {rule.root!r} is missing")
    elif isinstance(nodes[rule.root], SelectNode):
        problems.append("root must be a checking node, not select")

    graph: dict[str, list[str]] = {}
    for node in rule.nodes:
        if isinstance(node, SelectNode):
            if events is not None and node.event not in events:
                problems.append(f"{node.id}: unknown event {node.event!r}")
            for group, conditions in (("where", node.where), ("exclude", node.exclude)):
                for condition in conditions:
                    if fields is not None and condition.field not in fields:
                        problems.append(f"{node.id}.{group}: unknown field {condition.field!r}")
                    if condition.field in closed_values:
                        values = (
                            condition.value
                            if isinstance(condition.value, list)
                            else [condition.value]
                        )
                        for value in values:
                            if value not in closed_values[condition.field]:
                                problems.append(
                                    f"{node.id}.{group}: value {value!r} for field "
                                    f"{condition.field!r} is not in the closed vocabulary"
                                )
                    if (
                        numeric is not None
                        and condition.op in ("gt", "ge", "lt", "le")
                        and condition.field not in numeric
                    ):
                        problems.append(f"{node.id}.{group}: {condition.field!r} is not numeric")
        if isinstance(
            node, (CountNode, NoneAfterNode, EveryPrecededByNode, EveryFollowedWithinNode)
        ):
            for event in node.since:
                if events is not None and event not in events:
                    problems.append(f"{node.id}: unknown reset event {event!r}")
        if isinstance(node, SumCompareNode):
            for side_name, side in (("left", node.left), ("right", node.right)):
                if fields is not None and side.field not in fields:
                    problems.append(f"{node.id}.{side_name}: unknown field {side.field!r}")
                elif numeric is not None and side.field not in numeric:
                    problems.append(f"{node.id}.{side_name}: {side.field!r} is not numeric")
        if isinstance(node, FieldCompareNode):
            for field_name in (node.a, node.b):
                if fields is not None and field_name not in fields:
                    problems.append(f"{node.id}: unknown field {field_name!r}")
        if isinstance(node, AllOfNode) and not node.children:
            problems.append(f"{node.id}: all_of needs at least one child")

        graph[node.id] = []
        for role, target in _references(node):
            referenced = nodes.get(target)
            if referenced is None:
                problems.append(f"{node.id}.{role}: unknown node id {target!r}")
                continue
            graph[node.id].append(target)
            if role == "children":
                if isinstance(referenced, SelectNode):
                    problems.append(f"{node.id}.{role}: {target!r} is not a checking node")
            elif not isinstance(referenced, SelectNode):
                problems.append(f"{node.id}.{role}: {target!r} is not a select node")

    if _has_cycle(graph):
        problems.append("cycle in node references")
    if rule.root in nodes:
        stack = [(rule.root, 1)]
        too_deep = False
        while stack:
            node_id, depth = stack.pop()
            too_deep |= depth > 3
            if depth <= 3:
                # A shared child can occur on both a short and a too-deep path.
                stack.extend((child, depth + 1) for child in graph[node_id])
        if too_deep:
            problems.append("node depth exceeds 3")
        reachable: set[str] = set()
        pending = [rule.root]
        while pending:
            node_id = pending.pop()
            if node_id in reachable:
                continue
            reachable.add(node_id)
            pending.extend(graph[node_id])
        unreachable = sorted(nodes.keys() - reachable)
        if unreachable:
            problems.append(f"unreachable nodes: {unreachable}")
    return problems
