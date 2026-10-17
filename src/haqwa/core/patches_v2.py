"""Deterministic v2 rule edits for owner answers."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from .errors import INVALID_REQUEST, HaqwaError
from .rules_v2 import (
    ConditionV2,
    CountNode,
    EveryFollowedWithinNode,
    EveryPrecededByNode,
    NoneAfterNode,
    RuleV2,
    SelectNode,
)


class _PatchModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ScalarConditionV2(_PatchModel):
    """A scalar exclusion in Track A's decision wire format."""

    field: str = Field(min_length=1)
    op: Literal["eq", "ne"]
    value: str


class MembershipConditionV2(_PatchModel):
    """A membership exclusion in Track A's decision wire format."""

    field: str = Field(min_length=1)
    op: Literal["in"]
    values: list[str] = Field(min_length=1)


class AddResetV2(_PatchModel):
    """Add a reset event to a checking node."""

    op: Literal["add_reset"] = "add_reset"
    node_id: str = Field(min_length=1)
    event: str = Field(min_length=1)


class AddExcludeV2(_PatchModel):
    """Exempt matching events from one or more select nodes."""

    op: Literal["add_exclude"] = "add_exclude"
    select_ids: list[str] = Field(min_length=1)
    condition: ScalarConditionV2 | MembershipConditionV2


PatchV2 = Annotated[AddResetV2 | AddExcludeV2, Field(discriminator="op")]
_PATCH_ADAPTER = TypeAdapter(PatchV2)
_RESETTABLE = (CountNode, NoneAfterNode, EveryPrecededByNode, EveryFollowedWithinNode)


def apply_patch_v2(rule: RuleV2, patch: PatchV2 | dict[str, Any]) -> RuleV2:
    """Return a new rule with a validated, idempotent owner-answer patch applied.

    The caller supplies its vocabulary to ``validate_rule_v2`` after this edit.
    """
    try:
        parsed = _PATCH_ADAPTER.validate_python(patch)
    except ValidationError as exc:
        raise HaqwaError(INVALID_REQUEST, f"invalid v2 patch: {exc}") from exc

    nodes_by_id = {node.id: node for node in rule.nodes}
    if isinstance(parsed, AddResetV2):
        target = nodes_by_id.get(parsed.node_id)
        if target is None:
            raise HaqwaError(INVALID_REQUEST, f"unknown node id {parsed.node_id!r}")
        if not isinstance(target, _RESETTABLE):
            raise HaqwaError(INVALID_REQUEST, f"node {parsed.node_id!r} does not accept since")
        updated = (
            target.model_copy(update={"since": [*target.since, parsed.event]})
            if parsed.event not in target.since
            else target
        )
        replacements = {parsed.node_id: updated}
    else:
        for select_id in parsed.select_ids:
            target = nodes_by_id.get(select_id)
            if not isinstance(target, SelectNode):
                raise HaqwaError(INVALID_REQUEST, f"node {select_id!r} is not a select")
        condition = ConditionV2(
            field=parsed.condition.field,
            op=parsed.condition.op,
            value=(
                parsed.condition.values
                if isinstance(parsed.condition, MembershipConditionV2)
                else parsed.condition.value
            ),
        )
        replacements = {
            select_id: nodes_by_id[select_id].model_copy(
                update={"exclude": [*nodes_by_id[select_id].exclude, condition]}
            )
            if condition not in nodes_by_id[select_id].exclude
            else nodes_by_id[select_id]
            for select_id in parsed.select_ids
        }
    return rule.model_copy(
        update={"nodes": [replacements.get(node.id, node) for node in rule.nodes]}
    )
